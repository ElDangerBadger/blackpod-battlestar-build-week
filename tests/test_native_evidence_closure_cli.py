"""Offline lifecycle and bounded, opaque supplemental evidence loading."""
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

from blackpod_build_week.contracts.native_evidence_closure import (
    CATEGORIES, SUPPLEMENTAL_VERSION, NativeEvidenceSupplementalReview,
    NativeEvidenceClosureReviewRequest,
)
from blackpod_build_week.native_evidence_closure_cli import main, build_parser, _read, load_review_evidence
from blackpod_build_week.native_evidence_closure_example import request_for, _ref, _authority
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError


class OfflineBoundaryAndEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.anchor = type("Anchor", (), {"event_id": "journal-event-" + "a" * 64})()

    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output): code = main(args)
        return code, json.loads(output.getvalue())

    def material(self, *, extra=None):
        opaque = b'[{"evidence":{"path":"must-not-be-read.raw"}},"declaration only"]'
        sources = [{"evidence": _ref("source.raw", opaque), "source_url": "https://example.invalid/declared",
            "captured_at": None, "effective_coverage_start_at": None, "effective_coverage_end_at": None}]
        if extra is not None: sources.append(extra)
        supplemental = NativeEvidenceSupplementalReview.from_mapping({
            "schema_version": SUPPLEMENTAL_VERSION, "supplemental_review_id": "cli-authored-review",
            "recorded_at": "2025-04-07T10:00:00Z", "anchor_qualification_event_id": self.anchor.event_id,
            "candidate_qualification_event_id": None, "reviewer_id": "authored-unverified", "review_notes": "fixture only",
            "categories": [{"category": category, "status": "SOURCE_REVIEW_RECORDED", "source_event_ids": [],
                "source_documents": sources, "notes": "unauthenticated source declaration"} for category in CATEGORIES],
            "auto_trading_enabled": False, "authority": _authority()})
        request = request_for(self.anchor, review_id="cli-review", supplemental=_ref("supplemental.json", supplemental.to_bytes()))
        return request, supplemental, opaque

    def write(self, supplemental, opaque):
        (self.root / "supplemental.json").write_bytes(supplemental.to_bytes())
        (self.root / "source.raw").write_bytes(opaque)

    def test_exact_five_commands_have_no_activation_capture_or_execution_options(self):
        action = next(action for action in build_parser()._actions if isinstance(getattr(action, "choices", None), dict))
        self.assertEqual(set(action.choices), {"prepare", "assess", "record", "show", "verify"})
        for parser in action.choices.values():
            options = {option for item in parser._actions for option in item.option_strings}
            self.assertFalse(options & {"--credential-source", "--broker", "--auto-trading", "--activate", "--allow-market-data-get"})

    def test_missing_journal_verify_and_prepare_create_nothing(self):
        missing, output = self.root / "missing", self.root / "request.json"
        self.assertEqual(self.call(["verify", "--journal-root", str(missing)])[0], 2)
        code, result = self.call(["prepare", "--journal-root", str(missing), "--output", str(output),
            "--review-id", "missing", "--recorded-at", "2025-04-08T10:00:00Z", "--data-cutoff-at", "2025-04-08T10:00:00Z",
            "--anchor-qualification-event-id", self.anchor.event_id])
        self.assertEqual(code, 2); self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(missing.exists()); self.assertFalse(output.exists())

    def test_read_rejects_symlink_hardlink_ancestor_and_parent_traversal(self):
        target = self.root / "target.json"; target.write_bytes(b"{}")
        link = self.root / "link.json"; link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)): _read(link)
        link.unlink(); os.link(target, link)
        with self.assertRaises((OSError, ValueError)): _read(link)
        folder = self.root / "folder"; folder.mkdir()
        ancestor = self.root / "ancestor"; ancestor.symlink_to(folder, target_is_directory=True)
        with self.assertRaises((OSError, ValueError, JournalStoreError)): _read(ancestor / "missing.json")
        with self.assertRaisesRegex(ValueError, "traverse"): _read(folder / ".." / "target.json")

    def test_only_typed_leaf_references_are_loaded_and_opaque_bytes_preserved(self):
        request, supplemental, opaque = self.material(); self.write(supplemental, opaque)
        blobs = load_review_evidence(request, {}, self.root)
        self.assertEqual(blobs[sha256_bytes(opaque)], opaque)
        self.assertEqual(len(blobs), 2)
        self.assertFalse((self.root / "must-not-be-read.raw").exists())

    def test_closed_retained_evidence_requires_no_external_root(self):
        request, supplemental, opaque = self.material()
        blobs = {sha256_bytes(supplemental.to_bytes()): supplemental.to_bytes(), sha256_bytes(opaque): opaque}
        self.assertEqual(load_review_evidence(request, blobs, None), blobs)

    def test_missing_unretained_leaf_requires_explicit_root(self):
        request, supplemental, _ = self.material()
        with self.assertRaisesRegex(ValueError, "explicit evidence root"):
            load_review_evidence(request, {sha256_bytes(supplemental.to_bytes()): supplemental.to_bytes()}, None)

    def test_rehashed_wrapper_does_not_allow_changed_leaf(self):
        request, supplemental, opaque = self.material(); self.write(supplemental, opaque)
        (self.root / "source.raw").write_bytes(opaque + b" ")
        with self.assertRaisesRegex(ValueError, "hash or size"): load_review_evidence(request, {}, self.root)

    def test_retained_leaf_is_reverified_instead_of_trusted(self):
        request, supplemental, opaque = self.material()
        with self.assertRaisesRegex(ValueError, "hash or size"):
            load_review_evidence(request, {sha256_bytes(supplemental.to_bytes()): supplemental.to_bytes(), sha256_bytes(opaque): b"different"}, None)

    def test_distinct_reference_and_total_byte_bounds_precede_external_reads(self):
        request, supplemental, opaque = self.material(); self.write(supplemental, opaque)
        with patch("blackpod_build_week.native_evidence_closure_cli.MAX_REVIEW_REFERENCES", 1):
            with self.assertRaisesRegex(ValueError, "bound"): load_review_evidence(request, {}, self.root)
        with patch("blackpod_build_week.native_evidence_closure_cli.MAX_REVIEW_BYTES", len(supplemental.to_bytes()) + len(opaque) - 1):
            with self.assertRaisesRegex(ValueError, "bound"): load_review_evidence(request, {}, self.root)

    def test_conflicting_declared_path_is_rejected(self):
        second = {"evidence": _ref("source.raw", b"different"), "source_url": None,
            "captured_at": None, "effective_coverage_start_at": None, "effective_coverage_end_at": None}
        request, supplemental, opaque = self.material(extra=second); self.write(supplemental, opaque)
        with self.assertRaisesRegex(ValueError, "conflicting"): load_review_evidence(request, {}, self.root)


class NativeClosureCliLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_native_evidence_closure_journal import retained_closure_fixture
        cls.material, cls.source_request, cls.qualification, cls.base, cls.retained_temp = retained_closure_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.journal = self.root / "journal"
        shutil.copytree(self.base, self.journal)
        self.inputs = self.root / "input"; self.inputs.mkdir()
        self.request = NativeEvidenceClosureReviewRequest.from_mapping({**self.source_request.to_dict(), "review_id": "new-cli-closure"})
        self.request_path = self.inputs / "request.json"; self.request_path.write_bytes(self.request.to_bytes())

    def call(self, arguments):
        output = io.StringIO()
        with redirect_stdout(output): code = main(arguments)
        return code, json.loads(output.getvalue())

    def test_prepare_has_no_assessment_append_or_external_source_loading(self):
        before = [event.to_bytes() for event in JournalStore(self.journal).events()]
        inputs = self.inputs / "prepare-inputs.json"
        inputs.write_bytes(canonical_json_bytes({"supplemental_review_evidence": self.request.supplemental_review_evidence}))
        output = self.root / "prepared" / "request.json"
        code, result = self.call(["prepare", "--journal-root", str(self.journal), "--output", str(output),
            "--inputs", str(inputs), "--review-id", "prepared-cli", "--recorded-at", self.request.recorded_at,
            "--data-cutoff-at", self.request.data_cutoff_at, "--anchor-qualification-event-id", self.request.anchor_qualification_event_id])
        self.assertEqual(code, 0, result); self.assertFalse(result["assessment_performed"])
        self.assertFalse(result["supplemental_sources_loaded"])
        self.assertEqual([event.to_bytes() for event in JournalStore(self.journal).events()], before)

    def test_assess_is_immutable_and_never_appends(self):
        before = [event.to_bytes() for event in JournalStore(self.journal).events()]
        output = self.root / "reports" / "result.json"
        args = ["assess", "--request", str(self.request_path), "--journal-root", str(self.journal), "--output", str(output)]
        code, result = self.call(args); self.assertEqual(code, 0, result)
        report = output.read_bytes(); self.assertEqual(self.call(args)[0], 0); self.assertEqual(output.read_bytes(), report)
        self.assertFalse(json.loads(report)["native_gate_override"])
        self.assertEqual([event.to_bytes() for event in JournalStore(self.journal).events()], before)

    def test_record_retry_show_verify_and_original_source_bytes(self):
        before = [event.to_bytes() for event in JournalStore(self.journal).events()]
        args = ["record", "--request", str(self.request_path), "--journal-root", str(self.journal)]
        code, result = self.call(args); self.assertEqual(code, 0, result); self.assertTrue(result["written"])
        retry_code, retry = self.call(args)
        self.assertEqual(retry_code, 0, retry)
        self.assertFalse(retry["written"])
        code, shown = self.call(["show", "--journal-root", str(self.journal), "--event-id", result["event_id"]])
        self.assertEqual(code, 0, shown); self.assertEqual(shown["payload"]["result"]["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(shown["payload"]["result"]["realized_trade_pnl"])
        self.assertEqual([event.to_bytes() for event in JournalStore(self.journal).events()[:len(before)]], before)
        code, verified = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, verified); self.assertEqual(verified["event_count"], len(before) + 1)

    def test_journal_and_source_tree_cannot_be_report_storage(self):
        for output in (self.journal / "forbidden.json", Path(__file__).resolve().parents[1] / "src" / "forbidden-native-review.json"):
            code, result = self.call(["assess", "--request", str(self.request_path), "--journal-root", str(self.journal), "--output", str(output)])
            self.assertEqual(code, 2, result); self.assertFalse(output.exists())

    def test_show_rejects_native_qualification_instead_of_review(self):
        code, result = self.call(["show", "--journal-root", str(self.journal), "--event-id", self.request.anchor_qualification_event_id])
        self.assertEqual(code, 2, result)


if __name__ == "__main__": unittest.main()
