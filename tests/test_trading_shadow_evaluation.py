"""Offline arithmetic/counterfactual tests; fixtures establish no market edge."""
from __future__ import annotations

import ast
import copy
from decimal import Decimal, Inexact, Rounded, localcontext
import inspect
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_shadow_evaluation as engine
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.trading_shadow_intents import produce_shadow_intents
from blackpod_build_week.trading_research_evaluation import evaluate_research
from test_trading_shadow_intents import producer_fixture, rebind


class TradingShadowEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.f = producer_fixture()

    def report(self):
        return engine.evaluate_shadow_study(**self.f, production=produce_shadow_intents(**self.f))

    def fold(self, multiplier="1"):
        return next(row for row in self.report()["cost_stress_runs"] if row["multiplier"] == multiplier)["folds"][0]

    def single_episode(self, *, fee="0"):
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 9
        self.f["gates"]["cost_model"]["fee_per_fill"] = fee
        for index, session in enumerate(self.f["dataset"]["sessions"]):
            session["bars"][1]["close"] = str(10 + index)
        self.f["dataset"]["sessions"][9]["bars"][0]["open"] = "20"
        self.f["dataset"]["sessions"][9]["bars"][1]["open"] = "5"
        rebind(self.f)

    def test_flat_open_prices_have_zero_excess_and_falsify_positive_sign(self):
        result = self.report()
        self.assertEqual(result["status"], "SHADOW_SIMULATED")
        for run in result["cost_stress_runs"]:
            comparison = run["folds"][0]["comparison"]
            self.assertEqual(comparison["net_excess_vs_cash"], "0")
            self.assertEqual(comparison["net_excess_vs_control"], "0")
            self.assertEqual(comparison["falsification_status"], "NONPOSITIVE_REQUIRED_COMPARISON")
        self.assertEqual(result["cost_stress_consistency"][0]["status"], "NONPOSITIVE_REQUIRED_COMPARISON_AT_DECLARED_COST_STRESS")

    def test_control_matches_every_accepted_entry_notional_and_duration(self):
        result = self.report()
        production = produce_shadow_intents(**self.f)
        episodes = {row["episode_id"]: row for row in production["episodes"]}
        for run in result["cost_stress_runs"]:
            fills = {row["fill_id"]: row for row in run["candidate"]["folds"][0]["fills"]}
            for cohort in run["folds"][0]["control"]["cohorts"]:
                episode = episodes[cohort["episode_id"]]
                self.assertEqual(cohort["entry_purchase_notional"], fills[cohort["candidate_entry_fill_id"]]["notional"])
                self.assertTrue(cohort["exact_entry_purchase_notional_match"])
                self.assertEqual(cohort["exit_session_index"] - cohort["entry_session_index"], episode["holding_sessions"])
                self.assertEqual([row["symbol"] for row in cohort["legs"]], self.f["base_plan"]["universe"])
                self.assertEqual(sum(Decimal(row["entry_notional"]) for row in cohort["legs"]), Decimal(cohort["target_entry_purchase_notional"]))

    def test_control_fractional_quantity_is_explicit_arithmetic_ratio(self):
        self.single_episode()
        cohort = self.fold()["control"]["cohorts"][0]
        self.assertEqual([row["qty"] for row in cohort["legs"]], ["1.5", "1.5"])
        for leg in cohort["legs"]:
            self.assertTrue(leg["arithmetic_quantity_only"])
            self.assertEqual(leg["exact_quantity_ratio"], {"numerator": "15", "denominator": "10"})
        self.assertFalse(self.fold()["control"]["daily_path_exposure_matching"])

    def test_nonterminating_equal_weights_cannot_create_positive_excess_sign(self):
        self.f = producer_fixture(universe=["AAA", "BBB", "CCC"])
        self.f["base_plan"]["protocol"]["folds"][0]["test"]["end_index"] = 9
        self.f["study"]["sizing"]["per_symbol_notional"] = "68"
        for index, session in enumerate(self.f["dataset"]["sessions"]):
            for bar in session["bars"]:
                bar["open"] = "11" if index != 9 else "13"
                if bar["symbol"] != "AAA":
                    bar["close"] = str(10 + index)
        rebind(self.f)
        comparison = self.fold()["comparison"]
        self.assertEqual(comparison["candidate_net_pnl"], "4")
        self.assertEqual(comparison["sign_comparison_values"]["net_excess_vs_control"], "0")
        self.assertFalse(comparison["positive_vs_control"])
        self.assertEqual(self.report()["comparison_precision_policy"]["net_pnl_sign_scale"], 24)

    def test_independent_two_symbol_control_arithmetic_hand_calculation(self):
        self.single_episode()
        comparison = self.fold()["comparison"]
        self.assertEqual(comparison["candidate_net_pnl"], "30")
        self.assertEqual(comparison["control_net_pnl"], "7.5")
        self.assertEqual(comparison["net_excess_vs_control"], "22.5")
        self.assertEqual(comparison["net_excess_vs_cash"], "30")

    def test_fixed_fees_charged_for_each_control_leg_and_each_side(self):
        self.single_episode(fee="2")
        for multiplier, candidate, control in (("1", "26", "-0.5"), ("2", "22", "-8.5"), ("4", "14", "-24.5")):
            with self.subTest(multiplier=multiplier):
                comparison = self.fold(multiplier)["comparison"]
                self.assertEqual(comparison["candidate_net_pnl"], candidate)
                self.assertEqual(comparison["control_net_pnl"], control)
        summary = self.report()["cost_stress_consistency"][0]
        self.assertEqual(summary["status"], "POSITIVE_DESCRIPTIVE_SIGNS_AT_ALL_DECLARED_COST_STRESSES")
        self.assertFalse(summary["winner_selected"])
        self.assertFalse(summary["promotion_enabled"])
        self.assertEqual(summary["statistical_significance"], "NOT_ASSESSED")

    def test_stress_scales_all_four_source_bound_cost_components(self):
        self.f["gates"]["cost_model"] = {"spread_bps": "10", "slippage_bps": "2", "fee_bps": "3", "fee_per_fill": "0.1"}
        result = self.report()
        for run in result["cost_stress_runs"]:
            for field, value in self.f["gates"]["cost_model"].items():
                self.assertEqual(Decimal(run["cost_model"][field]), Decimal(value) * Decimal(run["multiplier"]))
        self.assertNotEqual(result["cost_stress_runs"][0]["candidate"]["folds"][0]["metrics"]["modeled_total_cost"], "0")

    def test_source_costs_override_old_data_quality_plan_placeholder(self):
        self.f["base_plan"]["cost_model"]["fee_per_fill"] = "100"
        rebind(self.f)
        result = self.report()
        self.assertEqual(result["cost_stress_runs"][0]["cost_model"]["fee_per_fill"], "0")
        self.assertEqual(result["cost_stress_runs"][0]["candidate"]["folds"][0]["metrics"]["fees"], "0")

    def test_gate_deferral_retains_reasons_without_fills_or_scores(self):
        self.f["gates"] = {"eligible": False, "reason_codes": ["COST_SOURCE_UNRESOLVED"], "cost_model": None,
                           "provenance": {"classification": "RETAINED_HISTORY_RESEARCH"}}
        result = self.report()
        self.assertEqual(result["status"], "DEFER_EVIDENCE_GATES")
        self.assertEqual(result["reason_codes"], ["COST_SOURCE_UNRESOLVED"])
        self.assertEqual(result["cost_stress_runs"], [])
        self.assertEqual(result["cost_stress_consistency"], [])
        self.assertIsNone(result["aggregate"])

    def test_truthy_boolean_gate_and_contradictory_reasons_reject(self):
        for changes in ({"eligible": 1}, {"eligible": True, "reason_codes": ["UNRESOLVED"]}, {"eligible": True, "cost_model": None}):
            with self.subTest(changes=changes):
                fixture = copy.deepcopy(self.f)
                fixture["gates"].update(changes)
                with self.assertRaises(ContractValidationError):
                    engine.evaluate_shadow_study(**fixture, production=produce_shadow_intents(**fixture))

    def test_blocked_gate_cannot_accept_previously_generated_exposure(self):
        production = produce_shadow_intents(**self.f)
        self.f["gates"] = {"eligible": False, "reason_codes": ["UNRESOLVED"], "cost_model": None, "provenance": {}}
        with self.assertRaisesRegex(ContractValidationError, "cannot produce"):
            engine.evaluate_shadow_study(**self.f, production=production)

    def test_forged_episode_or_extra_decision_rejects(self):
        for mutation in ("qty", "holding_sessions", "extra_decision"):
            with self.subTest(mutation=mutation):
                production = produce_shadow_intents(**self.f)
                if mutation == "extra_decision":
                    row = copy.deepcopy(production["intents"]["decisions"][0])
                    row["decision_id"] += "-forged"
                    production["intents"]["decisions"].append(row)
                else:
                    production["episodes"][0][mutation] = "1" if mutation == "qty" else 4
                with self.assertRaises(ContractValidationError):
                    engine.evaluate_shadow_study(**self.f, production=production)

    def test_producer_replay_rejects_changed_opportunity_without_changed_fills(self):
        production = produce_shadow_intents(**self.f)
        production["opportunities"][0]["reason_codes"] = ["POST_HOC"]
        with self.assertRaisesRegex(ContractValidationError, "exactly replay"):
            engine.evaluate_shadow_study(**self.f, production=production)

    def test_old_v2_data_quality_engine_still_rejects_nonempty_generated_intents(self):
        production = produce_shadow_intents(**self.f)
        production["intents"]["plan_id"] = self.f["base_plan"]["plan_id"]
        with self.assertRaisesRegex(ContractValidationError, "empty intents"):
            evaluate_research(self.f["base_plan"], self.f["dataset"], production["intents"])

    def test_candidate_entry_rejections_are_retained_and_do_not_create_controls(self):
        self.f["base_plan"]["risk"]["max_order_notional"] = "1"
        rebind(self.f)
        run = self.report()["cost_stress_runs"][0]
        self.assertTrue(run["candidate"]["folds"][0]["rejections"])
        self.assertFalse(run["candidate"]["folds"][0]["fills"])
        self.assertFalse(run["folds"][0]["control"]["cohorts"])
        self.assertEqual(run["folds"][0]["comparison"]["status"], "INCONCLUSIVE")

    def test_missing_control_symbol_volume_cannot_favor_candidate(self):
        self.single_episode()
        self.f["dataset"]["sessions"][7]["bars"][1]["volume"] = "0"
        rebind(self.f)
        fold = self.fold()
        cohort = fold["control"]["cohorts"][0]
        self.assertEqual(cohort["status"], "REJECTED_ENTRY")
        self.assertIn("CONTROL_ENTRY_KNOWN_VOLUME_INSUFFICIENT:BBB", cohort["reason_codes"])
        self.assertEqual(fold["comparison"]["status"], "INCONCLUSIVE")
        self.assertIsNone(fold["comparison"]["net_excess_vs_control"])

    def test_control_requires_independent_cash_for_all_leg_fees(self):
        self.single_episode(fee="4")
        self.f["base_plan"]["risk"]["initial_cash"] = "35"
        rebind(self.f)
        run = self.report()["cost_stress_runs"][0]
        self.assertEqual(len(run["candidate"]["folds"][0]["fills"]), 2)
        control = run["folds"][0]["control"]["cohorts"][0]
        self.assertIn("CONTROL_INSUFFICIENT_CASH", control["reason_codes"])
        self.assertEqual(run["folds"][0]["comparison"]["status"], "INCONCLUSIVE")

    def test_control_failed_exit_is_retained_open_and_comparison_inconclusive(self):
        self.single_episode()
        self.f["dataset"]["sessions"][8]["bars"][1]["volume"] = "0"
        rebind(self.f)
        control = self.fold()["control"]["cohorts"][0]
        self.assertEqual(control["status"], "OPEN")
        self.assertIn("CONTROL_EXIT_KNOWN_VOLUME_INSUFFICIENT:BBB", control["reason_codes"])
        self.assertIn("CONTROL_EXIT_NOT_COMPLETED", control["reason_codes"])
        self.assertIsNone(self.fold()["comparison"]["net_excess_vs_control"])

    def test_candidate_future_exit_clock_failure_preserves_open_lot(self):
        self.single_episode()
        self.f["dataset"]["sessions"][8]["available_at"] = "2026-06-11T17:00:00Z"
        rebind(self.f)
        run = self.report()["cost_stress_runs"][0]
        self.assertEqual(len(run["candidate"]["folds"][0]["fills"]), 1)
        self.assertTrue(run["candidate"]["folds"][0]["open_lots"])
        self.assertIn("CANDIDATE_EPISODE_EXIT_NOT_FILLED", run["folds"][0]["comparison"]["reason_codes"])

    def test_candidate_exit_risk_rejection_does_not_rewrite_the_entry(self):
        self.single_episode()
        self.f["base_plan"]["risk"]["max_order_notional"] = "35"
        rebind(self.f)
        run = self.report()["cost_stress_runs"][0]
        fold = run["candidate"]["folds"][0]
        self.assertEqual(len(fold["fills"]), 1)
        self.assertEqual(fold["fills"][0]["side"], "BUY")
        self.assertEqual(fold["rejections"][0]["reason_code"], "MAX_ORDER_NOTIONAL_EXCEEDED")
        self.assertEqual(run["folds"][0]["comparison"]["status"], "INCONCLUSIVE")

    def test_closed_candidate_cohorts_preserve_exact_fifo_entry_lineage(self):
        self.assertTrue(all(row["candidate_fifo_lineage_matched"] for row in self.fold()["control"]["cohorts"]))
        self.single_episode()
        self.f["base_plan"]["risk"]["max_order_notional"] = "35"
        rebind(self.f)
        self.assertIn("CANDIDATE_EPISODE_FIFO_LINEAGE_NOT_MATCHED", self.fold()["comparison"]["reason_codes"])

    def test_control_shared_opening_volume_is_not_reset_between_cohorts(self):
        # Both candidate symbols fit their own prior volume. Equal-weight
        # controls require more of expensive AAA's paired cheap BBB stock.
        for session in self.f["dataset"]["sessions"]:
            session["bars"][0]["open"] = "50"
            session["bars"][1]["open"] = "1"
            session["bars"][1]["volume"] = "100"
        rebind(self.f)
        cohorts = self.fold()["control"]["cohorts"]
        self.assertTrue(any(row["status"] == "REJECTED_ENTRY" and "CONTROL_ENTRY_KNOWN_VOLUME_INSUFFICIENT:BBB" in row["reason_codes"] for row in cohorts))

    def test_control_observed_price_risk_drift_prevents_positive_comparison(self):
        self.single_episode()
        self.f["base_plan"]["risk"].update(initial_cash="100", max_gross_exposure_fraction="0.31")
        self.f["dataset"]["sessions"][8]["bars"][1]["close"] = "99"
        rebind(self.f)
        fold = self.fold()
        self.assertTrue(fold["control"]["risk_breaches"])
        self.assertIn("CONTROL_OBSERVED_RISK_BREACH", fold["comparison"]["reason_codes"])

    def test_final_holdout_prices_never_change_production_or_scores(self):
        before = self.report()
        for session in self.f["dataset"]["sessions"][21:]:
            for bar in session["bars"]:
                bar.update(open="99", close="1", volume="0")
        rebind(self.f)
        self.assertEqual(before, self.report())
        for run in before["cost_stress_runs"]:
            self.assertTrue(all(row["session_index"] < 21 for row in run["candidate"]["folds"][0]["equity_curve"]))
            self.assertTrue(all(row["session_index"] < 21 for row in run["folds"][0]["control"]["equity_curve"]))

    def test_continuation_uses_same_three_session_duration_for_control(self):
        self.f = producer_fixture("FIVE_SESSION_CONTINUATION")
        for cohort in self.fold()["control"]["cohorts"]:
            self.assertEqual(cohort["holding_sessions"], 3)
            self.assertEqual(cohort["exit_session_index"] - cohort["entry_session_index"], 3)

    def test_all_failed_zero_sized_opportunities_remain_inconclusive(self):
        self.f["study"]["sizing"]["per_symbol_notional"] = "0.001"
        result = self.report()
        for run in result["cost_stress_runs"]:
            self.assertEqual(run["folds"][0]["comparison"]["status"], "INCONCLUSIVE")
            self.assertEqual(run["candidate"]["folds"][0]["metrics"]["fill_count"], 0)

    def test_stress_above_supported_cost_bound_defers_without_repair(self):
        self.f["gates"]["cost_model"]["spread_bps"] = "300"
        result = self.report()
        self.assertEqual(result["cost_stress_runs"][2]["status"], "DEFER_COST_STRESS_EXCEEDS_GENERIC_SUPPORTED_BOUND")
        self.assertIsNone(result["cost_stress_runs"][2]["candidate"])
        self.assertEqual(result["cost_stress_consistency"][0]["status"], "INCONCLUSIVE")

    def test_result_retains_shadow_authority_and_honest_scope(self):
        result = self.report()
        self.assertEqual(result["mode"], "SHADOW_RESEARCH")
        self.assertEqual(result["scope"], "DEVELOPMENT_TEST_ONLY")
        self.assertEqual(result["evidence_scope"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(any(result["authority"].values()))
        self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertFalse(result["final_holdout"]["access_sealed"])
        self.assertFalse(result["availability_semantics"]["historical_point_in_time_verified"])
        self.assertIsNone(result["aggregate"])

    def test_result_does_not_alias_or_mutate_source_documents(self):
        before = copy.deepcopy(self.f)
        result = self.report()
        self.assertEqual(before, self.f)
        result["gate_assessment"]["provenance"]["forged"] = True
        result["availability_semantics"]["source_provenance"]["source_evidence"].clear()
        self.assertEqual(before, self.f)

    def test_decimal_context_is_isolated_from_host_precision_and_traps(self):
        self.f["gates"]["cost_model"] = {"spread_bps": "1.5", "slippage_bps": "0.8", "fee_bps": "0.25", "fee_per_fill": "0.01"}
        expected = self.report()
        with localcontext() as context:
            context.prec = 7
            context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(expected, self.report())

    def test_implementation_imports_only_independent_pure_interfaces(self):
        tree = ast.parse(inspect.getsource(engine))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        for forbidden in ("galactica", "alpaca", "navigator", "modeldock", "subprocess", "socket"):
            self.assertFalse(any(forbidden in module.lower() for module in imports), forbidden)


if __name__ == "__main__":
    unittest.main()
