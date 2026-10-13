"""Offline replay/export and guarded explicit GET entry-point tests."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import shutil
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.train_market_evidence import TrainMarketCapturePlan, DEFAULT_LIMITS
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.train_market_capture import capture_train_quotes, read_capture
from blackpod_build_week.train_market_evidence_cli import main
from blackpod_build_week.train_market_evidence_example import fixture_sources, AuthoredQuoteTransport, FixtureClock
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.train_market_evidence_journal import capture_plan_material


class TrainEvidenceCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = fixture_sources(); cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve() / "journal"
        store = JournalStore(cls.base)
        for event, evidence in zip(cls.sources["events"], cls.sources["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)
        self.plan = prepare_capture_plan(self.sources["events"], self.sources["blobs"], capture_id="cli-train-plan", created_at="2025-04-02T10:00:00Z", base_plan_event_id=self.sources["studies"][0]["plan_event"].event_id)
        self.plan_path = self.root / "input" / "plan.json"; self.plan_path.parent.mkdir(); self.plan_path.write_bytes(self.plan.to_bytes())

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): status = main(args)
        return status, json.loads(out.getvalue())

    def registered(self, plan=None):
        if plan is not None: self.plan = plan; self.plan_path.write_bytes(plan.to_bytes())
        status, result = self.call(["register", "--plan", str(self.plan_path), "--journal-root", str(self.journal)])
        self.assertEqual(status, 0, result); self.plan_id = result["event_id"]; return result

    def captured(self, *, budget=2, limits=None):
        if limits is not None:
            value = self.plan.to_dict(); value["limits"] = limits; self.plan = TrainMarketCapturePlan.from_mapping(value)
        self.registered(self.plan)
        self.capture_root = self.root / "capture"
        capture_train_quotes(self.plan, self.capture_root, PaperCredentials("NOT_A_REAL_KEY", "NOT_A_REAL_SECRET"), source_blobs=self.sources["blobs"], request_budget=budget,
            transport=AuthoredQuoteTransport(self.sources), clock=FixtureClock(), sleeper=lambda _: None)
        self.snapshot_path = self.root / "input" / "snapshot.json"
        snapshot = read_capture(self.plan, self.capture_root, exported_at="2025-04-03T10:00:00Z")["snapshot"]
        self.snapshot_path.write_bytes(canonical_json_bytes(snapshot))
        return snapshot

    def export_args(self):
        return ["export", "--snapshot", str(self.snapshot_path), "--evidence-root", str(self.capture_root), "--plan-event-id", self.plan_id,
            "--journal-root", str(self.journal), "--export-id", "cli-train-export", "--output", str(self.root / "reports" / "export.json")]

    def test_register_retry_prepare_defaults_offline(self):
        first = self.registered(); self.assertTrue(first["written"]); self.assertFalse(self.registered()["written"])
        target = self.root / "prepared" / "plan.json"
        status, result = self.call(["prepare", "--capture-id", "prepared-train", "--created-at", self.plan.created_at,
            "--base-plan-event-id", self.plan.base_plan_event_id, "--journal-root", str(self.journal), "--output", str(target)])
        self.assertEqual(status, 0, result); self.assertEqual(result["provider_calls"], 0); self.assertEqual(result["planned_segments"], 12)

    def test_partial_export_and_identical_retry_preserve_capture(self):
        self.captured(); before = {str(p.relative_to(self.capture_root)): p.read_bytes() for p in self.capture_root.rglob("*") if p.is_file()}
        status, result = self.call(self.export_args()); self.assertEqual(status, 0, result); self.assertFalse(result["capture_complete"])
        self.assertEqual(result["counts"]["missing_symbol_sessions"], 20)
        status, retry = self.call(self.export_args()); self.assertEqual(status, 0, retry); self.assertFalse(retry["written"]); self.assertEqual(retry["segment_events_written"], 0)
        self.assertEqual(before, {str(p.relative_to(self.capture_root)): p.read_bytes() for p in self.capture_root.rglob("*") if p.is_file()})

    def test_lifetime_budget_blockers_do_not_invent_provider_attempts(self):
        limits = {**DEFAULT_LIMITS, "max_total_requests": 1, "max_requests_per_invocation": 1}
        snapshot = self.captured(budget=1, limits=limits)
        self.assertEqual(snapshot["attempt_count"], 1)
        self.assertTrue(any(s["status"] == "NOT_STARTED" and s["failure"]["code"] == "TOTAL_REQUEST_LIMIT" for s in snapshot["segments"] if s["failure"] is not None))
        status, result = self.call(self.export_args()); self.assertEqual(status, 0, result); self.assertEqual(result["segment_events_written"], 1)
        events, blobs = JournalStore(self.journal).verified_contents(); audit = events[-1].payload["result"]["capture_audit"]
        self.assertEqual(audit["attempt_count"], 1); self.assertFalse(result["capture_complete"])
        self.assertTrue(audit["checkpoint_evidence"])

    def test_capture_snapshot_and_failure_audit_retained_after_source_removal(self):
        self.captured(); status, result = self.call(self.export_args()); self.assertEqual(status, 0, result)
        before = JournalStore(self.journal).verify().to_dict(); shutil.rmtree(self.capture_root); self.snapshot_path.unlink()
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_live_capture_rejects_synthetic_scope_before_credentials(self):
        self.registered()
        with patch("blackpod_build_week.paper_account_probe.parse_credentials", side_effect=AssertionError("credentials must not be read")):
            status, result = self.call(["capture", "--plan-event-id", self.plan_id, "--journal-root", str(self.journal), "--capture-root", str(self.root / "live-forbidden"),
                "--credential-source", str(self.root / "unused.yaml"), "--credential-format", "GALACTICA_YAML", "--allow-market-data-get"])
        self.assertEqual(status, 2); self.assertIn("real-history", result["error"])

    def test_snapshot_offline_and_wrong_plan_rejects(self):
        self.captured(); target = self.root / "snapshots" / "export.json"
        status, result = self.call(["snapshot", "--plan-event-id", self.plan_id, "--journal-root", str(self.journal), "--capture-root", str(self.capture_root), "--exported-at", "2025-04-03T10:00:00Z", "--output", str(target)])
        self.assertEqual(status, 0, result); self.assertEqual(result["provider_calls"], 0)
        value = json.loads(self.snapshot_path.read_bytes()); value["capture_id"] = "wrong-capture"; self.snapshot_path.write_bytes(canonical_json_bytes(value))
        self.assertEqual(self.call(self.export_args())[0], 2)

    def test_hidden_captured_window_and_hash_change_reject(self):
        snapshot = self.captured()
        snapshot["segments"].pop(); self.snapshot_path.write_bytes(canonical_json_bytes(snapshot))
        self.assertEqual(self.call(self.export_args())[0], 2)

    def test_forged_operational_counts_reject_before_any_journal_append(self):
        snapshot = self.captured(); original = JournalStore(self.journal).verify().to_dict()
        snapshot["attempt_count"] += 10; self.snapshot_path.write_bytes(canonical_json_bytes(snapshot))
        status, result = self.call(self.export_args())
        self.assertEqual(status, 2)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), original)

    def test_outputs_cannot_overlap_journal_or_source(self):
        self.captured(); args = self.export_args(); args[-1] = str(self.journal / "export.json")
        self.assertEqual(self.call(args)[0], 2)

    def test_verify_show_and_missing_journal_are_read_only(self):
        self.captured(); status, result = self.call(self.export_args()); self.assertEqual(status, 0, result)
        status, shown = self.call(["show", "--event-id", result["event_id"], "--journal-root", str(self.journal)]); self.assertEqual(status, 0)
        self.assertFalse(shown["payload"]["result"]["economic_hypothesis_supported"])
        root = self.root / "absent"; self.assertEqual(self.call(["verify", "--journal-root", str(root)])[0], 2); self.assertFalse(root.exists())
