"""Offline sizing declarations: no optimality, future prices or desk activation."""
from __future__ import annotations

import copy
from decimal import Inexact, Rounded, localcontext
import inspect
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_shadow_risk_review as engine
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.contracts.trading_shadow_risk_review import (
    RISK_REVIEW_LIMITATIONS, TradingShadowRiskReview,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_trading_shadow_intents import producer_fixture, rebind, reference


def risk_review_fixture():
    original = producer_fixture(universe=["SYNTHA", "SYNTHB"])
    support = b"Invented fixture sizing specification. It approves simulation only.\n"
    support_ref = {"path": "fixture/sizing-brief.raw", "sha256": sha256_bytes(support), "size_bytes": len(support)}
    review = {
        "schema_version": "blackpod.trading_shadow_risk_review.v1", "risk_review_id": "fixture-risk-review",
        "recorded_at": "2026-07-03T00:00:00Z", "reviewer_id": "fixture-author",
        "review_notes": "Deterministic invented sizing checks; no trading policy or empirical edge.",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "SIMULATION_SIZING_ONLY",
        "status": "APPROVED_FOR_SHADOW", "base_plan_evidence": original["study"]["base_plan_evidence"],
        "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "simulation_risk": {
            "initial_cash": "1000", "max_order_notional": "100", "max_position_fraction": "0.2",
            "max_gross_exposure_fraction": "0.5", "max_volume_participation_fraction": "0.1",
            "max_staleness_seconds": 604800,
        },
        "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "100"},
        "source_evidence": [support_ref], "limitations": list(RISK_REVIEW_LIMITATIONS),
        "auto_trading_enabled": False, "authority": original["study"]["authority"],
    }
    blobs = {sha256_bytes(support): support}
    for document in (original["base_plan"], original["dataset"]):
        raw = canonical_json_bytes(document)
        blobs[sha256_bytes(raw)] = raw
    return {"review": review, "base_plan": original["base_plan"], "dataset": original["dataset"],
            "blobs": blobs, "study_registered_at": "2026-07-04T00:00:00Z"}


def rebind_risk_fixture(fixture):
    source = {"base_plan": fixture["base_plan"], "dataset": fixture["dataset"],
              "hypothesis": producer_fixture(universe=fixture["base_plan"]["universe"])["hypothesis"],
              "study": {}}
    rebind(source)
    fixture["review"]["base_plan_evidence"] = source["study"]["base_plan_evidence"]
    for document in (fixture["base_plan"], fixture["dataset"]):
        body = canonical_json_bytes(document)
        fixture["blobs"][sha256_bytes(body)] = body


class TradingShadowRiskReviewTests(unittest.TestCase):
    def setUp(self):
        self.f = risk_review_fixture()
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def review(self):
        return TradingShadowRiskReview.from_mapping(self.f["review"])

    def assess(self):
        return engine.assess_shadow_risk_review(**self.f)

    def test_strict_review_round_trip_and_immutable_nested_fields(self):
        typed = self.review()
        self.assertEqual(typed.to_mapping(), self.f["review"])
        self.assertEqual(TradingShadowRiskReview.from_bytes(typed.to_bytes()), typed)
        risk = typed.simulation_risk
        risk["initial_cash"] = "5"
        self.assertEqual(typed.simulation_risk["initial_cash"], "1000")
        with self.assertRaises((AttributeError, TypeError)):
            typed.status = "APPROVED_FOR_TRADING"

    def test_unknown_top_level_field_rejected(self):
        self.f["review"]["optimal"] = True
        with self.assertRaises(ContractValidationError): self.review()

    def test_missing_top_level_field_rejected(self):
        del self.f["review"]["review_notes"]
        with self.assertRaises(ContractValidationError): self.review()

    def test_unknown_version_domain_mode_scope_rejected(self):
        for field, value in (("schema_version", "future.v1"), ("domain", "INVESTMENT"),
                             ("mode", "PAPER"), ("scope", "DESK_ALLOCATION")):
            with self.subTest(field=field):
                self.f = risk_review_fixture(); self.f["review"][field] = value
                with self.assertRaises(ContractValidationError): self.review()

    def test_order_approval_status_rejected(self):
        self.f["review"]["status"] = "APPROVED_TO_TRADE"
        with self.assertRaises(ContractValidationError): self.review()

    def test_each_nonapproved_status_defers(self):
        for status in ("PROPOSED", "REJECTED", "DEFERRED"):
            with self.subTest(status=status):
                self.f["review"]["status"] = status
                report = self.assess()
                self.assertFalse(report["eligible"])
                self.assertIn("RISK_REVIEW_NOT_APPROVED_FOR_SHADOW", report["reason_codes"])

    def test_enabled_authority_or_autotrading_rejected(self):
        self.f["review"]["auto_trading_enabled"] = True
        with self.assertRaises(ContractValidationError): self.review()
        for field in self.f["review"]["authority"]:
            with self.subTest(field=field):
                self.f = risk_review_fixture(); self.f["review"]["authority"][field] = True
                with self.assertRaises(ContractValidationError): self.review()

    def test_truthy_numeric_autotrading_rejected(self):
        self.f["review"]["auto_trading_enabled"] = 0
        with self.assertRaises(ContractValidationError): self.review()

    def test_risk_fields_closed_and_all_required(self):
        for field in self.f["review"]["simulation_risk"]:
            with self.subTest(field=field):
                self.f = risk_review_fixture(); del self.f["review"]["simulation_risk"][field]
                with self.assertRaises(ContractValidationError): self.review()
        self.f = risk_review_fixture(); self.f["review"]["simulation_risk"]["leverage"] = "2"
        with self.assertRaises(ContractValidationError): self.review()

    def test_nondecimal_negative_zero_and_unbounded_risk_rejected(self):
        for value in (0, True, "-1", "0", "NaN", "1e3", "100000000000000000001"):
            with self.subTest(value=value):
                self.f = risk_review_fixture(); self.f["review"]["simulation_risk"]["initial_cash"] = value
                with self.assertRaises(ContractValidationError): self.review()

    def test_fraction_bound_and_type_rejected(self):
        for value in ("0", "1.01", "-0.1", 0.1):
            with self.subTest(value=value):
                self.f = risk_review_fixture(); self.f["review"]["simulation_risk"]["max_position_fraction"] = value
                with self.assertRaises(ContractValidationError): self.review()

    def test_staleness_boolean_and_out_of_range_rejected(self):
        for value in (True, 0, 366 * 86400 + 1):
            self.f["review"]["simulation_risk"]["max_staleness_seconds"] = value
            with self.assertRaises(ContractValidationError): self.review()

    def test_sizing_method_must_use_known_close(self):
        self.f["review"]["sizing"]["method"] = "NEXT_OPEN_OPTIMAL_QUANTITY"
        with self.assertRaises(ContractValidationError): self.review()

    def test_per_symbol_notional_must_fit_order_cap(self):
        self.f["review"]["sizing"]["per_symbol_notional"] = "101"
        with self.assertRaises(ContractValidationError): self.review()

    def test_per_symbol_notional_must_fit_position_cap(self):
        self.f["review"]["simulation_risk"]["max_position_fraction"] = "0.09"
        with self.assertRaises(ContractValidationError): self.review()

    def test_per_symbol_notional_must_fit_cash(self):
        self.f["review"]["simulation_risk"].update(initial_cash="50", max_position_fraction="1")
        with self.assertRaises(ContractValidationError): self.review()

    def test_source_evidence_nonempty_distinct_safe(self):
        for value in ([], [self.f["review"]["source_evidence"][0]] * 2,
                      [{"path": "../secret", "sha256": "a" * 64, "size_bytes": 1}]):
            self.f["review"]["source_evidence"] = value
            with self.assertRaises(ContractValidationError): self.review()

    def test_source_evidence_cannot_be_original_base_plan(self):
        self.f["review"]["source_evidence"] = [self.f["review"]["base_plan_evidence"]]
        with self.assertRaises(ContractValidationError): self.review()

    def test_mandatory_limitations_preserved(self):
        for limitation in RISK_REVIEW_LIMITATIONS:
            self.f["review"]["limitations"] = [item for item in RISK_REVIEW_LIMITATIONS if item != limitation]
            with self.assertRaises(ContractValidationError): self.review()

    def test_unknown_evidence_scope_rejected(self):
        self.f["review"]["evidence_scope"] = "LIVE_ACCOUNT"
        with self.assertRaises(ContractValidationError): self.review()

    def test_empty_notes_rejected(self):
        self.f["review"]["review_notes"] = "   "
        with self.assertRaises(ContractValidationError): self.review()

    def test_valid_fixture_assesses_full_universe_and_every_test_opportunity(self):
        report = self.assess()
        self.assertTrue(report["eligible"])
        self.assertEqual(report["status"], "READY_FOR_SHADOW_SIZING")
        self.assertEqual(report["opportunity_counts"], {"total": 24, "feasible_known_close": 24, "deferred": 0})
        self.assertEqual(report["budget_bounds"]["full_universe_declared_notional"], "200")
        self.assertEqual(report["budget_bounds"]["maximum_equal_symbol_notional_at_initial_cash"], "100")
        first = report["opportunities"][0]
        self.assertEqual(first["source_session_index"], 7)
        self.assertEqual(first["known_close"], "33")
        self.assertEqual(first["whole_quantity"], "3")
        self.assertEqual(first["known_close_notional"], "99")
        self.assertEqual(first["unallocated_symbol_budget"], "1")
        self.assertFalse(first["execution_or_fill_authorized"])

    def test_review_preserves_unapproved_and_unauthenticated_authority_semantics(self):
        report = self.assess()
        self.assertFalse(report["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        for field in ("reviewer_identity_authenticated", "human_execution_approval_verified", "desk_budget_activated", "strategy_selection_or_tuning_performed"):
            self.assertIs(report["provenance"][field], False)
        self.assertEqual(report["provenance"]["review_notes"], self.f["review"]["review_notes"])

    def test_exact_support_bytes_retained(self):
        material = engine.shadow_risk_review_material(**self.f)
        ref = self.f["review"]["source_evidence"][0]
        self.assertEqual(material["evidence"], {ref["path"]: self.f["blobs"][ref["sha256"]]})
        self.assertTrue(material["assessment"]["provenance"]["source_evidence_hash_verified"])

    def test_missing_blobs_cannot_make_review_eligible(self):
        self.f["blobs"] = None
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertIn("RISK_REVIEW_SOURCE_EVIDENCE_UNVERIFIED", report["reason_codes"])

    def test_missing_source_hash_rejected(self):
        ref = self.f["review"]["source_evidence"][0]
        del self.f["blobs"][ref["sha256"]]
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_rehashed_source_still_binds_original_reference(self):
        ref = self.f["review"]["source_evidence"][0]
        self.f["blobs"][ref["sha256"]] = b"x" * ref["size_bytes"]
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_nonbytes_source_rejected(self):
        ref = self.f["review"]["source_evidence"][0]
        self.f["blobs"][ref["sha256"]] = "fixture"
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_incorrect_source_size_rejected(self):
        self.f["review"]["source_evidence"][0]["size_bytes"] += 1
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_source_path_cannot_disguise_original_dataset(self):
        self.f["review"]["source_evidence"][0]["path"] = self.f["base_plan"]["dataset_evidence"]["path"]
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_plan_hash_mismatch_rejected(self):
        self.f["base_plan"]["risk"]["max_staleness_seconds"] += 1
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_dataset_hash_mismatch_rejected(self):
        self.f["dataset"]["sessions"][0]["bars"][0]["close"] = "20"
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_retained_plan_or_dataset_bytes_must_match_context(self):
        ref = self.f["review"]["base_plan_evidence"]
        self.f["blobs"][ref["sha256"]] = b"x" * ref["size_bytes"]
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_requires_plan_v2(self):
        self.f["base_plan"]["schema_version"] = "blackpod.trading_research_plan.v1"
        del self.f["base_plan"]["frozen_hypothesis_evidence"]
        del self.f["base_plan"]["evaluation_purpose"]
        self.f["review"]["base_plan_evidence"] = reference("fixture/base-plan.json", self.f["base_plan"])
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_review_cannot_precede_plan_freeze_or_dataset_capture(self):
        for when in ("2026-04-30T00:00:00Z", "2026-06-30T00:00:00Z"):
            self.f["review"]["recorded_at"] = when
            with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_review_cannot_follow_new_study_freeze(self):
        self.f["study_registered_at"] = "2026-07-02T00:00:00Z"
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_study_freeze_can_equal_review_clock(self):
        self.f["study_registered_at"] = self.f["review"]["recorded_at"]
        self.assertTrue(self.assess()["eligible"])

    def test_full_universe_declared_budget_exceeding_gross_defers_without_autotuning(self):
        self.f["review"]["simulation_risk"]["max_gross_exposure_fraction"] = "0.15"
        before = copy.deepcopy(self.f["review"])
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertIn("FULL_UNIVERSE_DECLARED_NOTIONAL_EXCEEDS_GROSS_CAP", report["reason_codes"])
        self.assertEqual(report["simulation_risk"], before["simulation_risk"])
        self.assertEqual(report["sizing"], before["sizing"])
        self.assertEqual(self.f["review"], before)

    def test_full_universe_cash_cap_cannot_be_exceeded(self):
        self.f["review"]["simulation_risk"].update(initial_cash="150", max_position_fraction="1", max_gross_exposure_fraction="1")
        report = self.assess()
        self.assertIn("FULL_UNIVERSE_DECLARED_NOTIONAL_EXCEEDS_CASH_CAP", report["reason_codes"])
        self.assertFalse(report["eligible"])

    def test_budget_below_one_share_is_per_opportunity_defer(self):
        self.f["review"]["sizing"]["per_symbol_notional"] = "30"
        report = self.assess()
        self.assertTrue(report["eligible"])
        self.assertGreater(report["opportunity_counts"]["deferred"], 0)
        self.assertIn("KNOWN_CLOSE_BUDGET_BELOW_ONE_WHOLE_SHARE", report["opportunities"][0]["reason_codes"])

    def test_all_budget_below_one_share_defers_entire_review(self):
        self.f["review"]["sizing"]["per_symbol_notional"] = "1"
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertEqual(report["opportunity_counts"]["feasible_known_close"], 0)
        self.assertIn("ALL_TEST_SIZING_OPPORTUNITIES_INFEASIBLE", report["reason_codes"])

    def test_known_volume_cap_is_reported_without_quantity_reduction(self):
        self.f["review"]["simulation_risk"]["max_volume_participation_fraction"] = "0.0001"
        report = self.assess()
        self.assertFalse(report["eligible"])
        first = report["opportunities"][0]
        self.assertEqual(first["whole_quantity"], "3")
        self.assertEqual(first["maximum_quantity_from_known_volume"], "0.1")
        self.assertIn("KNOWN_VOLUME_PARTICIPATION_CAP_EXCEEDED", first["reason_codes"])

    def test_future_open_prices_do_not_change_sizing_rows(self):
        before = self.assess()
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]: bar["open"] = "99"
        rebind_risk_fixture(self.f)
        after = self.assess()
        self.assertEqual(before["opportunities"], after["opportunities"])
        self.assertEqual(before["opportunity_counts"], after["opportunity_counts"])

    def test_holdout_prices_and_volumes_do_not_change_sizing_rows(self):
        before = self.assess()
        for session in self.f["dataset"]["sessions"][21:]:
            for bar in session["bars"]: bar.update(close="99", open="99", volume="0")
        rebind_risk_fixture(self.f)
        after = self.assess()
        self.assertEqual(before["opportunities"], after["opportunities"])
        self.assertEqual(before["opportunity_counts"], after["opportunity_counts"])

    def test_only_source_completed_close_sizes_each_row(self):
        before = self.assess()["opportunities"][0]
        self.f["dataset"]["sessions"][7]["bars"][0]["close"] = "25"
        rebind_risk_fixture(self.f)
        first = self.assess()["opportunities"][0]
        self.assertNotEqual(first["whole_quantity"], before["whole_quantity"])
        self.assertEqual(first["whole_quantity"], "4")
        self.assertEqual(first["known_close_notional"], "100")

    def test_ephemeral_projection_changes_only_risk_preserves_original_bytes(self):
        original = canonical_json_bytes(self.f["base_plan"])
        projected = engine.project_reviewed_base_plan(self.f["review"], self.f["base_plan"])
        self.assertIsInstance(projected, TradingResearchPlan)
        expected = copy.deepcopy(self.f["base_plan"])
        expected["risk"] = self.f["review"]["simulation_risk"]
        self.assertEqual(projected.to_mapping(), expected)
        self.assertEqual(canonical_json_bytes(self.f["base_plan"]), original)
        self.assertNotEqual(projected.to_bytes(), original)
        self.assertEqual(projected.plan_id, self.f["base_plan"]["plan_id"])

    def test_ephemeral_projection_does_not_convert_proposal_to_approval(self):
        self.f["review"]["status"] = "PROPOSED"
        projected = engine.project_reviewed_base_plan(self.f["review"], self.f["base_plan"])
        self.assertEqual(projected.risk, self.f["review"]["simulation_risk"])
        self.assertFalse(self.assess()["eligible"])

    def test_decimal_context_and_traps_do_not_change_deterministic_result(self):
        expected = self.assess()
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(self.assess(), expected)
            self.assertEqual(self.review().simulation_risk, self.f["review"]["simulation_risk"])

    def test_typed_and_mapping_inputs_produce_same_report(self):
        before = self.assess()
        self.f["review"] = self.review()
        self.f["base_plan"] = TradingResearchPlan.from_mapping(self.f["base_plan"])
        self.assertEqual(self.assess(), before)

    def test_repeated_results_identical_and_input_objects_unchanged(self):
        before = copy.deepcopy(self.f)
        self.assertEqual(self.assess(), self.assess())
        self.assertEqual(self.f, before)

    def test_synthetic_scope_cannot_apply_to_real_symbol(self):
        real = producer_fixture(universe=["QQQ", "SPY"])
        self.f["base_plan"], self.f["dataset"] = real["base_plan"], real["dataset"]
        rebind_risk_fixture(self.f)
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertIn("RISK_REVIEW_SYNTHETIC_SCOPE_REQUIRES_CONTROLLED_FIXTURE", report["reason_codes"])

    def test_real_scope_cannot_disguise_synthetic_symbols(self):
        self.f["review"]["evidence_scope"] = "RETAINED_HISTORY_RESEARCH"
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertIn("RISK_REVIEW_RETAINED_SCOPE_REJECTS_SYNTHETIC_SYMBOLS", report["reason_codes"])

    def test_declared_real_scope_can_use_retained_real_symbols_without_authentication(self):
        real = producer_fixture(universe=["QQQ", "SPY"])
        self.f["base_plan"], self.f["dataset"] = real["base_plan"], real["dataset"]
        self.f["review"]["evidence_scope"] = "RETAINED_HISTORY_RESEARCH"
        self.f["review"]["status"] = "PROPOSED"
        rebind_risk_fixture(self.f)
        report = self.assess()
        self.assertEqual(report["reason_codes"], ["RISK_REVIEW_NOT_APPROVED_FOR_SHADOW"])
        self.assertEqual(report["evidence_scope"], "RETAINED_HISTORY_RESEARCH")
        self.assertFalse(report["provenance"]["reviewer_identity_authenticated"])

    def test_test_range_beyond_retained_history_rejected(self):
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 19
        self.f["dataset"]["sessions"] = self.f["dataset"]["sessions"][:19]
        rebind_risk_fixture(self.f)
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_quantity_contract_bound_is_deferred_not_fitted(self):
        self.f["review"]["simulation_risk"].update(
            initial_cash="99999999999999999999", max_order_notional="99999999999999999999",
            max_position_fraction="1", max_gross_exposure_fraction="1")
        self.f["review"]["sizing"]["per_symbol_notional"] = "1"
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar.update(open="0.000000000000000001", high="0.000000000000000001",
                           low="0.000000000000000001", close="0.000000000000000001",
                           volume="99999999999999999999")
        self.f["review"]["sizing"]["per_symbol_notional"] = "1000"
        rebind_risk_fixture(self.f)
        report = self.assess()
        self.assertFalse(report["eligible"])
        self.assertEqual(report["opportunities"][0]["whole_quantity"], "1000000000000000000000")
        self.assertIn("WHOLE_SHARE_QUANTITY_OUTSIDE_CONTRACT_BOUND", report["opportunities"][0]["reason_codes"])

    def test_scope_cannot_infer_future_price_or_hypothesis_performance(self):
        report = self.assess()
        self.assertNotIn("expected_return", report)
        self.assertNotIn("strategy_returns", report)
        self.assertNotIn("selected_hypothesis", report)
        self.assertNotIn("next_open", report["opportunities"][0])
        self.assertNotIn("future_return", report["opportunities"][0])

    def test_resource_bound_rejects_more_than_10000_opportunities(self):
        seed = self.f["dataset"]["sessions"]
        from datetime import datetime, timedelta, timezone
        sessions = []
        for index in range(6000):
            session = copy.deepcopy(seed[0])
            when = datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(days=index)
            session.update(session_id="bounded-" + str(index),
                           open_at=when.replace(hour=9).isoformat().replace("+00:00", "Z"),
                           close_at=when.replace(hour=16).isoformat().replace("+00:00", "Z"),
                           available_at=when.replace(hour=16, second=1).isoformat().replace("+00:00", "Z"))
            sessions.append(session)
        self.f["dataset"].update(sessions=sessions, recorded_at="2099-01-01T00:00:00Z")
        self.f["review"]["recorded_at"] = "2099-01-02T00:00:00Z"
        self.f["study_registered_at"] = "2099-01-03T00:00:00Z"
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 5990
        self.f["base_plan"]["protocol"]["final_holdout"] = {"start_index": 5992, "end_index": 5999}
        rebind_risk_fixture(self.f)
        with self.assertRaises(engine.TradingShadowRiskReviewError): self.assess()

    def test_modules_do_not_import_live_or_galactica_logic(self):
        source = inspect.getsource(engine)
        for name in ("galactica", "navigator_adapter", "paper_order", "requests", "urllib", "modeldock", "auto_trading"):
            self.assertNotIn("import " + name, source)
        self.assertNotIn("best", source.lower())


if __name__ == "__main__":
    unittest.main()
