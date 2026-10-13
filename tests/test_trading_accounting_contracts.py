"""Offline accounting input isolation, precision bounds, and passive envelopes."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError
from decimal import Inexact, Overflow, ROUND_DOWN, Rounded, Subnormal, Underflow, localcontext

from blackpod_build_week.contracts.decision_journal import (
    JournalEvent, JOURNAL_EVENT_V7_SCHEMA_VERSION, TRADING_FILL_LOT_ACCOUNTING_EVENT_TYPE,
)
from blackpod_build_week.contracts.trading_accounting import (
    AccountingInput, PaperActivitiesInput, ACCOUNTING_METHOD, ACCOUNTING_SCOPE, ACCOUNTING_LIMITATIONS,
    PAPER_ACTIVITIES_SCHEMA_VERSION, TRADING_ACCOUNTING_SCHEMA_VERSION, PRECISION_POLICY,
    accounting_decimal, validate_accounting_result,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes

START = "2026-10-10T00:00:00Z"
END = "2026-10-12T00:00:00Z"


def authority():
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def fill_mapping():
    return {"activity_id": "fill-001", "order_id": "order-001", "symbol": "AAA", "side": "buy",
            "qty": "2.50", "price": "100.012300", "occurred_at": "2026-10-10T01:00:00Z"}


def fee_mapping():
    return {"activity_id": "fee-001", "order_id": "order-001", "fill_activity_id": "fill-001", "symbol": "AAA",
            "amount": "0.023", "currency": "USD", "occurred_at": "2026-10-10T02:00:00Z", "fee_type": "REGULATORY"}


def activities_mapping():
    return {"schema_version": PAPER_ACTIVITIES_SCHEMA_VERSION, "activity_set_id": "activities-001", "recorded_at": END,
            "mode": "PAPER", "account_id": "synthetic-paper-account", "currency": "USD",
            "window": {"started_at": START, "ended_at": END}, "fills": [fill_mapping()], "fees": [fee_mapping()],
            "coverage": {"fills_complete": True, "fees_complete": True, "scope_order_ids": ["order-001"]},
            "provenance": {"source_kind": "SYNTHETIC_FIXTURE", "source_evidence": {"path": "activities/raw.json", "sha256": "a" * 64, "size_bytes": 12}, "provider_verified": False},
            "authority": authority()}


def accounting_mapping():
    return {"schema_version": TRADING_ACCOUNTING_SCHEMA_VERSION, "accounting_id": "accounting-001", "recorded_at": END,
            "mode": "PAPER", "account_id": "synthetic-paper-account",
            "start_snapshot_event_id": "journal-event-" + "a" * 64, "start_snapshot_sha256": "b" * 64,
            "end_reconciliation_event_id": "journal-event-" + "c" * 64, "end_reconciliation_sha256": "d" * 64,
            "ownership_event_id": "journal-event-" + "e" * 64, "ownership_sha256": "f" * 64,
            "activities_evidence": {"path": "activities/normalized.json", "sha256": "1" * 64, "size_bytes": 42},
            "prior_accounting_event_id": None, "accounting_method": ACCOUNTING_METHOD, "scope": ACCOUNTING_SCOPE,
            "authority": authority()}


def result_mapping():
    document = AccountingInput.from_mapping(accounting_mapping())
    return {"status": "NO_EXECUTION_OBSERVED", "accounting_method": ACCOUNTING_METHOD, "precision_policy": dict(PRECISION_POLICY),
            "currency": "USD", "start_snapshot_event_id": document.start_snapshot_event_id,
            "end_reconciliation_event_id": document.end_reconciliation_event_id, "ownership_event_id": document.ownership_event_id,
            "activities_sha256": document.activities_evidence["sha256"], "matched_fills": [], "unmatched_fills": [],
            "matched_fees": [], "unmatched_fees": [], "open_lots": [], "closed_lots": [], "positions": [], "order_checks": [],
            "totals": {"buy_gross": "0", "sell_gross": "0", "gross_realized_pnl": None, "allocated_closed_fees": None,
                       "allocated_open_fees": None, "net_realized_pnl": None},
            "execution_observed": False, "attributable_execution_observed": False, "fees_complete": False,
            "realized_trade_pnl": None, "reason_codes": [], "limitations": list(ACCOUNTING_LIMITATIONS),
            "provider_verified": False, "ownership_authenticated": False, "execution_authority_granted": False,
            "readiness": False, "authority": authority()}


def accounting_event():
    document = AccountingInput.from_mapping(accounting_mapping())
    return {"schema_version": JOURNAL_EVENT_V7_SCHEMA_VERSION, "event_id": "journal-event-" + "2" * 64,
            "decision_id": "journal-decision-" + "3" * 64, "domain": "TRADING", "event_type": TRADING_FILL_LOT_ACCOUNTING_EVENT_TYPE,
            "recorded_at": document.recorded_at, "source": {"kind": "TRADING_FILL_LOT_ACCOUNTING", "accounting_id": document.accounting_id,
            "source_sha256": sha256_bytes(document.to_bytes())}, "evidence": [], "payload": {"accounting": document.to_dict(), "result": result_mapping()}}


def closed_result_mapping():
    result = result_mapping()
    result.update(status="GROSS_RECONCILED_FEES_PENDING", execution_observed=True, attributable_execution_observed=True,
        matched_fills=[{"activity_id": "buy-fill", "order_id": "buy-order", "attempt_sha256": "a" * 64, "symbol": "AAA", "side": "buy", "qty": "1", "price": "100", "occurred_at": "2026-10-10T01:00:00Z", "gross_value": "100", "fee_amount": None},
                       {"activity_id": "sell-fill", "order_id": "sell-order", "attempt_sha256": "b" * 64, "symbol": "AAA", "side": "sell", "qty": "1", "price": "110", "occurred_at": "2026-10-10T02:00:00Z", "gross_value": "110", "fee_amount": None}],
        closed_lots=[{"lot_id": "lot-001", "buy_activity_id": "buy-fill", "sell_activity_id": "sell-fill", "symbol": "AAA", "qty": "1", "buy_price": "100", "sell_price": "110", "gross_cost": "100", "gross_proceeds": "110", "gross_pnl": "10", "allocated_entry_fees": None, "allocated_exit_fees": None, "net_pnl": None}],
        positions=[{"symbol": "AAA", "expected_qty": "0", "observed_qty": "0", "matches": True}],
        order_checks=[{"order_id": "buy-order", "activity_filled_qty": "1", "broker_filled_qty": "1", "activity_gross_value": "100", "broker_gross_value": "100", "price_matches": True, "matches": True},
                      {"order_id": "sell-order", "activity_filled_qty": "1", "broker_filled_qty": "1", "activity_gross_value": "110", "broker_gross_value": "110", "price_matches": True, "matches": True}])
    result["totals"].update(buy_gross="100", sell_gross="110", gross_realized_pnl="10")
    result["reason_codes"] = ["FEES_INCOMPLETE"]
    return result


class TradingAccountingContractTests(unittest.TestCase):
    def test_immutable_round_trip_and_defensive_nested_copies(self):
        for contract, factory in ((PaperActivitiesInput, activities_mapping), (AccountingInput, accounting_mapping)):
            value = factory(); document = contract.from_mapping(value); original = document.to_bytes()
            value.clear(); document.to_dict().clear()
            self.assertEqual(document.to_bytes(), original)
            self.assertEqual(document, contract.from_bytes(original))
            with self.assertRaises((FrozenInstanceError, TypeError, AttributeError)):
                document._canonical_bytes = b"changed"

    def test_strict_unknown_and_missing_fields_at_every_input_boundary(self):
        for contract, factory, paths in ((PaperActivitiesInput, activities_mapping, ((), ("window",), ("coverage",), ("provenance",), ("provenance", "source_evidence"), ("authority",), ("fills", 0), ("fees", 0))),
                                        (AccountingInput, accounting_mapping, ((), ("activities_evidence",), ("authority",)))):
            for path in paths:
                for kind in ("missing", "extra"):
                    value = factory(); target = value
                    for part in path: target = target[part]
                    if kind == "missing": del target[next(iter(target))]
                    else: target["extra"] = True
                    with self.subTest(contract=contract.__name__, path=path, kind=kind), self.assertRaises(ContractValidationError):
                        contract.from_mapping(value)

    def test_only_paper_and_versioned_method_scope(self):
        for contract, factory in ((PaperActivitiesInput, activities_mapping), (AccountingInput, accounting_mapping)):
            for field, replacement in (("mode", "LIVE"), ("schema_version", "future")):
                value = factory(); value[field] = replacement
                with self.assertRaises(ContractValidationError): contract.from_mapping(value)
        for field, replacement in (("accounting_method", "LIFO"), ("scope", "TRADING_EXECUTION")):
            value = accounting_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): AccountingInput.from_mapping(value)

    def test_all_authority_fields_reject_true_and_non_booleans(self):
        for contract, factory in ((PaperActivitiesInput, activities_mapping), (AccountingInput, accounting_mapping)):
            for field in authority():
                for replacement in (True, 0, None):
                    value = factory(); value["authority"][field] = replacement
                    with self.assertRaises(ContractValidationError): contract.from_mapping(value)

    def test_identity_fields_preserve_exact_spelling(self):
        value = activities_mapping(); value["fills"][0]["activity_id"] = "20261010010000000::fill-ID"
        self.assertEqual(PaperActivitiesInput.from_mapping(value).fills[0]["activity_id"], "20261010010000000::fill-ID")
        for replacement in ("", " ../file", "fill/id", True):
            changed = activities_mapping(); changed["fills"][0]["activity_id"] = replacement
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(changed)

    def test_fixed_point_inputs_preserve_exact_strings_without_binary_conversion(self):
        document = PaperActivitiesInput.from_mapping(activities_mapping())
        self.assertEqual(document.fills[0]["qty"], "2.50")
        self.assertEqual(document.fills[0]["price"], "100.012300")
        for replacement in (1, 1.5, True, "NaN", "Infinity", "1e-999", "1e1", "+1", "01", ".1", "1.", "-1", "0", "0.0000000000000000001", "100000000000000000001"):
            value = activities_mapping(); value["fills"][0]["qty"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_signed_fees_and_explicit_zero_are_allowed(self):
        for amount in ("0", "-0.013", "0.000000000000000001"):
            value = activities_mapping(); value["fees"][0]["amount"] = amount
            self.assertEqual(PaperActivitiesInput.from_mapping(value).fees[0]["amount"], amount)

    def test_output_numeric_bounds_allow_exact_products_but_reject_float_exponents(self):
        self.assertEqual(accounting_decimal("1" + "0" * 40 + "." + "0" * 35 + "1", "product", output=True), "1" + "0" * 40 + "." + "0" * 35 + "1")
        for replacement in ("1e-80", 2, "1" * 81, "0." + "1" * 81):
            with self.assertRaises(ContractValidationError): accounting_decimal(replacement, "product", output=True)

    def test_numeric_bounds_and_full_activity_validation_ignore_hostile_decimal_context(self):
        value = activities_mapping()
        value["fills"][0].update(qty="0.000000000000000001", price="99999999999999999999.999999999999999999")
        value["fees"][0]["amount"] = "-0.000000000000000001"
        expected = PaperActivitiesInput.from_mapping(value).to_bytes()
        with localcontext() as context:
            context.prec = 2
            context.Emax = 5
            context.Emin = -5
            context.rounding = ROUND_DOWN
            for signal in (Inexact, Rounded, Overflow, Underflow, Subnormal):
                context.traps[signal] = True
            context.clear_flags()
            self.assertEqual(accounting_decimal("99999999999999999999.999999999999999999", "budget", positive=True), "99999999999999999999.999999999999999999")
            self.assertEqual(accounting_decimal("-0.000000000000000001", "fee"), "-0.000000000000000001")
            self.assertEqual(PaperActivitiesInput.from_mapping(value).to_bytes(), expected)
            self.assertFalse(any(context.flags.values()))

    def test_fill_side_symbol_currency_are_explicit(self):
        for path, replacement in ((("fills", 0, "side"), "close"), (("fills", 0, "symbol"), "aaa"), (("currency",), "EUR"), (("fees", 0, "currency"), "EUR")):
            value = activities_mapping(); target = value
            for part in path[:-1]: target = target[part]
            target[path[-1]] = replacement
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_activity_duplicate_ids_and_fill_fee_collisions_reject(self):
        for kind in ("fill", "fee", "cross"):
            value = activities_mapping()
            if kind == "fill": value["fills"].append(copy.deepcopy(value["fills"][0]))
            elif kind == "fee": value["fees"].append(copy.deepcopy(value["fees"][0]))
            else: value["fees"][0]["activity_id"] = value["fills"][0]["activity_id"]
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_coverage_is_explicit_bounded_and_never_inferred_from_empty_fees(self):
        value = activities_mapping(); value["fees"] = []; value["coverage"]["fees_complete"] = False
        self.assertFalse(PaperActivitiesInput.from_mapping(value).coverage["fees_complete"])
        for mutation in ({"fills_complete": 1}, {"fees_complete": None}, {"scope_order_ids": ["order-001", "order-001"]}, {"scope_order_ids": []}):
            changed = activities_mapping(); changed["coverage"].update(mutation)
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(changed)

    def test_activity_window_and_timestamp_normalization(self):
        value = activities_mapping(); value["fills"][0]["occurred_at"] = "2026-10-09T18:00:00-07:00"
        self.assertEqual(PaperActivitiesInput.from_mapping(value).fills[0]["occurred_at"], "2026-10-10T01:00:00Z")
        for path, replacement in ((("window", "started_at"), "2026-10-13T00:00:00Z"), (("window", "ended_at"), "2026-10-13T00:00:00Z"), (("fills", 0, "occurred_at"), "2026-10-09T23:59:59Z"), (("fills", 0, "occurred_at"), "2026-10-10")):
            changed = activities_mapping(); target = changed
            for part in path[:-1]: target = target[part]
            target[path[-1]] = replacement
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(changed)

    def test_date_only_fee_retains_date_without_fabricated_time(self):
        value = activities_mapping(); value["fees"][0]["occurred_at"] = "2026-10-10"
        self.assertEqual(PaperActivitiesInput.from_mapping(value).fees[0]["occurred_at"], "2026-10-10")

    def test_sub_microsecond_timestamps_cannot_collapse_into_false_fifo_sequence(self):
        for path in (("fills", 0, "occurred_at"), ("fees", 0, "occurred_at"), ("window", "started_at"), ("recorded_at",)):
            value = activities_mapping(); target = value
            for part in path[:-1]: target = target[part]
            target[path[-1]] = "2026-10-10T01:00:00.000000001Z"
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_date_only_fee_requires_entire_utc_day_and_valid_date(self):
        for mutation in ({"occurred_at": "2026-10-09"}, {"occurred_at": "2026-10-12"}, {"occurred_at": "2026-02-30"}):
            value = activities_mapping(); value["fees"][0].update(mutation)
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)
        value = activities_mapping(); value["fees"][0]["occurred_at"] = "2026-10-10"; value["window"]["started_at"] = "2026-10-10T00:00:01Z"
        with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_fee_links_can_be_explicitly_unattributed_or_missing_historical_fill(self):
        value = activities_mapping(); value["fees"][0].update(order_id=None, fill_activity_id=None, symbol=None)
        document = PaperActivitiesInput.from_mapping(value)
        self.assertIsNone(document.fees[0]["fill_activity_id"])
        value["fees"][0]["fill_activity_id"] = "unknown-fill"
        self.assertEqual(PaperActivitiesInput.from_mapping(value).fees[0]["fill_activity_id"], "unknown-fill")

    def test_known_fee_link_cannot_conflict_with_fill_order_symbol_time(self):
        for mutation in ({"symbol": "BBB"}, {"order_id": "order-002"}, {"occurred_at": "2026-10-10T00:59:59Z"}):
            value = activities_mapping(); value["coverage"]["scope_order_ids"].append("order-002"); value["fees"][0].update(mutation)
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_provenance_is_declared_and_cannot_claim_provider_attestation(self):
        for mutation in ({"provider_verified": True}, {"source_kind": "LIVE_PROVIDER"}):
            value = activities_mapping(); value["provenance"].update(mutation)
            with self.assertRaises(ContractValidationError): PaperActivitiesInput.from_mapping(value)

    def test_evidence_refs_paths_hashes_and_sizes(self):
        for mutation in ({"path": "../secret"}, {"path": "/absolute"}, {"sha256": "short"}, {"size_bytes": True}, {"size_bytes": -1}):
            for contract, factory, path in ((PaperActivitiesInput, activities_mapping, ("provenance", "source_evidence")), (AccountingInput, accounting_mapping, ("activities_evidence",))):
                value = factory(); target = value
                for part in path: target = target[part]
                target.update(mutation)
                with self.assertRaises(ContractValidationError): contract.from_mapping(value)

    def test_accounting_source_events_and_hashes_are_required_pairs(self):
        for field in ("start_snapshot_event_id", "end_reconciliation_event_id", "ownership_event_id", "start_snapshot_sha256", "end_reconciliation_sha256", "ownership_sha256"):
            value = accounting_mapping(); value[field] = None
            with self.assertRaises(ContractValidationError): AccountingInput.from_mapping(value)

    def test_prior_accounting_is_nullable_or_full_journal_event_id(self):
        value = accounting_mapping(); value["prior_accounting_event_id"] = "journal-event-" + "9" * 64
        self.assertEqual(AccountingInput.from_mapping(value).prior_accounting_event_id, value["prior_accounting_event_id"])
        value["prior_accounting_event_id"] = "journal-decision-" + "9" * 64
        with self.assertRaises(ContractValidationError): AccountingInput.from_mapping(value)

    def test_duplicate_json_keys_and_nonstandard_numbers_reject(self):
        for data in (b'{"schema_version":"x","schema_version":"y"}', b'{"amount":NaN}', b'[]'):
            for contract in (PaperActivitiesInput, AccountingInput):
                with self.assertRaises(ContractValidationError): contract.from_bytes(data)

    def test_passive_no_execution_result_and_envelope_round_trip(self):
        document = AccountingInput.from_mapping(accounting_mapping())
        self.assertEqual(validate_accounting_result(result_mapping(), document), result_mapping())
        event = JournalEvent.from_mapping(accounting_event())
        self.assertEqual(event, JournalEvent.from_bytes(event.to_bytes()))
        self.assertIsNone(event.payload["result"]["realized_trade_pnl"])

    def test_result_cannot_claim_authority_or_provider_identity(self):
        for field in ("provider_verified", "ownership_authenticated", "execution_authority_granted", "readiness"):
            value = accounting_event(); value["payload"]["result"][field] = True
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_result_no_execution_or_pending_cannot_claim_realized_pnl(self):
        for status in ("NO_EXECUTION_OBSERVED", "PENDING", "RECONCILED"):
            value = accounting_event(); result = value["payload"]["result"]; result["status"] = status
            result["totals"]["gross_realized_pnl"] = "1"
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_result_hash_and_link_identity_must_match_input(self):
        for field in ("start_snapshot_event_id", "end_reconciliation_event_id", "ownership_event_id", "activities_sha256"):
            value = accounting_event(); value["payload"]["result"][field] = "wrong"
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_result_precision_policy_is_fixed_and_rejects_bool_as_integer(self):
        for mutation in ({"calculation_precision": True}, {"calculation_precision": 28}, {"rounding": "ROUND_DOWN"}, {"residual": "DISCARD"}, {"fee_allocation_scale": 2}):
            value = accounting_event(); value["payload"]["result"]["precision_policy"].update(mutation)
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_report_unknown_fields_and_required_limits_reject(self):
        for mutation in ("unknown", "missing", "limits", "duplicate-reasons"):
            value = accounting_event(); result = value["payload"]["result"]
            if mutation == "unknown": result["policy_override"] = True
            elif mutation == "missing": del result["totals"]
            elif mutation == "limits": result["limitations"] = []
            else: result["reason_codes"] = ["UNKNOWN_FEES", "UNKNOWN_FEES"]
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_result_cannot_convert_unknown_fee_coverage_into_zero_net(self):
        value = accounting_event(); result = value["payload"]["result"]
        result["totals"]["net_realized_pnl"] = "0"; result["realized_trade_pnl"] = "0"
        with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_gross_reconciled_unknown_fee_result_retains_gross_and_null_net(self):
        result = closed_result_mapping()
        validated = validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))
        self.assertEqual(validated["totals"]["gross_realized_pnl"], "10")
        self.assertIsNone(validated["closed_lots"][0]["net_pnl"])

    def test_pending_closed_rows_cannot_claim_even_gross_pnl(self):
        result = closed_result_mapping(); result["status"] = "PENDING"; result["totals"]["gross_realized_pnl"] = None
        with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))

    def test_fee_pending_never_converts_missing_cost_into_zero_net(self):
        for path in (("closed_lots", 0, "net_pnl"), ("totals", "net_realized_pnl"), ("realized_trade_pnl",)):
            result = closed_result_mapping(); target = result
            for part in path[:-1]: target = target[part]
            target[path[-1]] = "0"
            with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))

    def test_report_retains_lot_and_exact_attempt_identity_types(self):
        for path, replacement in ((("matched_fills", 0, "attempt_sha256"), None), (("matched_fills", 0, "qty"), 1), (("closed_lots", 0, "qty"), "-1"), (("positions", 0, "matches"), 1), (("order_checks", 0, "broker_filled_qty"), "-1")):
            result = closed_result_mapping(); target = result
            for part in path[:-1]: target = target[part]
            target[path[-1]] = replacement
            with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))

    def test_report_row_unknown_fields_and_duplicate_execution_identities_reject(self):
        for mutation in ("extra", "duplicate", "also-unmatched"):
            result = closed_result_mapping()
            if mutation == "extra": result["closed_lots"][0]["forecast_probability"] = "0.9"
            elif mutation == "duplicate": result["matched_fills"].append(copy.deepcopy(result["matched_fills"][0]))
            else: result["unmatched_fills"].append({"activity_id": "buy-fill", "order_id": "buy-order", "reason_code": "UNMATCHED"})
            with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))

    def test_fee_allocations_require_exact_matched_fill_ids(self):
        for ids in ([], ["missing"], ["buy-fill", "buy-fill"]):
            result = closed_result_mapping(); result["matched_fees"] = [{"activity_id": "fee-001", "fill_activity_id": None, "order_id": "buy-order", "amount": "0.01", "allocated_fill_ids": ids}]
            with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))

    def test_report_without_any_individual_fills_can_retain_cumulative_execution_pending(self):
        result = result_mapping(); result.update(status="PENDING", execution_observed=True)
        self.assertTrue(validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))["execution_observed"])

    def test_order_matches_require_independent_gross_price_and_quantity_checks(self):
        for mutation in ({"broker_gross_value": "101"}, {"broker_gross_value": None}, {"broker_filled_qty": None}, {"price_matches": False}, {"activity_gross_value": 100}):
            result = closed_result_mapping(); result["order_checks"][0].update(mutation)
            with self.assertRaises(ContractValidationError): validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))
        result = closed_result_mapping(); result["order_checks"][0].update(broker_gross_value="101", price_matches=False, matches=False)
        self.assertFalse(validate_accounting_result(result, AccountingInput.from_mapping(accounting_mapping()))["order_checks"][0]["matches"])

    def test_v7_cannot_inherit_other_domain_event_type_or_source_kind(self):
        for path, replacement in ((("domain",), "INVESTMENT"), (("event_type",), "EVALUATION_RECORDED"), (("source", "kind"), "MISSION_STORE")):
            value = accounting_event(); target = value
            for part in path[:-1]: target = target[part]
            target[path[-1]] = replacement
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_historical_journal_versions_do_not_accept_accounting_event(self):
        for version in range(1, 7):
            value = accounting_event(); value["schema_version"] = "blackpod.decision_journal_event.v" + str(version)
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_envelope_source_digest_identity_and_time_match_input(self):
        for path, replacement in ((("source", "source_sha256"), "0" * 64), (("source", "accounting_id"), "other"), (("recorded_at",), "2026-10-13T00:00:00Z")):
            value = accounting_event(); target = value
            for part in path[:-1]: target = target[part]
            target[path[-1]] = replacement
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
