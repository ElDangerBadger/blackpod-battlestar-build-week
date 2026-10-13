"""Runnable synthetic shadow review examples, without providers or inference."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.desk_candidate_review import DeskReviewInput
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.desk_candidate_review import build_desk_review_event, evidence_for_desk_review
from blackpod_build_week.desk_candidate_review_cli import main as desk_cli, load_evidence, _references
from blackpod_build_week.desk_review_example import ACCOUNT_ID, example_material, fixture_native_sources, main, prepare_example
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


class DeskCandidateReviewExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "synthetic-example"
        self.addCleanup(self.temporary.cleanup)

    def call(self, function, argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = function(argv)
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def tree(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_pure_material_contains_no_test_import_dependency_or_actual_account(self):
        material = example_material()
        self.assertEqual(material["review"].account_id, ACCOUNT_ID)
        self.assertTrue(ACCOUNT_ID.startswith("synthetic-"))
        self.assertFalse(any(material["review"].authority.values()))
        self.assertFalse(material["event"].payload["result"]["auto_trading_enabled"])
        self.assertEqual(material["event"].payload["result"]["budgets_usd"], {"TRADING": "10190.63", "INVESTMENT": "10190.63"})
        source = (Path(__file__).resolve().parents[1] / "src/blackpod_build_week/desk_review_example.py").read_text()
        self.assertNotIn("from test_", source)
        self.assertNotIn("import test_", source)

    def test_material_bytes_and_native_source_closure_are_deterministic(self):
        first, second = example_material(), example_material()
        self.assertEqual(first["event"].to_bytes(), second["event"].to_bytes())
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertGreaterEqual(len(fixture_native_sources()), 24)

    def test_committed_review_template_matches_regenerated_synthetic_material(self):
        path = Path(__file__).resolve().parents[1] / "examples/desk_candidate_review.shadow.v1.json"
        template = DeskReviewInput.from_bytes(path.read_bytes())
        self.assertEqual(template.to_bytes(), example_material()["review"].to_bytes())

    def test_prepare_is_idempotent_and_seed_is_verified(self):
        first = prepare_example(self.root)
        retained = self.tree()
        second = prepare_example(self.root)
        self.assertTrue(first["seed_written"])
        self.assertFalse(second["seed_written"])
        self.assertEqual(self.tree(), retained)
        store = JournalStore(self.root / "journal")
        self.assertEqual(len(store.events()), 1)
        self.assertEqual(store.events()[0].payload["snapshot"]["capture_provenance"]["source_kind"], "SYNTHETIC_FIXTURE")
        self.assertEqual(store.verify().orphan_evidence_count, 0)

    def test_preparation_and_cli_record_assess_show_use_no_socket_or_subprocess(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")):
            prepared = self.call(main, ["--output-root", str(self.root)])
            args = ["--journal-root", str(self.root / "journal"), "--review", str(self.root / "review.json"), "--evidence-root", str(self.root / "evidence")]
            assessment = self.call(desk_cli, ["assess", *args])
            recorded = self.call(desk_cli, ["record", *args])
            self.assertEqual(assessment["event_id"], prepared["expected_event_id"])
            self.assertEqual(recorded["event_id"], prepared["expected_event_id"])
            self.assertTrue(recorded["written"])
            self.assertFalse(self.call(desk_cli, ["record", *args])["written"])
            shown = self.call(desk_cli, ["show", "--journal-root", str(self.root / "journal"), "--event-id", prepared["expected_event_id"]])
            self.assertEqual(shown["payload"]["result"], recorded["result"])
            self.assertEqual(JournalStore(self.root / "journal").verify().event_count, 2)

    def test_original_brigade_dissent_date_precision_and_missing_member_are_visible(self):
        material = example_material()
        analysis = json.loads(material["evidence"]["shadow-desk/analysis.json"])
        brigade = analysis["galactica"]["brigade"]
        self.assertEqual(brigade["source_as_of"], "2026-04-24")
        self.assertEqual(brigade["source_time_precision"], "DATE_ONLY_TIMEZONE_UNSPECIFIED")
        self.assertTrue(brigade["stale"])
        self.assertEqual(brigade["member_coverage"][0]["missing_members"], ["Blackwell_Decay"])
        self.assertEqual(brigade["parsed_report"]["symbols"][0]["decision"]["dissent"], ["Risk"])
        self.assertFalse(brigade["current_generation_enabled"])

    def test_reloaded_files_reproduce_material_without_test_fixture_imports(self):
        prepared = prepare_example(self.root)
        document = DeskReviewInput.from_bytes((self.root / "review.json").read_bytes())
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        blobs = load_evidence(self.root / "evidence", _references(document.to_dict()), blobs)
        event = build_desk_review_event(document, events, blobs)
        self.assertEqual(event.event_id, prepared["expected_event_id"])
        self.assertGreaterEqual(len(evidence_for_desk_review(document, events, blobs)), 30)
        self.assertFalse(event.payload["result"]["readiness"])
        self.assertIsNone(event.payload["result"]["realized_trade_pnl"])

    def test_verified_example_renders_reproducibly_as_passive_html(self):
        prepared = prepare_example(self.root)
        args = ["--journal-root", str(self.root / "journal"), "--review", str(self.root / "review.json"), "--evidence-root", str(self.root / "evidence")]
        self.call(desk_cli, ["record", *args])
        target = self.root / "reports" / "review.html"
        result = self.call(desk_cli, ["render", "--journal-root", str(self.root / "journal"), "--event-id", prepared["expected_event_id"], "--output", str(target)])
        raw = target.read_bytes()
        self.assertEqual(result["sha256"], sha256_bytes(raw))
        self.assertIn(b"AUTO-TRADING AUTHORITY OFF", raw)
        self.assertIn(b"current runtime status is checked separately", raw)
        self.assertIn(b"Synthetic fixture", raw)
        self.assertIn(b"NO ORDER AUTHORIZATION", raw)
        self.assertEqual(result["sha256"], self.call(desk_cli, ["render", "--journal-root", str(self.root / "journal"), "--event-id", prepared["expected_event_id"], "--output", str(target)])["sha256"])

    def test_canonical_source_or_fixture_overlap_rejected_before_writes(self):
        for target in (Path(__file__).resolve().parents[1] / "fixtures" / "synthetic-write-test", self.root / "missions" / "mission-test"):
            with self.assertRaises((ValueError, JournalStoreError)): prepare_example(target)
            self.assertFalse(target.exists())

    def test_symlink_and_existing_journal_ancestor_rejected_before_writes(self):
        prepare_example(self.root)
        before = self.tree()
        alias = Path(self.temporary.name).resolve() / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        for target in (alias / "new-example", self.root / "journal" / "new-example"):
            with self.assertRaises((ValueError, JournalStoreError)): prepare_example(target)
            self.assertFalse(target.exists())
        self.assertEqual(before, self.tree())

    def test_changed_example_file_conflicts_instead_of_overwrite(self):
        prepare_example(self.root)
        target = self.root / "review.json"
        target.write_bytes(b"unrelated existing bytes")
        with self.assertRaises(ValueError): prepare_example(self.root)
        self.assertEqual(target.read_bytes(), b"unrelated existing bytes")

    def test_invalid_source_fixture_fails_without_creating_output(self):
        fixtures = Path(self.temporary.name).resolve() / "broken-fixtures"
        (fixtures / "shadow_native_analysis").mkdir(parents=True)
        (fixtures / "shadow_native_analysis/source_bundle.v1.json").write_bytes(b'{"sources":{}}')
        with self.assertRaises(ValueError): prepare_example(self.root, fixture_root=fixtures)
        self.assertFalse(self.root.exists())


if __name__ == "__main__": unittest.main()
