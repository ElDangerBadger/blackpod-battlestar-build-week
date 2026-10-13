"""Offline tests of deterministic passive desk proposals and source replay."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext
import socket
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import patch

from blackpod_build_week import desk_candidate_review as engine
from blackpod_build_week.contracts.desk_candidate_review import DeskReviewInput
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_test_budget import build_paper_test_budget

NOW = "2026-10-12T21:00:00Z"


def metric_snapshot():
    return {"latestQuote": {"t": NOW, "bp": 99.9, "ap": 100.1, "bs": 10, "as": 20},
            "latestTrade": {"t": NOW, "p": 100.0},
            "dailyBar": {"t": "2026-10-12T04:00:00Z", "o": 100, "h": 102, "l": 98, "c": 100, "v": 10000},
            "prevDailyBar": {"t": "2026-10-09T04:00:00Z", "o": 99, "h": 101, "l": 97, "c": 99, "v": 10000}}


def metric_bars(count=61):
    start = datetime(2026, 7, 1, 4, tzinfo=timezone.utc)
    return [{"t": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"),
             "o": 100, "h": 102, "l": 98, "c": 100, "v": 10000} for i in range(count)]


class DeskReviewFixture:
    """Retained reviewed code plus explicit synthetic account/market evidence."""
    def __init__(self):
        from test_trading_reconciliation_engine import ReconciliationFixture
        from test_shadow_native_analysis import test_fixture_sources, test_fixture_market
        from blackpod_build_week.shadow_native_analysis import derive_native_analysis
        self.base = ReconciliationFixture()
        self.events, self.blobs = list(self.base.events), dict(self.base.blobs)
        self.recorded_at = "2026-10-15T21:00:00Z"
        self.market = test_fixture_market()
        self.market["captured_at"] = "2026-10-15T20:30:00Z"
        start = datetime(2026, 8, 15, 4, tzinfo=timezone.utc)
        for symbol, snapshot in self.market["snapshots"].items():
            snapshot["latestTrade"]["t"] = "2026-10-15T20:00:00Z"
            snapshot["latestQuote"]["t"] = "2026-10-15T20:00:00Z"
            snapshot["dailyBar"]["t"] = "2026-10-15T04:00:00Z"
            snapshot["prevDailyBar"]["t"] = "2026-10-14T04:00:00Z"
            self.market["bars"][symbol] = [{"t": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"),
                "o": 100, "h": 102, "l": 98, "c": 100, "v": 100000} for i in range(62)]
        self.market["source_evidence"] = [self.reference("shadow-desk/raw-snapshots.json", canonical_json_bytes(self.market["snapshots"])),
            self.reference("shadow-desk/raw-bars.json", canonical_json_bytes({"bars": self.market["bars"], "next_page_token": None}))]
        self.sources = test_fixture_sources()
        self.blobs.update({sha256_bytes(raw): raw for raw in self.sources.values()})
        self.analysis = derive_native_analysis(self.market, self.sources)
        self.issuer = {"schema_version": "blackpod.shadow_issuer_facts.v1", "captured_at": self.market["captured_at"], "facts": [], "source_evidence": []}
        for symbol, asset_class, corporate_action in (("SPY", "BROAD_EQUITY", False), ("USMV", "LOW_VOL_EQUITY", False), ("QUAL", "FACTOR_EQUITY", True)):
            url = "https://www.ssga.com/fixture/" + symbol.lower()
            excerpt = "Synthetic test excerpt for " + symbol + "; not real issuer research."
            raw = canonical_json_bytes({"schema_version": "blackpod.public_issuer_source.v1", "source_url": url,
                "retrieved_at": self.market["captured_at"], "content": excerpt})
            reference = self.reference("shadow-desk/issuer-source-" + symbol + ".json", raw)
            self.issuer["source_evidence"].append(reference)
            self.issuer["facts"].append({"symbol": symbol, "fund_name": "Synthetic " + symbol, "issuer": "Fixture issuer",
                "mandate": "Synthetic mandate for test coverage only", "structure": "ETF", "asset_class": asset_class,
                "corporate_action_before_horizon": corporate_action, "source_url": url, "as_of": "2026-10-15",
                "source_excerpt": excerpt, "source_evidence": reference})
        self.budget = build_paper_test_budget(self.base.snapshot_event, budget_id="fixture-paper-budget", recorded_at="2026-10-15T00:01:00Z", declared_by="fixture-human")
        self.document = self.document_for()

    def close(self): self.base.close()

    def reference(self, path, raw):
        self.blobs[sha256_bytes(raw)] = raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}

    def document_for(self, **changes):
        value = {"schema_version": "blackpod.shadow_two_desk_review.v1", "review_id": "fixture-desk-review", "recorded_at": self.recorded_at,
            "mode": "PAPER", "account_id": "fixture-account", "scope": "SHADOW_TWO_DESK_REVIEW_ONLY",
            "budget": {"proposal_evidence": self.reference("shadow-desk/budget.json", self.budget.to_bytes()),
                "source_snapshot_event_id": self.base.snapshot_event.event_id, "source_snapshot_sha256": self.base.snapshot_event.source["source_sha256"]},
            "sources": {"market_evidence": self.reference("shadow-desk/market.json", canonical_json_bytes(self.market)),
                "analysis_evidence": self.reference("shadow-desk/analysis.json", canonical_json_bytes(self.analysis)),
                "issuer_evidence": self.reference("shadow-desk/issuers.json", canonical_json_bytes(self.issuer))},
            "policy": {"status": "PROPOSED_SHADOW_ONLY", "max_entry_fraction": "0.10", "scenario_risk_fraction": "0.0025",
                "atr_multiple": "2", "price_buffer_fraction": "0.01", "investment_candidate_fraction": "0.20", "max_active_entries": 1,
                "max_completed_cycles": 1, "expires_at": "2026-10-16T21:00:00Z", "investment_horizon_days": 90, "benchmark_symbol": "SPY"},
            "authority": {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}}
        value.update(changes)
        return DeskReviewInput.from_mapping(value)

    def add(self, event, evidence):
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})

    def evidence(self): return engine.evidence_for_desk_review(self.document, self.events, self.blobs)

    def with_galactica(self):
        from blackpod_build_week.shadow_galactica_analysis import build_shadow_galactica_analysis
        source = (Path(__file__).resolve().parents[1] / "fixtures/shadow_galactica_analysis/spyglass.py").read_bytes()
        market_raw = canonical_json_bytes(self.market)
        self.blobs[sha256_bytes(market_raw)] = market_raw
        self.blobs[sha256_bytes(source)] = source
        galactica = build_shadow_galactica_analysis(market_raw, source, generated_at=self.recorded_at)
        native = self.analysis.get("native", self.analysis)
        references = list(native["source_evidence"]) + [ref for ref in galactica["source_evidence"].values() if ref is not None]
        self.analysis = {"schema_version": "blackpod.shadow_analysis_bundle.v1", "native": native,
                         "galactica": galactica, "source_evidence": references}
        self.document = self.document_for()
        return self

    def refresh_market(self):
        from blackpod_build_week.shadow_native_analysis import derive_native_analysis
        self.market["source_evidence"] = [self.reference("shadow-desk/raw-snapshots.json", canonical_json_bytes(self.market["snapshots"])),
            self.reference("shadow-desk/raw-bars.json", canonical_json_bytes({"bars": self.market["bars"], "next_page_token": None}))]
        self.analysis = derive_native_analysis(self.market, self.sources)
        self.document = self.document_for()
        return self


class MetricTests(unittest.TestCase):
    def calculate(self, snapshot=None, bars=None):
        return engine.calculate_symbol_metrics(snapshot or metric_snapshot(), bars if bars is not None else metric_bars(), captured_at=NOW)

    def test_atr_is_mean_true_range_and_returns_have_exact_offsets(self):
        values = self.calculate()
        self.assertEqual(values["atr14"], "4")
        self.assertEqual(values["sma20"], "100")
        self.assertEqual(values["sma50"], "100")
        self.assertEqual(values["return20_pct"], "0")
        self.assertEqual(values["return60_pct"], "0")
        self.assertEqual(values["iex_average_dollar_volume20"], "1000000")
        self.assertEqual(values["spread_pct"], "0.2")

    def test_gap_is_part_of_true_range(self):
        bars = metric_bars()
        bars[-1].update(o=110, h=112, l=108, c=110)
        values = self.calculate(bars=bars)
        with localcontext(Context(prec=64)):
            self.assertEqual(Decimal(values["atr14"]), Decimal(64) / 14)
        self.assertEqual(values["return20_pct"], "10")

    def test_insufficient_history_is_explicit_null(self):
        values = self.calculate(bars=metric_bars(10))
        for field in ("atr14", "sma20", "sma50", "return20_pct", "return60_pct", "iex_average_dollar_volume20"):
            self.assertIsNone(values[field])

    def test_crossed_and_zero_quotes_do_not_invent_spread(self):
        for bid, ask in ((101, 100), (0, 100), (0, 0)):
            snapshot = metric_snapshot()
            snapshot["latestQuote"].update(bp=bid, ap=ask)
            self.assertIsNone(self.calculate(snapshot)["spread_pct"])

    def test_true_range_needs_fifteen_bars(self):
        self.assertIsNone(self.calculate(bars=metric_bars(14))["atr14"])
        self.assertEqual(self.calculate(bars=metric_bars(15))["atr14"], "4")

    def test_duplicate_or_out_of_order_bars_rejected(self):
        for bars in (metric_bars() + [metric_bars()[-1]], list(reversed(metric_bars()))):
            with self.assertRaises(ValueError): self.calculate(bars=bars)

    def test_future_trade_quote_or_bar_rejected(self):
        for key in ("latestTrade", "latestQuote"):
            snapshot = metric_snapshot()
            snapshot[key]["t"] = "2026-10-13T00:00:00Z"
            with self.assertRaises(ValueError): self.calculate(snapshot)
        bars = metric_bars()
        bars[-1]["t"] = "2026-10-13T00:00:00Z"
        with self.assertRaises(ValueError): self.calculate(bars=bars)

    def test_invalid_daily_geometry_rejected(self):
        for field, value in (("l", 101), ("h", 99), ("v", -1), ("c", 0)):
            bars = metric_bars()
            bars[-1][field] = value
            with self.assertRaises(ValueError): self.calculate(bars=bars)

    def test_nonfinite_bool_or_exponent_provider_values_rejected(self):
        for value in (float("inf"), float("nan"), True, "1e2", None):
            snapshot = metric_snapshot()
            snapshot["latestTrade"]["p"] = value
            with self.assertRaises(ValueError): self.calculate(snapshot)

    def test_ambient_decimal_context_does_not_change_metrics(self):
        bars = metric_bars()
        bars[-1].update(o=110, h=112, l=108, c=110)
        expected = self.calculate(bars=bars)
        with localcontext(Context(prec=4)):
            self.assertEqual(self.calculate(bars=bars), expected)

    def test_metric_projection_uses_no_network(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.calculate()

    def test_nanosecond_provider_time_comparisons_preserve_original_values(self):
        snapshot = metric_snapshot()
        snapshot["latestQuote"]["t"] = "2026-10-12T20:00:00.123456789Z"
        snapshot["latestTrade"]["t"] = "2026-10-12T20:00:00.34576699Z"
        original = copy.deepcopy(snapshot)
        self.assertEqual(self.calculate(snapshot)["last"], "100")
        self.assertEqual(snapshot, original)

    def test_same_day_daily_bar_not_proven_complete_is_excluded(self):
        bars = metric_bars()
        bars[-1].update(t="2026-10-12T04:00:00Z", o=200, h=210, l=190, c=200)
        result = self.calculate(bars=bars)
        self.assertEqual(result["atr14"], "4")
        self.assertEqual(result["sma50"], "100")
        self.assertIsNone(result["return60_pct"])


class SizingTests(unittest.TestCase):
    def setUp(self):
        self.policy = {"max_entry_fraction": "0.10", "scenario_risk_fraction": "0.0025", "atr_multiple": "2",
            "price_buffer_fraction": "0.01", "investment_candidate_fraction": "0.20", "expires_at": "2026-10-13T21:00:00Z",
            "investment_horizon_days": 90, "benchmark_symbol": "SPY"}
        self.document = SimpleNamespace(policy=self.policy)

    def row(self, symbol, category="TRADING_PILOT", ask="100", atr="4"):
        return {"symbol": symbol, "category": category, "metrics": {"ask": ask, "atr14": atr}}

    def plan(self, rows):
        with localcontext(Context(prec=64)):
            return engine._plan(self.document, rows, Decimal("10190.63"), Decimal("10190.63"))

    def test_fixed_budget_risk_and_notional_limit_whole_shares(self):
        trading, investment = self.plan([self.row("QQQ")])
        self.assertEqual(trading["max_entry_notional_usd"], "1019.06")
        self.assertEqual(trading["qty"], 3)
        self.assertEqual(trading["buffered_price_usd"], "101")
        self.assertEqual(trading["estimated_notional_usd"], "303")
        self.assertEqual(trading["scenario_loss_usd"], "24")
        self.assertEqual(trading["total_round_trip_notional_usd"], "606")
        self.assertTrue(trading["authorization_required"])
        self.assertIsNone(trading["return_expectation"])
        self.assertFalse(investment["allocation_authorized"])

    def test_notional_limit_wins_for_low_atr(self):
        trading, _ = self.plan([self.row("QQQ", atr="0.1")])
        self.assertEqual(trading["qty"], 10)
        self.assertEqual(trading["estimated_notional_usd"], "1010")

    def test_no_whole_share_size_defers_instead_of_fractional_or_leverage(self):
        trading, _ = self.plan([self.row("QQQ", ask="2000")])
        self.assertEqual(trading["status"], "DEFER")
        self.assertIsNone(trading["symbol"])
        self.assertEqual(trading["qty"], 0)

    def test_zero_or_unrepresentable_stop_does_not_create_pilot(self):
        for atr in ("0", "60"):
            trading, _ = self.plan([self.row("QQQ", atr=atr)])
            self.assertEqual(trading["status"], "DEFER")

    def test_next_suitable_rank_is_used_if_first_cannot_fit(self):
        trading, _ = self.plan([self.row("DIA", ask="2000"), self.row("QQQ")])
        self.assertEqual(trading["symbol"], "QQQ")

    def test_investment_sizes_and_cash_conserve_fixed_budget(self):
        _, investment = self.plan([self.row("SPY", "INVESTMENT_RESEARCH"), self.row("USMV", "INVESTMENT_RESEARCH")])
        self.assertEqual([row["qty"] for row in investment["candidates"]], [20, 20])
        self.assertEqual(investment["total_notional_usd"], "4040")
        self.assertEqual(investment["cash_reserve_usd"], "6150.63")
        self.assertTrue(all(row["expected_return"] is None for row in investment["candidates"]))

    def test_pilot_symbol_is_not_proposed_to_both_desks(self):
        trading, investment = self.plan([self.row("QQQ"), self.row("QQQ", "INVESTMENT_RESEARCH"), self.row("SPY", "INVESTMENT_RESEARCH")])
        self.assertEqual(trading["symbol"], "QQQ")
        self.assertEqual([row["symbol"] for row in investment["candidates"]], ["SPY"])

    def test_at_most_three_research_slices_and_fixed_cash_conservation(self):
        _, investment = self.plan([self.row(symbol, "INVESTMENT_RESEARCH") for symbol in ("SPY", "USMV", "IWD", "QUAL")])
        self.assertEqual(len(investment["candidates"]), 3)
        self.assertEqual(Decimal(investment["total_notional_usd"]) + Decimal(investment["cash_reserve_usd"]), Decimal("10190.63"))


class ReviewProjectionTests(unittest.TestCase):
    def setUp(self): self.f = DeskReviewFixture()
    def tearDown(self): self.f.close()

    def assess(self, document=None):
        return engine.assess_desk_review(document or self.f.document, self.f.events, self.f.blobs)

    def test_source_bound_native_attention_and_conditional_pilot_not_trade_authority(self):
        result = self.assess()
        self.assertEqual(result["status"], "SHADOW_REVIEW_ONLY")
        self.assertEqual(result["budgets_usd"], {"TRADING": "12500.00", "INVESTMENT": "12500.00"})
        self.assertEqual(result["trading_plan"]["symbol"], "XLK")
        self.assertGreater(result["trading_plan"]["qty"], 0)
        self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(result["readiness"])
        self.assertTrue(all(value is False for value in result["authority"].values()))
        self.assertIn("ECONOMIC_TRADE_DEFERRED_NO_NATIVE_REVIEW_AND_FAVORABLE_DISCUSSION", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_native_confidence_remains_label_not_probability(self):
        result = self.assess()
        row = next(row for row in result["candidates"] if row["symbol"] == "XLK")
        self.assertEqual(row["native"]["candidate_state"], "REVIEW")
        self.assertIn("heuristic, not probability", row["native"]["confidence_label"])
        self.assertFalse(result["native_summary"]["independent_evidence"])

    def test_known_etn_structure_excluded(self):
        row = next(row for row in self.assess()["candidates"] if row["symbol"] == "VXZ")
        self.assertEqual(row["category"], "EXCLUDE")

    def test_missing_blob_fails_closed(self):
        digest = self.f.document.sources["market_evidence"]["sha256"]
        self.f.blobs.pop(digest)
        with self.assertRaises(ValueError): self.assess()

    def test_blob_hash_tamper_fails_closed(self):
        digest = self.f.document.sources["market_evidence"]["sha256"]
        self.f.blobs[digest] += b" "
        with self.assertRaises(ValueError): self.assess()

    def test_missing_source_code_fails_closed(self):
        self.f.blobs.pop(sha256_bytes(next(iter(self.f.sources.values()))))
        with self.assertRaises(ValueError): self.assess()

    def test_account_or_snapshot_binding_mismatch_fails(self):
        with self.assertRaises(ValueError): self.assess(self.f.document_for(account_id="another-account"))
        value = self.f.document.to_dict()
        value["budget"]["source_snapshot_sha256"] = "0" * 64
        with self.assertRaises(ValueError): self.assess(DeskReviewInput.from_mapping(value))

    def test_budget_recorded_after_review_fails(self):
        document = self.f.document_for(recorded_at="2026-10-14T21:00:00Z")
        with self.assertRaises(ValueError): self.assess(document)

    def test_immutable_event_replays_with_all_retained_original_code(self):
        event = engine.build_desk_review_event(self.f.document, self.f.events, self.f.blobs)
        evidence = self.f.evidence()
        self.assertEqual(event.domain, "CAPITAL_ALLOCATION")
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v8")
        self.assertTrue(set("native_analysis_code/" + path for path in self.f.sources) <= set(evidence))
        engine.validate_desk_review_event(event, self.f.events, self.f.blobs)

    def test_retry_uses_original_prefix_and_identity(self):
        first = engine.build_desk_review_event(self.f.document, self.f.events, self.f.blobs)
        self.f.add(first, self.f.evidence())
        later = self.f.document_for(review_id="later-review", recorded_at="2026-10-15T22:00:00Z")
        second = engine.build_desk_review_event(later, self.f.events, self.f.blobs)
        self.f.add(second, engine.evidence_for_desk_review(later, self.f.events, self.f.blobs))
        self.assertEqual(engine.build_desk_review_event(self.f.document, self.f.events, self.f.blobs).to_bytes(), first.to_bytes())

    def test_conflicting_retry_input_fails(self):
        first = engine.build_desk_review_event(self.f.document, self.f.events, self.f.blobs)
        self.f.add(first, self.f.evidence())
        changed = self.f.document.to_dict()
        changed["policy"]["max_entry_fraction"] = "0.20"
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.assess(DeskReviewInput.from_mapping(changed))

    def test_source_packets_and_events_are_immutable(self):
        before = (copy.deepcopy(self.f.market), copy.deepcopy(self.f.analysis), copy.deepcopy(self.f.issuer), [event.to_bytes() for event in self.f.events])
        self.assess()
        self.assertEqual(before, (self.f.market, self.f.analysis, self.f.issuer, [event.to_bytes() for event in self.f.events]))

    def test_complete_projection_is_offline(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            self.assess()

    def test_spyglass_is_replayed_on_identical_retained_market_and_code(self):
        self.f.with_galactica()
        result = self.assess()
        self.assertIn("BRIGADE_CURRENT_FORECASTS_UNAVAILABLE_INFERENCE_NOT_RUN", result["reason_codes"])
        self.assertNotIn("BRIGADE_HISTORICAL_OPINIONS_ARE_CONTEXT_ONLY_NOT_CURRENT_VOTES", result["reason_codes"])
        self.assertFalse(result["auto_trading_enabled"])
        self.assertIn("galactica/spyglass.py", self.f.evidence())

    def test_spyglass_challenge_blocks_candidate_instead_of_silent_override(self):
        for bars in self.f.market["bars"].values():
            for index, row in enumerate(bars):
                row["h"] = 105 if index % 10 == 5 else 102
        self.f.refresh_market()
        self.f.with_galactica()
        result = self.assess()
        self.assertTrue(any("RESISTANCE_HEADROOM_LT_STOP_SCENARIO" in row["reason_codes"] or "BEARISH_PATTERN" in row["reason_codes"]
                            or "DOWNWARD_BREAKOUT" in row["reason_codes"] for row in result["candidates"]))
        for row in result["candidates"]:
            if row["category"] not in {"INVESTMENT_RESEARCH", "EXCLUDE"} and set(row["reason_codes"]) & {"RESISTANCE_HEADROOM_LT_STOP_SCENARIO", "BEARISH_PATTERN", "DOWNWARD_BREAKOUT"}:
                self.assertEqual(row["category"], "DEFER")

    def test_spyglass_rehashed_facts_cannot_change_replay(self):
        self.f.with_galactica()
        self.f.analysis["galactica"]["spyglass"]["observations"][0]["bar_count"] += 1
        self.f.document = self.f.document_for()
        with self.assertRaises(ValueError): self.assess()

    def test_analysis_bundle_missing_evidence_union_rejected(self):
        self.f.with_galactica()
        self.f.analysis["source_evidence"] = self.f.analysis["source_evidence"][:-1]
        self.f.document = self.f.document_for()
        with self.assertRaises(ValueError): self.assess()

    def test_stale_quotes_or_trade_data_defer_all_unowned_entries(self):
        for snapshot in self.f.market["snapshots"].values():
            snapshot["latestQuote"]["t"] = "2026-10-13T19:00:00Z"
        self.f.refresh_market()
        result = self.assess()
        self.assertEqual(result["trading_plan"]["status"], "DEFER")
        self.assertEqual(result["trading_plan"]["qty"], 0)
        self.assertEqual(result["investment_plan"]["candidates"], [])

    def test_review_more_than_twenty_four_hours_after_capture_defers_size(self):
        document = self.f.document_for(recorded_at="2026-10-16T20:31:00Z")
        result = self.assess(document)
        self.assertEqual(result["trading_plan"]["status"], "DEFER")
        self.assertEqual(result["investment_plan"]["candidates"], [])

    def test_future_issuer_capture_is_rejected(self):
        self.f.issuer["captured_at"] = "2026-10-16T20:30:00Z"
        self.f.document = self.f.document_for()
        with self.assertRaisesRegex(ValueError, "issuer capture postdates"):
            self.assess()

    def test_future_galactica_generation_is_rejected(self):
        from blackpod_build_week.shadow_galactica_analysis import build_shadow_galactica_analysis
        self.f.with_galactica()
        source = self.f.blobs[self.f.analysis["galactica"]["source_evidence"]["spyglass"]["sha256"]]
        self.f.analysis["galactica"] = build_shadow_galactica_analysis(canonical_json_bytes(self.f.market), source,
            generated_at="2026-10-16T20:30:00Z")
        self.f.document = self.f.document_for()
        with self.assertRaisesRegex(ValueError, "Galactica analysis postdates"):
            self.assess()

    def test_unknown_source_pattern_never_becomes_probability_or_order(self):
        self.f.with_galactica()
        result = self.assess()
        self.assertTrue(all(row["confidence_is_probability"] is False for row in self.f.analysis["galactica"]["spyglass"]["observations"]))
        self.assertFalse(result["authority"]["execution_enabled"])

    def test_issuer_source_binding_and_corporate_action_exclusion(self):
        result = self.assess()
        self.assertEqual([row["symbol"] for row in result["investment_plan"]["candidates"]], ["SPY", "USMV"])
        qual = next(row for row in result["candidates"] if row["symbol"] == "QUAL")
        self.assertEqual(qual["category"], "EXCLUDE")
        self.assertIn("KNOWN_CORPORATE_ACTION_INSIDE_PROPOSED_HORIZON", qual["reason_codes"])

    def test_source_excerpt_tamper_fails_even_with_new_packet_hash(self):
        self.f.issuer["facts"][0]["source_excerpt"] = "An invented source claim"
        self.f.document = self.f.document_for()
        with self.assertRaises(ValueError): self.assess()

    def test_changed_normalized_quote_cannot_override_original_provider_evidence(self):
        self.f.market["snapshots"]["SPY"]["latestQuote"]["ap"] = 1
        self.f.document = self.f.document_for()
        with self.assertRaisesRegex(ValueError, "retained provider maps"):
            self.assess()


if __name__ == "__main__":
    unittest.main()
