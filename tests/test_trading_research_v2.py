"""Versioned historical-research semantics without legacy strategy inheritance."""
from __future__ import annotations

import copy
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_research import (
    TradingResearchDataset, TradingResearchIntents, TradingResearchPlan,
    validate_research_inputs,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_research_evaluation import evaluate_research, plan_chronological_splits
from blackpod_build_week.trading_research_evaluation import TradingResearchEvaluationError
from blackpod_build_week.trading_research_example import example_material
from test_trading_research_evaluation import ResearchEvaluationFixture


def versioned_fixture():
    """Authored test prices and references, not authenticated historical data."""
    fixture = ResearchEvaluationFixture()
    request = {"path": "historical/request.json", "sha256": "d" * 64, "size_bytes": 20}
    references = [request] + [
        {"path": "historical/source-%d.json" % index, "sha256": str(index) * 64, "size_bytes": 20}
        for index in range(1, 5)]
    fixture.dataset["schema_version"] = "blackpod.trading_research_dataset.v2"
    fixture.dataset["provenance"] = {
        "source_kind": "GOVERNED_HISTORICAL_INTAKE", "source_evidence": references,
        "timestamp_policy": "DECLARED_RETROSPECTIVE_SESSION_END_PLUS_LAG",
        "historical_point_in_time_verified": False,
        "governed_intake": {"intake_id": "authored-test-intake", "request_evidence": dict(request),
                            "method_version": "blackpod.alpaca_daily_history_projection.v1"},
        "availability_assumption": {"mode": "RETURNED_SESSION_END_PLUS_DECLARED_DELAY", "delay_seconds": 1,
                                    "declared_by": "synthetic-test-author", "rationale": "Authored test assumption only.",
                                    "assumption_verified": False},
    }
    fixture.plan["schema_version"] = "blackpod.trading_research_plan.v2"
    fixture.plan["evaluation_purpose"] = "DATA_QUALITY_ONLY"
    fixture.plan["frozen_hypothesis_evidence"] = {"path": "research/frozen-hypothesis.json", "sha256": "e" * 64, "size_bytes": 20}
    return fixture


class TradingResearchVersionedContractTests(unittest.TestCase):
    def setUp(self):
        self.f = versioned_fixture()
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))

    def reject_plan(self, mutation):
        value = copy.deepcopy(self.f.plan)
        mutation(value)
        with self.assertRaises(ContractValidationError):
            TradingResearchPlan.from_mapping(value)

    def reject_dataset(self, mutation):
        value = copy.deepcopy(self.f.dataset)
        mutation(value)
        with self.assertRaises(ContractValidationError):
            TradingResearchDataset.from_mapping(value)

    def test_v2_contracts_round_trip_without_mutating_inputs(self):
        for document, value in ((TradingResearchPlan, self.f.plan), (TradingResearchDataset, self.f.dataset)):
            before = canonical_json_bytes(value)
            typed = document.from_mapping(value)
            self.assertEqual(typed.to_bytes(), before)
            self.assertEqual(document.from_bytes(before).to_bytes(), before)
            typed.to_dict().clear()
            self.assertEqual(typed.to_bytes(), before)
            self.assertEqual(canonical_json_bytes(value), before)

    def test_missing_new_plan_fields_reject(self):
        for field in ("frozen_hypothesis_evidence", "evaluation_purpose"):
            with self.subTest(field=field):
                self.reject_plan(lambda row: row.pop(field))

    def test_unknown_top_level_fields_reject(self):
        self.reject_plan(lambda row: row.update(strategy_producer="native"))
        self.reject_dataset(lambda row: row.update(actual_publication_verified=True))

    def test_v2_plan_supports_only_data_quality_purpose(self):
        for purpose in ("EXTERNAL_INTENTS_ONLY", "BACKTEST", "PAPER_TRADING", "HYPOTHESIS_PRODUCER", None, 0):
            with self.subTest(purpose=purpose):
                self.reject_plan(lambda row: row.update(evaluation_purpose=purpose))

    def test_frozen_hypothesis_reference_strictness(self):
        for mutation in (
                lambda row: row["frozen_hypothesis_evidence"].update(path="../hypothesis.json"),
                lambda row: row["frozen_hypothesis_evidence"].update(sha256="invalid"),
                lambda row: row["frozen_hypothesis_evidence"].update(size_bytes=True),
                lambda row: row["frozen_hypothesis_evidence"].update(author="human"),
                lambda row: row.update(frozen_hypothesis_evidence=None)):
            self.reject_plan(mutation)

    def test_frozen_reference_cannot_alias_data_or_intents_path(self):
        for field in ("dataset_evidence", "intents_evidence"):
            self.reject_plan(lambda row: row["frozen_hypothesis_evidence"].update(path=row[field]["path"]))

    def test_strategy_independence_and_nonproducer_status_preserved(self):
        self.reject_plan(lambda row: row["strategy"].update(ancestry="GALACTICA_TRADING_RULES"))
        self.reject_plan(lambda row: row["strategy"].update(implementation_status="STRATEGY_READY"))

    def test_v2_plan_cannot_enable_auto_trading(self):
        for enabled in (True, 0, "false", None):
            self.reject_plan(lambda row: row.update(auto_trading_enabled=enabled))

    def test_v2_authority_cannot_be_granted(self):
        for field in self.f.plan["authority"]:
            self.reject_plan(lambda row: row["authority"].update({field: True}))
            self.reject_dataset(lambda row: row["authority"].update({field: True}))

    def test_v2_provenance_does_not_accept_v1_classifications(self):
        self.reject_dataset(lambda row: row["provenance"].update(source_kind="RETAINED_MARKET_CAPTURE"))
        self.reject_dataset(lambda row: row["provenance"].update(timestamp_policy="RETAINED_RECEIPT_AVAILABILITY"))

    def test_v2_provenance_requires_all_explicit_metadata(self):
        for field in ("governed_intake", "availability_assumption", "historical_point_in_time_verified"):
            self.reject_dataset(lambda row: row["provenance"].pop(field))

    def test_v2_provenance_unknown_fields_reject(self):
        self.reject_dataset(lambda row: row["provenance"].update(pit_proof="verified"))
        self.reject_dataset(lambda row: row["provenance"]["governed_intake"].update(provider_authenticated=True))
        self.reject_dataset(lambda row: row["provenance"]["availability_assumption"].update(actual=True))

    def test_v2_provenance_cannot_claim_point_in_time_verification(self):
        for claim in (True, "false", 0, None):
            self.reject_dataset(lambda row: row["provenance"].update(historical_point_in_time_verified=claim))
            self.reject_dataset(lambda row: row["provenance"]["availability_assumption"].update(assumption_verified=claim))

    def test_source_closure_requires_request_and_four_distinct_refs(self):
        self.reject_dataset(lambda row: row["provenance"]["source_evidence"].pop())
        self.reject_dataset(lambda row: row["provenance"]["source_evidence"].append(copy.deepcopy(row["provenance"]["source_evidence"][0])))
        self.reject_dataset(lambda row: row["provenance"]["source_evidence"][1].update(path=row["provenance"]["source_evidence"][0]["path"]))

    def test_governed_request_must_bind_exact_retained_reference(self):
        self.reject_dataset(lambda row: row["provenance"]["governed_intake"]["request_evidence"].update(sha256="f" * 64))
        self.reject_dataset(lambda row: row["provenance"]["governed_intake"]["request_evidence"].update(size_bytes=21))

    def test_governed_intake_identity_and_method_strictness(self):
        self.reject_dataset(lambda row: row["provenance"]["governed_intake"].update(intake_id=""))
        self.reject_dataset(lambda row: row["provenance"]["governed_intake"].update(method_version="unknown.v2"))

    def test_delay_rejects_boolean_negative_and_unbounded_values(self):
        for delay in (True, False, -1, 604801, "60", 1.0, None):
            self.reject_dataset(lambda row: row["provenance"]["availability_assumption"].update(delay_seconds=delay))

    def test_delay_allows_explicit_zero_and_maximum(self):
        for delay in (0, 604800):
            value = copy.deepcopy(self.f.dataset)
            value["provenance"]["availability_assumption"]["delay_seconds"] = delay
            self.assertEqual(TradingResearchDataset.from_mapping(value).provenance["availability_assumption"]["delay_seconds"], delay)

    def test_assumption_requires_declarer_rationale_and_exact_mode(self):
        for mutation in (
                lambda row: row["provenance"]["availability_assumption"].update(declared_by=""),
                lambda row: row["provenance"]["availability_assumption"].update(rationale=""),
                lambda row: row["provenance"]["availability_assumption"].update(mode="ACTUAL_CAPTURE_TIME"),
                lambda row: row["provenance"]["availability_assumption"].pop("declared_by")):
            self.reject_dataset(mutation)

    def test_assumed_availability_cannot_precede_regular_close_or_exceed_capture(self):
        self.reject_dataset(lambda row: row["sessions"][0].update(available_at=row["sessions"][0]["open_at"]))
        self.reject_dataset(lambda row: row["sessions"][0].update(available_at="2027-01-01T00:00:00Z"))

    def test_v2_preserves_ohlc_validation(self):
        self.reject_dataset(lambda row: row["sessions"][0]["bars"][0].update(close="101"))
        self.reject_dataset(lambda row: row["sessions"][0]["bars"][0].update(volume="-1"))

    def test_unknown_versions_do_not_gain_v2_fields(self):
        self.reject_dataset(lambda row: row.update(schema_version="blackpod.trading_research_dataset.v3"))
        self.reject_plan(lambda row: row.update(schema_version="blackpod.trading_research_plan.v3"))

    def test_v1_plan_cannot_consume_retrospective_v2_data(self):
        old = ResearchEvaluationFixture()
        with self.assertRaises(ContractValidationError):
            validate_research_inputs(old.plan, self.f.dataset, self.f.intents)

    def test_v2_plan_requires_governed_v2_data(self):
        old = ResearchEvaluationFixture()
        with self.assertRaises(ContractValidationError):
            validate_research_inputs(self.f.plan, old.dataset, self.f.intents)

    def test_v2_plan_requires_empty_intents(self):
        self.f.decision("synthetic-buy")
        with self.assertRaisesRegex(ContractValidationError, "empty intents"):
            validate_research_inputs(self.f.plan, self.f.dataset, self.f.intents)

    def test_v2_still_requires_matching_intent_plan(self):
        self.f.intents["plan_id"] = "other-plan"
        with self.assertRaises(ContractValidationError):
            validate_research_inputs(self.f.plan, self.f.dataset, self.f.intents)

    def test_v2_still_requires_matching_universe(self):
        self.f.plan["universe"] = ["BBB"]
        with self.assertRaises(ContractValidationError):
            validate_research_inputs(self.f.plan, self.f.dataset, self.f.intents)


class TradingResearchVersionedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.f = versioned_fixture()
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))

    def test_v2_data_quality_projection_cannot_invoke_simulator(self):
        with patch("blackpod_build_week.trading_research_evaluation._simulate_fold", side_effect=AssertionError("simulation forbidden")):
            report = self.f.report()
        self.assertEqual(report["schema_version"], "blackpod.trading_research_evaluation.v2")
        self.assertEqual(report["evaluation_purpose"], "DATA_QUALITY_ONLY")
        self.assertEqual(report["folds"][0]["status"], "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER")

    def test_v2_never_scores_performance_or_manufactures_decisions(self):
        report = self.f.report()
        for field in ("metrics", "benchmark"):
            self.assertIsNone(report["folds"][0][field])
        for field in ("decisions", "fills", "matched_lots", "open_lots", "equity_curve", "opening_equity_curve"):
            self.assertEqual(report["folds"][0][field], [])
        self.assertIsNone(report["aggregate"])
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertFalse(report["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_v2_assumptions_preserve_actual_receipt_distinction(self):
        report = self.f.report()
        semantics = report["availability_semantics"]
        self.assertEqual(semantics["classification"], "RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF")
        self.assertEqual(semantics["actual_receipt_availability"], "RETAINED_SOURCE_RECEIPTS_ONLY_NOT_PAST_PUBLICATION")
        self.assertEqual(semantics["modeled_historical_availability"], "DECLARED_RETROSPECTIVE_SESSION_END_PLUS_LAG")
        self.assertFalse(semantics["historical_point_in_time_verified"])
        self.assertEqual(semantics["availability_assumption"], self.f.dataset["provenance"]["availability_assumption"])

    def test_v2_preserves_source_and_hypothesis_identity_without_authentication_claims(self):
        report = self.f.report()
        self.assertEqual(report["source_artifact_binding"], self.f.dataset["provenance"]["governed_intake"])
        self.assertEqual(report["frozen_hypothesis_evidence"], self.f.plan["frozen_hypothesis_evidence"])
        self.assertEqual(report["hypothesis_status"], "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION")
        self.assertFalse(report["data_quality"]["source_provenance_authenticated"])
        self.assertFalse(report["data_quality"]["historical_source_reconstructed_by_pure_evaluator"])
        self.assertFalse(report["data_quality"]["model_training_verified"])
        self.assertFalse(report["data_quality"]["strategy_producer_present"])

    def test_v2_retains_limitations_revisions_survivorship_and_nonpreregistration(self):
        report = self.f.report()
        for code in ("RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF", "RETURNED_HISTORICAL_VALUES_MAY_INCLUDE_REVISIONS",
                     "SELECTED_UNIVERSE_NOT_SURVIVORSHIP_FREE", "FROZEN_HYPOTHESIS_IS_NOT_HISTORICAL_PREREGISTRATION",
                     "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER_OR_PERFORMANCE_ASSESSMENT"):
            self.assertIn(code, report["limitations"])

    def test_v2_preserves_purging_and_holdout_withholding(self):
        report = self.f.report()
        projection = report["protocol"]["folds"][0]
        self.assertEqual([row["source_index"] for row in projection["eligible_training_label_samples"]], [0, 1, 2])
        self.assertEqual(projection["purged_training_label_samples"][0]["source_index"], 3)
        self.assertIn("LABEL_TARGET_OUTSIDE_TRAIN", projection["purged_training_label_samples"][0]["reason_codes"])
        self.assertEqual(report["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertFalse(report["final_holdout"]["access_sealed"])

    def test_v2_split_projection_without_intents_matches_evaluation(self):
        self.assertEqual(plan_chronological_splits(self.f.plan, self.f.dataset), self.f.report()["protocol"])

    def test_v2_invalid_availability_retains_defer_without_scoring(self):
        self.f.dataset["sessions"][1]["available_at"] = "2026-06-07T17:00:00Z"
        report = self.f.report()
        self.assertEqual(report["folds"][0]["status"], "DEFER_SPLIT_AVAILABILITY_INVALID")
        self.assertTrue(report["data_quality"]["availability_failures"])
        self.assertIsNone(report["folds"][0]["metrics"])

    def test_v2_no_eligible_label_sample_defers(self):
        self.f.plan["horizon"]["label_horizon_sessions"] = 20
        report = self.f.report()
        self.assertEqual(report["folds"][0]["status"], "DEFER_SPLIT_AVAILABILITY_INVALID")
        self.assertEqual(report["protocol"]["folds"][0]["eligible_training_label_samples"], [])

    def test_v2_intraday_horizon_still_defers(self):
        self.f.plan["horizon"]["kind"] = "DAY"
        self.assertEqual(self.f.report()["folds"][0]["status"], "DEFER_UNSUPPORTED_DAY_HORIZON")

    def test_v2_nonempty_decisions_reject_before_projection(self):
        self.f.decision("buy")
        with patch("blackpod_build_week.trading_research_evaluation._split_projection", side_effect=AssertionError("projection forbidden")):
            with self.assertRaises(ContractValidationError):
                self.f.report()

    def test_v2_holdout_prices_do_not_change_data_quality_projection(self):
        before = self.f.report()
        for index in range(15, 18):
            self.f.price(index, opening="99", closing="1", volume="0")
        self.assertEqual(self.f.report(), before)

    def test_v2_projection_remains_bounded(self):
        large = ResearchEvaluationFixture(count=1100)
        self.f.dataset["sessions"] = large.dataset["sessions"]
        self.f.dataset["recorded_at"] = "2030-01-01T00:00:00Z"
        self.f.plan["protocol"] = {"embargo_sessions": 1,
            "final_holdout": {"start_index": 1090, "end_index": 1099},
            "folds": [{"fold_id": "fold-%d" % index, "train": {"start_index": 0, "end_index": 999},
                       "validation": {"start_index": 1001, "end_index": 1002},
                       "test": {"start_index": 1004 + index * 2, "end_index": 1005 + index * 2}}
                      for index in range(24)]}
        with self.assertRaisesRegex(TradingResearchEvaluationError, "20000"):
            self.f.report()

    def test_v2_inputs_remain_identical_and_result_does_not_alias_inputs(self):
        before = canonical_json_bytes([self.f.plan, self.f.dataset, self.f.intents])
        report = self.f.report()
        report["source_artifact_binding"]["request_evidence"]["path"] = "tampered-output.json"
        report["availability_semantics"]["availability_assumption"]["rationale"] = "tampered-output"
        self.assertEqual(canonical_json_bytes([self.f.plan, self.f.dataset, self.f.intents]), before)
        self.assertEqual(self.f.report()["source_artifact_binding"]["request_evidence"]["path"], "historical/request.json")


class TradingResearchVersionCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))

    def test_all_v1_example_documents_preserve_original_canonical_hashes(self):
        expected = {
            "plan": "6dfa2a20f4c6277fa0ec0293faf6183063b951025fb6d2565d9c14599f878397",
            "dataset": "4e9c757877bd77d99aac5da6af4e24772ec57bef80705030f447f151e13e337d",
            "intents": "3091c4b1b7e1309243420b21d1108482d08ff52200a612bb50031ca40414f4e6",
            "result": "8be014e03745e7eed610df0d44275a6fb6aaf37121100b2d48a71b1f85cddb14",
            "plan_event": "3ddc1c8287fe0cb9295d78153053fe3e600b6188306c0892079ddaeaa8b344dd",
            "evaluation_event": "8ccd5be8dbce4065eaf2f3eb09a7086fb7efdeea88a01bbf1195888fe518459c",
        }
        material = example_material()
        for key, digest in expected.items():
            value = material[key]
            raw = value.to_bytes() if hasattr(value, "to_bytes") else canonical_json_bytes(value)
            with self.subTest(document=key):
                self.assertEqual(sha256_bytes(raw), digest)

    def test_v1_supplied_decision_evaluation_preserves_original_hash(self):
        fixture = ResearchEvaluationFixture()
        fixture.decision("buy")
        fixture.decision("sell", source=8, action="SELL", qty="2")
        self.assertEqual(sha256_bytes(canonical_json_bytes(fixture.report())),
                         "3ef208f2a3f2d42f0118ce413bbb58b6a318958e6117dcef2b009161bf9bf3e9")


if __name__ == "__main__":
    unittest.main()
