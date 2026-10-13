"""Deterministic independent simulation/leakage tests; no provider or executor."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, Rounded, localcontext
import inspect
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_research_evaluation as engine
from blackpod_build_week.contracts.trading_research import (
    TradingResearchDataset, TradingResearchIntents, TradingResearchPlan,
)
from blackpod_build_week.hashing import canonical_json_bytes

AUTHORITY = {"execution_enabled": False, "authorization_enabled": False, "capital_activation_enabled": False, "policy_changes_enabled": False}


def stamp(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


class ResearchEvaluationFixture:
    """Entirely invented markets and externally authored decisions, no strategy."""
    def __init__(self, universe=None, count=18):
        universe = universe or ["AAA"]
        sessions = []
        for index in range(count):
            day = datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(days=index)
            sessions.append({"session_id": "s" + str(index),
                             "open_at": stamp(day.replace(hour=9)), "close_at": stamp(day.replace(hour=16)),
                             "available_at": stamp(day.replace(hour=16, second=1)),
                             "bars": [{"symbol": symbol, "open": "10", "high": "100", "low": "1",
                                       "close": "10", "volume": "1000"} for symbol in universe]})
        self.dataset = {"schema_version": "blackpod.trading_research_dataset.v1", "dataset_id": "invented-data",
                        "recorded_at": "2026-07-01T00:00:00Z", "universe": universe,
                        "provenance": {"source_kind": "SYNTHETIC_FIXTURE", "timestamp_policy": "SYNTHETIC_DECLARED",
                                       "historical_point_in_time_verified": False,
                                       "source_evidence": [{"path": "invented/source.json", "sha256": "a" * 64, "size_bytes": 1}]},
                        "sessions": sessions, "authority": AUTHORITY}
        self.plan = {"schema_version": "blackpod.trading_research_plan.v1", "plan_id": "new-research-plan",
                     "experiment_id": "invented-experiment", "registered_at": "2026-05-01T00:00:00Z",
                     "domain": "TRADING", "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
                     "strategy": {"strategy_id": "external-example", "version": "1",
                                  "hypothesis": "Invented data checks arithmetic only.", "expected_edge": "No economic edge asserted.",
                                  "falsification_conditions": ["Arithmetic fails."],
                                  "ancestry": "INDEPENDENT_NEW_RESEARCH_SPECIFICATION", "implementation_status": "EXTERNAL_INTENTS_ONLY"},
                     "universe": universe, "horizon": {"kind": "SWING", "max_holding_sessions": 20, "label_horizon_sessions": 1},
                     "dataset_evidence": {"path": "research/dataset.json", "sha256": "b" * 64, "size_bytes": 1},
                     "intents_evidence": {"path": "research/intents.json", "sha256": "c" * 64, "size_bytes": 1},
                     "protocol": {"folds": [{"fold_id": "f1", "train": {"start_index": 0, "end_index": 3},
                                              "validation": {"start_index": 5, "end_index": 6},
                                              "test": {"start_index": 8, "end_index": 13}}],
                                  "embargo_sessions": 1, "final_holdout": {"start_index": 15, "end_index": 17}},
                     "cost_model": {"spread_bps": "0", "slippage_bps": "0", "fee_bps": "0", "fee_per_fill": "0"},
                     "risk": {"initial_cash": "1000", "max_order_notional": "10000", "max_position_fraction": "1",
                              "max_gross_exposure_fraction": "1", "max_volume_participation_fraction": "0.1", "max_staleness_seconds": 86400},
                     "benchmark": {"kind": "CASH"}, "trial_registry": {"trial_id": "trial-one", "prior_trial_ids": []},
                     "auto_trading_enabled": False, "authority": AUTHORITY}
        self.intents = {"schema_version": "blackpod.trading_research_intents.v1", "intent_set_id": "invented-intents",
                        "plan_id": self.plan["plan_id"], "created_at": "2026-07-01T00:00:00Z",
                        "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [], "authority": AUTHORITY}

    def decision(self, identity, source=7, action="BUY", qty="2", symbol="AAA", fold="f1", when=None):
        session = self.dataset["sessions"][source]
        value = {"decision_id": identity, "fold_id": fold, "source_session_id": session["session_id"],
                 "decision_at": when or stamp(engine._time(session["available_at"]) + timedelta(seconds=1)),
                 "action": action, "symbol": symbol, "qty": qty}
        self.intents["decisions"].append(value)
        return value

    def price(self, index, opening=None, closing=None, symbol="AAA", volume=None):
        bar = next(bar for bar in self.dataset["sessions"][index]["bars"] if bar["symbol"] == symbol)
        if opening is not None: bar["open"] = opening
        if closing is not None: bar["close"] = closing
        if volume is not None: bar["volume"] = volume

    def report(self):
        return engine.evaluate_research(self.plan, self.dataset, self.intents)

    def fold(self):
        return self.report()["folds"][0]


class TradingResearchEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.f = ResearchEvaluationFixture()

    def reasons(self):
        return [row["reason_code"] for row in self.f.fold()["rejections"]]

    def test_declared_training_horizon_purges_boundary_label(self):
        split = engine.plan_chronological_splits(self.f.plan, self.f.dataset)
        row = split["folds"][0]
        self.assertEqual([item["source_index"] for item in row["eligible_training_label_samples"]], [0, 1, 2])
        self.assertEqual(row["purged_training_label_samples"][0]["source_index"], 3)
        self.assertIn("LABEL_TARGET_OUTSIDE_TRAIN", row["purged_training_label_samples"][0]["reason_codes"])
        self.assertFalse(row["model_training_verified"])

    def test_longer_label_horizon_increases_purge(self):
        self.f.plan["horizon"]["label_horizon_sessions"] = 2
        projection = self.f.report()["protocol"]["folds"][0]
        self.assertEqual(len(projection["eligible_training_label_samples"]), 2)
        self.assertEqual(len(projection["purged_training_label_samples"]), 2)

    def test_delayed_historical_label_is_not_available_at_train_cutoff(self):
        self.f.dataset["sessions"][1]["available_at"] = "2026-06-07T17:00:00Z"
        report = self.f.report()
        purged = report["protocol"]["folds"][0]["purged_training_label_samples"]
        self.assertIn("LABEL_NOT_AVAILABLE_BY_TRAIN_CUTOFF", purged[0]["reason_codes"])
        self.assertIn("FEATURE_AVAILABLE_AFTER_VALIDATION_START", purged[1]["reason_codes"])
        self.assertIn("s1", [row["session_id"] for row in report["data_quality"]["availability_failures"]])
        self.assertEqual(report["folds"][0]["status"], "DEFER_SPLIT_AVAILABILITY_INVALID")
        self.assertIsNone(report["folds"][0]["metrics"])

    def test_nonmonotone_feature_availability_is_purged_at_declared_train_cutoff(self):
        self.f.dataset["sessions"][1]["available_at"] = "2026-06-05T17:00:00Z"
        row = self.f.report()["protocol"]["folds"][0]
        changed = next(sample for sample in row["purged_training_label_samples"] if sample["source_index"] == 1)
        self.assertIn("FEATURE_NOT_AVAILABLE_BY_TRAIN_CUTOFF", changed["reason_codes"])
        self.assertEqual([sample["source_index"] for sample in row["eligible_training_label_samples"]], [2])

    def test_train_validation_gaps_are_retained(self):
        projection = self.f.report()["protocol"]["folds"][0]
        self.assertEqual(projection["train_to_validation_gap_sessions"], 1)
        self.assertEqual(projection["validation_to_test_gap_sessions"], 1)

    def test_final_holdout_is_withheld_and_not_access_sealed(self):
        report = self.f.report()
        self.assertEqual(report["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertFalse(report["final_holdout"]["access_sealed"])
        self.assertEqual([row["session_index"] for row in report["folds"][0]["equity_curve"]], list(range(8, 14)))

    def test_unseen_holdout_prices_do_not_change_scores(self):
        self.f.decision("buy")
        before = self.f.report()
        for index in range(15, 18): self.f.price(index, opening="99", closing="1", volume="0")
        self.assertEqual(before, self.f.report())

    def test_final_holdout_decision_is_explicitly_rejected(self):
        self.f.decision("heldout", source=14)
        self.assertEqual(self.reasons(), ["FINAL_HOLDOUT_WITHHELD"])

    def test_no_next_session_is_explicitly_rejected(self):
        self.f.decision("last", source=17)
        self.assertEqual(self.reasons(), ["NO_NEXT_SESSION"])

    def test_training_or_validation_fill_is_not_scored(self):
        self.f.decision("train", source=1)
        self.f.decision("validation", source=5)
        self.assertEqual(self.reasons(), ["UNSCORED_PARTITION", "UNSCORED_PARTITION"])

    def test_simple_roundtrip_conserves_cash_and_pnl(self):
        self.f.decision("buy")
        self.f.decision("sell", source=9, action="SELL")
        self.f.price(10, opening="15", closing="15")
        row = self.f.fold()
        self.assertEqual(row["metrics"]["ending_equity"], "1010")
        self.assertEqual(row["metrics"]["net_return"], "0.01")
        self.assertEqual(row["metrics"]["simulated_realized_net_pnl"], "10")
        self.assertEqual(row["open_lots"], [])

    def test_spread_slippage_and_both_fee_components_are_exact(self):
        self.f.plan["cost_model"] = {"spread_bps": "10", "slippage_bps": "5", "fee_bps": "10", "fee_per_fill": "0.1"}
        self.f.decision("buy")
        self.f.decision("sell", source=9, action="SELL")
        self.f.price(10, opening="15", closing="15")
        row = self.f.fold()
        self.assertEqual([fill["price"] for fill in row["fills"]], ["10.01", "14.985"])
        self.assertEqual(row["metrics"]["fees"], "0.24999")
        self.assertEqual(row["metrics"]["adverse_price_cost"], "0.05")
        self.assertEqual(row["metrics"]["modeled_total_cost"], "0.29999")
        self.assertEqual(row["metrics"]["simulated_total_pnl"], "9.70001")

    def test_open_position_is_marked_without_invented_exit(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy")
        self.f.price(13, closing="12")
        row = self.f.fold()
        self.assertEqual(len(row["fills"]), 1)
        self.assertEqual(row["metrics"]["simulated_realized_net_pnl"], "0")
        self.assertEqual(row["metrics"]["simulated_unrealized_net_pnl"], "3")
        self.assertEqual(row["metrics"]["ending_equity"], "1003")
        self.assertEqual(row["open_lots"][0]["remaining_qty"], "2")

    def test_partial_fifo_exit_preserves_lot_and_entry_fee(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy-a", qty="2")
        self.f.decision("buy-b", source=8, qty="3")
        self.f.price(9, opening="12", closing="12")
        self.f.decision("sell", source=9, action="SELL", qty="4")
        self.f.price(10, opening="15", closing="15")
        row = self.f.fold()
        self.assertEqual([match["qty"] for match in row["matched_lots"]], ["2", "2"])
        self.assertEqual(row["open_lots"][0]["remaining_qty"], "1")
        self.assertEqual(Decimal(row["metrics"]["simulated_realized_net_pnl"]) + Decimal(row["metrics"]["simulated_unrealized_net_pnl"]),
                         Decimal(row["metrics"]["simulated_total_pnl"]))

    def test_recurring_fifo_fee_allocations_conserve_final_remainder(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy", qty="3")
        for index in (8, 9, 10): self.f.decision("sell-" + str(index), source=index, action="SELL", qty="1")
        row = self.f.fold()
        with localcontext() as ctx:
            ctx.prec = 256
            self.assertEqual(sum(Decimal(match["allocated_entry_fee"]) for match in row["matched_lots"]), Decimal("1"))
        self.assertEqual(row["metrics"]["simulated_total_pnl"], "-4")

    def test_sell_cannot_create_a_short_position(self):
        self.f.decision("sell", action="SELL")
        self.assertEqual(self.reasons(), ["INSUFFICIENT_LONG_POSITION"])
        self.assertEqual(self.f.fold()["fills"], [])

    def test_sell_cannot_exceed_existing_long_quantity(self):
        self.f.decision("buy")
        self.f.decision("overexit", source=8, action="SELL", qty="3")
        self.assertEqual(self.reasons(), ["INSUFFICIENT_LONG_POSITION"])
        self.assertEqual(self.f.fold()["open_lots"][0]["remaining_qty"], "2")

    def test_decision_before_source_availability_is_rejected(self):
        self.f.decision("early", when=self.f.dataset["sessions"][7]["close_at"])
        self.assertEqual(self.reasons(), ["SOURCE_NOT_YET_AVAILABLE"])

    def test_decision_at_next_open_cannot_fill_that_open(self):
        self.f.decision("late", when=self.f.dataset["sessions"][8]["open_at"])
        self.assertEqual(self.reasons(), ["NEXT_OPEN_NOT_AFTER_DECISION"])

    def test_decision_after_next_open_is_not_shifted_to_later_session(self):
        self.f.decision("late", when="2026-06-09T09:00:01Z")
        self.assertEqual(self.reasons(), ["NEXT_OPEN_NOT_AFTER_DECISION"])

    def test_stale_source_rejection_is_explicit(self):
        self.f.plan["risk"]["max_staleness_seconds"] = 1
        self.f.decision("stale", when="2026-06-08T16:00:03Z")
        self.assertEqual(self.reasons(), ["STALE_SOURCE_OBSERVATION"])

    def test_staleness_boundary_is_inclusive(self):
        self.f.plan["risk"]["max_staleness_seconds"] = 61199
        self.f.decision("valid")
        self.assertEqual(self.reasons(), [])

    def test_microsecond_staleness_is_not_truncated(self):
        self.f.plan["risk"]["max_staleness_seconds"] = 1
        self.f.decision("stale", when="2026-06-08T16:00:02.000001Z")
        self.assertEqual(self.reasons(), ["STALE_SOURCE_OBSERVATION"])

    def test_source_can_be_fresh_at_decision_but_stale_at_execution_open(self):
        self.f.plan["risk"]["max_staleness_seconds"] = 61000
        self.f.decision("stale-at-fill")
        self.assertEqual(self.reasons(), ["SOURCE_STALE_AT_NEXT_OPEN"])

    def test_no_eligible_training_labels_defers_all_scoring(self):
        self.f.plan["horizon"]["label_horizon_sessions"] = 4
        self.f.decision("otherwise-valid")
        row = self.f.fold()
        self.assertEqual(row["status"], "DEFER_SPLIT_AVAILABILITY_INVALID")
        self.assertEqual(row["unscored_decision_ids"], ["otherwise-valid"])
        self.assertEqual(row["fills"], [])
        self.assertIsNone(row["metrics"])
        self.assertIsNone(row["benchmark"])

    def test_capture_time_historical_availability_cannot_be_backdated_to_score(self):
        for session in self.f.dataset["sessions"]:
            session["available_at"] = "2026-07-01T00:00:00Z"
        self.f.decision("late-capture", when="2026-06-08T16:00:02Z")
        row = self.f.fold()
        self.assertEqual(row["status"], "DEFER_SPLIT_AVAILABILITY_INVALID")
        self.assertEqual(row["fills"], [])
        self.assertIsNone(row["metrics"])

    def test_liquidity_uses_known_prior_volume_not_future_daily_volume(self):
        self.f.price(7, volume="10")
        self.f.price(8, volume="100000")
        self.f.decision("oversized", qty="2")
        self.assertEqual(self.reasons(), ["KNOWN_VOLUME_PARTICIPATION_EXCEEDED"])

    def test_future_daily_volume_cannot_reject_a_known_volume_admitted_fill(self):
        self.f.price(8, volume="0")
        self.f.decision("buy")
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.f.fold()["fills"][0]["known_volume"], "1000")

    def test_zero_prior_volume_rejects_without_partial_sizing(self):
        self.f.price(7, volume="0")
        self.f.decision("buy")
        self.assertEqual(self.reasons(), ["ZERO_KNOWN_VOLUME"])
        self.assertEqual(self.f.fold()["fills"], [])

    def test_liquidity_cap_pools_same_open_intents(self):
        self.f.price(7, volume="10")
        self.f.decision("a", qty="1")
        self.f.decision("b", qty="1")
        row = self.f.fold()
        self.assertEqual([fill["decision_id"] for fill in row["fills"]], ["a"])
        self.assertEqual(row["rejections"][0]["reason_code"], "KNOWN_VOLUME_PARTICIPATION_EXCEEDED")

    def test_rejected_liquidity_intent_does_not_consume_capacity(self):
        self.f.price(7, volume="10")
        self.f.decision("a-oversized", qty="2")
        self.f.decision("b-allowed", qty="1")
        self.assertEqual([fill["decision_id"] for fill in self.f.fold()["fills"]], ["b-allowed"])

    def test_liquidity_cap_pools_buy_and_sell_turnover(self):
        self.f.decision("initial", qty="2")
        self.f.price(8, volume="10")
        self.f.decision("a-buy", source=8, qty="1")
        self.f.decision("b-sell", source=8, action="SELL", qty="1")
        row = self.f.fold()
        self.assertEqual([fill["decision_id"] for fill in row["fills"]], ["initial", "a-buy"])
        self.assertEqual(row["rejections"][0]["reason_code"], "KNOWN_VOLUME_PARTICIPATION_EXCEEDED")

    def test_order_notional_limit_includes_modeled_fill_price(self):
        self.f.plan["risk"]["max_order_notional"] = "20"
        self.f.plan["cost_model"]["slippage_bps"] = "1"
        self.f.decision("buy")
        self.assertEqual(self.reasons(), ["MAX_ORDER_NOTIONAL_EXCEEDED"])

    def test_cash_limit_includes_fees(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy", qty="100")
        self.assertEqual(self.reasons(), ["INSUFFICIENT_CASH"])

    def test_position_fraction_uses_post_fee_equity(self):
        self.f.plan["risk"]["max_position_fraction"] = "0.02"
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy", qty="2")
        self.assertEqual(self.reasons(), ["MAX_POSITION_FRACTION_EXCEEDED"])

    def test_gross_exposure_is_consolidated_across_symbols(self):
        self.f = ResearchEvaluationFixture(["AAA", "BBB"])
        self.f.plan["risk"]["max_gross_exposure_fraction"] = "0.03"
        self.f.decision("a", symbol="AAA")
        self.f.decision("b", symbol="BBB")
        self.assertEqual(self.reasons(), ["MAX_GROSS_EXPOSURE_FRACTION_EXCEEDED"])
        self.assertEqual(len(self.f.fold()["fills"]), 1)

    def test_exit_reduces_exposure_even_when_existing_mark_is_above_buy_limit(self):
        self.f.plan["risk"]["max_position_fraction"] = "0.02"
        self.f.decision("buy", qty="2")
        self.f.price(9, opening="20", closing="20")
        self.f.decision("sell", source=8, action="SELL", qty="1")
        self.assertEqual(self.reasons(), [])

    def test_simultaneous_decisions_have_identity_order_independent_of_input_order(self):
        self.f = ResearchEvaluationFixture(["AAA", "BBB"])
        self.f.plan["risk"]["max_gross_exposure_fraction"] = "0.03"
        self.f.decision("b", symbol="BBB")
        self.f.decision("a", symbol="AAA")
        first = self.f.report()
        self.f.intents["decisions"].reverse()
        self.assertEqual(first, self.f.report())
        self.assertEqual(first["folds"][0]["fills"][0]["decision_id"], "a")

    def test_hold_is_acknowledged_without_fill_fee_or_position(self):
        self.f.decision("hold", action="HOLD", qty="0")
        row = self.f.fold()
        self.assertEqual(row["decisions"][0]["disposition"], "HOLD")
        self.assertEqual(row["fills"], [])
        self.assertEqual(row["metrics"]["modeled_total_cost"], "0")

    def test_hold_still_requires_available_and_current_source(self):
        self.f.decision("hold", action="HOLD", qty="0", when=self.f.dataset["sessions"][7]["close_at"])
        self.assertEqual(self.reasons(), ["SOURCE_NOT_YET_AVAILABLE"])

    def test_holding_limit_records_breach_without_invented_liquidation(self):
        self.f.plan["horizon"]["max_holding_sessions"] = 1
        self.f.decision("buy")
        row = self.f.fold()
        self.assertEqual(len(row["holding_breaches"]), 4)
        self.assertTrue(all(not breach["forced_exit"] for breach in row["holding_breaches"]))
        self.assertEqual(len(row["fills"]), 1)
        self.assertEqual(row["open_lots"][0]["remaining_qty"], "2")
        self.assertEqual(row["metrics"]["observed_simulation_risk_breach_count"], len(row["holding_breaches"]))

    def test_price_drift_annotates_open_and_close_concentration_without_exit(self):
        self.f.plan["risk"]["max_position_fraction"] = "0.02"
        self.f.decision("buy")
        self.f.price(8, closing="20")
        self.f.price(9, opening="20", closing="20")
        row = self.f.fold()
        self.assertEqual([(breach["session_id"], breach["mark_role"]) for breach in row["risk_breaches"]],
                         [("s8", "CLOSE"), ("s9", "OPEN"), ("s9", "CLOSE")])
        self.assertTrue(all(breach["reason_code"] == "MAX_POSITION_FRACTION_OBSERVED" and not breach["forced_exit"] for breach in row["risk_breaches"]))
        self.assertEqual(len(row["fills"]), 1)
        self.assertEqual(row["open_lots"][0]["remaining_qty"], "2")

    def test_consolidated_price_drift_records_gross_exposure_breach(self):
        self.f = ResearchEvaluationFixture(["AAA", "BBB"])
        self.f.plan["risk"]["max_position_fraction"] = "0.5"
        self.f.plan["risk"]["max_gross_exposure_fraction"] = "0.8"
        self.f.decision("a", qty="25", symbol="AAA")
        self.f.decision("b", qty="25", symbol="BBB")
        self.f.price(8, closing="100", symbol="AAA")
        self.f.price(8, closing="100", symbol="BBB")
        row = self.f.fold()
        self.assertEqual(row["risk_breaches"][0]["reason_code"], "MAX_GROSS_EXPOSURE_FRACTION_OBSERVED")
        self.assertIsNone(row["risk_breaches"][0]["symbol"])
        self.assertEqual(len(row["fills"]), 2)

    def test_rejected_fee_adjusted_admission_is_not_an_executed_risk_breach(self):
        self.f.plan["risk"]["max_position_fraction"] = "0.02"
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("fee-limited")
        row = self.f.fold()
        self.assertEqual(row["rejections"][0]["reason_code"], "MAX_POSITION_FRACTION_EXCEEDED")
        self.assertEqual(row["risk_breaches"], [])
        self.assertEqual(row["metrics"]["observed_simulation_risk_breach_count"], 0)

    def test_close_drawdown_uses_initial_cash_and_no_intraday_low_claim(self):
        self.f.decision("buy", qty="10")
        self.f.price(8, closing="5")
        self.f.price(9, closing="8")
        row = self.f.fold()
        self.assertEqual(row["metrics"]["maximum_close_drawdown"], "0.05")
        self.assertEqual(row["metrics"]["maximum_drawdown_duration_sessions"], 2)

    def test_initial_fill_fees_can_create_drawdown(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy")
        self.assertEqual(self.f.fold()["metrics"]["maximum_close_drawdown"], "0.001")

    def test_open_and_close_marks_are_distinct(self):
        self.f.decision("buy")
        self.f.price(8, closing="12")
        row = self.f.fold()
        self.assertEqual(row["opening_equity_curve"][0]["equity"], "1000")
        self.assertEqual(row["equity_curve"][0]["equity"], "1004")

    def test_empty_sample_does_not_invent_expectancy_or_profit_factor(self):
        metrics = self.f.fold()["metrics"]
        self.assertIsNone(metrics["simulated_net_expectancy_per_sell_fill"])
        self.assertIsNone(metrics["sell_fill_win_rate"])
        self.assertIsNone(metrics["sell_fill_profit_factor"])
        self.assertEqual(metrics["net_return"], "0")

    def test_no_losses_makes_profit_factor_undefined(self):
        self.f.decision("buy")
        self.f.decision("sell", source=8, action="SELL")
        self.f.price(9, opening="12")
        self.assertIsNone(self.f.fold()["metrics"]["sell_fill_profit_factor"])

    def test_losing_sample_has_defined_zero_profit_factor(self):
        self.f.decision("buy")
        self.f.decision("sell", source=8, action="SELL")
        self.f.price(9, opening="5")
        metrics = self.f.fold()["metrics"]
        self.assertEqual(metrics["sell_fill_profit_factor"], "0")
        self.assertEqual(metrics["sell_fill_win_rate"], "0")
        self.assertEqual(metrics["simulated_net_expectancy_per_sell_fill"], "-10")

    def test_zero_profit_exit_is_neither_winner_nor_loser(self):
        self.f.decision("buy")
        self.f.decision("sell", source=8, action="SELL")
        metrics = self.f.fold()["metrics"]
        self.assertEqual(metrics["profitable_sell_fill_count"], 0)
        self.assertEqual(metrics["losing_sell_fill_count"], 0)
        self.assertEqual(metrics["sell_fill_win_rate"], "0")

    def test_unannualized_metrics_do_not_claim_unimplemented_statistics(self):
        metrics = self.f.fold()["metrics"]
        for key in ("sharpe_ratio", "sortino_ratio", "annualized_return"):
            self.assertIsNone(metrics[key])
        self.assertEqual(metrics["statistical_significance"], "NOT_ASSESSED")

    def test_cash_benchmark_has_no_cost_or_return(self):
        baseline = self.f.fold()["benchmark"]
        self.assertEqual(baseline["kind"], "CASH")
        self.assertEqual(baseline["net_return"], "0")
        self.assertEqual(baseline["ending_equity"], "1000")

    def test_day_horizon_is_explicitly_deferred_not_daily_simulated(self):
        self.f.plan["horizon"]["kind"] = "DAY"
        self.f.decision("day-intent")
        row = self.f.fold()
        self.assertEqual(row["status"], "DEFER_UNSUPPORTED_DAY_HORIZON")
        self.assertEqual(row["unscored_decision_ids"], ["day-intent"])
        self.assertEqual(row["fills"], [])
        self.assertIsNone(row["metrics"])

    def test_each_fold_resets_cash_and_positions_without_return_aggregation(self):
        self.f = ResearchEvaluationFixture(count=25)
        self.f.plan["protocol"]["folds"].append({"fold_id": "f2", "train": {"start_index": 0, "end_index": 8},
                                                "validation": {"start_index": 10, "end_index": 12},
                                                "test": {"start_index": 14, "end_index": 20}})
        self.f.plan["protocol"]["final_holdout"] = {"start_index": 22, "end_index": 24}
        self.f.decision("f1buy")
        self.f.decision("f2exit", source=13, action="SELL", fold="f2")
        report = self.f.report()
        self.assertEqual(report["folds"][1]["rejections"][0]["reason_code"], "INSUFFICIENT_LONG_POSITION")
        self.assertEqual(report["folds"][1]["metrics"]["ending_equity"], "1000")
        self.assertIsNone(report["aggregate"])

    def test_ambient_decimal_precision_rounding_and_traps_cannot_change_result(self):
        self.f.plan["cost_model"]["fee_per_fill"] = "1"
        self.f.decision("buy", qty="3")
        self.f.decision("sell", source=8, action="SELL", qty="1")
        normal = canonical_json_bytes(self.f.report())
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.traps[Inexact] = True
            ctx.traps[Rounded] = True
            ctx.rounding = "ROUND_FLOOR"
            self.assertEqual(normal, canonical_json_bytes(self.f.report()))

    def test_inputs_remain_byte_identical_after_evaluation(self):
        before = canonical_json_bytes([self.f.plan, self.f.dataset, self.f.intents])
        self.f.report()
        self.assertEqual(before, canonical_json_bytes([self.f.plan, self.f.dataset, self.f.intents]))

    def test_mutating_a_report_cannot_change_later_precision_policy(self):
        original = self.f.report()
        changed = self.f.report()
        changed["precision_policy"]["calculation_precision"] = 1
        changed["authority"]["execution_enabled"] = True
        self.assertEqual(original, self.f.report())

    def test_typed_and_mapping_inputs_have_identical_result(self):
        actual = engine.evaluate_research(TradingResearchPlan.from_mapping(self.f.plan),
                                         TradingResearchDataset.from_mapping(self.f.dataset),
                                         TradingResearchIntents.from_mapping(self.f.intents))
        self.assertEqual(actual, self.f.report())

    def test_realized_trade_pnl_and_all_authority_remain_disabled(self):
        self.f.decision("buy")
        report = self.f.report()
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertFalse(report["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual(report["scope"], "DEVELOPMENT_EVALUATION_ONLY")

    def test_engine_has_no_native_strategy_or_execution_imports(self):
        imports = []
        for node in ast.walk(ast.parse(inspect.getsource(engine))):
            if isinstance(node, ast.Import): imports.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom): imports.append(node.module or "")
        forbidden = ("galactica", "battlestar", "brigade", "navigator", "broker", "spyglass", "forecast", "modeldock")
        self.assertFalse(any(word in name.lower() for name in imports for word in forbidden))

    def test_structural_missing_mark_is_rejected_not_forward_filled(self):
        self.f.dataset["sessions"][8]["bars"] = []
        with self.assertRaises(ValueError): self.f.report()

    def test_split_projection_rejects_indices_outside_data(self):
        self.f.plan["protocol"]["final_holdout"]["end_index"] = 999
        with self.assertRaises(ValueError): engine.plan_chronological_splits(self.f.plan, self.f.dataset)

    def test_combined_projection_bound_rejects_before_simulation_or_label_loops(self):
        self.f = ResearchEvaluationFixture(count=5000)
        self.f.dataset["recorded_at"] = "2050-01-01T00:00:00Z"
        self.f.plan["protocol"]["folds"] = [
            {"fold_id": "large-" + str(index), "train": {"start_index": 0, "end_index": 3999},
             "validation": {"start_index": 4500, "end_index": 4501},
             "test": {"start_index": 4603 + index, "end_index": 4603 + index}} for index in range(6)]
        self.f.plan["protocol"]["final_holdout"] = {"start_index": 4900, "end_index": 4999}
        with patch.object(engine, "_split_projection", side_effect=AssertionError("projection loops forbidden")):
            with self.assertRaisesRegex(ValueError, "20000"):
                self.f.report()
            with self.assertRaisesRegex(ValueError, "20000"):
                engine.plan_chronological_splits(self.f.plan, self.f.dataset)

    def test_stale_observation_never_produces_forced_or_repaired_fill(self):
        self.f.plan["risk"]["max_staleness_seconds"] = 1
        self.f.decision("stale", when="2026-06-08T16:00:03Z")
        row = self.f.fold()
        self.assertEqual(row["fills"], [])
        self.assertEqual(row["metrics"]["fill_count"], 0)
        self.assertEqual(row["metrics"]["ending_equity"], "1000")


if __name__ == "__main__":
    unittest.main()
