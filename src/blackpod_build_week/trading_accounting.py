"""Pure source-backed PAPER fill, FIFO lot, and explicitly attributed fee accounting.

This module has no provider, filesystem, executor or policy authority. Individual
activity identities are transactions; order cumulative quantities are checks.
Builders consume an already verified journal prefix; JournalStore verifies every
source projection at append and read. Every update replays the retained activity
set from a verified flat baseline.
Unknown fees never become zero, and a pending fill proof never yields trade P&L.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import parse_rfc3339
from .contracts.trading_accounting import ACCOUNTING_LIMITATIONS, PaperActivitiesInput, TradingAccountingInput, accounting_decimal
from .contracts.trading_reconciliation import BrokerSnapshotInput, DeskOwnershipInput, TradingReconciliationInput
from .hashing import canonical_json_bytes, sha256_bytes
from . import trading_reconciliation as reconciliation

ACCOUNTING_EVENT_TYPE = "TRADING_FILL_LOT_ACCOUNTING_RECORDED"
ACCOUNTING_SOURCE_KIND = "TRADING_FILL_LOT_ACCOUNTING"
ACCOUNTING_EVIDENCE_PATH = "trading/accounting.json"
PRECISION_POLICY = {"calculation_precision": 256, "fee_allocation_scale": 18,
                    "rounding": "ROUND_HALF_EVEN", "residual": "LAST_SLICE_REMAINDER"}
ZERO = Decimal("0")
FEE_QUANTUM = Decimal("0.000000000000000001")


class TradingAccountingError(ValueError):
    """An immutable accounting relationship or retained source cannot replay."""


def _time(value):
    return parse_rfc3339(value, "accounting timestamp")


def _number(value):
    return Decimal(value)


def _text(value):
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _bounded_observation(value):
    if value is None:
        return None
    text = _text(value)
    try:
        accounting_decimal(text, "broker numeric observation", output=True)
    except ValueError:
        return None
    return text


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if (not isinstance(raw, bytes) or sha256_bytes(raw) != reference["sha256"]
            or len(raw) != reference["size_bytes"]):
        raise TradingAccountingError("retained accounting evidence is missing or differs in hash/size")
    return raw


def _linked(events, event_id, event_type, digest, cutoff):
    matches = [(index, event) for index, event in enumerate(events) if event.event_id == event_id]
    if len(matches) != 1:
        raise TradingAccountingError("accounting link is absent or ambiguous")
    index, event = matches[0]
    if event.event_type != event_type or event.source["source_sha256"] != digest:
        raise TradingAccountingError("accounting link has a different type or canonical source hash")
    if _time(event.recorded_at) > _time(cutoff):
        raise TradingAccountingError("linked accounting evidence postdates the report")
    return index, event


def _retry_prefix(document, events):
    for index, event in enumerate(events):
        if event.event_type == ACCOUNTING_EVENT_TYPE and event.payload["accounting"]["accounting_id"] == document.accounting_id:
            if canonical_json_bytes(event.payload["accounting"]) != document.to_bytes():
                raise TradingAccountingError("accounting identity conflicts with changed input bytes")
            return events[:index]
    return events


def _activities(document, blobs):
    typed_raw = _blob(blobs, document.activities_evidence)
    activities = PaperActivitiesInput.from_bytes(typed_raw)
    reference = activities.provenance["source_evidence"]
    raw = _blob(blobs, reference)
    from .paper_activity_import import validate_activities_source
    try:
        validate_activities_source(activities, raw)
    except ValueError as exc:
        raise TradingAccountingError("activities do not reproduce retained source facts") from exc
    if activities.account_id != document.account_id or activities.mode != document.mode:
        raise TradingAccountingError("activities belong to another account or mode")
    if _time(activities.recorded_at) > _time(document.recorded_at):
        raise TradingAccountingError("activities were imported after the accounting report")
    if document.activities_evidence["path"] == reference["path"] and typed_raw != raw:
        raise TradingAccountingError("typed activities and original source evidence paths collide")
    return activities, {document.activities_evidence["path"]: typed_raw, reference["path"]: raw}


def _context_unbounded(document, events, blobs):
    si, start_event = _linked(events, document.start_snapshot_event_id, reconciliation.SNAPSHOT_EVENT_TYPE,
                              document.start_snapshot_sha256, document.recorded_at)
    start = BrokerSnapshotInput.from_mapping(start_event.payload["snapshot"])
    if reconciliation.build_snapshot_event(start, events[:si], blobs).to_bytes() != start_event.to_bytes():
        raise TradingAccountingError("starting snapshot does not reproduce source evidence")
    ri, end_event = _linked(events, document.end_reconciliation_event_id, reconciliation.RECONCILIATION_EVENT_TYPE,
                            document.end_reconciliation_sha256, document.recorded_at)
    end_input = TradingReconciliationInput.from_mapping(end_event.payload["reconciliation"])
    if reconciliation.build_reconciliation_event(end_input, events[:ri], blobs).to_bytes() != end_event.to_bytes():
        raise TradingAccountingError("ending reconciliation does not reproduce retained evidence")
    oi, ownership_event = _linked(events, document.ownership_event_id, reconciliation.OWNERSHIP_EVENT_TYPE,
                                  document.ownership_sha256, document.recorded_at)
    ownership = DeskOwnershipInput.from_mapping(ownership_event.payload["ownership"])
    if reconciliation.build_ownership_event(ownership, events[:oi], blobs).to_bytes() != ownership_event.to_bytes():
        raise TradingAccountingError("ownership does not reproduce retained evidence")
    if any(item.account_id != document.account_id or item.mode != document.mode for item in (start, end_input, ownership)):
        raise TradingAccountingError("linked accounting account or mode differs")
    if end_input.ownership_event_id != ownership_event.event_id or end_input.ownership_sha256 != document.ownership_sha256:
        raise TradingAccountingError("ending reconciliation has a different ownership declaration")
    end_snapshot_event = next((event for event in events[:ri] if event.event_id == end_input.broker_snapshot_event_id), None)
    if end_snapshot_event is None:
        raise TradingAccountingError("ending reconciliation snapshot is missing")
    end = BrokerSnapshotInput.from_mapping(end_snapshot_event.payload["snapshot"])
    if _time(start.capture_window["completed_at"]) > _time(end.capture_window["started_at"]):
        raise TradingAccountingError("starting snapshot overlaps or postdates ending capture")
    later_end = [event for event in events if event.event_type == reconciliation.RECONCILIATION_EVENT_TYPE
                 and event.payload["reconciliation"]["account_id"] == document.account_id]
    if later_end and later_end[-1].event_id != end_event.event_id:
        raise TradingAccountingError("accounting must bind the latest account reconciliation")
    activities, evidence = _activities(document, blobs)
    if (_time(activities.window["started_at"]) != _time(start.capture_window["completed_at"])
            or _time(activities.window["ended_at"]) != _time(end.capture_window["completed_at"])):
        raise TradingAccountingError("activity coverage must exactly span the starting/ending capture cutoffs")
    runtime = {"schema_version": "blackpod.runtime_export.v1", "events": [], "profiles": {}}
    if end_input.runtime_evidence is not None:
        runtime = reconciliation.verified_runtime_capture(_blob(blobs, end_input.runtime_evidence))
    attempts = reconciliation.runtime_attempts(runtime, document.account_id, document.mode)
    for prior_event in events:
        if prior_event.event_type != ACCOUNTING_EVENT_TYPE:
            continue
        prior_input = TradingAccountingInput.from_mapping(prior_event.payload["accounting"])
        prior_activities = PaperActivitiesInput.from_bytes(_blob(blobs, prior_input.activities_evidence))
        if prior_activities.activity_set_id == activities.activity_set_id and prior_activities.to_bytes() != activities.to_bytes():
            raise TradingAccountingError("activity set identity conflicts with changed retained input bytes")
    previous = [event for event in events if event.event_type == ACCOUNTING_EVENT_TYPE
                and event.payload["accounting"]["account_id"] == document.account_id
                and event.payload["accounting"]["mode"] == document.mode]
    if (document.prior_accounting_event_id is None) != (not previous):
        raise TradingAccountingError("accounting update must link the latest immutable account report")
    if previous:
        prior = previous[-1]
        if prior.event_id != document.prior_accounting_event_id:
            raise TradingAccountingError("accounting cannot branch from an older report")
        old_input = TradingAccountingInput.from_mapping(prior.payload["accounting"])
        if any(getattr(old_input, field) != getattr(document, field) for field in
               ("start_snapshot_event_id", "start_snapshot_sha256", "ownership_event_id", "ownership_sha256")):
            raise TradingAccountingError("accounting continuation cannot rewrite baseline or ownership")
        if _time(document.recorded_at) < _time(old_input.recorded_at):
            raise TradingAccountingError("accounting update timestamp cannot retreat")
        old_activities, _ = _activities(old_input, blobs)
        from .contracts.mission_request import parse_strict_json_object_bytes
        old_source = parse_strict_json_object_bytes(_blob(blobs, old_activities.provenance["source_evidence"]))
        new_source = parse_strict_json_object_bytes(_blob(blobs, activities.provenance["source_evidence"]))
        new_raw_rows = {row["id"]: canonical_json_bytes(row) for row in new_source["activities"]}
        if any(new_raw_rows.get(row["id"]) != canonical_json_bytes(row) for row in old_source["activities"]):
            raise TradingAccountingError("accounting update cannot change or omit retained original activity bytes")
        if _time(activities.window["ended_at"]) < _time(old_activities.window["ended_at"]):
            raise TradingAccountingError("activity coverage cutoff cannot retreat")
        for key in ("fills", "fees"):
            new_rows = {row["activity_id"]: row for row in getattr(activities, key)}
            for row in getattr(old_activities, key):
                if new_rows.get(row["activity_id"]) != row:
                    raise TradingAccountingError("accounting update cannot drop or rewrite a retained activity")
        same_cutoff = _time(activities.window["ended_at"]) == _time(old_activities.window["ended_at"])
        if same_cutoff and old_activities.coverage["fills_complete"] and not activities.coverage["fills_complete"]:
            raise TradingAccountingError("fill completeness cannot retreat")
        if same_cutoff and old_activities.coverage["fees_complete"] and not activities.coverage["fees_complete"]:
            raise TradingAccountingError("fee completeness cannot retreat")
        if set(old_activities.coverage["scope_order_ids"]) - set(activities.coverage["scope_order_ids"]):
            raise TradingAccountingError("declared activity scope cannot drop retained orders")
    return start, end, ownership, end_event.payload["result"], attempts, activities, evidence


def _calculation_context():
    return Context(prec=PRECISION_POLICY["calculation_precision"], rounding=ROUND_HALF_EVEN,
                   Emin=-999999, Emax=999999, capitals=1, clamp=0, flags=[],
                   traps=[DivisionByZero, InvalidOperation, Overflow])


def _context(document, events, blobs):
    with localcontext(_calculation_context()):
        return _context_unbounded(document, events, blobs)


def _split(total, weights):
    """Deterministically conserve one signed fee over ordered positive quantities."""
    if not weights:
        return []
    remaining, denominator, result = total, sum(weights, ZERO), []
    for index, weight in enumerate(weights):
        amount = remaining if index == len(weights) - 1 else (total * weight / denominator).quantize(FEE_QUANTUM, rounding=ROUND_HALF_EVEN)
        # Tiny fees split over many fills must not round into an invented
        # negative residual (or turn a rebate into an expense).
        amount = max(ZERO, min(remaining, amount)) if total >= 0 else min(ZERO, max(remaining, amount))
        result.append(amount)
        remaining -= amount
    return result


def _fee_allocations(activities, fills, orders):
    indexed = {fill["activity_id"]: fill for fill in fills}
    by_order = defaultdict(list)
    for fill in fills:
        by_order[fill["order_id"]].append(fill)
    amounts = {identity: ZERO for identity in indexed}
    matched, unmatched = [], []
    for fee in sorted(activities.fees, key=lambda row: (row["occurred_at"], row["activity_id"])):
        selected = []
        if fee["fill_activity_id"] is not None:
            fill = indexed.get(fee["fill_activity_id"])
            if fill is not None and (fee["order_id"] is None or fee["order_id"] == fill["order_id"]):
                selected = [fill]
        elif fee["order_id"] is not None:
            selected = by_order.get(fee["order_id"], [])
        if selected and fee["symbol"] is not None and any(fill["symbol"] != fee["symbol"] for fill in selected):
            selected = []
        if not selected:
            unmatched.append({"activity_id": fee["activity_id"], "reason_code": "FEE_HAS_NO_EXACT_ATTRIBUTED_FILL"})
            continue
        allocations = _split(_number(fee["amount"]), [_number(fill["qty"]) for fill in selected])
        for fill, amount in zip(selected, allocations):
            amounts[fill["activity_id"]] += amount
        matched.append({"activity_id": fee["activity_id"], "fill_activity_id": fee["fill_activity_id"],
                        "order_id": fee["order_id"], "amount": fee["amount"],
                        "allocated_fill_ids": [fill["activity_id"] for fill in selected]})
    return amounts, matched, unmatched


def _compute(document, start, end, ownership, end_result, attempts, activities):
    issues, fee_issues = set(), set()
    owned = set(ownership.desks["TRADING"])
    start_positions = {item["symbol"]: _number(item["qty"]) for item in start.positions}
    start_open = [item for item in start.orders if item["status"] not in reconciliation.TERMINAL and item["symbol"] in owned]
    if not start.completeness["positions_complete"] or not start.completeness["open_orders_complete"]:
        issues.add("STARTING_BOOK_INCOMPLETE")
    if any(start_positions.get(symbol, ZERO) != 0 for symbol in owned) or start_open:
        issues.add("STARTING_TRADING_BOOK_NOT_FLAT")
    if not activities.coverage["fills_complete"]:
        issues.add("FILL_ACTIVITY_COVERAGE_INCOMPLETE")
    if not end.completeness["positions_complete"]:
        issues.add("ENDING_POSITIONS_INCOMPLETE")
    if not end.completeness["open_orders_complete"] or not end.completeness["tracked_orders_complete"]:
        issues.add("ENDING_ORDER_COVERAGE_INCOMPLETE")
    if end_result["restart_barrier"]["entries_blocked"]:
        issues.add("EXECUTION_RECONCILIATION_PENDING")
    orders = {item["id"]: item for item in end.orders}
    classified = {item["order_id"]: item for item in end_result["orders"]}
    attempts_by_hash = {item["attempt_sha256"]: item for item in attempts}
    scope = set(activities.coverage["scope_order_ids"])
    fills, unmatched, activity_totals, activity_values = [], [], defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    all_fills = sorted(activities.fills, key=lambda row: (_time(row["occurred_at"]), row["activity_id"]))
    for fill in all_fills:
        activity_totals[fill["order_id"]] += _number(fill["qty"])
        activity_values[fill["order_id"]] += _number(fill["qty"]) * _number(fill["price"])
        order = orders.get(fill["order_id"])
        attribution = classified.get(fill["order_id"])
        reason = None
        attempt = None if attribution is None else attempts_by_hash.get(attribution["matched_attempt_sha256"])
        if fill["order_id"] not in scope:
            reason = "FILL_OUTSIDE_DECLARED_ACTIVITY_SCOPE"
        elif order is None:
            reason = "EXACT_BROKER_ORDER_NOT_OBSERVED"
        elif order["symbol"] != fill["symbol"] or order["side"] != fill["side"]:
            reason = "FILL_DIFFERS_FROM_EXACT_BROKER_ORDER"
        elif attribution is None or attempt is None:
            reason = "FILL_HAS_NO_EXACT_EXECUTION_ATTEMPT"
        elif (fill["symbol"] not in owned or attribution["desk"] != "TRADING"
              or _time(attempt["recorded_at"]) < _time(ownership.recorded_at)
              or order["submitted_at"] is None or _time(order["submitted_at"]) < _time(ownership.recorded_at)):
            reason = "EXECUTION_PREDATES_TRADING_OWNERSHIP_OR_IS_UNCLASSIFIED"
        elif _time(attempt["recorded_at"]) < _time(start.capture_window["completed_at"]):
            reason = "EXECUTION_ATTEMPT_PREDATES_FLAT_BASELINE"
        elif (_time(fill["occurred_at"]) < _time(attempt["recorded_at"])
              or _time(fill["occurred_at"]) < _time(order["submitted_at"])):
            reason = "FILL_PREDATES_EXACT_EXECUTION_ATTEMPT"
        elif any(order[field] is not None for field in ("replaces", "replaced_by", "parent_order_id")) or order["leg_ids"]:
            reason = "REPLACEMENT_OR_LEG_ATTRIBUTION_UNSUPPORTED"
        if reason is not None:
            issues.add(reason)
            unmatched.append({"activity_id": fill["activity_id"], "order_id": fill["order_id"], "reason_code": reason})
        else:
            fills.append({**fill, "attempt_sha256": attempt["attempt_sha256"],
                          "gross_value": _text(_number(fill["qty"]) * _number(fill["price"])), "fee_amount": None})
    # The latest broker position can conceal an earlier receipt claiming a
    # nonexistent holding. Check every admitted attempt against this period's
    # source fills and flat beginning, rather than trusting only the last one.
    # Prefix sums keep this bounded replay O((fills + attempts) log fills).
    timelines, prefixes, simultaneous = defaultdict(list), {}, defaultdict(set)
    for fill in all_fills:
        at = _time(fill["occurred_at"])
        timelines[fill["symbol"]].append((at, _number(fill["qty"]) * (1 if fill["side"] == "buy" else -1)))
        simultaneous[(fill["symbol"], at)].add(fill["order_id"])
    for symbol, timeline in timelines.items():
        total, sums = ZERO, [ZERO]
        for _, quantity in timeline:
            total += quantity
            sums.append(total)
        prefixes[symbol] = ([at for at, _ in timeline], sums)
    exact_order_ids = defaultdict(set)
    for fill in fills:
        exact_order_ids[fill["attempt_sha256"]].add(fill["order_id"])
    for attempt in attempts:
        at = _time(attempt["recorded_at"])
        if attempt["symbol"] not in owned or at < _time(start.capture_window["completed_at"]):
            continue
        if attempt["prior_qty"] is None:
            issues.add("EXECUTION_RECEIPT_PRIOR_POSITION_UNAVAILABLE")
            continue
        own_ids = exact_order_ids[attempt["attempt_sha256"]] | {attempt["order_id"]}
        times, sums = prefixes.get(attempt["symbol"], ([], [ZERO]))
        before = sums[bisect_left(times, at)]
        if simultaneous[(attempt["symbol"], at)] - own_ids:
            issues.add("AMBIGUOUS_PRIOR_POSITION_AT_ATTEMPT")
        elif before != _number(attempt["prior_qty"]):
            issues.add("EXECUTION_RECEIPT_PRIOR_POSITION_DIFFERS_FROM_SOURCE_FILLS")
    order_checks = []
    # All filled/new orders for this desk in the interval must be in the source
    # coverage. A scope list is a declaration, never a substitute for observations.
    relevant_orders = {identity for identity, order in orders.items()
                       if order["symbol"] in owned and order["submitted_at"] is not None
                       and _time(order["submitted_at"]) >= _time(start.capture_window["completed_at"])}
    if relevant_orders - scope:
        issues.add("ACTIVITY_SCOPE_OMITS_TRADING_ORDERS")
    for identity in sorted(scope | set(activity_totals)):
        order = orders.get(identity)
        observed = None if order is None else _number(order["filled_qty"])
        actual = activity_totals[identity]
        quantity_matches = observed is not None and actual == observed
        broker_value = (ZERO if observed == 0 else
                        observed * _number(order["filled_avg_price"]) if observed is not None and order["filled_avg_price"] is not None else None)
        observed_text, broker_value_text = _bounded_observation(observed), _bounded_observation(broker_value)
        if (observed is not None and observed_text is None) or (broker_value is not None and broker_value_text is None):
            issues.add("UNSUPPORTED_BROKER_NUMERIC_PRECISION")
        price_matches = broker_value_text is not None and broker_value == activity_values[identity]
        order_checks.append({"order_id": identity, "activity_filled_qty": _text(actual),
                             "broker_filled_qty": observed_text,
                             "activity_gross_value": _text(activity_values[identity]),
                             "broker_gross_value": broker_value_text,
                             "price_matches": price_matches, "matches": quantity_matches and price_matches})
        if not quantity_matches:
            issues.add("INDIVIDUAL_FILLS_DO_NOT_MATCH_CUMULATIVE_ORDER_QUANTITY")
        if not price_matches:
            issues.add("BROKER_AVERAGE_PRICE_MISSING" if broker_value is None else "INDIVIDUAL_FILL_VALUE_DIFFERS_FROM_BROKER_AVERAGE")
    fees, matched_fees, unmatched_fees = _fee_allocations(activities, fills, orders)
    fees_complete = activities.coverage["fees_complete"] and not unmatched_fees
    if not activities.coverage["fees_complete"]:
        fee_issues.add("FEES_INCOMPLETE")
    if unmatched_fees:
        fee_issues.add("UNALLOCATED_FEES")
    grouped = defaultdict(list)
    for fill in fills:
        grouped[(fill["symbol"], fill["occurred_at"])].append(fill)
    for group in grouped.values():
        if len(group) > 1:
            signatures = {(fill["side"], _number(fill["price"]), fees[fill["activity_id"]] / _number(fill["qty"])) for fill in group}
            if len(signatures) > 1:
                issues.add("AMBIGUOUS_EXECUTION_ORDER")
    lots, closed, expected = defaultdict(list), [], defaultdict(lambda: ZERO)
    for fill in fills:
        quantity, price = _number(fill["qty"]), _number(fill["price"])
        if fill["side"] == "buy":
            lots[fill["symbol"]].append({"lot_id": _identity("fill-lot", {"account_id": document.account_id, "activity_id": fill["activity_id"]}),
                "buy_activity_id": fill["activity_id"], "symbol": fill["symbol"], "opened_at": fill["occurred_at"],
                "original_qty": quantity, "remaining_qty": quantity, "unit_price": price, "remaining_fee": fees[fill["activity_id"]]})
            expected[fill["symbol"]] += quantity
        else:
            if quantity > expected[fill["symbol"]]:
                issues.add("LONG_ONLY_SELL_EXCEEDS_SOURCE_BACKED_LOTS")
                continue
            remaining, slices = quantity, []
            for lot in lots[fill["symbol"]]:
                if lot["remaining_qty"] == 0:
                    continue
                part = min(remaining, lot["remaining_qty"])
                entry_fee = (lot["remaining_fee"] if part == lot["remaining_qty"] else
                             (lot["remaining_fee"] * part / lot["remaining_qty"]).quantize(FEE_QUANTUM, rounding=ROUND_HALF_EVEN))
                slices.append((lot, part, entry_fee))
                remaining -= part
                if remaining == 0:
                    break
            exit_allocations = _split(fees[fill["activity_id"]], [part for _, part, _ in slices])
            for (lot, part, entry_fee), exit_fee in zip(slices, exit_allocations):
                cost, proceeds = part * lot["unit_price"], part * price
                closed.append({"lot_id": lot["lot_id"], "buy_activity_id": lot["buy_activity_id"], "sell_activity_id": fill["activity_id"],
                    "symbol": fill["symbol"], "qty": _text(part), "buy_price": _text(lot["unit_price"]), "sell_price": _text(price),
                    "gross_cost": _text(cost), "gross_proceeds": _text(proceeds), "gross_pnl": _text(proceeds - cost),
                    "allocated_entry_fees": _text(entry_fee) if fees_complete else None,
                    "allocated_exit_fees": _text(exit_fee) if fees_complete else None,
                    "net_pnl": _text(proceeds - cost - entry_fee - exit_fee) if fees_complete else None})
                lot["remaining_qty"] -= part
                lot["remaining_fee"] -= entry_fee
            expected[fill["symbol"]] -= quantity
    observed_positions = {item["symbol"]: _number(item["qty"]) for item in end.positions}
    positions = []
    for symbol in sorted(owned | set(expected)):
        observed = observed_positions.get(symbol, ZERO) if end.completeness["positions_complete"] else observed_positions.get(symbol)
        observed_text = _bounded_observation(observed)
        if observed is not None and observed_text is None:
            issues.add("UNSUPPORTED_BROKER_NUMERIC_PRECISION")
        match = observed_text is not None and observed == expected[symbol]
        positions.append({"symbol": symbol, "expected_qty": _text(expected[symbol]),
                          "observed_qty": observed_text, "matches": match})
        if not match:
            issues.add("SOURCE_BACKED_LOTS_DO_NOT_MATCH_ENDING_POSITION")
    open_lots = [{"lot_id": lot["lot_id"], "buy_activity_id": lot["buy_activity_id"], "symbol": lot["symbol"], "opened_at": lot["opened_at"],
                  "original_qty": _text(lot["original_qty"]), "remaining_qty": _text(lot["remaining_qty"]), "unit_price": _text(lot["unit_price"]),
                  "gross_cost": _text(lot["remaining_qty"] * lot["unit_price"]),
                  "allocated_entry_fees": _text(lot["remaining_fee"]) if fees_complete else None}
                 for symbol in sorted(lots) for lot in lots[symbol] if lot["remaining_qty"] > 0]
    execution = bool(all_fills) or end_result["execution_observed"]
    attributable = bool(fills)
    status = ("PENDING" if issues else "NO_EXECUTION_OBSERVED" if not execution
              else "RECONCILED" if fees_complete else "GROSS_RECONCILED_FEES_PENDING")
    proof = status in {"RECONCILED", "GROSS_RECONCILED_FEES_PENDING"} and attributable
    gross = sum((_number(row["gross_pnl"]) for row in closed), ZERO) if proof and closed else None
    closed_fees = sum((_number(row["allocated_entry_fees"]) + _number(row["allocated_exit_fees"]) for row in closed), ZERO) if proof and fees_complete and closed else None
    open_fees = sum((_number(row["allocated_entry_fees"]) for row in open_lots), ZERO) if proof and fees_complete else None
    net = gross - closed_fees if gross is not None and closed_fees is not None else None
    if not proof:
        for row in closed:
            row["gross_pnl"] = row["net_pnl"] = None
    for fill in fills:
        fill["fee_amount"] = _text(fees[fill["activity_id"]]) if fees_complete else None
    return {"status": status, "accounting_method": "FIFO_LONG_ONLY", "currency": "USD", "precision_policy": dict(PRECISION_POLICY),
        "start_snapshot_event_id": document.start_snapshot_event_id, "end_reconciliation_event_id": document.end_reconciliation_event_id,
        "ownership_event_id": document.ownership_event_id, "activities_sha256": document.activities_evidence["sha256"],
        "matched_fills": fills, "unmatched_fills": unmatched, "matched_fees": matched_fees, "unmatched_fees": unmatched_fees,
        "open_lots": open_lots, "closed_lots": closed, "positions": positions, "order_checks": order_checks,
        "totals": {"buy_gross": _text(sum((_number(row["gross_value"]) for row in fills if row["side"] == "buy"), ZERO)),
                   "sell_gross": _text(sum((_number(row["gross_value"]) for row in fills if row["side"] == "sell"), ZERO)),
                   "gross_realized_pnl": None if gross is None else _text(gross),
                   "allocated_closed_fees": None if closed_fees is None else _text(closed_fees),
                   "allocated_open_fees": None if open_fees is None else _text(open_fees),
                   "net_realized_pnl": None if net is None else _text(net)},
        "execution_observed": execution, "attributable_execution_observed": attributable, "fees_complete": fees_complete,
        "realized_trade_pnl": None if net is None else _text(net), "reason_codes": sorted(issues | fee_issues),
        "limitations": list(ACCOUNTING_LIMITATIONS), "provider_verified": False, "ownership_authenticated": False,
        "execution_authority_granted": False, "readiness": False, "authority": document.authority}


def assess_accounting(document: TradingAccountingInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    with localcontext(_calculation_context()):
        start, end, ownership, result, attempts, activities, _ = _context(document, events, blobs or {})
        return _compute(document, start, end, ownership, result, attempts, activities)


def evidence_for_accounting(document: TradingAccountingInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    *_, evidence = _context(document, events, blobs or {})
    if ACCOUNTING_EVIDENCE_PATH in evidence and evidence[ACCOUNTING_EVIDENCE_PATH] != document.to_bytes():
        raise TradingAccountingError("accounting evidence path collides with retained activities")
    return {ACCOUNTING_EVIDENCE_PATH: document.to_bytes(), **evidence}


def build_accounting_event(document: TradingAccountingInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    evidence = evidence_for_accounting(document, events, blobs)
    decision_id = _identity("journal-decision", {"kind": ACCOUNTING_SOURCE_KIND, "account_id": document.account_id, "mode": document.mode})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v7",
        "event_id": _identity("journal-event", {"decision_id": decision_id, "event_type": ACCOUNTING_EVENT_TYPE, "accounting_id": document.accounting_id}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": ACCOUNTING_EVENT_TYPE, "recorded_at": document.recorded_at,
        "source": {"kind": ACCOUNTING_SOURCE_KIND, "accounting_id": document.accounting_id, "source_sha256": sha256_bytes(document.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"accounting": document.to_dict(), "result": assess_accounting(document, events, blobs)}})


def validate_accounting_event(event, previous_events, blobs):
    if event.event_type != ACCOUNTING_EVENT_TYPE:
        raise TradingAccountingError("unsupported accounting event")
    document = TradingAccountingInput.from_mapping(event.payload["accounting"])
    if build_accounting_event(document, previous_events, blobs).to_bytes() != event.to_bytes():
        raise TradingAccountingError("accounting event does not reproduce retained evidence and immutable prefix")
