"""Pure PAPER evidence projection and conservative restart reconciliation.

Nothing here contacts a broker, reads a filesystem, submits an order, or grants
authority. Provider provenance and desk declarations remain unauthenticated.
Known orders are correlated by exact retained identifiers, never by proximity
in time, symbol, or an observed position. Cumulative fills are observations;
they are not transactions to add together or realized trade profit.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.trading_reconciliation import BrokerSnapshotInput, DeskOwnershipInput, TradingReconciliationInput
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes

SNAPSHOT_EVENT_TYPE = "PAPER_BROKER_SNAPSHOT_RECORDED"
OWNERSHIP_EVENT_TYPE = "TRADING_DESK_OWNERSHIP_RECORDED"
RECONCILIATION_EVENT_TYPE = "TRADING_EXECUTION_RECONCILED"
TERMINAL = frozenset({"filled", "canceled", "expired", "rejected", "replaced"})


class TradingReconciliationError(ValueError):
    """Evidence or an append-only relationship cannot be reproduced."""


def _time(value):
    return parse_rfc3339(value, "reconciliation timestamp")


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _json(raw):
    if not isinstance(raw, bytes):
        raise TradingReconciliationError("retained source must be bytes")
    try:
        return parse_strict_json_object_bytes(raw)
    except (ValueError, RecursionError) as exc:
        raise TradingReconciliationError("retained source is not bounded strict JSON") from exc


def _blob(blobs, digest):
    raw = blobs.get(digest)
    if not isinstance(raw, bytes) or sha256_bytes(raw) != digest:
        raise TradingReconciliationError("retained source hash mismatch or missing evidence")
    return raw


def _linked(events, event_id, kind, cutoff):
    matching = [item for item in events if item.event_id == event_id]
    if len(matching) != 1 or matching[0].event_type != kind:
        raise TradingReconciliationError("linked event has missing, ambiguous or wrong identity")
    event = matching[0]
    if _time(event.recorded_at) > _time(cutoff):
        raise TradingReconciliationError("linked evidence postdates the input")
    return event


def _active(events, kind, account_id, cutoff, mode="PAPER"):
    candidates = [item for item in events if item.event_type == kind
                  and item.payload[{SNAPSHOT_EVENT_TYPE: "snapshot", OWNERSHIP_EVENT_TYPE: "ownership", RECONCILIATION_EVENT_TYPE: "reconciliation"}[kind]].get("account_id") == account_id
                  and item.payload[{SNAPSHOT_EVENT_TYPE: "snapshot", OWNERSHIP_EVENT_TYPE: "ownership", RECONCILIATION_EVENT_TYPE: "reconciliation"}[kind]].get("mode") == mode]
    if candidates and _time(candidates[-1].recorded_at) > _time(cutoff):
        raise TradingReconciliationError("account event timestamp cannot retreat")
    return candidates[-1] if candidates else None


def _flatten_orders(orders):
    result = []
    for order in orders:
        result.append(order)
        result.extend(_flatten_orders(order.get("legs") or []))
    return result


def verified_runtime_capture(raw: bytes) -> dict:
    """Verify a retained ledger prefix and immutable profiles without disk reads.

    This verifies local hashes and the declared account. It cannot attest who
    wrote a completely rewritten chain or prove a broker accepted an attempt.
    """
    capture = _json(raw)
    if set(capture) != {"schema_version", "events", "profiles"} or capture["schema_version"] != "blackpod.runtime_export.v1":
        raise TradingReconciliationError("unsupported runtime capture")
    if not isinstance(capture["events"], list) or len(capture["events"]) > 100000 or not isinstance(capture["profiles"], dict):
        raise TradingReconciliationError("runtime capture exceeds bounds")
    from .auto_trading_runtime import validate_profile, validate_execution_receipt_v2, _identifier as runtime_identifier
    for digest, profile in capture["profiles"].items():
        try:
            validate_profile(profile, verify_files=False)
        except (ValueError, TypeError, KeyError) as exc:
            raise TradingReconciliationError("retained runtime profile is structurally invalid") from exc
        if sha256_bytes(canonical_json_bytes(profile)) != digest:
            raise TradingReconciliationError("runtime profile identity mismatch")
    previous, sessions, actions = None, {}, set()
    for sequence, event in enumerate(capture["events"], 1):
        if not isinstance(event, dict) or set(event) != {"schema_version", "sequence", "previous_sha256", "event_sha256", "kind", "payload"}:
            raise TradingReconciliationError("invalid runtime event shape")
        unsigned = {key: value for key, value in event.items() if key != "event_sha256"}
        if (event["schema_version"] != "blackpod.auto_trading_runtime_event.v1"
                or type(event["sequence"]) is not int or event["sequence"] != sequence or event["previous_sha256"] != previous
                or event["event_sha256"] != sha256_bytes(canonical_json_bytes(unsigned))):
            raise TradingReconciliationError("runtime prefix hash or sequence mismatch")
        payload = event["payload"]
        if not isinstance(payload, dict) or not isinstance(event["kind"], str):
            raise TradingReconciliationError("runtime payload is not an object")
        _time(payload.get("recorded_at"))
        if event["kind"] == "CONTROL":
            if set(payload) != {"action_id", "session_id", "profile_sha256", "entries_enabled", "recorded_at", "operator_id"}:
                raise TradingReconciliationError("invalid runtime control")
            for field in ("action_id", "session_id", "operator_id"):
                runtime_identifier(payload[field], field)
            digest = payload["profile_sha256"]
            if (type(payload["entries_enabled"]) is not bool or payload["action_id"] in actions
                    or not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
                raise TradingReconciliationError("invalid runtime control")
            actions.add(payload["action_id"])
            if payload["entries_enabled"]:
                profile = capture["profiles"].get(payload["profile_sha256"])
                if profile is None or payload["session_id"] in sessions:
                    raise TradingReconciliationError("runtime startup lacks a unique retained profile")
                sessions[payload["session_id"]] = profile
        elif event["kind"] in {"WORKER_STATUS", "BROKER_GUARD"}:
            runtime_identifier(payload.get("session_id"), "session_id")
            profile = sessions.get(payload.get("session_id"))
            if profile is None or payload.get("mode") != profile["mode"]:
                raise TradingReconciliationError("receipt lacks a matching startup mode")
            if event["kind"] == "WORKER_STATUS":
                allowed_fields = {"session_id", "mode", "recorded_at", "state", "error_type", "manual_position_check_required", "auto_restart_enabled"}
                state = payload.get("state")
                if (set(payload) - allowed_fields or not isinstance(state, str)
                        or state not in {"STARTING", "RUNNING", "DRAINING", "STOPPED", "FAILED", "START_FAILED"}
                        or payload.get("auto_restart_enabled", False) is not False):
                    raise TradingReconciliationError("invalid worker lifecycle receipt")
                states = [item["payload"]["state"] for item in capture["events"][:sequence - 1]
                          if item["kind"] == "WORKER_STATUS" and item["payload"]["session_id"] == payload["session_id"]]
                transitions = {None: {"STARTING", "START_FAILED"}, "STARTING": {"RUNNING", "FAILED"},
                               "RUNNING": {"DRAINING", "STOPPED", "FAILED"}, "DRAINING": {"DRAINING", "STOPPED", "FAILED"}}
                if state not in transitions.get(states[-1] if states else None, set()):
                    raise TradingReconciliationError("worker lifecycle cannot restart or skip required states")
            else:
                fields = {"session_id", "mode", "recorded_at", "profile_id", "domain", "account_mode", "symbol", "side", "qty", "outcome", "reason_code", "order_id", "capital_authorization_id"}
                v2 = payload.get("schema_version") == "blackpod.trading_execution_receipt.v2"
                if v2:
                    fields |= {"schema_version", "account_id", "attempt_id", "prior_qty", "client_order_id"}
                    validate_execution_receipt_v2(payload, profile, capture["events"][:sequence - 1])
                if (not isinstance(payload.get("symbol"), str) or not isinstance(payload.get("qty"), str)
                        or len(payload["qty"]) > 128 or not isinstance(payload.get("reason_code"), str)
                        or len(payload["reason_code"]) > 256
                        or (payload.get("order_id") is not None and (not isinstance(payload["order_id"], str) or len(payload["order_id"]) > 128))
                        or not isinstance(payload.get("side"), str) or not isinstance(payload.get("outcome"), str)):
                    raise TradingReconciliationError("broker receipt scalar types or lengths differ from runtime contract")
                if (set(payload) != fields or payload["profile_id"] != profile["profile_id"]
                        or payload["domain"] != "TRADING" or payload["account_mode"] != profile["mode"]
                        or payload["capital_authorization_id"] != profile["capital_authorization_id"]
                        or payload["outcome"] not in ({"ATTEMPT", "SUBMITTED", "BLOCKED", "AMBIGUOUS"} if v2 else {"ATTEMPT", "SUBMITTED", "BLOCKED"})
                        or payload["side"] not in {"buy", "sell", "close"}):
                    raise TradingReconciliationError("broker receipt differs from retained profile")
                if v2 and (payload["account_id"] != profile["account_id"] or
                           (payload["outcome"] != "BLOCKED" and (not isinstance(payload["attempt_id"], str) or not payload["attempt_id"]))):
                    raise TradingReconciliationError("v2 execution receipt identity is missing or mismatched")
                if v2:
                    from .contracts.trading_reconciliation import decimal_text
                    if payload["prior_qty"] is not None:
                        decimal_text(payload["prior_qty"], "receipt.prior_qty")
                    if payload["outcome"] in {"ATTEMPT", "SUBMITTED", "AMBIGUOUS"} and payload["prior_qty"] is None:
                        raise TradingReconciliationError("admitted v2 receipt lacks prior position")
                    if payload["client_order_id"] is not None and (not isinstance(payload["client_order_id"], str) or not payload["client_order_id"]):
                        raise TradingReconciliationError("client order identity must be a string or null")
                if payload["outcome"] in {"ATTEMPT", "SUBMITTED"}:
                    if payload["symbol"] not in profile["symbols"]:
                        raise TradingReconciliationError("attempt targets an unowned native profile symbol")
                    try:
                        qty = Decimal(payload["qty"])
                        if not qty.is_finite() or qty <= 0:
                            raise ValueError
                    except Exception as exc:
                        raise TradingReconciliationError("runtime attempted quantity is invalid") from exc
                if payload["outcome"] == "SUBMITTED" and (not isinstance(payload["order_id"], str) or not payload["order_id"] or payload["order_id"] == "DRY-RUN"):
                    raise TradingReconciliationError("accepted receipt lacks exact broker identity")
        else:
            raise TradingReconciliationError("unknown runtime event kind")
        previous = event["event_sha256"]
    return capture


parse_runtime_capture = verified_runtime_capture


def runtime_attempts(capture: Mapping, account_id: str, mode="PAPER") -> list[dict]:
    """Correlate serialized legacy receipts; never search broker facts by symbol."""
    sessions, pending, results, attempts_by_id = {}, {}, [], {}
    for event in capture["events"]:
        payload = event["payload"]
        if event["kind"] == "CONTROL" and payload["entries_enabled"]:
            profile = capture["profiles"][payload["profile_sha256"]]
            if profile["account_id"] != account_id or profile["mode"] != mode:
                raise TradingReconciliationError("runtime control belongs to a different account or mode")
            sessions[payload["session_id"]] = profile
        if event["kind"] != "BROKER_GUARD":
            continue
        profile = sessions[payload["session_id"]]
        if profile["account_id"] != account_id or profile["mode"] != mode:
            raise TradingReconciliationError("runtime evidence belongs to a different broker account or mode")
        key = payload["session_id"]
        if payload["outcome"] == "ATTEMPT":
            item = {"attempt_sha256": event["event_sha256"], "recorded_at": payload["recorded_at"],
                    "session_id": key, "symbol": payload["symbol"], "side": payload["side"], "qty": payload["qty"],
                    "order_id": None, "client_order_id": payload.get("client_order_id"),
                    "prior_qty": payload.get("prior_qty"), "attempt_id": payload.get("attempt_id")}
            if item["attempt_id"] is not None:
                if item["attempt_id"] in attempts_by_id:
                    raise TradingReconciliationError("durable attempt identity was reused")
                attempts_by_id[item["attempt_id"]] = item
            results.append(item)
            pending.setdefault(key, []).append(item)
        elif payload["outcome"] == "SUBMITTED":
            candidates = ([attempts_by_id[payload["attempt_id"]]] if payload.get("attempt_id") in attempts_by_id
                          else [] if "attempt_id" in payload else pending.get(key, []))
            if len(candidates) != 1 or any(candidates[0][field] != payload[field] for field in ("symbol", "side", "qty")):
                raise TradingReconciliationError("submission cannot be uniquely linked to an earlier durable attempt")
            if candidates[0]["order_id"] is not None or candidates[0]["session_id"] != key:
                raise TradingReconciliationError("durable attempt cannot have multiple acceptance receipts")
            candidates[0]["order_id"] = payload["order_id"]
            if payload.get("client_order_id") is not None:
                if candidates[0]["client_order_id"] not in {None, payload["client_order_id"]}:
                    raise TradingReconciliationError("client order identity changed after attempt")
                candidates[0]["client_order_id"] = payload["client_order_id"]
            pending[key] = []
        elif payload["outcome"] == "AMBIGUOUS" and payload.get("attempt_id") in attempts_by_id:
            # A returned identity is useful evidence even when persisting the
            # acceptance receipt failed. Only a later exact broker observation
            # can resolve it; this is never an instruction to submit again.
            original = attempts_by_id[payload["attempt_id"]]
            for field in ("order_id", "client_order_id"):
                observed = payload.get(field)
                if observed is not None:
                    if original[field] not in {None, observed}:
                        raise TradingReconciliationError("ambiguous result replaced a known broker identity")
                    original[field] = observed
    ids = [item["order_id"] for item in results if item["order_id"] is not None]
    if len(set(ids)) != len(ids):
        raise TradingReconciliationError("broker order identity is reused across attempts")
    return results


def durable_restart_barrier(runtime_capture: bytes | Mapping, orders=(), *, account_id: str, mode="PAPER", complete=False, positions=None) -> dict:
    """Never turn a missing order or lost acceptance into permission to retry.

    Only exact broker terminal observations resolve identified attempts. A
    replacement requires its linked successor and terminal chain. This helper
    does not start a process or create executable retry instructions.
    """
    raw = runtime_capture if isinstance(runtime_capture, bytes) else canonical_json_bytes(runtime_capture)
    capture = verified_runtime_capture(raw)
    attempts = runtime_attempts(capture, account_id, mode)
    flat = _flatten_orders(orders)
    indexed = {item["id"]: item for item in flat}
    if len(indexed) != len(flat):
        raise TradingReconciliationError("ambiguous broker order identities")
    unresolved = []
    quantities = None if positions is None else {item["symbol"]: Decimal(item["qty"]) for item in positions}
    latest = {item["symbol"]: item["attempt_sha256"] for item in attempts}
    for attempt in attempts:
        identity = attempt["order_id"]
        if identity is None and attempt["client_order_id"] is not None:
            identified = [item for item in flat if item.get("client_order_id") == attempt["client_order_id"]]
            if len(identified) > 1: raise TradingReconciliationError("ambiguous exact client order identity")
            if identified: identity = identified[0]["id"]
        order = indexed.get(identity)
        reason = None
        if identity is None:
            reason = "SUBMISSION_ACCEPTANCE_UNKNOWN"
        elif order is None:
            reason = "EXACT_ORDER_NOT_OBSERVED"
        elif order.get("symbol") != attempt["symbol"] or (attempt["side"] != "close" and order.get("side") != attempt["side"]):
            reason = "EXACT_ORDER_PARAMETERS_DIFFER"
        elif order.get("qty") is None or Decimal(order["qty"]) != Decimal(attempt["qty"]):
            reason = "EXACT_ORDER_QUANTITY_UNVERIFIED"
        elif order.get("status") == "filled" and Decimal(order["filled_qty"]) != Decimal(order["qty"]):
            reason = "FILLED_STATUS_QUANTITY_UNVERIFIED"
        elif not complete:
            reason = "BROKER_SNAPSHOT_INCOMPLETE"
        else:
            visited = set()
            while order.get("status") == "replaced":
                if order["id"] in visited:
                    reason = "REPLACEMENT_CHAIN_CYCLE"; break
                visited.add(order["id"])
                successor = indexed.get(order.get("replaced_by"))
                if successor is None or successor.get("replaces") != order["id"] or successor.get("symbol") != attempt["symbol"]:
                    reason = "REPLACEMENT_SUCCESSOR_UNVERIFIED"; break
                order = successor
            if reason is None and order.get("status") not in TERMINAL:
                reason = "ORDER_NOT_TERMINAL"
            if reason is None and quantities is not None and latest[attempt["symbol"]] == attempt["attempt_sha256"]:
                if attempt["prior_qty"] is None:
                    reason = "POSITION_BASELINE_NOT_RECORDED"
                elif order["id"] != identity:
                    reason = "REPLACEMENT_FILL_ATTRIBUTION_UNVERIFIED"
                else:
                    prior, filled = Decimal(attempt["prior_qty"]), Decimal(order["filled_qty"])
                    sign = 1 if attempt["side"] == "buy" or (attempt["side"] == "close" and prior < 0) else -1
                    if quantities.get(attempt["symbol"], Decimal(0)) != prior + sign * filled:
                        reason = "TERMINAL_FILL_NOT_REFLECTED_IN_POSITION"
        if reason:
            unresolved.append({"attempt_sha256": attempt["attempt_sha256"], "order_id": identity, "reason_code": reason})
    return {"entries_blocked": bool(unresolved), "unresolved_attempts": unresolved,
            "automatic_resubmission_enabled": False, "execution_authority_granted": False}


def normalize_broker_orders(values: Sequence[Mapping]) -> list[dict]:
    """Flatten selected provider fields; unexpected provider fields are dropped."""
    orders = []
    def flatten(item, parent=None):
        if not isinstance(item, Mapping):
            raise TradingReconciliationError("broker order is not an object")
        keys = ("id", "client_order_id", "symbol", "side", "status", "type", "time_in_force", "qty", "notional", "filled_qty", "filled_avg_price",
                "submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at", "failed_at", "replaced_at", "replaces", "replaced_by")
        order = {key: item.get(key) for key in keys}
        for field in ("submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at", "failed_at", "replaced_at"):
            value = order[field]
            if value is not None:
                try:
                    if not isinstance(value, str) or len(value) > 64 or "T" not in value:
                        raise ValueError
                    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if timestamp.tzinfo is None: raise ValueError
                    order[field] = timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                except (ValueError, OverflowError) as exc:
                    raise TradingReconciliationError("provider order timestamp is not timezone aware") from exc
        children = item.get("legs") or []
        if not isinstance(children, list) or len(children) > 500:
            raise TradingReconciliationError("broker order children exceed bounds")
        order.update(parent_order_id=parent, leg_ids=[leg["id"] for leg in children])
        orders.append(order)
        if len(orders) > 2000:
            raise TradingReconciliationError("broker order facts exceed bounds")
        for child in children: flatten(child, item["id"])
    for item in values: flatten(item)
    return orders


def probe_snapshot_facts(raw: bytes) -> dict:
    """Convert selected facts from a confirmed GET-only probe, preserving bytes.

    The caller supplies identity/provenance fields for the strict input. No
    historical orders or trades are inferred from the probe's OPEN-only query.
    """
    source = _json(raw)
    if source.get("schema_version") == "blackpod.paper_broker_capture.v1":
        if set(source) != {"schema_version", "probe", "tracked_order_ids", "tracked_order_requests", "tracked_orders", "capture_completed_at"}:
            raise TradingReconciliationError("composite paper capture has unknown or missing fields")
        facts = probe_snapshot_facts(canonical_json_bytes(source["probe"]))
        ids, requests, raw_orders = source["tracked_order_ids"], source["tracked_order_requests"], source["tracked_orders"]
        if (not isinstance(ids, list) or len(ids) > 500 or len(set(ids)) != len(ids)
                or not isinstance(requests, list) or not isinstance(raw_orders, list)
                or len(ids) != len(requests) or len(ids) != len(raw_orders)):
            raise TradingReconciliationError("tracked order request coverage is incomplete")
        last = facts["capture_window"]["completed_at"]
        indexed = {item["id"]: item for item in facts["orders"]}
        for identity, request, raw_order in zip(ids, requests, raw_orders):
            if (not isinstance(identity, str) or not isinstance(request, dict)
                    or set(request) != {"method", "path", "http_status", "started_at", "completed_at"}
                    or request["method"] != "GET" or request["path"] != "/v2/orders/" + identity or request["http_status"] != 200
                    or not isinstance(raw_order, dict) or raw_order.get("id") != identity
                    or _time(request["started_at"]) < _time(last) or _time(request["completed_at"]) < _time(request["started_at"])):
                raise TradingReconciliationError("tracked order does not match the exact successful request")
            last = request["completed_at"]
            for order in normalize_broker_orders([raw_order]):
                old = indexed.get(order["id"])
                if old is not None:
                    for key in ("symbol", "side", "qty", "type", "time_in_force", "client_order_id", "notional"):
                        if old[key] != order[key]: raise TradingReconciliationError("tracked order identity parameters changed")
                    if Decimal(order["filled_qty"]) < Decimal(old["filled_qty"]):
                        raise TradingReconciliationError("tracked order cumulative fill retreated")
                    if old["updated_at"] and order["updated_at"] and _time(order["updated_at"]) < _time(old["updated_at"]):
                        raise TradingReconciliationError("tracked order response retreated")
                    if old["parent_order_id"] is not None and order["parent_order_id"] is None:
                        order["parent_order_id"] = old["parent_order_id"]
                    if old["leg_ids"] and not order["leg_ids"]:
                        order["leg_ids"] = old["leg_ids"]
                indexed[order["id"]] = order
        if _time(source["capture_completed_at"]) < _time(last):
            raise TradingReconciliationError("composite capture predates exact order reads")
        facts["orders"] = list(indexed.values())
        facts["capture_window"]["completed_at"] = source["capture_completed_at"]
        facts["completeness"]["tracked_orders_complete"] = True
        return facts
    if (source.get("schema_version") != "blackpod.alpaca_paper_probe.v1" or source.get("result") != "CONFIRMED"
            or source.get("mode") != "PAPER" or source.get("paper_origin") != "https://paper-api.alpaca.markets"
            or source.get("complete") is not True or source.get("account_authenticated") is not True
            or source.get("account_identity_verified") is not True
            or source.get("snapshot_atomic") is not False
            or any(source.get(field) != 0 for field in ("orders_submitted", "orders_cancelled", "positions_closed"))):
        raise TradingReconciliationError("source is not a confirmed non-executing PAPER probe")
    expected_paths = ("/v2/account", "/v2/positions", "/v2/orders?status=open&limit=500&nested=true", "/v2/clock")
    requests = source.get("requests")
    if (not isinstance(requests, list) or len(requests) != 4
            or any(item.get("method") != "GET" or item.get("path") != path or item.get("http_status") != 200
                   or item.get("result") != "VERIFIED_SELECTED_FIELDS" for item, path in zip(requests, expected_paths))):
        raise TradingReconciliationError("probe endpoint evidence is incomplete")
    account = source["account"]
    normalized_account = {key: account.get(key) for key in ("status", "trading_blocked", "account_blocked", "currency", "equity", "cash", "buying_power")}
    positions = [{key: item.get(key) for key in ("symbol", "qty", "side", "market_value", "avg_entry_price", "current_price")} for item in source["positions"]]
    orders = normalize_broker_orders(source["open_orders"])
    return {"account_id": account["id"], "mode": "PAPER", "account": normalized_account,
            "positions": positions, "orders": orders,
            "capture_window": {"started_at": source["capture_started_at"], "completed_at": source["capture_completed_at"]},
            "completeness": {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": False}}


def snapshot_input_from_probe(raw: bytes, *, snapshot_id: str, evidence_path: str) -> BrokerSnapshotInput:
    facts = probe_snapshot_facts(raw)
    return BrokerSnapshotInput.from_mapping({"schema_version": "blackpod.paper_broker_snapshot.v1", "snapshot_id": snapshot_id,
        "captured_at": facts["capture_window"]["completed_at"], **facts,
        "capture_provenance": {"source_kind": "ALPACA_PAPER_GET_IMPORT", "origin": "https://paper-api.alpaca.markets",
            "source_evidence": {"path": evidence_path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
            "sequential_capture": True, "snapshot_atomic": False, "provider_verified": False},
        "authority": {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}})


def _snapshot_source(snapshot, blobs):
    reference = snapshot.capture_provenance["source_evidence"]
    raw = _blob(blobs, reference["sha256"])
    if len(raw) != reference["size_bytes"]:
        raise TradingReconciliationError("snapshot source byte length differs")
    if snapshot.capture_provenance["source_kind"] == "ALPACA_PAPER_GET_IMPORT":
        facts = probe_snapshot_facts(raw)
    else:
        source = _json(raw)
        if source.pop("schema_version", None) != "blackpod.paper_broker_fixture.v1":
            raise TradingReconciliationError("synthetic snapshot must retain explicitly labeled fixture facts")
        facts = source
    expected = {key: snapshot.to_dict()[key] for key in ("account_id", "mode", "account", "positions", "orders", "capture_window", "completeness")}
    if facts != expected:
        raise TradingReconciliationError("snapshot does not match retained selected broker facts")
    if _time(snapshot.captured_at) < _time(snapshot.capture_window["completed_at"]):
        raise TradingReconciliationError("snapshot identity predates completion of capture")
    return {reference["path"]: raw}


def _common_report(document):
    return {"execution_authority_granted": False, "readiness": False, "realized_trade_pnl": None,
            "authority": document.authority}


def assess_snapshot(snapshot: BrokerSnapshotInput, events=(), blobs=None) -> dict:
    events = _retry_prefix(snapshot, events, "snapshot", "snapshot_id")
    _snapshot_source(snapshot, blobs or {})
    previous = _active(events, SNAPSHOT_EVENT_TYPE, snapshot.account_id, snapshot.captured_at)
    if previous is not None:
        old = previous.payload["snapshot"]
        if _time(snapshot.capture_window["completed_at"]) < _time(old["capture_window"]["completed_at"]):
            raise TradingReconciliationError("broker capture cutoff cannot retreat")
        prior_orders = {}
        for known in events:
            if known.event_type == SNAPSHOT_EVENT_TYPE and known.payload["snapshot"]["account_id"] == snapshot.account_id:
                prior_orders.update({item["id"]: item for item in known.payload["snapshot"]["orders"]})
        for order in snapshot.orders:
            prior = prior_orders.get(order["id"])
            if prior is None: continue
            for key in ("symbol", "side", "type", "time_in_force", "client_order_id", "qty", "notional", "replaces", "parent_order_id"):
                if prior[key] != order[key]:
                    raise TradingReconciliationError("broker order identity changed immutable parameters")
            if Decimal(order["filled_qty"]) < Decimal(prior["filled_qty"]):
                raise TradingReconciliationError("cumulative fill quantity cannot retreat")
            if prior["status"] in TERMINAL and order["status"] != prior["status"]:
                raise TradingReconciliationError("terminal broker order cannot become a different state")
            if prior["updated_at"] and order["updated_at"] and _time(order["updated_at"]) < _time(prior["updated_at"]):
                raise TradingReconciliationError("broker order observation cannot retreat")
            if prior["replaced_by"] is not None and prior["replaced_by"] != order["replaced_by"]:
                raise TradingReconciliationError("broker replacement lineage changed")
    indexed = {item["id"]: item for item in snapshot.orders}
    for order in snapshot.orders:
        for key in ("submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at", "failed_at", "replaced_at"):
            if order[key] is not None and _time(order[key]) > _time(snapshot.capture_window["completed_at"]):
                raise TradingReconciliationError("broker order timestamp postdates the capture")
        if order["submitted_at"] and order["updated_at"] and _time(order["updated_at"]) < _time(order["submitted_at"]):
            raise TradingReconciliationError("broker order update predates submission")
        if order["status"] == "filled" and order["qty"] is not None and Decimal(order["filled_qty"]) != Decimal(order["qty"]):
            raise TradingReconciliationError("filled broker status requires the full declared quantity")
        visited, current = set(), order
        while current["replaced_by"] is not None and current["replaced_by"] in indexed:
            if current["id"] in visited:
                raise TradingReconciliationError("broker replacement cycle")
            visited.add(current["id"])
            successor = indexed[current["replaced_by"]]
            if successor["replaces"] != current["id"] or successor["symbol"] != current["symbol"] or successor["side"] != current["side"]:
                raise TradingReconciliationError("broker replacement link is inconsistent")
            current = successor
    return {"position_count": len(snapshot.positions), "order_count": len(snapshot.orders),
            "position_classifications": [{"symbol": item["symbol"], "desk": "UNCLASSIFIED"} for item in snapshot.positions],
            "order_classifications": [{"order_id": item["id"], "symbol": item["symbol"], "desk": "UNCLASSIFIED"} for item in snapshot.orders],
            "execution_observed": any(Decimal(item["filled_qty"]) > 0 for item in snapshot.orders),
            "provider_verified": False, **_common_report(snapshot)}


def _build(document, kind, id_field, payload_key, report_key, report, evidence, decision_key):
    digest = sha256_bytes(document.to_bytes())
    recorded_at = document.captured_at if kind == "PAPER_BROKER_SNAPSHOT" else document.recorded_at
    event_type = {"PAPER_BROKER_SNAPSHOT": SNAPSHOT_EVENT_TYPE, "TRADING_DESK_OWNERSHIP": OWNERSHIP_EVENT_TYPE,
                  "TRADING_EXECUTION_RECONCILIATION": RECONCILIATION_EVENT_TYPE}[kind]
    decision_id = _identity("journal-decision", decision_key)
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v6",
        "event_id": _identity("journal-event", {"decision_id": decision_id, "event_type": event_type, id_field: getattr(document, id_field)}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": event_type, "recorded_at": recorded_at,
        "source": {"kind": kind, id_field: getattr(document, id_field), "source_sha256": digest},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {payload_key: document.to_dict(), report_key: report},
    })


def _retry_prefix(document, events, key, id_field):
    """Replay an identical identity against its original immutable prefix."""
    for index, event in enumerate(events):
        if event.schema_version == "blackpod.decision_journal_event.v6" and key in event.payload:
            previous = event.payload[key]
            if previous[id_field] == getattr(document, id_field):
                if canonical_json_bytes(previous) != document.to_bytes():
                    raise TradingReconciliationError("retained input identity conflicts with changed bytes")
                return events[:index]
    return events


def evidence_for_snapshot(snapshot: BrokerSnapshotInput, events=(), blobs=None) -> dict[str, bytes]:
    return {"trading/snapshot.json": snapshot.to_bytes(), **_snapshot_source(snapshot, blobs or {})}


def build_snapshot_event(snapshot: BrokerSnapshotInput, events=(), blobs=None) -> JournalEvent:
    events = _retry_prefix(snapshot, events, "snapshot", "snapshot_id")
    evidence = evidence_for_snapshot(snapshot, events, blobs)
    return _build(snapshot, "PAPER_BROKER_SNAPSHOT", "snapshot_id", "snapshot", "assessment",
                  assess_snapshot(snapshot, events, blobs), evidence,
                  {"kind": "PAPER_BROKER_SNAPSHOT", "account_id": snapshot.account_id, "mode": snapshot.mode})


def _bound_snapshot(document, events, blobs):
    event = _linked(events, document.broker_snapshot_event_id, SNAPSHOT_EVENT_TYPE, document.recorded_at)
    snapshot = BrokerSnapshotInput.from_mapping(event.payload["snapshot"])
    if (snapshot.account_id != document.account_id or snapshot.mode != document.mode
            or event.source["source_sha256"] != document.broker_snapshot_sha256):
        raise TradingReconciliationError("snapshot account, mode or canonical hash differs")
    prefix = events[:next(index for index, item in enumerate(events) if item.event_id == event.event_id)]
    if build_snapshot_event(snapshot, prefix, blobs).to_bytes() != event.to_bytes():
        raise TradingReconciliationError("linked snapshot does not match retained source projection")
    latest = _active(events, SNAPSHOT_EVENT_TYPE, document.account_id, document.recorded_at)
    if latest is not None and latest.event_id != event.event_id:
        raise TradingReconciliationError("new decisions must bind the latest recorded broker capture")
    return snapshot, event


def _desk(symbol, ownership, observed_at=None):
    if ownership is None or (observed_at is not None and _time(observed_at) < _time(ownership.recorded_at)):
        return "UNCLASSIFIED"
    return next((desk for desk, symbols in ownership.desks.items() if symbol in symbols), "UNCLASSIFIED")


def assess_ownership(ownership: DeskOwnershipInput, events=(), blobs=None) -> dict:
    events = _retry_prefix(ownership, events, "ownership", "ownership_id")
    snapshot, _ = _bound_snapshot(ownership, events, blobs or {})
    previous = _active(events, OWNERSHIP_EVENT_TYPE, ownership.account_id, ownership.recorded_at)
    if (ownership.supersedes_event_id is None) != (previous is None) or (previous is not None and ownership.supersedes_event_id != previous.event_id):
        raise TradingReconciliationError("ownership amendment must supersede the active account declaration")
    old = {} if previous is None else {symbol: desk for desk, symbols in previous.payload["ownership"]["desks"].items() for symbol in symbols}
    new = {symbol: desk for desk, symbols in ownership.desks.items() for symbol in symbols}
    released = sorted(set(old) - set(new))
    reassigned = sorted(symbol for symbol in old.keys() & new.keys() if old[symbol] != new[symbol])
    changed = set(released) | set(reassigned)
    if changed:
        if not all(snapshot.completeness[key] for key in ("positions_complete", "open_orders_complete")):
            raise TradingReconciliationError("ownership release requires a complete current book")
        if previous is not None and _time(snapshot.capture_window["started_at"]) < _time(previous.recorded_at):
            raise TradingReconciliationError("ownership release requires a capture after the original declaration")
        if changed & {item["symbol"] for item in snapshot.positions if Decimal(item["qty"]) != 0}:
            raise TradingReconciliationError("held symbols cannot be released or reassigned")
        if changed & {item["symbol"] for item in snapshot.orders if item["status"] not in TERMINAL}:
            raise TradingReconciliationError("symbols with an open order cannot be released or reassigned")
    return {"effective_at": ownership.recorded_at, "added_symbols": sorted(set(new) - set(old)),
            "released_symbols": released, "reassigned_symbols": reassigned,
            "baseline_positions": [{"symbol": item["symbol"], "desk": _desk(item["symbol"], ownership), "qty": item["qty"]} for item in snapshot.positions],
            "baseline_orders": [{"order_id": item["id"], "symbol": item["symbol"], "desk": _desk(item["symbol"], ownership)} for item in snapshot.orders],
            "identity_authenticated": False, **_common_report(ownership)}


def evidence_for_ownership(ownership: DeskOwnershipInput, events=(), blobs=None):
    events = _retry_prefix(ownership, events, "ownership", "ownership_id")
    _bound_snapshot(ownership, events, blobs or {})
    return {"trading/ownership.json": ownership.to_bytes()}


def build_ownership_event(ownership: DeskOwnershipInput, events=(), blobs=None):
    events = _retry_prefix(ownership, events, "ownership", "ownership_id")
    return _build(ownership, "TRADING_DESK_OWNERSHIP", "ownership_id", "ownership", "assessment",
                  assess_ownership(ownership, events, blobs), evidence_for_ownership(ownership, events, blobs),
                  {"kind": "TRADING_DESK_OWNERSHIP", "account_id": ownership.account_id, "mode": ownership.mode})


def _reconciliation_context(document, events, blobs):
    snapshot, _ = _bound_snapshot(document, events, blobs)
    ownership = None
    active = _active(events, OWNERSHIP_EVENT_TYPE, document.account_id, document.recorded_at)
    if document.ownership_event_id is not None:
        event = _linked(events, document.ownership_event_id, OWNERSHIP_EVENT_TYPE, document.recorded_at)
        if active is None or active.event_id != event.event_id:
            raise TradingReconciliationError("reconciliation ownership must be the active declaration")
        ownership = DeskOwnershipInput.from_mapping(event.payload["ownership"])
        if event.source["source_sha256"] != document.ownership_sha256 or ownership.account_id != document.account_id:
            raise TradingReconciliationError("reconciliation ownership account or hash differs")
        prefix = events[:next(index for index, item in enumerate(events) if item.event_id == event.event_id)]
        if build_ownership_event(ownership, prefix, blobs).to_bytes() != event.to_bytes():
            raise TradingReconciliationError("ownership does not match retained projection")
    elif active is not None:
        raise TradingReconciliationError("known desk ownership cannot be silently omitted")
    previous = _active(events, RECONCILIATION_EVENT_TYPE, document.account_id, document.recorded_at)
    if (document.prior_reconciliation_event_id is None) != (previous is None) or (previous is not None and previous.event_id != document.prior_reconciliation_event_id):
        raise TradingReconciliationError("reconciliation must append to the latest account result")
    capture = {"schema_version": "blackpod.runtime_export.v1", "events": [], "profiles": {}}
    if document.runtime_evidence is not None:
        raw = _blob(blobs, document.runtime_evidence["sha256"])
        if len(raw) != document.runtime_evidence["size_bytes"]:
            raise TradingReconciliationError("runtime evidence byte length differs")
        capture = verified_runtime_capture(raw)
        if any(_time(item["payload"]["recorded_at"]) > _time(snapshot.capture_window["completed_at"]) for item in capture["events"]):
            raise TradingReconciliationError("runtime prefix postdates broker capture cutoff")
    if previous is not None and previous.payload["reconciliation"]["runtime_evidence"] is not None:
        old_ref = previous.payload["reconciliation"]["runtime_evidence"]
        old_capture = verified_runtime_capture(_blob(blobs, old_ref["sha256"]))
        if capture["events"][:len(old_capture["events"])] != old_capture["events"]:
            raise TradingReconciliationError("runtime prefix cannot retreat or replace previously retained events")
        if any(capture["profiles"].get(key) != value for key, value in old_capture["profiles"].items()):
            raise TradingReconciliationError("retained runtime profiles cannot change")
    return snapshot, ownership, capture


def assess_reconciliation(document: TradingReconciliationInput, events=(), blobs=None):
    events = _retry_prefix(document, events, "reconciliation", "reconciliation_id")
    snapshot, ownership, capture = _reconciliation_context(document, events, blobs or {})
    attempts = runtime_attempts(capture, document.account_id, document.mode)
    orders = {item["id"]: item for item in snapshot.orders}
    matched, results = {}, []
    for attempt in attempts:
        order = orders.get(attempt["order_id"])
        if order is None and attempt["client_order_id"] is not None:
            matches = [item for item in snapshot.orders if item["client_order_id"] == attempt["client_order_id"]]
            if len(matches) > 1: raise TradingReconciliationError("broker client order identity is ambiguous")
            if matches:
                order = matches[0]
                attempt["order_id"] = order["id"]
        if order is not None:
            if order["symbol"] != attempt["symbol"] or (attempt["side"] != "close" and order["side"] != attempt["side"]):
                raise TradingReconciliationError("exact identified order differs from attempted parameters")
            if attempt["client_order_id"] is not None and order["client_order_id"] != attempt["client_order_id"]:
                raise TradingReconciliationError("broker client order identity differs from durable attempt")
            if order["qty"] is not None and Decimal(order["qty"]) != Decimal(attempt["qty"]):
                raise TradingReconciliationError("broker requested quantity differs from durable attempt")
            matched[order["id"]] = attempt["attempt_sha256"]
        chain, current, seen = [], order, set()
        while current is not None and current["status"] == "replaced" and current["replaced_by"] in orders:
            if current["id"] in seen: raise TradingReconciliationError("replacement chain cycle")
            seen.add(current["id"])
            current = orders[current["replaced_by"]]
            chain.append(current["id"])
            matched[current["id"]] = attempt["attempt_sha256"]
        status = ("ACCEPTANCE_UNKNOWN" if attempt["order_id"] is None else "NOT_OBSERVED" if order is None
                  else "REPLACED_PENDING" if current["status"] == "replaced"
                  else "BROKER_TERMINAL" if current["status"] in TERMINAL else "ORDER_OPEN")
        results.append({key: attempt[key] for key in ("attempt_sha256", "session_id", "symbol", "side", "qty", "order_id", "client_order_id")}
                       | {"status": status, "broker_status": None if order is None else order["status"],
                          "filled_qty": None if order is None else order["filled_qty"],
                          "filled_avg_price": None if order is None else order["filled_avg_price"], "replacement_order_ids": chain})
    complete = all(snapshot.completeness.values())
    # Exact-client-id discoveries bind only this observation. The retained
    # receipt remains untouched, so lost acceptance never becomes a retry.
    barrier = durable_restart_barrier(capture, snapshot.orders, account_id=document.account_id, mode=document.mode,
                                      complete=complete, positions=snapshot.positions)
    classified_orders = [{"order_id": item["id"], "symbol": item["symbol"],
                          "desk": "UNCLASSIFIED" if item["submitted_at"] is None else _desk(item["symbol"], ownership, item["submitted_at"]),
                          "status": item["status"], "filled_qty": item["filled_qty"], "filled_avg_price": item["filled_avg_price"],
                          "matched_attempt_sha256": matched.get(item["id"])} for item in snapshot.orders]
    execution = any(Decimal(item["filled_qty"]) > 0 for item in snapshot.orders)
    attributed = any(item["matched_attempt_sha256"] is not None and item["desk"] == "TRADING" and Decimal(item["filled_qty"]) > 0 for item in classified_orders)
    return {"status": "NO_EXECUTION_OBSERVED" if not attempts and not snapshot.orders else "PENDING" if barrier["entries_blocked"] or not complete else "RECONCILED",
            "positions": [{"symbol": item["symbol"], "desk": _desk(item["symbol"], ownership, snapshot.captured_at), "qty": item["qty"]} for item in snapshot.positions],
            "orders": classified_orders, "attempts": results, "restart_barrier": barrier,
            "execution_observed": execution, "attributable_execution_observed": attributed,
            "provider_verified": False, "ownership_authenticated": False, **_common_report(document),
            "limitations": ["NON_ATOMIC_BROKER_SNAPSHOT", "DECLARED_DESK_OWNERSHIP_UNAUTHENTICATED", "PROVIDER_IDENTITY_NOT_ATTESTED",
                            "NO_ATTRIBUTABLE_COST_BASIS_OR_FEES", "CUMULATIVE_FILLS_NOT_ADDITIVE", "NO_EXECUTION_AUTHORITY"]}


def evidence_for_reconciliation(document: TradingReconciliationInput, events=(), blobs=None):
    events = _retry_prefix(document, events, "reconciliation", "reconciliation_id")
    _reconciliation_context(document, events, blobs or {})
    evidence = {"trading/reconciliation.json": document.to_bytes()}
    if document.runtime_evidence is not None:
        evidence[document.runtime_evidence["path"]] = _blob(blobs or {}, document.runtime_evidence["sha256"])
    return evidence


def build_reconciliation_event(document: TradingReconciliationInput, events=(), blobs=None):
    events = _retry_prefix(document, events, "reconciliation", "reconciliation_id")
    return _build(document, "TRADING_EXECUTION_RECONCILIATION", "reconciliation_id", "reconciliation", "result",
                  assess_reconciliation(document, events, blobs), evidence_for_reconciliation(document, events, blobs),
                  {"kind": "TRADING_EXECUTION_RECONCILIATION", "account_id": document.account_id, "mode": document.mode})


def validate_trading_reconciliation_event(event, previous_events, blobs):
    dispatch = {SNAPSHOT_EVENT_TYPE: (BrokerSnapshotInput, "snapshot", build_snapshot_event, "trading/snapshot.json"),
                OWNERSHIP_EVENT_TYPE: (DeskOwnershipInput, "ownership", build_ownership_event, "trading/ownership.json"),
                RECONCILIATION_EVENT_TYPE: (TradingReconciliationInput, "reconciliation", build_reconciliation_event, "trading/reconciliation.json")}
    if event.event_type not in dispatch:
        raise TradingReconciliationError("unsupported reconciliation event")
    contract, key, builder, source_path = dispatch[event.event_type]
    document = contract.from_mapping(event.payload[key])
    if _blob(blobs, event.source["source_sha256"]) != document.to_bytes():
        raise TradingReconciliationError("retained input differs from event source")
    if not any(ref["path"] == source_path and ref["sha256"] == event.source["source_sha256"] for ref in event.evidence):
        raise TradingReconciliationError("input source evidence path differs")
    if builder(document, previous_events, blobs).to_bytes() != event.to_bytes():
        raise TradingReconciliationError("event differs from deterministic retained-source projection")


def summarize_trading_reconciliation(events, *, account_id=None):
    results = [item for item in events if item.event_type == RECONCILIATION_EVENT_TYPE
               and (account_id is None or item.payload["reconciliation"]["account_id"] == account_id)]
    if not results:
        return {"status": "NOT_RECORDED", "execution_authority_granted": False, "readiness": False, "realized_trade_pnl": None}
    return {"event_id": results[-1].event_id, "account_id": results[-1].payload["reconciliation"]["account_id"], **results[-1].payload["result"]}
