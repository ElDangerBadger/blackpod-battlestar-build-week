"""Runnable passive PAPER commands with synthetic retained evidence only."""
from __future__ import annotations
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from test_trading_reconciliation_engine import ReconciliationFixture, NOW
from test_paper_account_probe import FakeTransport, PAPER_ENV
from blackpod_build_week import trading_reconciliation_cli as cli
from blackpod_build_week import paper_account_safety as safety
from blackpod_build_week import paper_account_probe as probe
from blackpod_build_week.auto_trading_runtime import RuntimeLedger, _immutable
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


class TradingReconciliationCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.inputs = self.base / "inputs"
        self.inputs.mkdir()
        self.root = self.base / "journal"
        self.fixture = ReconciliationFixture()
        self.addCleanup(self.fixture.close)
        self.snapshot_file = self.write("snapshot.json", self.fixture.snapshot.to_bytes())
        self.evidence_file = self.write("broker-source.json", self.fixture.blobs[self.fixture.snapshot.capture_provenance["source_evidence"]["sha256"]])
        self.ownership_file = self.write("ownership.json", self.fixture.ownership.to_bytes())
        self.reconciliation_file = self.write("reconciliation.json", self.fixture.reconciliation.to_bytes())
        self.runtime_file = self.write("runtime.json", canonical_json_bytes(self.fixture.capture))
        self.enterContext(mock.patch.object(safety, "account_state_root", side_effect=lambda account: self.base / "account-state" / sha256_bytes(account.encode())))

    def write(self, name, raw):
        path = self.inputs / name
        path.write_bytes(raw)
        return path

    def invoke(self, *args):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            try:
                code = cli.main(list(args))
            except SystemExit as exc:
                code = exc.code
        value = json.loads(stdout.getvalue()) if stdout.getvalue() else None
        return code, value, stderr.getvalue()

    def seed(self):
        store = JournalStore(self.root)
        for event in self.fixture.events:
            store.append(event, self.fixture.blobs)
        return store

    def ownership_args(self):
        return ("record-ownership", "--journal-root", str(self.root), "--ownership", str(self.ownership_file),
                "--confirm-account-id", self.fixture.ownership.account_id,
                "--confirm-desk-scope-sha256", sha256_bytes(canonical_json_bytes(self.fixture.ownership.desks)))

    def test_import_snapshot_retains_verified_source_and_retries_without_mutation(self):
        args = ("import-snapshot", "--journal-root", str(self.root), "--snapshot", str(self.snapshot_file), "--evidence", str(self.evidence_file))
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(result["written"])
        self.assertEqual(result["orders_submitted"], 0)
        before = (self.root / "entries" / "00000001.json").read_bytes()
        code, repeated, error = self.invoke(*args)
        self.assertEqual(code, 0)
        self.assertFalse(repeated["written"])
        self.assertEqual((self.root / "entries" / "00000001.json").read_bytes(), before)
        self.assertEqual(JournalStore(self.root).verify().event_count, 1)

    def test_import_confirmed_empty_probe_preserves_open_only_query_limitations(self):
        credentials = self.base / "credentials" / "fixture.env"
        credentials.parent.mkdir()
        credentials.write_bytes(PAPER_ENV)
        fetch = FakeTransport()
        fetch.values["/v2/positions"] = []
        fetch.values[probe.ENDPOINTS[2][1]] = []
        result = probe.probe_paper_account(credentials, "PAPER_ENV", self.inputs / "probe-captures", transport=fetch, now=lambda: NOW)
        code, recorded, error = self.invoke("import-probe", "--journal-root", str(self.root), "--probe", result["evidence_path"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(recorded["snapshot"]["orders"], [])
        self.assertFalse(recorded["snapshot"]["completeness"]["tracked_orders_complete"])
        self.assertFalse(recorded["assessment"]["execution_observed"])
        self.assertFalse(recorded["assessment"]["execution_authority_granted"])
        self.assertIsNone(recorded["assessment"]["realized_trade_pnl"])
        self.assertEqual(JournalStore(self.root).verify().event_count, 1)

    def test_unconfirmed_probe_cannot_be_imported_as_verified_account_history(self):
        failed = self.write("failed-probe.json", canonical_json_bytes({"schema_version": probe.SCHEMA_VERSION, "result": "NOT_CONFIRMED"}))
        code, result, _ = self.invoke("import-probe", "--journal-root", str(self.root), "--probe", str(failed))
        self.assertEqual(code, 2)
        self.assertIsNone(result)
        self.assertFalse(self.root.exists())

    def test_ownership_requires_exact_account_and_desk_scope_confirmations(self):
        store = JournalStore(self.root)
        store.append(self.fixture.snapshot_event, self.fixture.blobs)
        args = list(self.ownership_args())
        for field, invalid in (("--confirm-account-id", "wrong-account"), ("--confirm-desk-scope-sha256", "f" * 64)):
            modified = args.copy()
            modified[modified.index(field) + 1] = invalid
            code, result, _ = self.invoke(*modified)
            self.assertEqual(code, 2)
            self.assertIsNone(result)
            self.assertEqual(store.verify().event_count, 1)
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(result["assessment"]["identity_authenticated"])
        self.assertFalse(result["assessment"]["execution_authority_granted"])
        self.assertFalse(result["ownership"]["authority"]["capital_activation_enabled"])

    def test_ownership_missing_confirmation_flags_do_not_write(self):
        args = self.ownership_args()
        for truncated in (args[:5], args[:7]):
            code, _, _ = self.invoke(*truncated)
            self.assertEqual(code, 2)
        self.assertFalse(self.root.exists())

    def test_record_reconciliation_retains_runtime_prefix_then_retries_from_retained_evidence(self):
        store = self.seed()
        args = ("record-reconciliation", "--journal-root", str(self.root), "--reconciliation", str(self.reconciliation_file),
                "--runtime-evidence", str(self.runtime_file))
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(result["result"]["execution_observed"])
        self.assertEqual(result["result"]["attempts"][0]["filled_qty"], "2")
        self.runtime_file.unlink()
        code, repeated, error = self.invoke(*args[:-2])
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(repeated["written"])
        self.assertEqual(store.verify().event_count, 3)

    def test_reconcile_builds_exact_links_and_keeps_authority_disabled(self):
        self.seed()
        args = ("reconcile", "--journal-root", str(self.root), "--snapshot-event-id", self.fixture.snapshot_event.event_id,
                "--ownership-event-id", self.fixture.ownership_event.event_id, "--reconciliation-id", "cli-derived",
                "--recorded-at", NOW, "--runtime-evidence", str(self.runtime_file))
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(result["reconciliation"]["broker_snapshot_event_id"], self.fixture.snapshot_event.event_id)
        self.assertEqual(result["reconciliation"]["ownership_event_id"], self.fixture.ownership_event.event_id)
        self.assertIsNone(result["reconciliation"]["realized_trade_pnl"])
        self.assertFalse(result["result"]["readiness"])
        code, repeated, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(repeated["written"])

    def test_show_is_read_only_and_missing_event_creates_nothing(self):
        store = self.seed()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        code, result, error = self.invoke("show", "--journal-root", str(self.root), "--event-id", self.fixture.snapshot_event.event_id)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(result["event_id"], self.fixture.snapshot_event.event_id)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        absent = self.base / "absent-journal"
        code, _, _ = self.invoke("show", "--journal-root", str(absent), "--event-id", "unknown")
        self.assertEqual(code, 2)
        self.assertFalse(absent.exists())

    def test_export_runtime_only_reads_verified_receipts_and_profile_bytes(self):
        root = self.base / "runtime"
        ledger = RuntimeLedger(root)
        _immutable(root / "profiles" / (self.fixture.profile_sha + ".json"), canonical_json_bytes(self.fixture.profile))
        for event in self.fixture.capture["events"]:
            ledger.append(event["kind"], event["payload"])
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        target = self.base / "exports" / "runtime.json"
        code, result, error = self.invoke("export-runtime", "--runtime-root", str(root), "--output", str(target))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(target.read_bytes()), self.fixture.capture)
        self.assertEqual(result["sha256"], sha256_bytes(target.read_bytes()))
        self.assertEqual(before, {path: path.read_bytes() for path in root.rglob("*") if path.is_file()})

    def test_export_runtime_rejects_corrupted_profile_and_nested_output(self):
        root = self.base / "runtime"
        ledger = RuntimeLedger(root)
        profile_path = root / "profiles" / (self.fixture.profile_sha + ".json")
        _immutable(profile_path, canonical_json_bytes(self.fixture.profile))
        for event in self.fixture.capture["events"]:
            ledger.append(event["kind"], event["payload"])
        nested = root / "export" / "runtime.json"
        code, _, _ = self.invoke("export-runtime", "--runtime-root", str(root), "--output", str(nested))
        self.assertEqual(code, 2)
        self.assertFalse(nested.exists())
        value = self.fixture.profile.copy()
        value["account_id"] = "another-account"
        profile_path.write_bytes(canonical_json_bytes(value))
        target = self.base / "exports" / "bad.json"
        code, _, _ = self.invoke("export-runtime", "--runtime-root", str(root), "--output", str(target))
        self.assertEqual(code, 2)
        self.assertFalse(target.exists())

    def test_export_runtime_cannot_write_inside_canonical_mission_storage(self):
        runtime = self.base / "absent-runtime"
        mission = self.base / "canonical-mission"
        (mission / "request").mkdir(parents=True)
        request = mission / "request" / "mission_request.json"
        request.write_bytes(b'{"synthetic":"source marker only"}')
        original = request.read_bytes()
        for target in (mission / "export.json", mission / "request" / "export.json"):
            with self.subTest(target=target):
                code, result, _ = self.invoke("export-runtime", "--runtime-root", str(runtime), "--output", str(target))
                self.assertEqual(code, 2)
                self.assertIsNone(result)
                self.assertFalse(target.exists())
        self.assertEqual(request.read_bytes(), original)
        self.assertFalse(runtime.exists())

    def test_install_paper_book_is_explicit_and_does_not_activate_capital(self):
        self.seed()
        args = ("install-paper-book", "--journal-root", str(self.root), "--ownership-event-id", self.fixture.ownership_event.event_id,
                "--confirm-account-id", self.fixture.ownership.account_id)
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(result["written"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["capital_policy_activated"])
        code, repeated, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(repeated["written"])
        self.assertFalse(repeated["execution_authorized"])

    def test_evidence_and_journal_roots_cannot_overlap(self):
        before = {path: path.read_bytes() for path in self.inputs.rglob("*") if path.is_file()}
        code, _, _ = self.invoke("import-snapshot", "--journal-root", str(self.inputs),
            "--snapshot", str(self.snapshot_file), "--evidence", str(self.evidence_file))
        self.assertEqual(code, 2)
        self.assertEqual(before, {path: path.read_bytes() for path in self.inputs.rglob("*") if path.is_file()})


if __name__ == "__main__":
    unittest.main()
