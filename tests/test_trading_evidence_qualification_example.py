"""Qualification fixtures preserve old research and all operational boundaries."""
import ast
import contextlib
import inspect
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_evidence_qualification_example as example
from blackpod_build_week.contracts.trading_evidence_qualification import (
    TradingEvidenceQualificationPolicy, TradingEvidenceQualificationRequest,
)
from blackpod_build_week.contracts.mission_request import parse_rfc3339
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.trading_evidence_qualification import qualify_evidence


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class QualificationExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve() / "qualification-example"
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

    def case(self, identity="clean-declared-design"):
        return next(row for row in self.material["cases"] if row["case_id"] == identity)

    def test_four_cases_distinguish_readiness_from_insufficient_inactive_or_contaminated_evidence(self):
        self.assertEqual([row["status"] for row in self.summary["cases"]], [
            "READY_FOR_QUALIFIED_STUDY_DESIGN", "DEFER_EVIDENCE_QUALIFICATION",
            "DEFER_EVIDENCE_QUALIFICATION", "DEFER_EVIDENCE_QUALIFICATION"])
        self.assertTrue(self.case()["result"]["eligible_for_study_design"])
        self.assertFalse(self.case("insufficient-joint-sample")["result"]["eligible_for_study_design"])
        self.assertFalse(self.case("inactive-proposed-design")["result"]["eligible_for_study_design"])
        self.assertFalse(self.case("forbidden-holdout-cost-evidence")["result"]["eligible_for_study_design"])

    def test_twenty_two_events_preserve_fourteen_original_v16_fixture_events(self):
        original = self.material["original"]["events"]
        self.assertEqual(len(original), 14)
        self.assertEqual(len(self.events), 22)
        self.assertEqual([event.to_bytes() for event in self.events[:14]],
                         [event.to_bytes() for event in original])
        self.assertTrue(all(event.schema_version == "blackpod.decision_journal_event.v18"
                            for event in self.events[14:]))

    def test_policy_is_recorded_before_its_linked_qualification(self):
        positions = {event.event_id: index for index, event in enumerate(self.events)}
        for row in self.material["cases"]:
            self.assertLess(positions[row["policy_event"].event_id], positions[row["assessment_event"].event_id])
            self.assertEqual(row["request"].policy_event_id, row["policy_event"].event_id)
            self.assertEqual(row["assessment_event"].payload["policy_event_id"], row["policy_event"].event_id)
            self.assertLess(parse_rfc3339(row["policy"].recorded_at, "freeze"),
                            parse_rfc3339(row["request"].recorded_at, "assessment"))

    def test_policy_and_result_append_to_original_hypothesis_decision(self):
        catalog = self.material["original"]["events"][0]
        for row in self.material["cases"]:
            self.assertEqual(row["policy_event"].decision_id, catalog.decision_id)
            self.assertEqual(row["assessment_event"].decision_id, catalog.decision_id)
            self.assertEqual(row["policy_event"].payload["links"]["hypothesis_event_id"], catalog.event_id)

    def test_training_quote_rows_are_exact_authored_subsets_of_unchanged_source(self):
        material = self.material
        old_ref = material["original"]["costs"]["request"].quote_pages[0]["body_evidence"]
        old = json.loads(material["blobs"][old_ref["sha256"]])
        self.assertEqual(sum(len(rows) for rows in old["quotes"].values()), 80)
        count = 0
        for chain in material["training_quote_chains"]:
            page = chain["pages"][0]
            body = json.loads(material["blobs"][page["body_evidence"]["sha256"]])
            for symbol, rows in body["quotes"].items():
                for row in rows:
                    self.assertIn(row, old["quotes"][symbol])
                count += len(rows)
        self.assertEqual(count, 24)
        self.assertTrue(self.summary["new_quote_bodies_are_authored_subsets_not_provider_captures"])

    def test_training_query_and_all_rows_exclude_validation_test_and_holdout(self):
        material = self.material
        fold = material["plan"].protocol["folds"][0]
        sessions = material["dataset"].sessions
        training_dates = {sessions[index]["open_at"][:10]
                          for index in range(fold["train"]["start_index"], fold["train"]["end_index"] + 1)}
        for chain in material["training_quote_chains"]:
            for page in chain["pages"]:
                body = json.loads(material["blobs"][page["body_evidence"]["sha256"]])
                receipt = json.loads(material["blobs"][page["receipt_evidence"]["sha256"]])
                self.assertEqual(receipt["query"]["start"], sessions[fold["train"]["start_index"]]["open_at"])
                self.assertTrue(all(row["t"][:10] in training_dates
                                    for rows in body["quotes"].values() for row in rows))
                self.assertEqual(receipt["body_sha256"], page["body_evidence"]["sha256"])

    def test_clean_training_coverage_is_twelve_quotes_per_symbol_without_real_cost_claims(self):
        calibration = self.case()["result"]["training_calibration"]
        self.assertEqual(calibration["status"], "READY_FOR_SHADOW_QUALIFICATION")
        fold = calibration["folds"][0]
        self.assertEqual(fold["native_quote_count"], 24)
        self.assertEqual(fold["missing_symbol_sessions"], [])
        self.assertEqual([row["eligible_quote_count"] for row in fold["training_measurements"]], [12, 12])
        self.assertFalse(calibration["cost_applicability_verified"])
        self.assertFalse(calibration["opening_execution_capacity_verified"])

    def test_spread_observations_and_declared_fee_slippage_have_separate_origins(self):
        row = self.case()
        assumptions = self.material["assumptions"]
        self.assertEqual(assumptions.parameters, {"slippage_bps": "5", "fee_bps": "0", "fee_per_fill": "0.10"})
        origin = assumptions.origin_evidence[0]
        self.assertIn(b"not estimated from strategy returns", self.blobs[origin["sha256"]])
        model = row["result"]["training_calibration"]["folds"][0]["cost_model"]
        self.assertEqual(model["spread_bps"], "9.995002498750624688")
        self.assertEqual(model["slippage_bps"], assumptions.parameters["slippage_bps"])
        self.assertFalse(row["result"]["provenance"]["provider_authenticity_verified"])

    def test_capacity_is_daily_volume_proxy_and_never_opening_fill_capacity(self):
        fold = self.case()["result"]["training_calibration"]["folds"][0]
        self.assertTrue(all(row["daily_quantity_research_proxy"] == "100" for row in fold["capacity_proxy"]))
        self.assertTrue(all(row["minimum_training_daily_volume"] == "10000" for row in fold["capacity_proxy"]))
        self.assertFalse(fold["opening_execution_capacity_verified"])
        self.assertTrue(all(not row["opening_fill_capacity_verified"]
                            for row in self.case()["result"]["risk"]["capacity_checks"]))

    def test_proposed_policy_keeps_missing_protocol_and_assumptions_explicit(self):
        row = self.case("inactive-proposed-design")
        self.assertEqual(row["policy"].status, "PROPOSED")
        self.assertIsNone(row["policy"].training_cost_assumptions_evidence)
        self.assertIsNone(row["policy"].uncertainty_protocol)
        self.assertIn("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW", row["result"]["reason_codes"])
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", row["result"]["reason_codes"])

    def test_holdout_contamination_is_retained_and_contributes_no_calibration_measurements(self):
        row = self.case("forbidden-holdout-cost-evidence")
        self.assertIn("NONTRAINING_QUOTE_EVIDENCE_REJECTED", row["result"]["reason_codes"])
        fold = row["result"]["training_calibration"]["folds"][0]
        self.assertEqual(fold["native_quote_count"], 80)
        self.assertTrue(fold["quote_evidence_contaminated"])
        self.assertIsNone(fold["training_measurements"])
        self.assertIsNone(fold["cost_model"])
        self.assertFalse(fold["eligible"])

    def test_pre_signal_windows_include_eligible_rows_and_explicit_exit_boundary_deferrals(self):
        result = self.case()["result"]["continuity"]
        self.assertEqual(result["counts"]["opportunities"], 18)
        self.assertEqual(result["counts"]["combined_eligible"], 16)
        self.assertEqual(result["counts"]["deferred"], 2)
        self.assertTrue(any("DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST" in row["reason_codes"]
                            for row in result["opportunities"]))
        self.assertEqual(result["price_policy"], "RAW_UNMODIFIED_NO_REINDEX")

    def test_joint_sample_counts_use_distinct_dates_and_do_not_lower_frozen_minimum(self):
        clean, insufficient = self.case(), self.case("insufficient-joint-sample")
        self.assertEqual(clean["policy"].uncertainty_protocol, insufficient["policy"].uncertainty_protocol)
        self.assertEqual(clean["policy"].uncertainty_protocol["minimum_evaluation_sessions"], 8)
        clean_dates = {row["source_session_id"] for row in clean["result"]["risk"]["capacity_checks"] if row["joint_eligible"]}
        insufficient_dates = {row["source_session_id"] for row in insufficient["result"]["risk"]["capacity_checks"] if row["joint_eligible"]}
        self.assertEqual(len(clean_dates), 8)
        self.assertEqual(len(insufficient_dates), 6)
        self.assertIn("DECLARED_UNCERTAINTY_QUALIFIED_SAMPLE_INFEASIBLE", insufficient["result"]["reason_codes"])
        self.assertEqual(insufficient["result"]["uncertainty_status"], "INFEASIBLE")
        self.assertEqual(clean["hypothesis_id"], "previous-session-reversal-v1")
        self.assertEqual(insufficient["hypothesis_id"], "five-session-continuation-v1")
        self.assertFalse(clean["result"]["economic_hypothesis_supported"])
        self.assertFalse(insufficient["result"]["economic_hypothesis_supported"])

    def test_uncertainty_protocol_is_frozen_without_computing_statistics_or_economic_support(self):
        result = self.case()["result"]
        self.assertEqual(result["uncertainty_status"], "FROZEN_NOT_EVALUATED")
        self.assertEqual(result["uncertainty_protocol"], example.fixture_uncertainty_protocol())
        self.assertFalse(result["uncertainty_computed"])
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertFalse(result["uncertainty_protocol"]["parameter_search_allowed"])
        self.assertEqual(result["provenance"]["design_freeze_semantics"], "DESIGN_FROZEN_BEFORE_THIS_CALIBRATION_ONLY")

    def test_no_old_gate_override_or_final_holdout_scoring(self):
        for row in self.material["cases"]:
            result = row["result"]
            self.assertFalse(result["existing_gate_override"])
            self.assertEqual(result["continuity"]["final_holdout"]["scoring_status"], "WITHHELD")
            self.assertEqual(result["continuity"]["final_holdout"]["start_index"], 35)
            self.assertEqual(result["continuity"]["final_holdout"]["end_index"], 39)
            self.assertIsNone(result["realized_trade_pnl"])
            self.assertEqual(result["execution_status"], "NOT_EXECUTED")

    def test_qualification_itself_does_not_generate_intents_or_compute_strategy_returns(self):
        row = self.case()
        with patch("blackpod_build_week.trading_shadow_intents.produce_shadow_intents", side_effect=AssertionError("intent production forbidden")), \
             patch("blackpod_build_week.trading_shadow_evaluation.evaluate_shadow_study", side_effect=AssertionError("return scoring forbidden")):
            result = qualify_evidence(row["request"], self.events, self.blobs)["result"]
        self.assertEqual(result, row["result"])
        self.assertFalse(result["uncertainty_computed"])

    def test_all_execution_capital_policy_and_authenticated_approval_flags_remain_off(self):
        for row in self.material["cases"]:
            result = row["result"]
            self.assertFalse(result["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in result["authority"].values()))
            self.assertFalse(result["provenance"]["reviewer_identity_authenticated"])
            self.assertFalse(result["provenance"]["historical_point_in_time_verified"])
        self.assertEqual(self.summary["provider_calls"], 0)
        self.assertEqual(self.summary["orders_submitted"], 0)
        self.assertEqual(self.summary["model_inference_calls"], 0)
        self.assertFalse(self.summary["desk_budget_activated"])
        self.assertFalse(self.summary["capital_transfers_enabled"])

    def test_journal_verifies_complete_retention_without_orphans(self):
        verification = self.summary["journal_verification"]
        self.assertEqual(verification["event_count"], 22)
        self.assertEqual(verification["orphan_evidence_count"], 0)
        self.assertEqual(verification["staging_orphan_count"], 0)
        self.assertGreater(verification["evidence_count"], 53)

    def test_exported_policy_and_request_bytes_are_strict_and_replayable(self):
        for row in self.summary["cases"]:
            policy = TradingEvidenceQualificationPolicy.from_bytes((self.root / row["policy_path"]).read_bytes())
            request = TradingEvidenceQualificationRequest.from_bytes((self.root / row["request_path"]).read_bytes())
            self.assertEqual(policy.policy_id, row["policy_id"])
            result = qualify_evidence(request, self.events, self.blobs)["result"]
            self.assertEqual(result["status"], row["status"])
            self.assertEqual(json.loads((self.root / row["result_path"]).read_bytes()), result)

    def test_exact_example_retry_preserves_all_files_and_mtimes(self):
        before = state(self.root)
        result = example.prepare_example(self.root)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["journal_verification"], self.summary["journal_verification"])
        self.assertEqual(state(self.root), before)

    def test_retained_journal_replays_without_exported_inputs_or_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "copy"
            shutil.copytree(self.root, root)
            shutil.rmtree(root / "input")
            shutil.rmtree(root / "evidence")
            self.assertEqual(JournalStore(root / "journal").verify().to_dict(),
                             self.summary["journal_verification"])

    def test_example_contains_no_legacy_strategy_or_provider_import(self):
        tree = ast.parse(inspect.getsource(example))
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(any(name in module for name in ("galactica", "alpaca", "modeldock", "navigator_adapter"))
                             for module in modules))

    def test_symlink_output_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                status = example.main(["--output-root", str(link)])
            self.assertEqual(status, 2)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(error.getvalue())


if __name__ == "__main__":
    unittest.main()
