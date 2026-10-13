"""Strict immutable PAPER observation, desk declaration, and reconciliation inputs.

These are retained offline observations and declarations. They do not grant
execution/capital authority or authenticate an imported provider/desk identity.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .decision_journal import (
    _ImmutableDocument, _boolean, _enum, _hash, _identifier, _object, _string,
    validate_evidence_path,
)
from .investment_review import _event_id, _fixed_boolean, _list, disabled_authority
from .mission_request import (
    ContractValidationError, normalize_rfc3339, parse_rfc3339, parse_strict_json_object_bytes,
)

BROKER_SNAPSHOT_SCHEMA_VERSION = "blackpod.paper_broker_snapshot.v1"
DESK_OWNERSHIP_SCHEMA_VERSION = "blackpod.trading_desk_ownership.v1"
TRADING_RECONCILIATION_SCHEMA_VERSION = "blackpod.trading_execution_reconciliation.v1"
PAPER_ORIGIN = "https://paper-api.alpaca.markets"
RECONCILIATION_SCOPE = "PAPER_RECONCILIATION_ONLY"
_DECIMAL = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-_/]{0,31}$")
ORDER_STATUSES = frozenset({
    "new", "partially_filled", "filled", "done_for_day", "canceled", "expired", "replaced", "pending_cancel",
    "pending_replace", "accepted", "pending_new", "accepted_for_bidding", "stopped", "rejected", "suspended", "calculated", "held",
})
ORDER_TIME_FIELDS = frozenset({"submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at", "failed_at", "replaced_at"})


def decimal_text(value, name, *, positive=False, nonnegative=False):
    """Preserve supplied decimal spelling, excluding binary/boolean numbers."""
    if not isinstance(value, str) or len(value) > 128 or not _DECIMAL.fullmatch(value):
        raise ContractValidationError(name + " must be a bounded finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ContractValidationError(name + " must be a bounded finite decimal string") from exc
    if not number.is_finite() or abs(number) > Decimal("1e20") or (positive and number <= 0) or (nonnegative and number < 0):
        raise ContractValidationError(name + " is outside the permitted decimal range")
    return value


def symbol_text(value, name="symbol"):
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise ContractValidationError(name + " must be an explicit uppercase broker symbol")
    return value


def evidence_reference(value, name="source evidence"):
    result = _object(value, {"path", "sha256", "size_bytes"}, name)
    result["path"] = validate_evidence_path(result["path"])
    result["sha256"] = _hash(result["sha256"], name + ".sha256")
    if type(result["size_bytes"]) is not int or not 0 <= result["size_bytes"] <= 64 * 1024 * 1024:
        raise ContractValidationError(name + ".size_bytes must be a bounded nonnegative integer")
    return result


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def _base(value, fields, schema, name):
    result = _object(value, fields, name)
    _constant(result, "schema_version", schema)
    _constant(result, "mode", "PAPER")
    result["account_id"] = _identifier(result["account_id"], "account_id")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _snapshot(value):
    result = _base(value, {
        "schema_version", "snapshot_id", "captured_at", "capture_window", "mode", "account_id", "account",
        "positions", "orders", "completeness", "capture_provenance", "authority",
    }, BROKER_SNAPSHOT_SCHEMA_VERSION, "broker snapshot")
    result["snapshot_id"] = _identifier(result["snapshot_id"], "snapshot_id")
    result["captured_at"] = normalize_rfc3339(result["captured_at"], "captured_at")
    window = _object(result["capture_window"], {"started_at", "completed_at"}, "capture_window")
    for field in window: window[field] = normalize_rfc3339(window[field], "capture_window." + field)
    start = parse_rfc3339(window["started_at"], "started_at")
    end = parse_rfc3339(window["completed_at"], "completed_at")
    if not start <= end <= parse_rfc3339(result["captured_at"], "captured_at"):
        raise ContractValidationError("capture window must be ordered and end no later than captured_at")
    result["capture_window"] = window
    account = _object(result["account"], {"status", "trading_blocked", "account_blocked", "currency", "equity", "cash", "buying_power"}, "account")
    account["status"] = _string(account["status"], "account.status", 64)
    account["trading_blocked"] = _boolean(account["trading_blocked"], "account.trading_blocked")
    if account["account_blocked"] is not None:
        account["account_blocked"] = _boolean(account["account_blocked"], "account.account_blocked")
    if account["currency"] is not None and (not isinstance(account["currency"], str) or not re.fullmatch(r"[A-Z]{3}", account["currency"])):
        raise ContractValidationError("account.currency must be null or an uppercase three-letter code")
    for field in ("equity", "cash"):
        account[field] = decimal_text(account[field], "account." + field)
    if account["buying_power"] is not None:
        account["buying_power"] = decimal_text(account["buying_power"], "account.buying_power")
    result["account"] = account
    positions, seen = [], set()
    for entry in _list(result["positions"], "positions"):
        item = _object(entry, {"symbol", "qty", "side", "market_value", "avg_entry_price", "current_price"}, "position")
        item["symbol"] = symbol_text(item["symbol"])
        if item["symbol"] in seen: raise ContractValidationError("positions contains duplicate symbol")
        seen.add(item["symbol"])
        item["qty"] = decimal_text(item["qty"], "position.qty")
        qty = Decimal(item["qty"])
        if qty == 0: raise ContractValidationError("open position qty must be nonzero")
        item["side"] = _enum(item["side"], {"long", "short"}, "position.side")
        if (qty > 0) != (item["side"] == "long"):
            raise ContractValidationError("position side must agree with signed qty")
        if item["market_value"] is not None:
            item["market_value"] = decimal_text(item["market_value"], "position.market_value")
            market_value = Decimal(item["market_value"])
            if market_value == 0 or (market_value > 0) != (qty > 0):
                raise ContractValidationError("signed position valuation must agree with qty")
        for field in ("avg_entry_price", "current_price"):
            if item[field] is not None: item[field] = decimal_text(item[field], "position." + field, positive=True)
        positions.append(item)
    if len(positions) > 1000: raise ContractValidationError("positions exceeds the supported count")
    result["positions"] = positions
    orders, identities = [], set()
    for entry in _list(result["orders"], "orders"):
        item = _object(entry, {
            "id", "client_order_id", "symbol", "side", "status", "type", "time_in_force", "qty", "notional", "filled_qty",
            "filled_avg_price", "replaces", "replaced_by", "parent_order_id", "leg_ids",
        } | ORDER_TIME_FIELDS, "order")
        item["id"] = _identifier(item["id"], "order.id")
        if item["id"] in identities: raise ContractValidationError("orders contains duplicate id")
        identities.add(item["id"])
        for field in ("client_order_id", "replaces", "replaced_by", "parent_order_id"):
            if item[field] is not None: item[field] = _identifier(item[field], "order." + field)
            if field != "client_order_id" and item[field] == item["id"]:
                raise ContractValidationError("order lineage cannot self-reference")
        item["symbol"] = symbol_text(item["symbol"])
        item["side"] = _enum(item["side"], {"buy", "sell"}, "order.side")
        item["status"] = _enum(item["status"], ORDER_STATUSES, "order.status")
        item["type"] = _enum(item["type"], {"market", "limit", "stop", "stop_limit", "trailing_stop"}, "order.type")
        item["time_in_force"] = _enum(item["time_in_force"], {"day", "gtc", "opg", "cls", "ioc", "fok"}, "order.time_in_force")
        for field in ("qty", "notional", "filled_avg_price"):
            if item[field] is not None: item[field] = decimal_text(item[field], "order." + field, positive=True)
        if item["qty"] is None and item["notional"] is None:
            raise ContractValidationError("order must retain qty or notional")
        item["filled_qty"] = decimal_text(item["filled_qty"], "order.filled_qty", nonnegative=True)
        if item["qty"] is not None and Decimal(item["filled_qty"]) > Decimal(item["qty"]):
            raise ContractValidationError("cumulative filled_qty cannot exceed order qty")
        for field in ORDER_TIME_FIELDS:
            if item[field] is not None: item[field] = normalize_rfc3339(item[field], "order." + field)
        legs = [_identifier(identity, "order.leg_ids") for identity in _list(item["leg_ids"], "leg_ids")]
        if len(set(legs)) != len(legs) or item["id"] in legs:
            raise ContractValidationError("order leg_ids cannot duplicate or self-reference")
        item["leg_ids"] = legs
        orders.append(item)
    if len(orders) > 2000: raise ContractValidationError("orders exceeds the supported count")
    for item in orders:
        if set(item["leg_ids"]) - identities:
            raise ContractValidationError("order leg_ids must bind retained order observations")
    # Flat observations retain nesting without allowing recursive broker lineage.
    by_id = {item["id"]: item for item in orders}
    complete, active = set(), set()
    def walk(identity, depth=0):
        if identity in active or depth > 16:
            raise ContractValidationError("order leg lineage is cyclic or exceeds supported depth")
        if identity in complete: return
        active.add(identity)
        for child in by_id[identity]["leg_ids"]: walk(child, depth + 1)
        active.remove(identity); complete.add(identity)
    for identity in by_id: walk(identity)
    result["orders"] = orders
    complete = _object(result["completeness"], {"positions_complete", "open_orders_complete", "tracked_orders_complete"}, "completeness")
    for field in complete: complete[field] = _boolean(complete[field], "completeness." + field)
    result["completeness"] = complete
    provenance = _object(result["capture_provenance"], {"source_kind", "origin", "source_evidence", "sequential_capture", "snapshot_atomic", "provider_verified"}, "capture_provenance")
    provenance["source_kind"] = _enum(provenance["source_kind"], {"ALPACA_PAPER_GET_IMPORT", "SYNTHETIC_FIXTURE"}, "source_kind")
    _constant(provenance, "origin", PAPER_ORIGIN)
    for field, expected in (("sequential_capture", True), ("snapshot_atomic", False), ("provider_verified", False)):
        _fixed_boolean(provenance, field, expected)
    provenance["source_evidence"] = evidence_reference(provenance["source_evidence"])
    result["capture_provenance"] = provenance
    return result


def _ownership(value):
    result = _base(value, {
        "schema_version", "ownership_id", "recorded_at", "declared_by", "mode", "account_id", "broker_snapshot_event_id",
        "broker_snapshot_sha256", "desks", "status", "supersedes_event_id", "identity_authenticated", "authority",
    }, DESK_OWNERSHIP_SCHEMA_VERSION, "desk ownership")
    for field in ("ownership_id", "declared_by"): result[field] = _identifier(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["broker_snapshot_event_id"] = _event_id(result["broker_snapshot_event_id"], "broker_snapshot_event_id")
    result["broker_snapshot_sha256"] = _hash(result["broker_snapshot_sha256"], "broker_snapshot_sha256")
    if result["supersedes_event_id"] is not None: result["supersedes_event_id"] = _event_id(result["supersedes_event_id"], "supersedes_event_id")
    _constant(result, "status", "DECLARED")
    _fixed_boolean(result, "identity_authenticated", False)
    desks = _object(result["desks"], {"TRADING", "INVESTMENT"}, "desks")
    for desk, symbols in desks.items():
        desks[desk] = [symbol_text(symbol) for symbol in _list(symbols, desk)]
        if len(set(desks[desk])) != len(desks[desk]) or len(desks[desk]) > 1000:
            raise ContractValidationError("desk symbols must be unique and bounded")
    if set(desks["TRADING"]) & set(desks["INVESTMENT"]):
        raise ContractValidationError("same-symbol ownership across desks is unsupported")
    result["desks"] = desks
    return result


def _reconciliation(value):
    result = _base(value, {
        "schema_version", "reconciliation_id", "recorded_at", "mode", "account_id", "broker_snapshot_event_id",
        "broker_snapshot_sha256", "ownership_event_id", "ownership_sha256", "runtime_evidence", "prior_reconciliation_event_id",
        "scope", "realized_trade_pnl", "authority",
    }, TRADING_RECONCILIATION_SCHEMA_VERSION, "trading reconciliation")
    result["reconciliation_id"] = _identifier(result["reconciliation_id"], "reconciliation_id")
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["broker_snapshot_event_id"] = _event_id(result["broker_snapshot_event_id"], "broker_snapshot_event_id")
    result["broker_snapshot_sha256"] = _hash(result["broker_snapshot_sha256"], "broker_snapshot_sha256")
    if (result["ownership_event_id"] is None) != (result["ownership_sha256"] is None):
        raise ContractValidationError("ownership event and hash must both be absent or both present")
    if result["ownership_event_id"] is not None:
        result["ownership_event_id"] = _event_id(result["ownership_event_id"], "ownership_event_id")
        result["ownership_sha256"] = _hash(result["ownership_sha256"], "ownership_sha256")
    if result["runtime_evidence"] is not None: result["runtime_evidence"] = evidence_reference(result["runtime_evidence"], "runtime_evidence")
    if result["prior_reconciliation_event_id"] is not None:
        result["prior_reconciliation_event_id"] = _event_id(result["prior_reconciliation_event_id"], "prior_reconciliation_event_id")
    _constant(result, "scope", RECONCILIATION_SCOPE)
    if result["realized_trade_pnl"] is not None:
        raise ContractValidationError("this reconciliation does not evaluate realized trade P&L")
    return result


class _ReconciliationDocument(_ImmutableDocument):
    __slots__ = ()
    def __init__(self, value):
        try: super().__init__(value)
        except (RecursionError, ValueError, OverflowError, InvalidOperation) as exc:
            if isinstance(exc, ContractValidationError): raise
            raise ContractValidationError("trading reconciliation nesting or numeric representation exceeds supported limits") from exc

    @classmethod
    def from_bytes(cls, value: bytes):
        try: parsed = parse_strict_json_object_bytes(value, document_name=cls.__name__)
        except (RecursionError, ValueError, OverflowError) as exc:
            if isinstance(exc, ContractValidationError): raise
            raise ContractValidationError("trading reconciliation JSON exceeds supported parser limits") from exc
        return cls.from_mapping(parsed)


class BrokerSnapshotInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_snapshot)


class DeskOwnershipInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_ownership)


class TradingReconciliationInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_reconciliation)

# Short name used by the pure engine; both expose the same immutable schema.
ReconciliationInput = TradingReconciliationInput

RECONCILIATION_LIMITATIONS = (
    "NON_ATOMIC_BROKER_SNAPSHOT", "DECLARED_DESK_OWNERSHIP_UNAUTHENTICATED", "PROVIDER_IDENTITY_NOT_ATTESTED",
    "NO_ATTRIBUTABLE_COST_BASIS_OR_FEES", "CUMULATIVE_FILLS_NOT_ADDITIVE", "NO_EXECUTION_AUTHORITY",
)
_DESKS = frozenset({"TRADING", "INVESTMENT", "UNCLASSIFIED"})


def _no_authority_report(value, fields, name):
    result = _object(value, fields, name)
    for field in ("provider_verified", "identity_authenticated", "ownership_authenticated", "execution_authority_granted", "readiness"):
        if field in result: _fixed_boolean(result, field, False)
    if result["realized_trade_pnl"] is not None:
        raise ContractValidationError("PAPER observations do not evaluate realized trade P&L")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _classified_positions(value, *, baseline=False, unclassified=False):
    entries, seen = [], set()
    for entry in _list(value, "positions"):
        item = _object(entry, {"symbol", "desk", "qty"} if baseline else {"symbol", "desk"}, "classified position")
        item["symbol"] = symbol_text(item["symbol"])
        if item["symbol"] in seen: raise ContractValidationError("position classifications contain duplicate symbols")
        seen.add(item["symbol"])
        item["desk"] = _enum(item["desk"], {"UNCLASSIFIED"} if unclassified else _DESKS, "desk")
        if baseline: item["qty"] = decimal_text(item["qty"], "position.qty")
        entries.append(item)
    return entries


def _classified_orders(value, *, unclassified=False):
    entries, seen = [], set()
    for entry in _list(value, "orders"):
        item = _object(entry, {"order_id", "symbol", "desk"}, "classified order")
        item["order_id"] = _identifier(item["order_id"], "order_id")
        if item["order_id"] in seen: raise ContractValidationError("order classifications contain duplicate order IDs")
        seen.add(item["order_id"])
        item["symbol"] = symbol_text(item["symbol"])
        item["desk"] = _enum(item["desk"], {"UNCLASSIFIED"} if unclassified else _DESKS, "desk")
        entries.append(item)
    return entries


def _unique_symbols(value, field):
    result = [symbol_text(item, field) for item in _list(value, field)]
    if len(set(result)) != len(result): raise ContractValidationError(field + " contains duplicate symbols")
    return result


def validate_snapshot_assessment(value, snapshot: BrokerSnapshotInput):
    result = _no_authority_report(value, {
        "position_count", "order_count", "position_classifications", "order_classifications", "execution_observed",
        "provider_verified", "execution_authority_granted", "readiness", "realized_trade_pnl", "authority",
    }, "snapshot assessment")
    for field, expected in (("position_count", len(snapshot.positions)), ("order_count", len(snapshot.orders))):
        if type(result[field]) is not int or result[field] != expected:
            raise ContractValidationError(field + " must match retained snapshot")
    result["position_classifications"] = _classified_positions(result["position_classifications"], unclassified=True)
    expected_positions = {(item["symbol"], "UNCLASSIFIED") for item in snapshot.positions}
    if {(item["symbol"], item["desk"]) for item in result["position_classifications"]} != expected_positions:
        raise ContractValidationError("snapshot position classifications must retain the full unclassified book")
    result["order_classifications"] = _classified_orders(result["order_classifications"], unclassified=True)
    if {(item["order_id"], item["symbol"]) for item in result["order_classifications"]} != {(item["id"], item["symbol"]) for item in snapshot.orders}:
        raise ContractValidationError("snapshot order classifications must retain exact order identities")
    _fixed_boolean(result, "execution_observed", any(Decimal(item["filled_qty"]) > 0 for item in snapshot.orders))
    return result


def validate_ownership_assessment(value, ownership: DeskOwnershipInput):
    result = _no_authority_report(value, {
        "effective_at", "added_symbols", "released_symbols", "reassigned_symbols", "baseline_positions", "baseline_orders",
        "identity_authenticated", "execution_authority_granted", "readiness", "realized_trade_pnl", "authority",
    }, "ownership assessment")
    result["effective_at"] = normalize_rfc3339(result["effective_at"], "effective_at")
    if result["effective_at"] != ownership.recorded_at:
        raise ContractValidationError("ownership effective_at must match original declaration")
    for field in ("added_symbols", "released_symbols", "reassigned_symbols"):
        result[field] = _unique_symbols(result[field], field)
    result["baseline_positions"] = _classified_positions(result["baseline_positions"], baseline=True)
    result["baseline_orders"] = _classified_orders(result["baseline_orders"])
    for item in (*result["baseline_positions"], *result["baseline_orders"]):
        expected = next((desk for desk, symbols in ownership.desks.items() if item["symbol"] in symbols), "UNCLASSIFIED")
        if item["desk"] != expected:
            raise ContractValidationError("baseline desk classification must match explicit declaration")
    return result


def validate_reconciliation_result(value, reconciliation: ReconciliationInput):
    result = _no_authority_report(value, {
        "status", "positions", "orders", "attempts", "restart_barrier", "execution_observed", "attributable_execution_observed",
        "provider_verified", "ownership_authenticated", "execution_authority_granted", "readiness", "realized_trade_pnl", "authority", "limitations",
    }, "reconciliation result")
    result["status"] = _enum(result["status"], {"NO_EXECUTION_OBSERVED", "RECONCILED", "PENDING"}, "status")
    result["positions"] = _classified_positions(result["positions"], baseline=True)
    orders, seen = [], set()
    for entry in _list(result["orders"], "orders"):
        item = _object(entry, {"order_id", "symbol", "desk", "status", "filled_qty", "filled_avg_price", "matched_attempt_sha256"}, "reconciled order")
        item["order_id"] = _identifier(item["order_id"], "order_id")
        if item["order_id"] in seen: raise ContractValidationError("reconciled orders contain duplicate order IDs")
        seen.add(item["order_id"])
        item["symbol"] = symbol_text(item["symbol"])
        item["desk"] = _enum(item["desk"], _DESKS, "desk")
        item["status"] = _enum(item["status"], ORDER_STATUSES, "broker status")
        item["filled_qty"] = decimal_text(item["filled_qty"], "filled_qty", nonnegative=True)
        if item["filled_avg_price"] is not None: item["filled_avg_price"] = decimal_text(item["filled_avg_price"], "filled_avg_price", positive=True)
        if item["matched_attempt_sha256"] is not None: item["matched_attempt_sha256"] = _hash(item["matched_attempt_sha256"], "matched_attempt_sha256")
        orders.append(item)
    result["orders"] = orders
    attempts, seen = [], set()
    for entry in _list(result["attempts"], "attempts"):
        item = _object(entry, {
            "attempt_sha256", "session_id", "symbol", "side", "qty", "order_id", "client_order_id", "status", "broker_status",
            "filled_qty", "filled_avg_price", "replacement_order_ids",
        }, "execution attempt")
        item["attempt_sha256"] = _hash(item["attempt_sha256"], "attempt_sha256")
        if item["attempt_sha256"] in seen: raise ContractValidationError("duplicate execution attempt hash")
        seen.add(item["attempt_sha256"])
        item["session_id"] = _identifier(item["session_id"], "session_id")
        item["symbol"] = symbol_text(item["symbol"])
        item["side"] = _enum(item["side"], {"buy", "sell", "close"}, "attempt.side")
        item["qty"] = decimal_text(item["qty"], "attempt.qty", positive=True)
        for field in ("order_id", "client_order_id"):
            if item[field] is not None: item[field] = _identifier(item[field], field)
        item["status"] = _enum(item["status"], {"ACCEPTANCE_UNKNOWN", "NOT_OBSERVED", "ORDER_OPEN", "BROKER_TERMINAL", "REPLACED_PENDING"}, "attempt.status")
        if item["broker_status"] is not None: item["broker_status"] = _enum(item["broker_status"], ORDER_STATUSES, "broker_status")
        if item["filled_qty"] is not None: item["filled_qty"] = decimal_text(item["filled_qty"], "attempt.filled_qty", nonnegative=True)
        if item["filled_avg_price"] is not None: item["filled_avg_price"] = decimal_text(item["filled_avg_price"], "attempt.filled_avg_price", positive=True)
        replacements = [_identifier(identity, "replacement_order_ids") for identity in _list(item["replacement_order_ids"], "replacement_order_ids")]
        if len(set(replacements)) != len(replacements): raise ContractValidationError("duplicate replacement order ID")
        item["replacement_order_ids"] = replacements
        attempts.append(item)
    result["attempts"] = attempts
    attempt_hashes = {item["attempt_sha256"] for item in attempts}
    if any(item["matched_attempt_sha256"] is not None and item["matched_attempt_sha256"] not in attempt_hashes for item in orders):
        raise ContractValidationError("order refers to an unknown reconciled attempt")
    barrier = _object(result["restart_barrier"], {"entries_blocked", "unresolved_attempts", "automatic_resubmission_enabled", "execution_authority_granted"}, "restart_barrier")
    unresolved, seen = [], set()
    for entry in _list(barrier["unresolved_attempts"], "unresolved_attempts"):
        item = _object(entry, {"attempt_sha256", "order_id", "reason_code"}, "unresolved attempt")
        item["attempt_sha256"] = _hash(item["attempt_sha256"], "unresolved attempt hash")
        if item["attempt_sha256"] not in attempt_hashes or item["attempt_sha256"] in seen:
            raise ContractValidationError("unresolved attempts must bind unique retained attempts")
        seen.add(item["attempt_sha256"])
        if item["order_id"] is not None: item["order_id"] = _identifier(item["order_id"], "order_id")
        item["reason_code"] = _identifier(item["reason_code"], "reason_code")
        unresolved.append(item)
    barrier["unresolved_attempts"] = unresolved
    barrier["entries_blocked"] = _boolean(barrier["entries_blocked"], "entries_blocked")
    if unresolved and not barrier["entries_blocked"]:
        raise ContractValidationError("unresolved attempts require the restart entry barrier")
    for field in ("automatic_resubmission_enabled", "execution_authority_granted"):
        _fixed_boolean(barrier, field, False)
    result["restart_barrier"] = barrier
    result["execution_observed"] = _boolean(result["execution_observed"], "execution_observed")
    result["attributable_execution_observed"] = _boolean(result["attributable_execution_observed"], "attributable_execution_observed")
    if result["attributable_execution_observed"] and not result["execution_observed"]:
        raise ContractValidationError("attributable execution requires observed execution")
    if result["execution_observed"] != any(Decimal(item["filled_qty"]) > 0 for item in orders):
        raise ContractValidationError("execution_observed must reflect cumulative broker fill facts")
    if reconciliation.ownership_event_id is None and any(item["desk"] != "UNCLASSIFIED" for item in (*result["positions"], *orders)):
        raise ContractValidationError("missing ownership must remain UNCLASSIFIED")
    if result["limitations"] != list(RECONCILIATION_LIMITATIONS):
        raise ContractValidationError("reconciliation must retain the fixed scope limitations")
    return result
