"""Offline declarations, immutable exports, exact retries and safe paths."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.trading_evidence_qualification_cli import main
from blackpod_build_week.trading_evidence_qualification_journal import policy_material
from blackpod_build_week.trading_evidence_qualification_example import fixture_material
from blackpod_build_week.contracts.trading_evidence_qualification import TradingEvidenceQualificationRequest


class QualificationCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = fixture_material(); cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve() / "journal"
        store = JournalStore(cls.base)
        for event, evidence in zip(cls.material["original"]["events"], cls.material["original"]["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)
        self.policy = self.material["cases"][0]["policy"]
        self.evidence = self.root / "evidence"
        for path, raw in self.material["evidence"].items():
            target = self.evidence / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        self.policy_path = self.root / "input" / "policy.json"; self.policy_path.parent.mkdir()
        self.policy_path.write_bytes(self.policy.to_bytes())

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): code = main(args)
        return code, json.loads(out.getvalue())

    def register(self):
        return self.call(["register", "--policy", str(self.policy_path), "--evidence-root", str(self.evidence), "--journal-root", str(self.journal)])

    def request_path(self):
        code, registered = self.register(); self.assertEqual(code, 0, registered)
        doc = TradingEvidenceQualificationRequest.from_mapping({"schema_version": "blackpod.trading_evidence_qualification_request.v1",
            "qualification_id": "cli-test-qualified", "policy_event_id": registered["event_id"], "recorded_at": "2025-04-02T11:00:00Z",
            "data_cutoff_at": "2025-04-02T10:30:00Z", "supersedes_event_id": None, "auto_trading_enabled": False, "authority": self.policy.authority})
        path = self.root / "input" / "request.json"; path.write_bytes(doc.to_bytes()); return path

    def test_register_exact_retry_and_record_show_verify(self):
        path = self.request_path(); self.assertFalse(self.register()[1]["written"])
        args = ["record", "--request", str(path), "--journal-root", str(self.journal)]
        code, result = self.call(args); self.assertEqual(code, 0, result); self.assertTrue(result["written"])
        self.assertEqual(result["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertFalse(self.call(args)[1]["written"])
        code, shown = self.call(["show", "--event-id", result["event_id"], "--journal-root", str(self.journal)])
        self.assertEqual(code, 0); self.assertFalse(shown["payload"]["result"]["economic_hypothesis_supported"])
        code, summary = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0); self.assertEqual(summary["event_count"], 16)

    def test_assess_immutable_export_does_not_append(self):
        path = self.request_path(); before = JournalStore(self.journal).verify().to_dict()
        output = self.root / "reports" / "qualification.json"
        args = ["assess", "--request", str(path), "--journal-root", str(self.journal), "--output", str(output)]
        code, result = self.call(args); self.assertEqual(code, 0, result)
        original = output.read_bytes(); self.assertEqual(self.call(args)[0], 0); self.assertEqual(original, output.read_bytes())
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_prepare_defaults_proposed_and_does_not_calibrate(self):
        inputs = self.root / "declarations" / "inputs.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({"supporting_evidence": self.policy.supporting_evidence,
            "training_quote_chains": None, "training_cost_assumptions_evidence": None, "uncertainty_protocol": None}))
        output = self.root / "prepared" / "policy.json"
        args = ["prepare", "--journal-root", str(self.journal), "--inputs", str(inputs), "--policy-id", "prepared-cli",
            "--recorded-at", self.policy.recorded_at, "--base-plan-event-id", self.policy.base_plan_event_id,
            "--reviewer-id", "cli-test", "--review-notes", "Offline proposal.", "--output", str(output)]
        code, result = self.call(args); self.assertEqual(code, 0, result); self.assertEqual(result["status"], "PROPOSED")
        self.assertFalse(result["calibration_performed"]); self.assertEqual(JournalStore(self.journal).verify().event_count, 14)

    def test_missing_external_support_requires_evidence_root(self):
        code, result = self.call(["register", "--policy", str(self.policy_path), "--journal-root", str(self.journal)])
        self.assertEqual(code, 2); self.assertIn("evidence root", result["error"])

    def test_source_hash_change_rejects(self):
        path = self.evidence / self.policy.supporting_evidence[0]["path"]; path.write_bytes(b"changed")
        self.assertEqual(self.register()[0], 2)

    def test_source_symlink_and_ancestor_symlink_reject(self):
        original = self.evidence / self.policy.supporting_evidence[0]["path"]
        copy = self.root / "outside.raw"; copy.write_bytes(original.read_bytes()); original.unlink(); original.symlink_to(copy)
        self.assertEqual(self.register()[0], 2)

    def test_unsafe_journal_output_rejects(self):
        path = self.request_path()
        code, result = self.call(["assess", "--request", str(path), "--journal-root", str(self.journal), "--output", str(self.journal / "outside.json")])
        self.assertEqual(code, 2); self.assertIn("separate", result["error"])

    def test_repository_output_rejects(self):
        path = self.request_path(); target = Path(__file__).resolve().parents[1] / "src" / "forbidden-qualified.json"
        code, result = self.call(["assess", "--request", str(path), "--journal-root", str(self.journal), "--output", str(target)])
        self.assertEqual(code, 2); self.assertFalse(target.exists())

    def test_missing_verify_does_not_create_storage(self):
        root = self.root / "missing"
        self.assertEqual(self.call(["verify", "--journal-root", str(root)])[0], 2); self.assertFalse(root.exists())

    def test_unknown_native_event_show_rejects(self):
        native = self.material["original"]["events"][0]
        self.assertEqual(self.call(["show", "--event-id", native.event_id, "--journal-root", str(self.journal)])[0], 2)
