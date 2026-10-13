"""Strict passive PAPER execution-activity and FIFO accounting contracts.

Execution activities are individual retained fills, never differences of broker
cumulative averages. Completeness and provider labels remain supplied claims.
Accounting can describe broker executions; it grants no trading authority and
cannot rewrite a source mission or turn a SHADOW decision into a traded mission.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from .decision_journal import _boolean, _enum, _hash, _identifier, _object
from .investment_review import _event_id, _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError, normalize_rfc3339, parse_rfc3339
from .trading_reconciliation import _ReconciliationDocument, evidence_reference, symbol_text

PAPER_ACTIVITIES_SCHEMA_VERSION = "blackpod.paper_activities.v1"
TRADING_ACCOUNTING_SCHEMA_VERSION = "blackpod.trading_fill_lot_accounting.v1"
ACCOUNTING_SCOPE = "PAPER_FILL_LOT_ACCOUNTING_ONLY"
ACCOUNTING_METHOD = "FIFO_LONG_ONLY"
PRECISION_POLICY = {
    "calculation_precision": 256, "fee_allocation_scale": 18,
    "rounding": "ROUND_HALF_EVEN", "residual": "LAST_SLICE_REMAINDER",
}
ACCOUNTING_LIMITATIONS = (
    "DECLARED_ACTIVITY_AND_FEE_COMPLETENESS", "NON_ATOMIC_BROKER_SNAPSHOT",
    "DECLARED_DESK_OWNERSHIP_UNAUTHENTICATED", "PROVIDER_IDENTITY_NOT_ATTESTED",
    "LONG_ONLY_FIFO_NO_CORPORATE_ACTIONS", "BOUNDED_FEE_COVERAGE_NOT_FINAL_SETTLEMENT",
    "NO_MISSION_PNL_ATTRIBUTION", "NO_EXECUTION_AUTHORITY",
)
_INPUT_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$")
_OUTPUT_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,80})?$")
_MAX_ACTIVITIES = 20000


def accounting_decimal(value, name, *, positive=False, nonnegative=False, output=False):
    """Bound exact fixed-point values independently of ambient Decimal context."""
    pattern = _OUTPUT_DECIMAL if output else _INPUT_DECIMAL
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ContractValidationError(name + " must be a bounded fixed-point decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ContractValidationError(name + " must be a bounded fixed-point decimal string") from exc
    if (not output and number.copy_abs() > Decimal("1e20")) or (positive and number <= 0) or (nonnegative and number < 0):
        raise ContractValidationError(name + " is outside the permitted accounting range")
    return value


def accounting_timestamp(value, name):
    """Reject precision the existing datetime representation cannot retain."""
    if isinstance(value, str):
        fraction = re.search(r"T[0-9]{2}:[0-9]{2}:[0-9]{2}\.([0-9]+)", value)
        if fraction and len(fraction.group(1)) > 6:
            raise ContractValidationError(name + " exceeds supported microsecond timestamp precision")
    return normalize_rfc3339(value, name)


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def _base(value, fields, schema, name):
    result = _object(value, fields, name)
    _constant(result, "schema_version", schema)
    _constant(result, "mode", "PAPER")
    result["account_id"] = _identifier(result["account_id"], "account_id")
    result["recorded_at"] = accounting_timestamp(result["recorded_at"], "recorded_at")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _activities(value):
    result = _base(value, {
        "schema_version", "activity_set_id", "recorded_at", "mode", "account_id", "currency", "window",
        "fills", "fees", "coverage", "provenance", "authority",
    }, PAPER_ACTIVITIES_SCHEMA_VERSION, "paper activities")
    result["activity_set_id"] = _identifier(result["activity_set_id"], "activity_set_id")
    _constant(result, "currency", "USD")
    window = _object(result["window"], {"started_at", "ended_at"}, "window")
    for field in window:
        window[field] = accounting_timestamp(window[field], "window." + field)
    start, end = (parse_rfc3339(window[field], field) for field in ("started_at", "ended_at"))
    if not start <= end <= parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("activity window must be ordered and end no later than recorded_at")
    result["window"] = window
    coverage = _object(result["coverage"], {"fills_complete", "fees_complete", "scope_order_ids"}, "coverage")
    for field in ("fills_complete", "fees_complete"):
        coverage[field] = _boolean(coverage[field], "coverage." + field)
    scope = [_identifier(item, "scope_order_ids") for item in _list(coverage["scope_order_ids"], "scope_order_ids")]
    if len(scope) > _MAX_ACTIVITIES or len(set(scope)) != len(scope):
        raise ContractValidationError("scope_order_ids must be unique and bounded")
    coverage["scope_order_ids"] = scope
    result["coverage"] = coverage
    scope_set, identities, fills, fill_by_id = set(scope), set(), [], {}

    def identity_time(item, *, fee=False):
        item["activity_id"] = _identifier(item["activity_id"], "activity_id")
        if item["activity_id"] in identities:
            raise ContractValidationError("activity identities must be unique across fills and fees")
        identities.add(item["activity_id"])
        if fee and isinstance(item["occurred_at"], str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", item["occurred_at"]):
            try:
                day = date.fromisoformat(item["occurred_at"])
                lower = datetime.combine(day, datetime.min.time(), timezone.utc)
                upper = lower + timedelta(days=1)
            except (ValueError, OverflowError) as exc:
                raise ContractValidationError("fee occurred_at must be a valid calendar date or timestamp") from exc
            if not (start <= lower and upper <= end):
                raise ContractValidationError("date-only fee must have its full UTC calendar day inside the activity window")
            return
        item["occurred_at"] = accounting_timestamp(item["occurred_at"], "occurred_at")
        if not start <= parse_rfc3339(item["occurred_at"], "occurred_at") <= end:
            raise ContractValidationError("activity occurred_at must fall within the explicit activity window")

    for entry in _list(result["fills"], "fills"):
        item = _object(entry, {"activity_id", "order_id", "symbol", "side", "qty", "price", "occurred_at"}, "fill")
        identity_time(item)
        item["order_id"] = _identifier(item["order_id"], "fill.order_id")
        if item["order_id"] not in scope_set:
            raise ContractValidationError("fill order_id must be included in explicit scope_order_ids")
        item["symbol"] = symbol_text(item["symbol"])
        item["side"] = _enum(item["side"], {"buy", "sell"}, "fill.side")
        for field in ("qty", "price"):
            item[field] = accounting_decimal(item[field], "fill." + field, positive=True)
        fills.append(item)
        fill_by_id[item["activity_id"]] = item
    fees = []
    for entry in _list(result["fees"], "fees"):
        item = _object(entry, {"activity_id", "order_id", "fill_activity_id", "symbol", "amount", "currency", "occurred_at", "fee_type"}, "fee")
        identity_time(item, fee=True)
        for field in ("order_id", "fill_activity_id"):
            if item[field] is not None:
                item[field] = _identifier(item[field], "fee." + field)
        if item["order_id"] is not None and item["order_id"] not in scope_set:
            raise ContractValidationError("fee order_id must be included in explicit scope_order_ids")
        if item["symbol"] is not None:
            item["symbol"] = symbol_text(item["symbol"])
        item["amount"] = accounting_decimal(item["amount"], "fee.amount")
        _constant(item, "currency", "USD")
        item["fee_type"] = _enum(item["fee_type"], {"COMMISSION", "REGULATORY", "EXCHANGE", "OTHER"}, "fee.fee_type")
        linked = fill_by_id.get(item["fill_activity_id"])
        if linked is not None:
            if item["order_id"] is not None and item["order_id"] != linked["order_id"]:
                raise ContractValidationError("fee order_id conflicts with its retained fill")
            if item["symbol"] is not None and item["symbol"] != linked["symbol"]:
                raise ContractValidationError("fee symbol conflicts with its retained fill")
            if "T" in item["occurred_at"] and parse_rfc3339(item["occurred_at"], "fee occurred_at") < parse_rfc3339(linked["occurred_at"], "fill occurred_at"):
                raise ContractValidationError("linked fee cannot occur before its retained fill")
        fees.append(item)
    if len(fills) + len(fees) > _MAX_ACTIVITIES:
        raise ContractValidationError("activities exceeds the supported count")
    result["fills"], result["fees"] = fills, fees
    provenance = _object(result["provenance"], {"source_kind", "source_evidence", "provider_verified"}, "provenance")
    provenance["source_kind"] = _enum(provenance["source_kind"], {"ALPACA_PAPER_ACTIVITY_IMPORT", "SYNTHETIC_FIXTURE"}, "provenance.source_kind")
    provenance["source_evidence"] = evidence_reference(provenance["source_evidence"])
    _fixed_boolean(provenance, "provider_verified", False)
    result["provenance"] = provenance
    return result


def _accounting(value):
    result = _base(value, {
        "schema_version", "accounting_id", "recorded_at", "mode", "account_id", "start_snapshot_event_id",
        "start_snapshot_sha256", "end_reconciliation_event_id", "end_reconciliation_sha256", "ownership_event_id",
        "ownership_sha256", "activities_evidence", "prior_accounting_event_id", "accounting_method", "scope", "authority",
    }, TRADING_ACCOUNTING_SCHEMA_VERSION, "fill-lot accounting")
    result["accounting_id"] = _identifier(result["accounting_id"], "accounting_id")
    for prefix in ("start_snapshot", "end_reconciliation", "ownership"):
        result[prefix + "_event_id"] = _event_id(result[prefix + "_event_id"], prefix + "_event_id")
        result[prefix + "_sha256"] = _hash(result[prefix + "_sha256"], prefix + "_sha256")
    result["activities_evidence"] = evidence_reference(result["activities_evidence"], "activities_evidence")
    if result["prior_accounting_event_id"] is not None:
        result["prior_accounting_event_id"] = _event_id(result["prior_accounting_event_id"], "prior_accounting_event_id")
    _constant(result, "accounting_method", ACCOUNTING_METHOD)
    _constant(result, "scope", ACCOUNTING_SCOPE)
    return result


class PaperActivitiesInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_activities)


class TradingAccountingInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_accounting)


ActivitiesInput = PaperActivitiesInput
AccountingInput = TradingAccountingInput


def _rows(value, name, fields, *, ids=(), nullable_ids=(), hashes=(), nullable_hashes=(), symbols=(), decimals=(), nullable_decimals=(), times=()):
    rows = []
    for entry in _list(value, name):
        row = _object(entry, set(fields), name + " row")
        for field in ids:
            row[field] = _identifier(row[field], name + "." + field)
        for field in nullable_ids:
            if row[field] is not None: row[field] = _identifier(row[field], name + "." + field)
        for field in hashes:
            row[field] = _hash(row[field], name + "." + field)
        for field in nullable_hashes:
            if row[field] is not None: row[field] = _hash(row[field], name + "." + field)
        for field in symbols:
            row[field] = symbol_text(row[field], name + "." + field)
        for field in decimals:
            row[field] = accounting_decimal(row[field], name + "." + field, output=True)
        for field in nullable_decimals:
            if row[field] is not None: row[field] = accounting_decimal(row[field], name + "." + field, output=True)
        for field in times:
            row[field] = normalize_rfc3339(row[field], name + "." + field)
        rows.append(row)
    if len(rows) > _MAX_ACTIVITIES * 2:
        raise ContractValidationError(name + " exceeds the supported count")
    return rows


def validate_accounting_result(value, accounting: TradingAccountingInput):
    """Validate the report shape; retained-source replay verifies its economics."""
    result = _object(value, {
        "status", "accounting_method", "precision_policy", "currency", "start_snapshot_event_id",
        "end_reconciliation_event_id", "ownership_event_id", "activities_sha256", "matched_fills", "unmatched_fills",
        "matched_fees", "unmatched_fees", "open_lots", "closed_lots", "positions", "order_checks", "totals",
        "execution_observed", "attributable_execution_observed", "fees_complete", "realized_trade_pnl", "reason_codes",
        "limitations", "provider_verified", "ownership_authenticated", "execution_authority_granted", "readiness", "authority",
    }, "fill-lot accounting result")
    result["status"] = _enum(result["status"], {"NO_EXECUTION_OBSERVED", "RECONCILED", "GROSS_RECONCILED_FEES_PENDING", "PENDING"}, "accounting status")
    _constant(result, "accounting_method", ACCOUNTING_METHOD)
    _constant(result, "currency", "USD")
    policy = _object(result["precision_policy"], set(PRECISION_POLICY), "precision_policy")
    for field, expected in PRECISION_POLICY.items():
        if type(policy[field]) is not type(expected) or policy[field] != expected:
            raise ContractValidationError("precision_policy." + field + " must use the versioned accounting policy")
    result["precision_policy"] = policy
    for field in ("start_snapshot_event_id", "end_reconciliation_event_id", "ownership_event_id"):
        if result[field] != getattr(accounting, field):
            raise ContractValidationError(field + " must bind the supplied accounting input")
    if result["activities_sha256"] != accounting.activities_evidence["sha256"]:
        raise ContractValidationError("activities_sha256 must bind the retained activities evidence")
    result["matched_fills"] = _rows(result["matched_fills"], "matched_fills", {
        "activity_id", "order_id", "attempt_sha256", "symbol", "side", "qty", "price", "occurred_at", "gross_value", "fee_amount",
    }, ids=("activity_id", "order_id"), hashes=("attempt_sha256",), symbols=("symbol",),
        decimals=("qty", "price", "gross_value"), nullable_decimals=("fee_amount",), times=("occurred_at",))
    for row in result["matched_fills"]:
        row["side"] = _enum(row["side"], {"buy", "sell"}, "matched fill side")
        for field in ("qty", "price", "gross_value"):
            accounting_decimal(row[field], "matched fill " + field, output=True, positive=True)
    result["unmatched_fills"] = _rows(result["unmatched_fills"], "unmatched_fills", {"activity_id", "order_id", "reason_code"}, ids=("activity_id", "order_id", "reason_code"))
    result["matched_fees"] = _rows(result["matched_fees"], "matched_fees", {
        "activity_id", "fill_activity_id", "order_id", "amount", "allocated_fill_ids",
    }, ids=("activity_id",), nullable_ids=("fill_activity_id", "order_id"), decimals=("amount",))
    for row in result["matched_fees"]:
        fill_ids = [_identifier(item, "allocated_fill_ids") for item in _list(row["allocated_fill_ids"], "allocated_fill_ids", nonempty=True)]
        if len(set(fill_ids)) != len(fill_ids):
            raise ContractValidationError("allocated_fill_ids must be unique")
        row["allocated_fill_ids"] = fill_ids
    result["unmatched_fees"] = _rows(result["unmatched_fees"], "unmatched_fees", {"activity_id", "reason_code"}, ids=("activity_id", "reason_code"))
    result["open_lots"] = _rows(result["open_lots"], "open_lots", {
        "lot_id", "buy_activity_id", "symbol", "opened_at", "original_qty", "remaining_qty", "unit_price", "gross_cost", "allocated_entry_fees",
    }, ids=("lot_id", "buy_activity_id"), symbols=("symbol",), times=("opened_at",),
        decimals=("original_qty", "remaining_qty", "unit_price", "gross_cost"), nullable_decimals=("allocated_entry_fees",))
    for row in result["open_lots"]:
        for field in ("original_qty", "remaining_qty", "unit_price", "gross_cost"):
            accounting_decimal(row[field], "open lot " + field, output=True, positive=True)
        if Decimal(row["remaining_qty"]) > Decimal(row["original_qty"]):
            raise ContractValidationError("open lot remaining_qty cannot exceed original_qty")
    result["closed_lots"] = _rows(result["closed_lots"], "closed_lots", {
        "lot_id", "buy_activity_id", "sell_activity_id", "symbol", "qty", "buy_price", "sell_price", "gross_cost",
        "gross_proceeds", "gross_pnl", "allocated_entry_fees", "allocated_exit_fees", "net_pnl",
    }, ids=("lot_id", "buy_activity_id", "sell_activity_id"), symbols=("symbol",),
        decimals=("qty", "buy_price", "sell_price", "gross_cost", "gross_proceeds"),
        nullable_decimals=("gross_pnl", "allocated_entry_fees", "allocated_exit_fees", "net_pnl"))
    for row in result["closed_lots"]:
        for field in ("qty", "buy_price", "sell_price", "gross_cost", "gross_proceeds"):
            accounting_decimal(row[field], "closed lot " + field, output=True, positive=True)
    result["positions"] = _rows(result["positions"], "positions", {"symbol", "expected_qty", "observed_qty", "matches"}, symbols=("symbol",), decimals=("expected_qty",), nullable_decimals=("observed_qty",))
    for row in result["positions"]:
        row["matches"] = _boolean(row["matches"], "position.matches")
        accounting_decimal(row["expected_qty"], "expected_qty", output=True, nonnegative=True)
    result["order_checks"] = _rows(result["order_checks"], "order_checks", {
        "order_id", "activity_filled_qty", "broker_filled_qty", "activity_gross_value", "broker_gross_value", "price_matches", "matches",
    }, ids=("order_id",), decimals=("activity_filled_qty", "activity_gross_value"), nullable_decimals=("broker_filled_qty", "broker_gross_value"))
    for row in result["order_checks"]:
        row["matches"] = _boolean(row["matches"], "order check.matches")
        row["price_matches"] = _boolean(row["price_matches"], "order check.price_matches")
        accounting_decimal(row["activity_filled_qty"], "activity_filled_qty", output=True, nonnegative=True)
        accounting_decimal(row["activity_gross_value"], "activity_gross_value", output=True, nonnegative=True)
        if row["broker_filled_qty"] is not None:
            accounting_decimal(row["broker_filled_qty"], "broker_filled_qty", output=True, nonnegative=True)
        if row["broker_gross_value"] is not None:
            accounting_decimal(row["broker_gross_value"], "broker_gross_value", output=True, nonnegative=True)
        price_matches = row["broker_gross_value"] is not None and Decimal(row["activity_gross_value"]) == Decimal(row["broker_gross_value"])
        quantity_matches = row["broker_filled_qty"] is not None and Decimal(row["activity_filled_qty"]) == Decimal(row["broker_filled_qty"])
        if row["price_matches"] != price_matches or row["matches"] != (quantity_matches and price_matches):
            raise ContractValidationError("order matches must independently reflect exact quantity and gross-value comparisons")
    for key, identity in (("matched_fills", "activity_id"), ("unmatched_fills", "activity_id"), ("matched_fees", "activity_id"), ("unmatched_fees", "activity_id"), ("open_lots", "lot_id"), ("positions", "symbol"), ("order_checks", "order_id")):
        if len({row[identity] for row in result[key]}) != len(result[key]):
            raise ContractValidationError(key + " contains duplicate identities")
    for matched, unmatched in (("matched_fills", "unmatched_fills"), ("matched_fees", "unmatched_fees")):
        if {row["activity_id"] for row in result[matched]} & {row["activity_id"] for row in result[unmatched]}:
            raise ContractValidationError("an activity cannot be both matched and unmatched")
    fill_ids = {row["activity_id"] for row in result["matched_fills"]}
    if any(set(row["allocated_fill_ids"]) - fill_ids for row in result["matched_fees"]):
        raise ContractValidationError("fee allocations must refer to matched retained fills")
    totals = _object(result["totals"], {"buy_gross", "sell_gross", "gross_realized_pnl", "allocated_closed_fees", "allocated_open_fees", "net_realized_pnl"}, "accounting totals")
    for field in totals:
        if totals[field] is not None:
            totals[field] = accounting_decimal(totals[field], "totals." + field, output=True, nonnegative=field in {"buy_gross", "sell_gross"})
    if totals["buy_gross"] is None or totals["sell_gross"] is None:
        raise ContractValidationError("gross buy/sell values must be explicit decimal observations")
    result["totals"] = totals
    for field in ("execution_observed", "attributable_execution_observed", "fees_complete"):
        result[field] = _boolean(result[field], field)
    if (result["matched_fills"] or result["unmatched_fills"]) and not result["execution_observed"]:
        raise ContractValidationError("retained individual fill activities require observed execution")
    if result["attributable_execution_observed"] and not result["matched_fills"]:
        raise ContractValidationError("attributable executions require matched individual fills")
    if result["realized_trade_pnl"] is not None:
        result["realized_trade_pnl"] = accounting_decimal(result["realized_trade_pnl"], "realized_trade_pnl", output=True)
    for field in ("provider_verified", "ownership_authenticated", "execution_authority_granted", "readiness"):
        _fixed_boolean(result, field, False)
    result["authority"] = disabled_authority(result["authority"])
    reasons = [_identifier(item, "reason_codes") for item in _list(result["reason_codes"], "reason_codes")]
    if len(reasons) != len(set(reasons)):
        raise ContractValidationError("reason_codes must be unique")
    result["reason_codes"] = reasons
    if result["limitations"] != list(ACCOUNTING_LIMITATIONS):
        raise ContractValidationError("accounting must retain the versioned scope limitations")
    if result["status"] not in {"RECONCILED", "GROSS_RECONCILED_FEES_PENDING"} or not result["attributable_execution_observed"]:
        if any(totals[field] is not None for field in ("gross_realized_pnl", "net_realized_pnl")) or result["realized_trade_pnl"] is not None or any(row["gross_pnl"] is not None or row["net_pnl"] is not None for row in result["closed_lots"]):
            raise ContractValidationError("incomplete or non-executed accounting cannot claim realized P&L")
    if result["status"] == "RECONCILED" and not result["fees_complete"]:
        raise ContractValidationError("fully reconciled accounting requires explicit complete fee coverage")
    if not result["fees_complete"] or result["status"] == "GROSS_RECONCILED_FEES_PENDING":
        if totals["net_realized_pnl"] is not None or result["realized_trade_pnl"] is not None or any(row["net_pnl"] is not None for row in result["closed_lots"]):
            raise ContractValidationError("unknown fee coverage cannot claim net P&L")
    if result["realized_trade_pnl"] != totals["net_realized_pnl"]:
        raise ContractValidationError("realized_trade_pnl must equal attributable net accounting P&L")
    return result
