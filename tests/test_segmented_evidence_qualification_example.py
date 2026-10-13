"""One offline fixture chain exercises collection versus design qualification."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import segmented_evidence_qualification_example as example
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class SegmentedQualificationExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve() / "example"
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("provider forbidden")):
            cls.material = example.example_material()
            cls.summary = example.prepare_example(cls.root)
            cls.events, cls.blobs = JournalStore(cls.root / "journal").verified_contents()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def case(self, identity="full-reversal"):
        return next(row for row in self.material["cases"] if row["case_id"] == identity)

    def test_seven_expected_cases_distinguish_collection_and_governed_design_readiness(self):
        self.assertEqual(len(self.summary["cases"]), 7)
        self.assertEqual([row["status"] for row in self.summary["cases"]],
                         ["READY_FOR_QUALIFIED_STUDY_DESIGN"] + ["DEFER_EVIDENCE_QUALIFICATION"] * 6)
        self.assertEqual(self.summary["data_status"], "SYNTHETIC_FIXTURE_ONLY")

    def test_full_reversal_uses_segmented_method_and_preserves_the_old_incompatibility_marker(self):
        row = self.case()
        result = row["result"]
        self.assertEqual(result["training_calibration"]["calibration_source"], "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY")
        self.assertFalse(result["provenance"]["old_policy_quote_chains_used"])
        self.assertFalse(result["provenance"]["old_policy_cost_model_overridden"])
        self.assertEqual(result["provenance"]["v19_consumer_v18_status"], "INCOMPATIBLE_SEGMENTED_INPUT")
        self.assertTrue(result["eligible_for_study_design"])
        self.assertFalse(result["existing_gate_override"])

    def test_partial_and_terminal_empty_exports_keep_missing_pairs_and_defer(self):
        partial, empty = self.case("partial-reversal"), self.case("terminal-empty-reversal")
        self.assertEqual(partial["capture"]["result"]["counts"]["missing_symbol_sessions"], 20)
        self.assertEqual(empty["capture"]["result"]["counts"]["missing_symbol_sessions"], 2)
        self.assertFalse(partial["capture"]["result"]["capture_complete"])
        self.assertTrue(empty["capture"]["result"]["capture_complete"])
        for row in (partial, empty):
            self.assertFalse(row["result"]["eligible_for_study_design"])
            self.assertIn("TRAIN_SYMBOL_SESSION_COVERAGE_INCOMPLETE", row["result"]["reason_codes"])

    def test_continuation_keeps_the_same_sample_minimum_and_is_not_a_profitability_comparison(self):
        reversal, continuation = self.case(), self.case("insufficient-continuation")
        self.assertEqual(reversal["policy"].uncertainty_protocol, continuation["policy"].uncertainty_protocol)
        self.assertEqual(reversal["policy"].uncertainty_protocol["minimum_evaluation_sessions"], 8)
        for row, count in ((reversal, 8), (continuation, 6)):
            dates = {item["source_session_id"] for item in row["result"]["risk"]["capacity_checks"] if item["joint_eligible"]}
            self.assertEqual(len(dates), count)
            self.assertFalse(row["result"]["economic_hypothesis_supported"])
            self.assertFalse(row["result"]["uncertainty_computed"])
        self.assertIn("DECLARED_UNCERTAINTY_QUALIFIED_SAMPLE_INFEASIBLE", continuation["result"]["reason_codes"])

    def test_inactive_proposed_policy_and_missing_assumptions_remain_deferred(self):
        proposed, missing = self.case("inactive-proposed"), self.case("missing-assumptions")
        self.assertEqual(proposed["policy"].status, "PROPOSED")
        self.assertIn("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW", proposed["result"]["reason_codes"])
        self.assertIsNone(missing["policy"].training_cost_assumptions_evidence)
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", missing["result"]["reason_codes"])

    def test_quotes_do_not_manufacture_independent_coverage_and_native_evidence_is_separate(self):
        full = self.case()["result"]["provenance"]
        self.assertTrue(full["inherited_native_coverage_supported"])
        self.assertEqual(full["export_continuity_coverage"]["status"], "UNRESOLVED")
        self.assertFalse(full["export_continuity_packet_applied_to_native_windows"])
        missing = self.case("missing-independent-coverage")
        self.assertTrue(missing["capture"]["result"]["coverage_complete"])
        self.assertIsNone(missing["policy"].continuity_event_id)
        self.assertIn("CONTINUITY_SOURCE_MISSING", missing["result"]["reason_codes"])
        self.assertFalse(missing["result"]["eligible_for_study_design"])

    def test_original_twenty_two_events_and_policies_are_byte_identical(self):
        original = self.material["original"]["events"]
        self.assertEqual(len(original), 22)
        self.assertEqual([event.to_bytes() for event in self.events[:22]], [event.to_bytes() for event in original])
        for row in self.material["cases"]:
            event = next(event for event in self.events if event.event_id == row["policy_event"].event_id)
            self.assertEqual(event.payload["policy"], row["policy"].to_dict())
            self.assertEqual(sha256_bytes(row["policy"].to_bytes()), row["result"]["provenance"]["original_policy_sha256"])

    def test_new_consumer_retains_compact_refs_without_copying_raw_pages(self):
        by_id = {event.event_id: event for event in self.events}
        for row in self.material["cases"]:
            assessment = by_id[row["qualification_event"].event_id]
            page_digests = {ref["sha256"] for identity in row["capture"]["result"]["segment_event_ids"]
                for page in by_id[identity].payload["request"]["pages"] for ref in page.values()}
            retained = {ref["sha256"] for ref in assessment.evidence}
            self.assertTrue(page_digests)
            self.assertFalse(page_digests & retained)
            self.assertTrue(page_digests <= set(self.blobs))
        self.assertFalse(self.summary["raw_corpus_duplicated_by_consumer"])

    def test_authored_sources_do_not_claim_operational_capture_or_historical_authentication(self):
        for row in self.material["cases"]:
            provenance = row["result"]["provenance"]
            self.assertFalse(provenance["capture_audit_selected"])
            self.assertFalse(provenance["source_authentication_verified"])
            self.assertFalse(provenance["historical_point_in_time_verified"])
            self.assertFalse(provenance["reviewer_identity_authenticated"])
            self.assertIn("CAPTURE_OPERATION_AUDIT_NOT_SELECTED", row["result"]["limitations"])
        self.assertFalse(self.summary["operational_capture_audit_claimed"])

    def test_no_execution_capital_inference_returns_or_holdout_authority(self):
        self.assertEqual(self.summary["provider_calls"], 0)
        self.assertEqual(self.summary["real_credential_files_read"], 0)
        self.assertEqual(self.summary["model_inference_calls"], 0)
        self.assertEqual(self.summary["orders_submitted"], 0)
        self.assertFalse(self.summary["new_strategy_returns_computed"])
        self.assertFalse(self.summary["desk_budget_activated"])
        self.assertFalse(self.summary["capital_transfers_enabled"])
        self.assertFalse(self.summary["final_holdout_scored"])
        for row in self.material["cases"]:
            result = row["result"]
            self.assertFalse(result["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in result["authority"].values()))
            self.assertEqual(result["execution_status"], "NOT_EXECUTED")
            self.assertIsNone(result["realized_trade_pnl"])

    def test_one_mixed_version_journal_has_all_eighty_four_events_without_orphans(self):
        verification = self.summary["journal_verification"]
        self.assertEqual(verification["event_count"], 84)
        self.assertEqual(verification["orphan_evidence_count"], 0)
        self.assertEqual(verification["staging_orphan_count"], 0)
        self.assertEqual(sum(event.schema_version == "blackpod.decision_journal_event.v20" for event in self.events), 14)

    def test_identical_example_retry_verifies_prefix_and_writes_no_event(self):
        before = state(self.root)
        with patch.object(JournalStore, "append", side_effect=AssertionError("verified full prefix must not be republished")), \
             patch("blackpod_build_week.decision_journal_batch.append_journal_batch",
                   side_effect=AssertionError("verified full prefix requires no publication")):
            result = example.prepare_example(self.root)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["journal_verification"], self.summary["journal_verification"])
        self.assertEqual(state(self.root), before)

    def test_exact_retry_finishes_an_interrupted_valid_prefix_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "interrupted"
            shutil.copytree(self.root, root)
            entries = sorted((root / "journal" / "entries").glob("*.json"))
            for entry in entries[80:]:
                entry.unlink()
            original_prefix = {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
                               for path in entries[:80]}
            result = example.prepare_example(root)
            self.assertEqual(result["events_written"], 4)
            self.assertEqual(result["journal_verification"], self.summary["journal_verification"])
            self.assertEqual({path: (root.joinpath(path).read_bytes(), root.joinpath(path).stat().st_mtime_ns)
                              for path in original_prefix}, original_prefix)

    def test_retained_only_replay_survives_export_removal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "copy"
            shutil.copytree(self.root, root)
            shutil.rmtree(root / "input"); shutil.rmtree(root / "evidence")
            self.assertEqual(JournalStore(root / "journal").verify().to_dict(), self.summary["journal_verification"])

    def test_symlink_output_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target"; target.mkdir()
            link = root / "link"; link.symlink_to(target, target_is_directory=True)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = example.main(["--output-root", str(link)])
            self.assertEqual(status, 2)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(errors.getvalue())


if __name__ == "__main__":
    unittest.main()
