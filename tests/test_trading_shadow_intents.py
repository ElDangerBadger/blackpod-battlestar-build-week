"""Causal, deterministic original producers; invented prices are not an edge."""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
import inspect
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_shadow_intents as producer
from blackpod_build_week.contracts.mission_request import ContractValidationError, parse_rfc3339
from blackpod_build_week.contracts.trading_research import TradingResearchIntents
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_hypotheses import catalog_documents, catalog_hypotheses, hypothesis_research_strategy
from test_trading_research_evaluation import ResearchEvaluationFixture


def reference(path, value):
    body = canonical_json_bytes(value)
    return {"path": path, "sha256": sha256_bytes(body), "size_bytes": len(body)}


def producer_fixture(family="PREVIOUS_SESSION_REVERSAL", universe=None):
    """Source identities are authored fixtures; the parent journal verifies real sources."""
    base = ResearchEvaluationFixture(universe=universe or ["AAA", "BBB"], count=24)
    hypothesis = next(document.to_mapping() for document in catalog_documents(
        catalog_hypotheses("2026-05-01T00:00:00Z", "fixture-author")) if document.signal["family"] == family)
    dataset = base.dataset
    for index, session in enumerate(dataset["sessions"]):
        for bar in session["bars"]:
            bar["close"] = str(40 - index if family == "PREVIOUS_SESSION_REVERSAL" else 10 + index)
    request = {"path": "fixture/request.json", "sha256": "a" * 64, "size_bytes": 1}
    dataset["schema_version"] = "blackpod.trading_research_dataset.v2"
    dataset["provenance"] = {
        "source_kind": "GOVERNED_HISTORICAL_INTAKE", "source_evidence": [request] + [
            {"path": "fixture/source-%s.raw" % index, "sha256": str(index) * 64, "size_bytes": 1} for index in range(1, 5)],
        "timestamp_policy": "DECLARED_RETROSPECTIVE_SESSION_END_PLUS_LAG", "historical_point_in_time_verified": False,
        "governed_intake": {"intake_id": "invented-intake", "request_evidence": request,
                            "method_version": "blackpod.alpaca_daily_history_projection.v1"},
        "availability_assumption": {"mode": "RETURNED_SESSION_END_PLUS_DECLARED_DELAY", "delay_seconds": 1,
                                    "declared_by": "fixture-author", "rationale": "Invented clocks; no PIT proof.",
                                    "assumption_verified": False},
    }
    plan = base.plan
    plan.update(schema_version="blackpod.trading_research_plan.v2", evaluation_purpose="DATA_QUALITY_ONLY",
                frozen_hypothesis_evidence=reference("fixture/hypothesis.json", hypothesis),
                dataset_evidence=reference("fixture/dataset.json", dataset), **hypothesis_research_strategy(hypothesis))
    plan["protocol"]["folds"][0]["test"]["end_index"] = 19
    plan["protocol"]["final_holdout"] = {"start_index": 21, "end_index": 23}
    study = {
        "schema_version": "blackpod.trading_shadow_study.v1", "study_id": "invented-shadow-study",
        "experiment_id": "invented-shadow-experiment", "registered_at": "2026-07-02T00:00:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
        "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "base_plan_evidence": reference("fixture/base-plan.json", plan),
        "price_continuity_evidence": None, "cost_evidence": None,
        "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "100"},
        "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"},
        "cost_stress_multipliers": ["1", "2", "4"], "trial_registry": {"trial_id": "invented-shadow-trial", "prior_trial_ids": []},
        "auto_trading_enabled": False, "authority": copy.deepcopy(plan["authority"]),
    }
    return {"study": study, "base_plan": plan, "dataset": dataset, "hypothesis": hypothesis,
            "gates": {"eligible": True, "reason_codes": [], "cost_model": copy.deepcopy(plan["cost_model"]),
                      "provenance": {"classification": "SYNTHETIC_FIXTURE_ONLY"}}}


def rebind(value):
    value["base_plan"]["dataset_evidence"] = reference("fixture/dataset.json", value["dataset"])
    value["base_plan"]["frozen_hypothesis_evidence"] = reference("fixture/hypothesis.json", value["hypothesis"])
    value["study"]["base_plan_evidence"] = reference("fixture/base-plan.json", value["base_plan"])


class TradingShadowIntentTests(unittest.TestCase):
    def setUp(self):
        self.f = producer_fixture()
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def produce(self):
        return producer.produce_shadow_intents(**self.f)

    def test_reversal_produces_prior_session_negative_return_candidates(self):
        result = self.produce()
        self.assertEqual(result["status"], "PRODUCED_SHADOW_RESEARCH_ONLY")
        self.assertTrue(result["episodes"])
        first = result["episodes"][0]
        self.assertEqual(first["source_session_index"], 7)
        self.assertEqual(first["entry_session_index"], 8)
        self.assertEqual(first["exit_session_index"], 9)
        self.assertEqual(first["holding_sessions"], 1)
        self.assertEqual(first["qty"], "3")
        self.assertEqual(first["sizing_reference_close"], "33")
        self.assertEqual([row["session_index"] for row in first["known_inputs"]], [6, 7])

    def test_continuation_produces_five_session_positive_return_candidates(self):
        self.f = producer_fixture("FIVE_SESSION_CONTINUATION")
        result = self.produce()
        first = result["episodes"][0]
        self.assertEqual(first["source_session_index"], 7)
        self.assertEqual(first["entry_session_index"], 8)
        self.assertEqual(first["exit_session_index"], 11)
        self.assertEqual(first["holding_sessions"], 3)
        self.assertEqual(first["qty"], "5")
        self.assertEqual([row["session_index"] for row in first["known_inputs"]], list(range(2, 8)))

    def test_intents_round_trip_through_original_strict_contract(self):
        result = self.produce()
        typed = TradingResearchIntents.from_mapping(result["intents"])
        self.assertEqual(typed.to_mapping(), result["intents"])
        self.assertEqual(typed.plan_id, self.f["study"]["study_id"] + "-candidate")
        self.assertEqual(typed.origin, "EXTERNALLY_AUTHORED_RESEARCH_ONLY")
        self.assertEqual(typed.created_at, self.f["study"]["registered_at"])

    def test_every_decision_strictly_follows_source_availability_and_precedes_next_open(self):
        result = self.produce()
        sessions = self.f["dataset"]["sessions"]
        indices = {row["session_id"]: index for index, row in enumerate(sessions)}
        for decision in result["intents"]["decisions"]:
            index = indices[decision["source_session_id"]]
            when = parse_rfc3339(decision["decision_at"], "decision_at")
            self.assertEqual(when - parse_rfc3339(sessions[index]["available_at"], "available_at"), timedelta(microseconds=1))
            self.assertLess(when, parse_rfc3339(sessions[index + 1]["open_at"], "open_at"))

    def test_every_candidate_input_is_available_before_its_decision(self):
        for episode in self.produce()["episodes"]:
            when = parse_rfc3339(episode["decision_at"], "decision_at")
            for row in episode["known_inputs"]:
                self.assertLessEqual(parse_rfc3339(row["available_at"], "available_at"), when)
                self.assertLessEqual(row["session_index"], episode["source_session_index"])

    def test_zero_returns_are_never_candidates_for_either_family(self):
        for family in ("PREVIOUS_SESSION_REVERSAL", "FIVE_SESSION_CONTINUATION"):
            with self.subTest(family=family):
                self.f = producer_fixture(family)
                for session in self.f["dataset"]["sessions"]:
                    for bar in session["bars"]:
                        bar["close"] = "10"
                rebind(self.f)
                result = self.produce()
                self.assertFalse(result["episodes"])
                self.assertFalse(result["intents"]["decisions"])
                self.assertTrue(all(row["reason_codes"] == ["ZERO_RETURN_NO_CANDIDATE"] for row in result["opportunities"]))

    def test_wrong_return_sign_is_not_a_candidate(self):
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar["close"] = str(10 + int(session["session_id"][1:]))
        rebind(self.f)
        result = self.produce()
        self.assertFalse(result["episodes"])
        self.assertTrue(all(row["reason_codes"] == ["CONDITION_NOT_SATISFIED"] for row in result["opportunities"]))

    def test_two_selected_symbols_are_independent_and_sorted(self):
        result = self.produce()
        self.assertEqual([row["symbol"] for row in result["episodes"][:2]], ["AAA", "BBB"])
        for symbol in self.f["base_plan"]["universe"]:
            episodes = [row for row in result["episodes"] if row["symbol"] == symbol]
            for previous, current in zip(episodes, episodes[1:]):
                self.assertGreater(current["entry_session_index"], previous["exit_session_index"])

    def test_does_not_reenter_while_planned_position_is_open(self):
        self.f = producer_fixture("FIVE_SESSION_CONTINUATION", ["AAA"])
        rows = self.produce()["opportunities"]
        self.assertEqual(rows[0]["status"], "SCHEDULED_ENTRY")
        self.assertEqual(rows[1]["reason_codes"], ["PLANNED_POSITION_ALREADY_OPEN"])
        self.assertEqual(rows[2]["reason_codes"], ["PLANNED_POSITION_ALREADY_OPEN"])
        self.assertEqual(rows[3]["status"], "SCHEDULED_EXIT")
        self.assertEqual(rows[4]["status"], "SCHEDULED_ENTRY")

    def test_all_opportunities_are_retained(self):
        result = self.produce()
        self.assertEqual(len(result["opportunities"]), 12 * 2)
        self.assertEqual(len({row["opportunity_id"] for row in result["opportunities"]}), 24)
        self.assertTrue(all(row["status"] in {"SCHEDULED_ENTRY", "SCHEDULED_EXIT", "DEFER", "NO_CANDIDATE"}
                            for row in result["opportunities"]))

    def test_entries_and_exits_stay_within_development_test(self):
        result = self.produce()
        for episode in result["episodes"]:
            self.assertGreaterEqual(episode["entry_session_index"], 8)
            self.assertLessEqual(episode["exit_session_index"], 19)
            self.assertIsNotNone(episode["exit_decision_id"])
            self.assertEqual(episode["status"], "SCHEDULED_SHADOW")
        self.assertTrue(all(row["source_session_index"] < 19 for row in result["opportunities"]))

    def test_exact_quantity_and_symbol_preserved_in_scheduled_exit(self):
        result = self.produce()
        by_id = {row["decision_id"]: row for row in result["intents"]["decisions"]}
        for episode in result["episodes"]:
            entry, exit_decision = by_id[episode["entry_decision_id"]], by_id[episode["exit_decision_id"]]
            self.assertEqual(entry["action"], "BUY")
            self.assertEqual(exit_decision["action"], "SELL")
            self.assertEqual(entry["qty"], exit_decision["qty"])
            self.assertEqual(entry["symbol"], exit_decision["symbol"])

    def test_future_open_prices_do_not_change_production(self):
        before = self.produce()
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar["open"] = "99"
        rebind(self.f)
        self.assertEqual(before, self.produce())

    def test_future_volume_does_not_change_production(self):
        before = self.produce()
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar["volume"] = "0"
        rebind(self.f)
        self.assertEqual(before, self.produce())

    def test_holdout_prices_and_clocks_do_not_change_any_output(self):
        before = self.produce()
        for session in self.f["dataset"]["sessions"][21:]:
            for bar in session["bars"]:
                bar.update(open="99", close="1", volume="0")
            session["available_at"] = "2026-06-30T23:59:59Z"
        rebind(self.f)
        self.assertEqual(before, self.produce())

    def test_future_close_changes_cannot_change_prior_entry_or_size(self):
        before = self.produce()
        for session in self.f["dataset"]["sessions"][8:]:
            for bar in session["bars"]:
                bar["close"] = "99"
        rebind(self.f)
        after = self.produce()
        before_entries = [row for row in before["intents"]["decisions"] if row["source_session_id"] == "s7"]
        after_entries = [row for row in after["intents"]["decisions"] if row["source_session_id"] == "s7"]
        self.assertEqual(before_entries, after_entries)
        self.assertEqual(before["opportunities"][:2], after["opportunities"][:2])

    def test_budget_floor_uses_known_completed_close(self):
        self.f["study"]["sizing"]["per_symbol_notional"] = "65.999999999999999999"
        self.assertEqual(self.produce()["episodes"][0]["qty"], "1")

    def test_tiny_return_preserves_exact_sign_when_display_rounds_to_zero(self):
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar.update(close="10000000000000000000", high="99999999999999999999")
        for bar in self.f["dataset"]["sessions"][7]["bars"]:
            bar["close"] = "9999999999999999999.999999999999999999"
        self.f["study"]["sizing"]["per_symbol_notional"] = "10000000000000000000"
        rebind(self.f)
        row = self.produce()["opportunities"][0]
        self.assertEqual(row["status"], "SCHEDULED_ENTRY")
        self.assertEqual(row["observed_return"], "0")
        self.assertEqual(row["observed_return_sign"], "NEGATIVE")
        self.assertIn("SIGN_USES_UNROUNDED_DECIMAL", row["observed_return_precision"])

    def test_budget_below_one_share_defers_without_fractional_roundup(self):
        self.f["study"]["sizing"]["per_symbol_notional"] = "0.01"
        result = self.produce()
        self.assertFalse(result["episodes"])
        self.assertTrue(all(row["reason_codes"] in (["KNOWN_CLOSE_BUDGET_BELOW_ONE_WHOLE_SHARE"], ["DECLARED_EXIT_OUTSIDE_TEST"])
                            for row in result["opportunities"]))

    def test_out_of_contract_quantity_defers_instead_of_truncating(self):
        self.f["study"]["sizing"]["per_symbol_notional"] = "99999999999999999999"
        for session in self.f["dataset"]["sessions"]:
            for bar in session["bars"]:
                bar["close"] = str(Decimal(bar["close"]) / Decimal("100"))
                bar["low"] = "0.01"
        rebind(self.f)
        result = self.produce()
        self.assertFalse(result["episodes"])
        self.assertTrue(any(row["reason_codes"] == ["WHOLE_SHARE_QUANTITY_OUTSIDE_CONTRACT_BOUND"] for row in result["opportunities"]))

    def test_nonmonotone_lookback_availability_defers_without_exposing_unknown_close(self):
        self.f["dataset"]["sessions"][6]["available_at"] = "2026-06-20T17:00:00Z"
        rebind(self.f)
        rows = self.produce()["opportunities"][:2]
        self.assertTrue(all(row["reason_codes"] == ["LOOKBACK_INPUT_NOT_YET_AVAILABLE"] for row in rows))
        self.assertTrue(all("known_inputs" not in row for row in rows))

    def test_source_not_available_before_next_open_defers_entry(self):
        self.f["dataset"]["sessions"][7]["available_at"] = self.f["dataset"]["sessions"][8]["open_at"]
        rebind(self.f)
        rows = self.produce()["opportunities"][:2]
        self.assertTrue(all(row["reason_codes"] == ["NEXT_OPEN_NOT_AFTER_DECISION"] for row in rows))

    def test_stale_next_open_defers_entry(self):
        self.f["base_plan"]["risk"]["max_staleness_seconds"] = 1
        rebind(self.f)
        result = self.produce()
        self.assertFalse(result["episodes"])
        self.assertTrue(any(row["reason_codes"] == ["SOURCE_STALE_AT_NEXT_OPEN"] for row in result["opportunities"]))

    def test_delayed_exit_clock_preserves_earlier_entry(self):
        self.f = producer_fixture("FIVE_SESSION_CONTINUATION", ["AAA"])
        before = self.produce()["intents"]["decisions"][0]
        self.f["dataset"]["sessions"][10]["available_at"] = self.f["dataset"]["sessions"][11]["open_at"]
        rebind(self.f)
        result = self.produce()
        episode = result["episodes"][0]
        self.assertEqual(result["intents"]["decisions"][0], before)
        self.assertEqual(episode["status"], "DEFER_EXIT_CLOCK_UNAVAILABLE")
        self.assertIsNone(episode["exit_decision_id"])
        self.assertEqual(episode["reason_codes"], ["NEXT_OPEN_NOT_AFTER_DECISION"])
        self.assertEqual(len(result["episodes"]), 1)

    def test_insufficient_lookback_defers_without_imputation(self):
        self.f = producer_fixture("FIVE_SESSION_CONTINUATION", ["AAA"])
        fold = self.f["base_plan"]["protocol"]["folds"][0]
        fold.update(train={"start_index": 0, "end_index": 0}, validation={"start_index": 2, "end_index": 2},
                    test={"start_index": 4, "end_index": 19})
        rebind(self.f)
        rows = self.produce()["opportunities"]
        self.assertEqual(rows[0]["reason_codes"], ["INSUFFICIENT_COMPLETED_LOOKBACK"])
        self.assertEqual(rows[1]["reason_codes"], ["INSUFFICIENT_COMPLETED_LOOKBACK"])

    def test_missing_or_unknown_gate_defers_with_empty_intents(self):
        for gates in (None, {}, [], {"eligible": True}, {"eligible": True, "reason_codes": [], "cost_model": None}):
            with self.subTest(gates=gates):
                self.f["gates"] = gates
                result = self.produce()
                self.assertEqual(result["status"], "DEFER_GATE_EVIDENCE")
                self.assertFalse(result["intents"]["decisions"])
                self.assertFalse(result["episodes"])
                self.assertFalse(result["opportunities"])

    def test_truthy_non_boolean_gate_never_passes(self):
        for eligible in (1, "true", [], None, False):
            with self.subTest(eligible=eligible):
                self.f["gates"]["eligible"] = eligible
                self.assertEqual(self.produce()["status"], "DEFER_GATE_EVIDENCE")

    def test_gate_reasons_are_retained_sorted_and_deduplicated(self):
        self.f["gates"].update(eligible=False, reason_codes=["UNVERIFIED_PRICE_CONTINUITY", "UNVERIFIED_COSTS", "UNVERIFIED_COSTS"])
        result = self.produce()
        self.assertEqual(result["reason_codes"], ["GATE_EVIDENCE_NOT_ELIGIBLE", "UNVERIFIED_COSTS", "UNVERIFIED_PRICE_CONTINUITY"])

    def test_gate_true_with_unresolved_reasons_remains_deferred(self):
        self.f["gates"]["reason_codes"] = ["UNRESOLVED"]
        self.assertEqual(self.produce()["status"], "DEFER_GATE_EVIDENCE")

    def test_gate_model_missing_or_malformed_never_falls_back_to_old_plan_costs(self):
        for model in (None, {}, {"spread_bps": "1"}, {"spread_bps": 0, "slippage_bps": "0", "fee_bps": "0", "fee_per_fill": "0"}):
            with self.subTest(model=model):
                self.f["gates"]["cost_model"] = model
                result = self.produce()
                self.assertIn("GATE_COST_MODEL_UNVERIFIED", result["reason_codes"])
                self.assertFalse(result["intents"]["decisions"])

    def test_gate_reason_shape_invalid_defers(self):
        for reasons in (None, "reason", [None], [1], [""]):
            with self.subTest(reasons=reasons):
                self.f["gates"]["reason_codes"] = reasons
                self.assertIn("GATE_REASON_CODES_UNVERIFIED", self.produce()["reason_codes"])

    def test_missing_or_unknown_gate_fields_fail_closed(self):
        for mutation in (lambda row: row.pop("provenance"), lambda row: row.update(provenance=None),
                         lambda row: row.update(override=True)):
            with self.subTest(mutation=mutation):
                value = copy.deepcopy(self.f)
                mutation(value["gates"])
                result = producer.produce_shadow_intents(**value)
                self.assertEqual(result["status"], "DEFER_GATE_EVIDENCE")
                self.assertFalse(result["intents"]["decisions"])

    def test_fold_end_candidate_is_retained_as_deferred(self):
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 18
        rebind(self.f)
        result = self.produce()
        final = result["opportunities"][-2:]
        self.assertTrue(all(row["reason_codes"] == ["DECLARED_EXIT_OUTSIDE_TEST"] for row in final))
        self.assertTrue(all(row["source_session_index"] == 17 for row in final))

    def test_full_opportunity_projection_has_a_resource_bound(self):
        many = ResearchEvaluationFixture(universe=["AAA", "BBB"], count=5024)
        self.f["dataset"]["sessions"] = many.dataset["sessions"]
        self.f["dataset"]["recorded_at"] = "2050-01-01T00:00:00Z"
        self.f["study"]["registered_at"] = "2050-01-02T00:00:00Z"
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 5019
        self.f["base_plan"]["protocol"]["final_holdout"] = {"start_index": 5021, "end_index": 5023}
        rebind(self.f)
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "10000-row bound"):
            self.produce()

    def test_all_authority_remains_disabled_and_no_realized_pnl_claim_is_added(self):
        result = self.produce()
        self.assertFalse(result["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in result["authority"].values()))
        self.assertTrue(all(value is False for value in result["intents"]["authority"].values()))
        self.assertEqual(result["evidence_scope"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertNotIn("realized_trade_pnl", result)
        self.assertNotIn("metrics", result)
        self.assertNotIn("winner", result)

    def test_retries_are_byte_identical_and_inputs_unchanged(self):
        before = canonical_json_bytes(self.f)
        first, second = self.produce(), self.produce()
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        self.assertEqual(canonical_json_bytes(self.f), before)

    def test_global_decimal_context_cannot_change_quantity_or_sign(self):
        expected = canonical_json_bytes(self.produce())
        with localcontext() as context:
            context.prec = 3
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(canonical_json_bytes(self.produce()), expected)

    def test_invented_hypothesis_family_or_changed_rules_are_rejected(self):
        self.f["hypothesis"]["signal"]["lookback_sessions"] = 2
        rebind(self.f)
        with self.assertRaises(ContractValidationError):
            self.produce()

    def test_plan_strategy_must_match_original_hypothesis_exactly(self):
        self.f["base_plan"]["strategy"]["hypothesis"] = "Altered narrative."
        rebind(self.f)
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "exact frozen hypothesis"):
            self.produce()

    def test_plan_horizon_must_match_original_hypothesis_exactly(self):
        self.f["base_plan"]["horizon"]["max_holding_sessions"] = 2
        rebind(self.f)
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "exact frozen hypothesis"):
            self.produce()

    def test_base_plan_hash_mismatch_is_rejected(self):
        self.f["base_plan"]["risk"]["initial_cash"] = "999"
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "base plan evidence"):
            self.produce()

    def test_dataset_hash_mismatch_is_rejected(self):
        self.f["dataset"]["sessions"][7]["bars"][0]["close"] = "50"
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "dataset evidence"):
            self.produce()

    def test_hypothesis_hash_mismatch_is_rejected(self):
        self.f["hypothesis"]["author_id"] = "other-author"
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "frozen hypothesis evidence"):
            self.produce()

    def test_v1_plan_cannot_gain_new_producer_semantics(self):
        self.f["base_plan"].pop("evaluation_purpose")
        self.f["base_plan"].pop("frozen_hypothesis_evidence")
        self.f["base_plan"]["schema_version"] = "blackpod.trading_research_plan.v1"
        self.f["study"]["base_plan_evidence"] = reference("fixture/base-plan.json", self.f["base_plan"])
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "frozen v2"):
            self.produce()

    def test_registration_cannot_precede_frozen_sources(self):
        self.f["study"]["registered_at"] = "2026-06-01T00:00:00Z"
        with self.assertRaisesRegex(producer.TradingShadowIntentError, "cannot precede"):
            self.produce()

    def test_changed_live_authority_never_passes_contract(self):
        for document in ("study", "base_plan", "dataset", "hypothesis"):
            with self.subTest(document=document):
                value = copy.deepcopy(self.f)
                value[document]["authority"]["execution_enabled"] = True
                with self.assertRaises(ContractValidationError):
                    producer.produce_shadow_intents(**value)

    def test_auto_trading_cannot_be_enabled(self):
        self.f["study"]["auto_trading_enabled"] = True
        with self.assertRaises(ContractValidationError):
            self.produce()

    def test_engine_has_no_legacy_provider_execution_or_io_imports(self):
        source = inspect.getsource(producer)
        for forbidden in ("import requests", "import urllib", "import alpaca", "import Galactica", "import galactica",
                          "from .adapters", "from .modeldock", "open(", "subprocess", "socket", "read_bytes", "write_bytes"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
