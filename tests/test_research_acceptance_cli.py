"""Explicit offline CLI inputs and protected, immutable output behavior."""
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
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.research_acceptance_cli import main, _candidate_blobs
from blackpod_build_week.contracts.research_assessment import ResearchAssessmentRequest
from test_research_acceptance_trading import material_with_blobs, acceptance_request


class ResearchAcceptanceCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = material_with_blobs()
        cls.temporary = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temporary.cleanup)
        cls.base = Path(cls.temporary.name).resolve() / "journal"
        store = JournalStore(cls.base)
        for event, evidence in zip(cls.original["events"], cls.original["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)
        self.request = acceptance_request(self.original)
        self.path = self.root / "input" / "request.json"; self.path.parent.mkdir()
        self.write_request()

    def write_request(self):
        self.path.write_bytes(canonical_json_bytes(self.request))

    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output): code = main(args)
        return code, json.loads(output.getvalue())

    def args(self, command):
        return [command, "--journal-root", str(self.journal), "--request", str(self.path)]

    def test_prepare_binds_exact_native_registration_without_writes(self):
        before = JournalStore(self.journal).verify().to_dict()
        output = self.root / "prepared"
        code, result = self.call(["prepare", "--journal-root", str(self.journal), "--research-event-id", self.request["research_event_id"],
            "--assessment-id", "cli-prepared", "--recorded-at", self.request["recorded_at"], "--data-cutoff-at", self.request["data_cutoff_at"],
            "--evaluation-event-id", self.request["evaluation_event_id"], "--output-directory", str(output)])
        self.assertEqual(code, 0)
        document = ResearchAssessmentRequest.from_bytes(Path(result["request_path"]).read_bytes())
        self.assertEqual(document.hypothesis, self.request["hypothesis"])
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_assess_is_passive_and_writes_immutable_report(self):
        before = JournalStore(self.journal).verify().to_dict()
        target = self.root / "reports" / "assessment.json"
        code, result = self.call(self.args("assess") + ["--output", str(target)])
        self.assertEqual(code, 0); self.assertEqual(result["classification"], "CONTRADICTED")
        self.assertFalse(result["auto_trading_enabled"])
        original = target.read_bytes()
        self.assertEqual(self.call(self.args("assess") + ["--output", str(target)])[0], 0)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_record_idempotent_show_and_verify(self):
        code, result = self.call(self.args("record")); self.assertEqual(code, 0); self.assertTrue(result["written"])
        code, retry = self.call(self.args("record")); self.assertEqual(code, 0); self.assertFalse(retry["written"])
        self.assertEqual(result["event_id"], retry["event_id"])
        code, shown = self.call(["show", "--journal-root", str(self.journal), "--event-id", result["event_id"]])
        self.assertEqual(code, 0); self.assertEqual(shown["payload"]["assessment"]["classification"], "CONTRADICTED")
        code, verified = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0); self.assertEqual(verified["event_count"], len(self.original["events"]) + 1)

    def test_untrusted_external_result_retained_invalid_without_rewriting(self):
        raw = canonical_json_bytes({"status": "asserted-support"}); evidence = self.root / "claims"; evidence.mkdir()
        (evidence / "result.json").write_bytes(raw)
        self.request["candidate_result_evidence"] = {"path": "result.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        self.write_request()
        code, result = self.call(self.args("record") + ["--evidence-root", str(evidence)])
        self.assertEqual(code, 0); self.assertEqual(result["classification"], "INVALID")
        events, blobs = JournalStore(self.journal).verified_contents()
        self.assertEqual(blobs[sha256_bytes(raw)], raw)
        self.assertEqual(tuple(event.to_bytes() for event in events[:-1]), tuple(event.to_bytes() for event in self.original["events"]))

    def test_candidate_requires_explicit_root_or_retained_bytes(self):
        self.request["candidate_result_evidence"] = {"path": "claim.json", "sha256": "a" * 64, "size_bytes": 1}; self.write_request()
        code, result = self.call(self.args("record")); self.assertEqual(code, 2); self.assertIn("explicit evidence root", result["error"])

    def test_retained_candidate_cannot_bypass_size_bound(self):
        self.request["candidate_result_evidence"] = {"path": "claims/large.json", "sha256": "a" * 64, "size_bytes": 4 * 1024 * 1024 + 1}
        request = ResearchAssessmentRequest.from_mapping(self.request)
        with self.assertRaisesRegex(ValueError, "4 MiB"): _candidate_blobs(request, {"a" * 64: b"already retained"}, None, self.journal)

    def test_output_cannot_write_into_journal(self):
        code, result = self.call(self.args("assess") + ["--output", str(self.journal / "assessment.json")])
        self.assertEqual(code, 2); self.assertIn("separate", result["error"])

    def test_output_cannot_write_into_repository_source(self):
        target = Path(__file__).resolve().parents[1] / "src" / "forbidden-assessment.json"
        code, result = self.call(self.args("assess") + ["--output", str(target)])
        self.assertEqual(code, 2); self.assertFalse(target.exists()); self.assertIn("source trees", result["error"])

    def test_input_symlink_and_ancestor_symlink_reject(self):
        alias = self.root / "alias"; alias.symlink_to(self.path.parent, target_is_directory=True)
        for path in (alias / "request.json", self.root / "linked-request.json"):
            if path.name == "linked-request.json": path.symlink_to(self.path)
            args = ["record", "--journal-root", str(self.journal), "--request", str(path)]
            code, _ = self.call(args); self.assertEqual(code, 2)

    def test_missing_journal_verify_does_not_create_directory(self):
        missing = self.root / "missing-journal"
        code, _ = self.call(["verify", "--journal-root", str(missing)])
        self.assertEqual(code, 2); self.assertFalse(missing.exists())

    def test_invalid_request_and_unsupported_show_reject(self):
        self.request["auto_trading_enabled"] = True; self.write_request()
        self.assertEqual(self.call(self.args("record"))[0], 2)
        self.assertEqual(self.call(["show", "--journal-root", str(self.journal), "--event-id", self.original["events"][0].event_id])[0], 2)
