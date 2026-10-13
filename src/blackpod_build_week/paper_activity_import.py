"""Pure, offline normalization of retained PAPER account-activity exports.

An export envelope supplies explicit account, window and coverage declarations;
the activity rows supply execution facts. Neither the envelope nor a local hash
attests provider identity or grants trading authority. Order snapshots are never
converted into fills, and account-level fees never acquire invented order IDs.
"""
from __future__ import annotations

from datetime import date
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
import re

from .contracts.decision_journal import _identifier, _object
from .contracts.mission_request import (
    ContractValidationError, normalize_rfc3339, parse_rfc3339, parse_strict_json_object_bytes,
)
from .contracts.trading_reconciliation import symbol_text
from .hashing import canonical_json_bytes, sha256_bytes


ACTIVITY_EXPORT_SCHEMA_VERSION = "blackpod.paper_activity_export.v1"
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_ACTIVITIES = 20000
_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$")
_AUTHORITY = {field: False for field in (
    "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
)}


class PaperActivityImportError(ValueError):
    """A retained export is unsupported, conflicting, or not source-faithful."""


def _decimal(value, name, *, positive=False, nonnegative=False):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise PaperActivityImportError(name + " must be a bounded fixed-point decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise PaperActivityImportError(name + " is not a finite decimal") from exc
    if (not number.is_finite() or number.copy_abs() > Decimal("1e20")
            or (positive and number <= 0) or (nonnegative and number < 0)):
        raise PaperActivityImportError(name + " is outside the permitted decimal range")
    return value


def _timestamp(value, name):
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise PaperActivityImportError(name + " must be a timezone-aware timestamp with at most microsecond precision")
    return normalize_rfc3339(value, name)


def _fee_date(value):
    """Retain date-only provider precision instead of inventing midnight."""
    if isinstance(value, str) and _DATE.fullmatch(value):
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise PaperActivityImportError("fee.date is not a valid calendar date") from exc
        return value
    return _timestamp(value, "fee.date")


def _nullable_id(row, field):
    value = row.get(field)
    return None if value is None else _identifier(value, "activity." + field)


def _fill(row):
    fields = {"id", "order_id", "symbol", "side", "qty", "price", "transaction_time"}
    if not fields <= row.keys():
        raise PaperActivityImportError("FILL activity is missing required execution facts")
    side = row["side"]
    if side not in {"buy", "sell"}:
        raise PaperActivityImportError("FILL side must be buy or sell")
    if "type" in row and row["type"] not in {"fill", "partial_fill"}:
        raise PaperActivityImportError("FILL type must be fill or partial_fill")
    qty = _decimal(row["qty"], "fill.qty", positive=True)
    if "cum_qty" in row:
        cum_qty = _decimal(row["cum_qty"], "fill.cum_qty", positive=True)
        if Decimal(cum_qty) < Decimal(qty):
            raise PaperActivityImportError("FILL cumulative quantity cannot be below execution quantity")
    if "leaves_qty" in row:
        _decimal(row["leaves_qty"], "fill.leaves_qty", nonnegative=True)
    return {
        "activity_id": _identifier(row["id"], "activity.id"),
        "order_id": _identifier(row["order_id"], "activity.order_id"),
        "symbol": symbol_text(row["symbol"]), "side": side,
        "qty": qty, "price": _decimal(row["price"], "fill.price", positive=True),
        "occurred_at": _timestamp(row["transaction_time"], "fill.transaction_time"),
    }


def _fee(row, currency):
    if not {"id", "net_amount", "date"} <= row.keys():
        raise PaperActivityImportError("FEE activity is missing required amount or date facts")
    if row.get("currency", currency) != currency:
        raise PaperActivityImportError("FEE currency differs from export currency")
    # Raw net_amount is signed account cash flow: a debit is negative. The
    # accounting contract uses positive expenses and negative fee credits.
    # copy_negate is exact and independent of the ambient Decimal context.
    cash_flow = Decimal(_decimal(row["net_amount"], "fee.net_amount"))
    expense = "0" if cash_flow == 0 else format(cash_flow.copy_negate(), "f")
    # Alpaca's generic FEE activity does not establish a regulatory/commission
    # subtype. A date, symbol or description does not establish order linkage.
    return {
        "activity_id": _identifier(row["id"], "activity.id"),
        "order_id": _nullable_id(row, "order_id"),
        "fill_activity_id": _nullable_id(row, "fill_activity_id"),
        "symbol": None if row.get("symbol") is None else symbol_text(row["symbol"]),
        "amount": expense,
        "currency": currency, "occurred_at": _fee_date(row["date"]), "fee_type": "OTHER",
    }


def _check_cumulative(rows, complete):
    """Detect contradictions in optional raw per-order cumulative fill facts."""
    orders = {}
    for row in rows:
        if row["activity_type"] == "FILL":
            orders.setdefault(row["order_id"], []).append(row)
    # Do not inherit a caller's exponent limits or rounding traps. A fresh
    # context keeps retained-source validation deterministic in every process.
    context = Context(prec=256, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                      capitals=1, clamp=0, flags=[], traps=[DivisionByZero, InvalidOperation, Overflow])
    with localcontext(context):
        for entries in orders.values():
            if not all("cum_qty" in row for row in entries):
                continue
            # Same-order cumulative quantity provides a defensible sequence
            # within equal timestamps, but is not used as a lot quantity.
            entries = sorted(entries, key=lambda row: (
                parse_rfc3339(row["transaction_time"], "fill.transaction_time"), Decimal(row["cum_qty"]),
            ))
            previous = None
            for row in entries:
                cumulative, qty = Decimal(row["cum_qty"]), Decimal(row["qty"])
                if previous is not None:
                    expected = previous + qty
                    if cumulative < expected or (complete and cumulative != expected):
                        raise PaperActivityImportError("retained cumulative fills contradict individual execution quantities or completeness")
                previous = cumulative


def normalize_activity_export(raw: bytes) -> dict:
    """Select exact broker facts from one explicit versioned export envelope.

    Unknown financial activity types fail closed, including transfers, splits,
    dividends, and crypto fees. Byte-identical duplicate activity rows are
    deduplicated; a reused identity with changed retained facts is rejected.
    Supported timestamps have at most microsecond precision. Higher precision
    is rejected rather than truncated into an invented FIFO ordering.
    """
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_SOURCE_BYTES:
            raise PaperActivityImportError("activity source must be nonempty bounded bytes")
        source = _object(parse_strict_json_object_bytes(raw, document_name="paper activity export"), {
            "schema_version", "recorded_at", "account_id", "mode", "currency", "window", "coverage",
            "source_kind", "activities",
        }, "paper activity export")
        if source["schema_version"] != ACTIVITY_EXPORT_SCHEMA_VERSION:
            raise PaperActivityImportError("unsupported paper activity export schema")
        if source["mode"] != "PAPER" or source["currency"] != "USD":
            raise PaperActivityImportError("only explicit PAPER USD exports are supported")
        if source["source_kind"] not in {"ALPACA_PAPER_ACTIVITY_IMPORT", "SYNTHETIC_FIXTURE"}:
            raise PaperActivityImportError("unsupported declared activity source kind")
        _identifier(source["account_id"], "account_id")
        recorded_at = _timestamp(source["recorded_at"], "recorded_at")
        window = _object(source["window"], {"started_at", "ended_at"}, "activity window")
        window = {field: _timestamp(value, "window." + field) for field, value in window.items()}
        coverage = _object(source["coverage"], {"fills_complete", "fees_complete", "scope_order_ids"}, "activity coverage")
        for field in ("fills_complete", "fees_complete"):
            if type(coverage[field]) is not bool:
                raise PaperActivityImportError("coverage." + field + " must be an explicit boolean")
        scope = coverage["scope_order_ids"]
        if not isinstance(scope, list) or len(scope) > _MAX_ACTIVITIES:
            raise PaperActivityImportError("scope_order_ids must be a bounded list")
        scope = [_identifier(value, "scope_order_ids") for value in scope]
        if len(set(scope)) != len(scope):
            raise PaperActivityImportError("scope_order_ids cannot contain duplicates")
        coverage["scope_order_ids"] = scope
        rows = source["activities"]
        if not isinstance(rows, list) or len(rows) > _MAX_ACTIVITIES:
            raise PaperActivityImportError("activities must be a bounded list")
        fills, fees, seen, retained_rows = [], [], {}, []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("activity_type"), str):
                raise PaperActivityImportError("each activity must have an explicit activity_type")
            # SDK exports may repeat account/mode/currency on each row. The
            # envelope cannot relabel a contradictory retained provider fact.
            for field in ("account_id", "mode", "currency"):
                if field in row and row[field] != source[field]:
                    raise PaperActivityImportError("activity." + field + " contradicts the explicit export envelope")
            kind = row["activity_type"]
            if kind not in {"FILL", "FEE"}:
                raise PaperActivityImportError("unsupported financial activity type: " + kind[:64])
            selected = _fill(row) if kind == "FILL" else _fee(row, source["currency"])
            identity = selected["activity_id"]
            exact = canonical_json_bytes(row)
            if identity in seen:
                if seen[identity] != exact:
                    raise PaperActivityImportError("activity identity conflicts with changed retained facts")
                continue
            seen[identity] = exact
            retained_rows.append(row)
            (fills if kind == "FILL" else fees).append(selected)
        _check_cumulative(retained_rows, coverage["fills_complete"])
        return {
            "recorded_at": recorded_at, "mode": "PAPER", "account_id": source["account_id"],
            "currency": "USD", "window": window, "coverage": coverage, "source_kind": source["source_kind"],
            "fills": fills, "fees": fees,
        }
    except PaperActivityImportError:
        raise
    except (ContractValidationError, RecursionError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
        raise PaperActivityImportError("invalid retained paper activity export: " + str(exc)) from exc


def activities_input_from_export(raw: bytes, *, activity_set_id: str | None = None,
                                 import_id: str | None = None, evidence_path: str):
    """Create a strict import without writing files or consulting a provider."""
    from .contracts.trading_accounting import PaperActivitiesInput
    if (activity_set_id is None) == (import_id is None):
        raise PaperActivityImportError("supply exactly one activity_set_id (or its import_id alias)")
    selected = normalize_activity_export(raw)
    source_kind = selected.pop("source_kind")
    try:
        return PaperActivitiesInput.from_mapping({
            "schema_version": "blackpod.paper_activities.v1", "activity_set_id": activity_set_id or import_id,
            **selected,
            "provenance": {"source_kind": source_kind,
                           "source_evidence": {"path": evidence_path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
                           "provider_verified": False},
            "authority": dict(_AUTHORITY),
        })
    except (ContractValidationError, RecursionError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
        if isinstance(exc, PaperActivityImportError):
            raise
        raise PaperActivityImportError("activity import failed strict validation: " + str(exc)) from exc


def validate_activities_source(activities, raw: bytes) -> dict:
    """Reproduce a typed import from its retained original export bytes."""
    reference = activities.provenance["source_evidence"]
    if (not isinstance(raw, bytes) or len(raw) != reference["size_bytes"]
            or sha256_bytes(raw) != reference["sha256"]):
        raise PaperActivityImportError("activity source evidence hash or length differs")
    projected = activities_input_from_export(raw, activity_set_id=activities.activity_set_id,
                                             evidence_path=reference["path"])
    if projected.to_bytes() != activities.to_bytes():
        raise PaperActivityImportError("activity import differs from retained original source facts")
    return normalize_activity_export(raw)
