"""Offline typed reads, early write guards and the five-command lifecycle."""
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

from blackpod_build_week.contracts.reconciled_shadow_qualification import ReconciledShadowQualificationRequest
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.reconciled_shadow_qualification_cli import main, build_parser, load_qualification_evidence, _read


class TypedReaderAndGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_reconciled_shadow_qualification_example import fixture_material
        cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.request = self.material["request"]
        result = self.material["original"]["result"]
        self.references = [self.request.intake_result_evidence, result["policy_evidence"], result["dataset_evidence"], result["original_native_masks"]["evidence"]]
        self.blobs = {ref["sha256"]: self.material["blobs"][ref["sha256"]] for ref in self.references}

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): code = main(args)
        return code, json.loads(out.getvalue())

    def write_sources(self):
        for reference in self.references:
            path = self.root / reference["path"]; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.blobs[reference["sha256"]])

    def test_exactly_five_commands_expose_no_authority_evidence_or_provider_switch(self):
        command = next(item for item in build_parser()._actions if isinstance(getattr(item, "choices", None), dict))
        self.assertEqual(set(command.choices), {"prepare", "assess", "record", "show", "verify"})
        for parser in command.choices.values():
            options = {option for item in parser._actions for option in item.option_strings}
            self.assertFalse(options & {"--status", "--coverage", "--risk", "--cost", "--activate", "--allow-market-data-get", "--credential-source", "--auto-trading", "--broker", "--policy"})

    def test_schema_only_prepare_never_reads_or_claims_verified_history(self):
        inputs = self.root / "inputs" / "prepare.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({key: getattr(self.request, key) for key in ("intake_event_id", "intake_result_evidence", "supersedes_event_id")}))
        output = self.root / "prepared" / "request.json"
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("must not scan")):
            code, result = self.call(["prepare", "--qualification-id", self.request.qualification_id, "--recorded-at", self.request.recorded_at,
                "--data-cutoff-at", self.request.data_cutoff_at, "--inputs", str(inputs), "--output", str(output)])
        self.assertEqual(code, 0, result); self.assertFalse(result["source_history_verified"]); self.assertFalse(result["assessment_performed"])
        self.assertEqual(output.read_bytes(), self.request.to_bytes())

    def test_prepare_rejects_extra_governance_fields_and_changed_request_bytes(self):
        inputs = self.root / "inputs" / "prepare.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({key: getattr(self.request, key) for key in ("intake_event_id", "intake_result_evidence", "supersedes_event_id")} | {"coverage_complete": True}))
        code, result = self.call(["prepare", "--qualification-id", self.request.qualification_id, "--recorded-at", self.request.recorded_at,
            "--data-cutoff-at", self.request.data_cutoff_at, "--inputs", str(inputs), "--output", str(self.root / "prepared" / "request.json")])
        self.assertEqual(code, 2, result)
        with self.assertRaises(ValueError): ReconciledShadowQualificationRequest.from_mapping({**self.request.to_dict(), "auto_trading_enabled": True})

    def test_typed_traversal_reads_only_four_bound_leaves_not_raw_source_inventories(self):
        self.write_sources(); loaded = load_qualification_evidence(self.request, {}, self.root)
        self.assertEqual(loaded, self.blobs)
        inventory = self.material["original"]["policy"].independent_inventories[0]
        self.assertNotIn(inventory["sha256"], loaded)

    def test_retained_closure_needs_no_external_files(self):
        with patch("blackpod_build_week.evidence_reconciliation_cli._read", side_effect=AssertionError("external reads forbidden")):
            self.assertEqual(load_qualification_evidence(self.request, self.blobs, None), self.blobs)

    def test_missing_changed_and_corrupt_retained_leaves_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "explicit evidence root"): load_qualification_evidence(self.request, {}, None)
        self.write_sources(); mask = self.references[-1]; (self.root / mask["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash or size"): load_qualification_evidence(self.request, {}, self.root)
        retained = dict(self.blobs); retained[mask["sha256"]] = b"changed"
        with self.assertRaisesRegex(ValueError, "hash or size"): load_qualification_evidence(self.request, retained, None)

    def test_combined_reference_and_byte_bounds_reject_before_unbounded_reads(self):
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_REFERENCES", 2):
            with self.assertRaisesRegex(ValueError, "bound"): load_qualification_evidence(self.request, self.blobs, None)
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "bound"): load_qualification_evidence(self.request, self.blobs, None)

    def test_unsafe_input_links_and_parent_traversal_reject(self):
        target = self.root / "target"; target.write_bytes(b"source"); link = self.root / "link"; link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)): _read(link)
        link.unlink(); os.link(target, link)
        with self.assertRaises((OSError, ValueError)): _read(link)
        with self.assertRaisesRegex(ValueError, "traverse"): _read(self.root / "child" / ".." / "target")

    def test_protected_output_paths_reject_before_source_scan(self):
        repository = Path(__file__).resolve().parents[1]
        runtime = self.root / "runtime"; runtime.mkdir(); (runtime / "worker.lock").write_bytes(b"")
        journal = self.root / "journal"; journal.mkdir()
        for output in (repository / "src" / "forbidden-shadow.json", repository / ".git" / "forbidden-shadow.json", runtime / "child" / "result.json", journal / "report.json"):
            with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("guard first")):
                code, result = self.call(["assess", "--request", str(self.root / "input" / "missing.json"), "--journal-root", str(journal), "--output", str(output)])
            self.assertEqual(code, 2, result); self.assertFalse(output.exists())

    def test_missing_verify_does_not_create_storage_or_read_verified_contents(self):
        journal = self.root / "missing-journal"
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("verify must use one verify scan")):
            code, result = self.call(["verify", "--journal-root", str(journal)])
        self.assertEqual(code, 2, result); self.assertFalse(journal.exists())


class ReconciledShadowLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_reconciled_shadow_qualification_example import retained_fixture
        cls.material, cls.base, cls.retained_temp = retained_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out): code = main(args)
        return code, json.loads(out.getvalue())

    def test_assess_record_exact_retry_show_verify_preserve_source_bytes(self):
        original = {path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}
        request = ReconciledShadowQualificationRequest.from_mapping({**self.material["request"].to_dict(),
            "qualification_id": "cli-linked-shadow-qualification", "recorded_at": "2025-04-12T12:00:00Z", "data_cutoff_at": "2025-04-12T11:00:00Z",
            "supersedes_event_id": self.material["event"].event_id})
        request_file = self.root / "inputs" / "request.json"; request_file.parent.mkdir(); request_file.write_bytes(request.to_bytes())
        report = self.root / "reports" / "qualification.json"
        code, assessed = self.call(["assess", "--request", str(request_file), "--journal-root", str(self.journal), "--output", str(report)])
        self.assertEqual(code, 0, assessed); self.assertFalse(assessed["journal_written"])
        self.assertEqual({path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}, original)
        args = ["record", "--request", str(request_file), "--journal-root", str(self.journal)]
        code, recorded = self.call(args); self.assertEqual(code, 0, recorded); self.assertTrue(recorded["written"])
        code, retried = self.call(args); self.assertEqual(code, 0, retried); self.assertFalse(retried["written"])
        code, shown = self.call(["show", "--event-id", recorded["event_id"], "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, shown); self.assertEqual(shown["payload"]["result"], json.loads(report.read_bytes()))
        self.assertEqual(shown["payload"]["request"]["supersedes_event_id"], self.material["event"].event_id)
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("verify must not pre-scan")):
            code, summary = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, summary); self.assertEqual(summary["event_count"], len(original) + 1)
        self.assertEqual(summary["orphan_evidence_count"], 0); self.assertEqual(summary["staging_orphan_count"], 0)
        self.assertEqual({name: (self.journal / "entries" / name).read_bytes() for name in original}, original)

    def test_show_rejects_old_intake_and_projection_failure_does_not_append(self):
        code, result = self.call(["show", "--event-id", self.material["intake_event"].event_id, "--journal-root", str(self.journal)])
        self.assertEqual(code, 2, result)
        request = ReconciledShadowQualificationRequest.from_mapping({**self.material["request"].to_dict(), "qualification_id": "excluded-source-clock", "data_cutoff_at": "2025-04-01T00:00:00Z"})
        request_file = self.root / "inputs" / "request.json"; request_file.parent.mkdir(); request_file.write_bytes(request.to_bytes())
        count = len(tuple((self.journal / "entries").glob("*.json")))
        code, result = self.call(["record", "--request", str(request_file), "--journal-root", str(self.journal)])
        self.assertEqual(code, 2, result); self.assertEqual(len(tuple((self.journal / "entries").glob("*.json"))), count)


if __name__ == "__main__": unittest.main()
