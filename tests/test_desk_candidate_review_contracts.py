"""Offline strict passive two-desk contracts and additive journal envelopes."""
from __future__ import annotations

import copy
import unittest
from decimal import Inexact, Rounded, ROUND_DOWN, localcontext

from blackpod_build_week.contracts.decision_journal import (
    JournalEvent, JOURNAL_EVENT_V8_SCHEMA_VERSION, SHADOW_DESK_REVIEW_EVENT_TYPE,
)
from blackpod_build_week.contracts.desk_candidate_review import (
    DeskReviewInput, DESK_REVIEW_SCHEMA_VERSION, DESK_REVIEW_SCOPE, DESK_REVIEW_LIMITATIONS, DESK_REVIEW_METHOD_VERSION,
    METRIC_FIELDS, validate_review_result,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import sha256_bytes


def authority():
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def evidence(path):
    return {"path": path, "sha256": "a" * 64, "size_bytes": 12}


def review_mapping():
    return {"schema_version": DESK_REVIEW_SCHEMA_VERSION, "review_id": "review-001",
        "recorded_at": "2026-10-12T20:00:00Z", "mode": "PAPER", "account_id": "synthetic-paper-account",
        "scope": DESK_REVIEW_SCOPE, "budget": {"proposal_evidence": evidence("budget/proposal.json"),
            "source_snapshot_event_id": "journal-event-" + "b" * 64, "source_snapshot_sha256": "c" * 64},
        "sources": {"market_evidence": evidence("sources/market.json"), "analysis_evidence": evidence("sources/analysis.json"),
            "issuer_evidence": evidence("sources/issuers.json")},
        "policy": {"status": "PROPOSED_SHADOW_ONLY", "max_entry_fraction": "0.10", "scenario_risk_fraction": "0.0025",
            "atr_multiple": "2", "price_buffer_fraction": "0.01", "investment_candidate_fraction": "0.20",
            "max_active_entries": 1, "max_completed_cycles": 1, "expires_at": "2026-10-13T20:00:00Z",
            "investment_horizon_days": 90, "benchmark_symbol": "SPY"}, "authority": authority()}


def candidate(symbol="AAA", category="TRADING_PILOT", rank=1):
    return {"symbol": symbol, "category": category, "rank": rank, "metrics": dict.fromkeys(METRIC_FIELDS),
            "native": {"candidate_state": "WATCH", "senate_disposition": "MONITOR", "confidence_label": "0.7 (heuristic, not probability)"},
            "reason_codes": []}


def result_mapping():
    document = DeskReviewInput.from_mapping(review_mapping())
    return {"method_version": DESK_REVIEW_METHOD_VERSION, "status": "SHADOW_REVIEW_ONLY", "account_id": document.account_id,
        "budget_source_snapshot_event_id": document.budget["source_snapshot_event_id"],
        "budgets_usd": {"TRADING": "10190.63", "INVESTMENT": "10190.63"}, "market_as_of": "2026-10-12T19:59:00Z",
        "native_summary": {"oracle_state": "RISK_ON", "candidate_counts": {"WATCH": 2}, "senate_counts": {"MONITOR": 2}, "independent_evidence": False},
        "candidates": [candidate(), candidate("BBB", "INVESTMENT_RESEARCH")],
        "trading_plan": {"status": "CONDITIONAL_FUNCTIONAL_PILOT", "symbol": "AAA", "qty": 5, "max_entry_notional_usd": "1019.06",
            "buffered_price_usd": "101", "estimated_notional_usd": "505", "stop_distance_usd": "2", "scenario_loss_usd": "10",
            "total_round_trip_notional_usd": "1010", "maximum_completed_cycles": 1, "max_active_entries": 1, "time_exit_minutes": 30,
            "expiry": document.policy["expires_at"], "authorization_required": True, "purpose": "EXECUTION_AND_ACCOUNTING_TEST", "return_expectation": None},
        "investment_plan": {"status": "RESEARCH_ONLY", "horizon_days": 90,
            "candidates": [{"symbol": "BBB", "qty": 10, "buffered_price_usd": "101", "estimated_notional_usd": "1010",
                "hypothesis": "Proposed relative-strength persistence over the stated horizon.",
                "invalidation_conditions": ["Persistent decline below the stated moving average."], "expected_return": None}],
            "total_notional_usd": "1010", "cash_reserve_usd": "9180.63", "allocation_authorized": False},
        "ownership_proposal": {"TRADING": ["AAA"], "INVESTMENT": ["BBB"], "status": "PROPOSED_NOT_INSTALLED"},
        "readiness": False, "auto_trading_enabled": False, "realized_trade_pnl": None, "authority": authority(),
        "reason_codes": ["EXPLICIT_APPROVAL_REQUIRED"], "limitations": list(DESK_REVIEW_LIMITATIONS)}


def review_event():
    document = DeskReviewInput.from_mapping(review_mapping())
    return {"schema_version": JOURNAL_EVENT_V8_SCHEMA_VERSION, "event_id": "journal-event-" + "d" * 64,
        "decision_id": "journal-decision-" + "e" * 64, "domain": "CAPITAL_ALLOCATION", "event_type": SHADOW_DESK_REVIEW_EVENT_TYPE,
        "recorded_at": document.recorded_at, "source": {"kind": "SHADOW_DESK_REVIEW", "review_id": document.review_id,
            "source_sha256": sha256_bytes(document.to_bytes())}, "evidence": [],
        "payload": {"review": document.to_dict(), "result": result_mapping()}}


def at(value, path):
    target = value
    for part in path: target = target[part]
    return target


class DeskCandidateReviewContractTests(unittest.TestCase):
    def test_immutable_round_trip_and_defensive_nested_copies(self):
        value = review_mapping(); document = DeskReviewInput.from_mapping(value); retained = document.to_bytes()
        value["policy"]["max_entry_fraction"] = "1"
        document.to_dict()["policy"]["max_entry_fraction"] = "1"
        document.policy["max_entry_fraction"] = "1"
        self.assertEqual(document.to_bytes(), retained)
        self.assertEqual(document, DeskReviewInput.from_bytes(retained))
        with self.assertRaises((TypeError, AttributeError)):
            document._canonical_bytes = b"rewritten"

    def test_strict_input_fields_at_every_nested_boundary(self):
        for path in ((), ("budget",), ("budget", "proposal_evidence"), ("sources",), ("sources", "market_evidence"),
                     ("sources", "analysis_evidence"), ("sources", "issuer_evidence"), ("policy",), ("authority",)):
            for operation in ("missing", "extra"):
                value = review_mapping(); node = at(value, path)
                if operation == "missing": del node[next(iter(node))]
                else: node["extra"] = True
                with self.subTest(path=path, operation=operation), self.assertRaises(ContractValidationError):
                    DeskReviewInput.from_mapping(value)

    def test_paper_proposal_scope_and_version_only(self):
        for field, changed in (("schema_version", "future"), ("mode", "LIVE"), ("scope", "EXECUTION")):
            value = review_mapping(); value[field] = changed
            with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)
        value = review_mapping(); value["policy"]["status"] = "ACTIVE"
        with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_no_input_authority_can_be_activated(self):
        for field in authority():
            for invalid in (True, 0, None):
                value = review_mapping(); value["authority"][field] = invalid
                with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_fractions_reject_float_boolean_nonfinite_and_out_of_bounds(self):
        for field in ("max_entry_fraction", "scenario_risk_fraction", "investment_candidate_fraction"):
            for invalid in (0.1, True, "NaN", "1e-1", "-1", "0", "1.0001", "0.0000000000000000001"):
                value = review_mapping(); value["policy"][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ContractValidationError):
                    DeskReviewInput.from_mapping(value)

    def test_atr_and_buffer_have_explicit_scenario_bounds(self):
        for field, invalids in (("atr_multiple", ("0", "-1", "101", 2)), ("price_buffer_fraction", ("-0.1", "1.1", False))):
            for invalid in invalids:
                value = review_mapping(); value["policy"][field] = invalid
                with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)
        value = review_mapping(); value["policy"]["price_buffer_fraction"] = "0"
        self.assertEqual(DeskReviewInput.from_mapping(value).policy["price_buffer_fraction"], "0")

    def test_only_one_entry_and_one_cycle_without_boolean_coercion(self):
        for field in ("max_active_entries", "max_completed_cycles"):
            for invalid in (0, 2, True, "1"):
                value = review_mapping(); value["policy"][field] = invalid
                with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_expiry_must_be_prospective_and_timestamps_preserve_supported_precision(self):
        for expiry in ("2026-10-12T20:00:00Z", "2026-10-11T20:00:00Z", "2026-10-13T20:00:00.1234567Z"):
            value = review_mapping(); value["policy"]["expires_at"] = expiry
            with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_horizon_and_benchmark_explicit_and_bounded(self):
        for invalid in (0, 3651, True, "90"):
            value = review_mapping(); value["policy"]["investment_horizon_days"] = invalid
            with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)
        value = review_mapping(); value["policy"]["benchmark_symbol"] = "spy"
        with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_evidence_paths_hashes_sizes_and_identity_are_strict(self):
        for field, invalids in (("path", ("../secret", "/absolute", "a\\b")), ("sha256", ("a" * 63, "A" * 64, [])), ("size_bytes", (-1, True, 64 * 1024 * 1024 + 1))):
            for invalid in invalids:
                value = review_mapping(); value["sources"]["market_evidence"][field] = invalid
                with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)
        value = review_mapping(); value["budget"]["source_snapshot_event_id"] = "journal-decision-" + "b" * 64
        with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_duplicate_reference_paths_are_rejected_even_with_different_bytes(self):
        value = review_mapping(); value["sources"]["market_evidence"]["path"] = value["budget"]["proposal_evidence"]["path"]
        with self.assertRaises(ContractValidationError): DeskReviewInput.from_mapping(value)

    def test_hostile_decimal_context_cannot_change_input_validation(self):
        expected = DeskReviewInput.from_mapping(review_mapping()).to_bytes()
        with localcontext() as context:
            context.prec = 1; context.rounding = ROUND_DOWN; context.traps[Inexact] = True; context.traps[Rounded] = True
            self.assertEqual(expected, DeskReviewInput.from_mapping(review_mapping()).to_bytes())

    def test_result_strict_fields_at_every_nested_boundary(self):
        document = DeskReviewInput.from_mapping(review_mapping())
        paths = ((), ("budgets_usd",), ("native_summary",), ("candidates", 0), ("candidates", 0, "metrics"),
            ("candidates", 0, "native"), ("trading_plan",), ("investment_plan",), ("investment_plan", "candidates", 0),
            ("ownership_proposal",), ("authority",))
        for path in paths:
            for operation in ("missing", "extra"):
                value = result_mapping(); node = at(value, path)
                if operation == "missing": del node[next(iter(node))]
                else: node["extra"] = True
                with self.subTest(path=path, operation=operation), self.assertRaises(ContractValidationError):
                    validate_review_result(value, document)

    def test_output_stays_off_unready_and_unrealized(self):
        for field, changed in (("auto_trading_enabled", True), ("readiness", True), ("realized_trade_pnl", "1"), ("status", "APPROVED"), ("method_version", "future")):
            value = result_mapping(); value[field] = changed
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))
        for field in authority():
            value = result_mapping(); value["authority"][field] = True
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_no_expected_returns_or_portfolio_authority_are_invented(self):
        for path, field, invalid in ((("trading_plan",), "return_expectation", "0.1"), (("trading_plan",), "authorization_required", False),
            (("investment_plan",), "allocation_authorized", True), (("investment_plan", "candidates", 0), "expected_return", "0.1"),
            (("ownership_proposal",), "status", "INSTALLED"), (("native_summary",), "independent_evidence", True)):
            value = result_mapping(); at(value, path)[field] = invalid
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_disjoint_proposed_ownership_and_exact_plan_scopes(self):
        for replacements in ({"TRADING": ["AAA", "BBB"]}, {"INVESTMENT": ["AAA"]}, {"INVESTMENT": []}, {"TRADING": ["ZZZ"]}):
            value = result_mapping(); value["ownership_proposal"].update(replacements)
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_duplicate_candidates_research_and_ranks_are_rejected(self):
        for alteration in ("symbol", "rank", "research"):
            value = result_mapping()
            if alteration == "symbol": value["candidates"].append(copy.deepcopy(value["candidates"][0]))
            elif alteration == "rank": value["candidates"].append(candidate("CCC"))
            else: value["investment_plan"]["candidates"].append(copy.deepcopy(value["investment_plan"]["candidates"][0]))
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_quantities_are_whole_shares_not_boolean_or_fractional(self):
        for path in (("trading_plan",), ("investment_plan", "candidates", 0)):
            for invalid in (True, "1", 1.5, -1, 1000000001):
                value = result_mapping(); at(value, path)["qty"] = invalid
                with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_output_cannot_claim_more_than_one_cycle_or_unbound_expiry(self):
        for field, invalid in (("maximum_completed_cycles", 2), ("max_active_entries", True), ("time_exit_minutes", 31), ("expiry", "2026-10-14T20:00:00Z")):
            value = result_mapping(); value["trading_plan"][field] = invalid
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_native_confidence_is_a_label_and_counts_are_bounded_integers(self):
        for path, field, invalid in ((("candidates", 0, "native"), "confidence_label", 0.9), (("candidates", 0, "native"), "candidate_state", "BUY"),
            (("native_summary", "candidate_counts"), "WATCH", True), (("native_summary", "senate_counts"), "MONITOR", -1)):
            value = result_mapping(); at(value, path)[field] = invalid
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_negative_returns_allowed_but_prices_and_output_money_must_be_nonnegative(self):
        value = result_mapping(); value["candidates"][0]["metrics"]["return20_pct"] = "-9.5"
        validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))
        for path, field in ((("candidates", 0, "metrics"), "last"), (("trading_plan",), "estimated_notional_usd"), (("investment_plan",), "cash_reserve_usd")):
            value = result_mapping(); at(value, path)[field] = "-1"
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_market_time_cannot_be_future_and_limits_cannot_be_removed(self):
        for field, invalid in (("market_as_of", "2026-10-13T20:00:00Z"), ("limitations", []), ("reason_codes", ["DUP", "DUP"])):
            value = result_mapping(); value[field] = invalid
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_declared_notional_and_reserve_cannot_exceed_or_create_desk_capital(self):
        for path, field, invalid in ((("trading_plan",), "estimated_notional_usd", "1020"), (("trading_plan",), "max_entry_notional_usd", "10191"),
            (("investment_plan",), "total_notional_usd", "10191"), (("investment_plan",), "cash_reserve_usd", "9180.64")):
            value = result_mapping(); at(value, path)[field] = invalid
            with self.assertRaises(ContractValidationError): validate_review_result(value, DeskReviewInput.from_mapping(review_mapping()))

    def test_v8_envelope_round_trip_and_source_identity_binding(self):
        event = JournalEvent.from_mapping(review_event())
        self.assertEqual(event, JournalEvent.from_bytes(event.to_bytes()))
        for field, invalid in (("kind", "TRADING_ORDER"), ("review_id", "different-review"), ("source_sha256", "f" * 64)):
            value = review_event(); value["source"][field] = invalid
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_v8_cannot_be_reclassified_as_single_desk_order_or_change_timestamp(self):
        for field, invalid in (("event_type", "EXECUTABLE_ORDER"), ("domain", "TRADING"), ("recorded_at", "2026-10-12T20:00:01Z")):
            value = review_event(); value[field] = invalid
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_v8_payload_strictly_distinguishes_review_and_result(self):
        value = review_event(); value["payload"]["orders"] = []
        with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_parser_duplicate_keys_and_excess_nesting_fail_cleanly(self):
        for data in (b'{"mode":"PAPER","mode":"LIVE"}', b'{"nested":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'):
            with self.assertRaises(ContractValidationError): DeskReviewInput.from_bytes(data)


if __name__ == "__main__":
    unittest.main()
