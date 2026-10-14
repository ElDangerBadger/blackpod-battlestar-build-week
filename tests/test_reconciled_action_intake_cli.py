"""Offline typed loading, policy bundles and immutable CLI lifecycle."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.effective_date_reconciliation import IndependentActionInventory
from blackpod_build_week.contracts.qqq_distribution_inventory import QQQDistributionInventory, URL
from blackpod_build_week.contracts.reconciled_action_intake import ReconciledActionIntakePolicy, ReconciledActionIntakeRequest, POLICY_CONSTANTS, REQUEST_CONSTANTS, AUTHORITY
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_action_intake_cli import main, build_parser, load_inventory_evidence, load_policy_evidence, load_intake_evidence, _read
from blackpod_build_week.reconciled_action_journal import POLICY_PATH


def reference(path, raw): return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def reader_material():
    """Typed declarations with opaque leaves; not a semantic source fixture."""
    files = {}
    def retain(path, value):
        raw = value if isinstance(value, bytes) else value.to_bytes()
        files[path] = raw; return reference(path, raw)
    dataset = retain("source/dataset.raw", b"opaque dataset")
    native = retain("source/native.raw", b"opaque native source")
    masks = retain("source/masks.raw", b"opaque original masks")
    old = IndependentActionInventory.from_mapping({"schema_version": "blackpod.independent_action_inventory.v1", "inventory_id": "unit-authored",
        "recorded_at": "2025-04-08T10:00:00Z", "profile": "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "publisher": "AUTHORED", "source_url": "https://example.invalid/authored", "captured_at": "2025-04-08T09:00:00Z",
        "body_evidence": retain("source/actions.raw", b'[{"evidence":{"path":"never-follow.raw"}}]'),
        "declared_coverage": {"symbols": ["SYNTHA", "SYNTHB"], "action_types": ["cash_dividends"], "effective_start": "2025-01-01", "effective_end": "2025-02-01", "completeness": "UNKNOWN"},
        "supporting_evidence": [retain("source/support.raw", b"opaque support")], "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    old_ref = retain("declarations/authored.json", old)
    qqq = QQQDistributionInventory.from_mapping({"schema_version": "blackpod.qqq_distribution_inventory.v1", "inventory_id": "unit-qqq",
        "recorded_at": "2025-04-08T10:00:00Z", "profile": "INVESCO_QQQ_DISTRIBUTIONS_JSON_V1", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "publisher": "INVESCO", "source_url": URL, "captured_at": "2025-04-08T09:00:00Z",
        "body_evidence": retain("source/qqq.raw", b'[{"source_url":"https://example.invalid/never-fetch"}]'),
        "receipt_evidence": retain("source/receipt.raw", b"opaque capture receipt"), "discovery_evidence": retain("source/discovery.raw", b"opaque publisher discovery"),
        "declared_coverage": {"symbols": ["QQQ"], "action_types": ["cash_dividends"], "effective_start": "2025-01-01", "effective_end": "2025-02-01", "completeness": "UNKNOWN"},
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    qqq_ref = retain("declarations/qqq.json", qqq)
    policy = ReconciledActionIntakePolicy.from_mapping({**POLICY_CONSTANTS, "policy_id": "unit-frozen-policy", "recorded_at": "2025-04-09T10:00:00Z",
        "anchor_review_event_id": "journal-event-" + "a" * 64, "dataset_evidence": dataset, "native_continuity_export_evidence": native,
        "original_native_masks_evidence": masks, "independent_inventories": [old_ref, qqq_ref], "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    policy_ref = retain("declarations/policy.json", policy)
    request = ReconciledActionIntakeRequest.from_mapping({**REQUEST_CONSTANTS, "intake_id": "unit-intake", "recorded_at": "2025-04-10T12:00:00Z", "data_cutoff_at": "2025-04-10T11:00:00Z",
        "policy_event_id": "journal-event-" + "b" * 64, "policy_evidence": policy_ref, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    return policy, request, files


class TypedReaderAndGuardTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.policy, self.request, self.files = reader_material()

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): result = main(args)
        return result, json.loads(out.getvalue())

    def write_sources(self):
        for name, raw in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def test_seven_commands_expose_no_operational_switch_or_provider(self):
        command = next(item for item in build_parser()._actions if isinstance(getattr(item, "choices", None), dict))
        self.assertEqual(set(command.choices), {"prepare-policy", "register-policy", "prepare", "assess", "record", "show", "verify"})
        for parser in command.choices.values():
            options = {option for item in parser._actions for option in item.option_strings}
            self.assertFalse(options & {"--status", "--allow-market-data-get", "--credential-source", "--activate", "--auto-trading", "--broker"})

    def test_schema_only_prepare_never_reads_history(self):
        inputs = self.root / "inputs" / "prepare.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({key: getattr(self.request, key) for key in ("policy_event_id", "policy_evidence", "supersedes_event_id")}))
        output = self.root / "prepared" / "request.json"
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("must not scan")):
            code, result = self.call(["prepare", "--intake-id", self.request.intake_id, "--recorded-at", self.request.recorded_at, "--data-cutoff-at", self.request.data_cutoff_at,
                "--inputs", str(inputs), "--output", str(output)])
        self.assertEqual(code, 0, result); self.assertFalse(result["source_history_verified"]); self.assertFalse(result["assessment_performed"])
        self.assertEqual(output.read_bytes(), self.request.to_bytes())

    def test_typed_traversal_preserves_opaque_body_receipt_discovery_and_support(self):
        self.write_sources(); blobs = load_intake_evidence(self.request, {}, self.root)
        self.assertEqual(set(blobs), {sha256_bytes(raw) for raw in self.files.values()})
        self.assertFalse((self.root / "never-follow.raw").exists())

    def test_retained_closure_needs_no_external_files(self):
        blobs = {sha256_bytes(raw): raw for raw in self.files.values()}
        with patch("blackpod_build_week.evidence_reconciliation_cli._read", side_effect=AssertionError("external reads forbidden")):
            self.assertEqual(load_intake_evidence(self.request, blobs, None), blobs)

    def test_missing_and_changed_leaves_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "explicit evidence root"): load_policy_evidence(self.policy, {}, None)
        self.write_sources(); (self.root / "source/qqq.raw").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash or size"): load_policy_evidence(self.policy, {}, self.root)
        blobs = {sha256_bytes(raw): raw for raw in self.files.values()}; blobs[self.policy.original_native_masks_evidence["sha256"]] = b"changed"
        with self.assertRaisesRegex(ValueError, "hash or size"): load_policy_evidence(self.policy, blobs, None)

    def test_reference_bounds_and_unknown_manifest_schema_reject(self):
        self.write_sources()
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_REFERENCES", 2):
            with self.assertRaisesRegex(ValueError, "bound"): load_policy_evidence(self.policy, {}, self.root)
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "bound"): load_policy_evidence(self.policy, {}, self.root)
        raw = b'{"schema_version":"untrusted.unknown"}'
        with self.assertRaisesRegex(ValueError, "unsupported typed"):
            load_inventory_evidence([reference("unknown.json", raw)], {sha256_bytes(raw): raw}, None)

    def test_unsafe_input_links_and_traversal_reject(self):
        target = self.root / "target"; target.write_bytes(b"source"); link = self.root / "link"; link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)): _read(link)
        link.unlink(); os.link(target, link)
        with self.assertRaises((OSError, ValueError)): _read(link)
        with self.assertRaisesRegex(ValueError, "traverse"): _read(self.root / "child" / ".." / "target")

    def test_output_guards_precede_policy_or_intake_scans(self):
        source = Path(__file__).resolve().parents[1] / "src" / "forbidden-reconciled.json"
        runtime = self.root / "runtime"; runtime.mkdir(); (runtime / "ledger.lock").write_bytes(b"")
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("guard first")):
            code, result = self.call(["prepare-policy", "--anchor-review-event-id", self.policy.anchor_review_event_id, "--policy-id", "unsafe", "--recorded-at", self.policy.recorded_at,
                "--journal-root", str(self.root / "journal"), "--inputs", str(self.root / "input" / "missing.json"), "--output-directory", str(source)])
            self.assertEqual(code, 2, result)
            code, result = self.call(["assess", "--journal-root", str(self.root / "journal"), "--request", str(self.root / "input" / "missing.json"), "--output", str(runtime / "nested" / "result.json")])
            self.assertEqual(code, 2, result)
        self.assertFalse(source.exists()); self.assertFalse((runtime / "nested").exists())

    def test_proposed_status_and_missing_journal_cannot_become_operational(self):
        with self.assertRaises(ValueError): ReconciledActionIntakePolicy.from_mapping({**self.policy.to_dict(), "status": "PROPOSED"})
        missing = self.root / "missing-journal"
        code, result = self.call(["verify", "--journal-root", str(missing)])
        self.assertEqual(code, 2, result); self.assertFalse(missing.exists())


class FrozenPolicyLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_reconciled_action_intake_example import retained_fixture
        cls.material, cls.base, cls.retained_temp = retained_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): result = main(args)
        return result, json.loads(out.getvalue())

    def test_policy_bundle_register_assess_record_retry_show_and_verify(self):
        original = {path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}
        inputs = self.root / "inputs" / "policy.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({"independent_inventories": self.material["policy"].independent_inventories}))
        bundle = self.root / "bundle"
        code, prepared = self.call(["prepare-policy", "--anchor-review-event-id", self.material["anchor_event"].event_id, "--policy-id", "cli-frozen-policy", "--recorded-at", "2025-04-11T10:00:00Z",
            "--journal-root", str(self.journal), "--inputs", str(inputs), "--output-directory", str(bundle)])
        self.assertEqual(code, 0, prepared); self.assertFalse(prepared["journal_written"])
        policy_file = bundle / POLICY_PATH; frozen = policy_file.read_bytes()
        args = ["register-policy", "--policy", str(policy_file), "--journal-root", str(self.journal), "--evidence-root", str(bundle)]
        code, registered = self.call(args); self.assertEqual(code, 0, registered); self.assertTrue(registered["written"])
        code, retry = self.call(args); self.assertEqual(code, 0, retry); self.assertFalse(retry["written"])
        self.assertEqual(policy_file.read_bytes(), frozen)
        request = ReconciledActionIntakeRequest.from_mapping({**REQUEST_CONSTANTS, "intake_id": "cli-intake", "recorded_at": "2025-04-12T12:00:00Z", "data_cutoff_at": "2025-04-12T11:00:00Z",
            "policy_event_id": registered["event_id"], "policy_evidence": reference(POLICY_PATH, frozen), "supersedes_event_id": None, "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
        request_file = self.root / "inputs" / "request.json"; request_file.write_bytes(request.to_bytes())
        before = {path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}
        report = self.root / "reports" / "intake.json"
        code, assessed = self.call(["assess", "--request", str(request_file), "--journal-root", str(self.journal), "--output", str(report)])
        self.assertEqual(code, 0, assessed); self.assertFalse(assessed["journal_written"])
        self.assertEqual({path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}, before)
        args = ["record", "--request", str(request_file), "--journal-root", str(self.journal)]
        code, recorded = self.call(args); self.assertEqual(code, 0, recorded); self.assertTrue(recorded["written"])
        code, retried = self.call(args); self.assertEqual(code, 0, retried); self.assertFalse(retried["written"])
        code, shown = self.call(["show", "--event-id", recorded["event_id"], "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, shown); self.assertFalse(shown["payload"]["result"]["legacy_source_compatible"])
        code, summary = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, summary); self.assertEqual(summary["event_count"], len(original) + 2)
        self.assertEqual({name: (self.journal / "entries" / name).read_bytes() for name in original}, original)

    def test_show_rejects_old_v22_anchor(self):
        code, result = self.call(["show", "--event-id", self.material["anchor_event"].event_id, "--journal-root", str(self.journal)])
        self.assertEqual(code, 2, result)


if __name__ == "__main__": unittest.main()
