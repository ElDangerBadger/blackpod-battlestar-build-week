"""Explicit GET-only paper captures including exact tracked order identities."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import hmac
from http.client import HTTPException
from pathlib import Path
import re
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler

from .paper_account_probe import (
    PAPER_ORIGIN, MAX_RESPONSE_BYTES, MAX_CREDENTIAL_BYTES, PaperResponse, PaperTransportError,
    _RefuseRedirects, _read_regular, _parse_response, _publish, _validate_paths, parse_credentials, paper_get,
    probe_paper_account,
)

_ORDER_ID = re.compile(r"^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$")
_FIELDS = {"id", "client_order_id", "symbol", "side", "status", "type", "time_in_force", "qty", "notional",
    "filled_qty", "filled_avg_price", "submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at",
    "failed_at", "replaced_at", "replaces", "replaced_by", "legs"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _selected_order(value, depth=0):
    if not isinstance(value, dict) or depth > 4:
        raise ValueError("order response is not a bounded object")
    result = {key: value[key] for key in _FIELDS - {"legs"} if key in value}
    if value.get("legs") is not None:
        if not isinstance(value["legs"], list) or len(value["legs"]) > 100:
            raise ValueError("order legs exceed bounds")
        result["legs"] = [_selected_order(leg, depth + 1) for leg in value["legs"]]
    else:
        result["legs"] = None
    return result


def exact_order_get(order_id, headers, timeout):
    if not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id):
        raise PaperTransportError("ORDER_ID_INVALID")
    url = PAPER_ORIGIN + "/v2/orders/" + order_id
    request = Request(url, headers=dict(headers), method="GET")
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise PaperTransportError("REDIRECT_REFUSED")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise PaperTransportError("RESPONSE_TOO_LARGE")
            return PaperResponse(response.status, raw)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise PaperTransportError("HTTP_ERROR", status) from None
    except (OSError, URLError, TimeoutError, socket.timeout, HTTPException):
        raise PaperTransportError("TRANSPORT_ERROR") from None


def capture_paper_orders(source: Path, credential_format: str, output_root: Path, order_ids=(), *,
                         expected_account_id=None, probe_transport=None, order_transport=None, now=None):
    """No submit/cancel/close/retry. Failed exact reads retain partial evidence."""
    ids = list(order_ids)
    if (len(ids) > 100 or any(not isinstance(value, str) or not _ORDER_ID.fullmatch(value) for value in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("tracked broker order IDs must be unique UUIDs (at most 100)")
    source, output_root = Path(source).absolute(), Path(output_root).absolute()
    _validate_paths(source, output_root)
    credentials = parse_credentials(_read_regular(source, MAX_CREDENTIAL_BYTES), credential_format)
    headers = {"APCA-API-KEY-ID": credentials.key_id, "APCA-API-SECRET-KEY": credentials.secret_key, "Accept": "application/json"}
    def consistent_probe_transport(path, selected_headers, timeout):
        if any(not hmac.compare_digest(selected_headers.get(key, ""), headers[key])
               for key in ("APCA-API-KEY-ID", "APCA-API-SECRET-KEY")):
            raise PaperTransportError("CREDENTIAL_SOURCE_CHANGED")
        return (probe_transport or paper_get)(path, headers, timeout)
    probe = probe_paper_account(source, credential_format, output_root,
        expected_account_id=expected_account_id, transport=consistent_probe_transport, now=now)
    if probe["report"]["result"] != "CONFIRMED":
        return {"result": "NOT_CONFIRMED", **probe, "orders_submitted": 0}
    clock, fetch = now or _now, order_transport or exact_order_get
    capture = {"schema_version": "blackpod.paper_broker_capture.v1", "probe": probe["report"],
        "tracked_order_ids": ids, "tracked_order_requests": [], "tracked_orders": [], "capture_completed_at": None}
    complete = True
    for order_id in ids:
        request = {"method": "GET", "path": "/v2/orders/" + order_id, "http_status": None,
                   "started_at": clock(), "completed_at": None}
        try:
            response = fetch(order_id, headers, 10)
            request["http_status"] = response.status
            value = _selected_order(_parse_response(response))
            if value.get("id") != order_id:
                raise ValueError("exact order identity mismatch")
            from .trading_reconciliation import normalize_broker_orders, snapshot_input_from_probe
            from .contracts.trading_reconciliation import BrokerSnapshotInput
            candidate = snapshot_input_from_probe(json.dumps(probe["report"], allow_nan=False).encode(),
                snapshot_id="selected-order-validation", evidence_path="broker/validation.json").to_dict()
            candidate["orders"] = normalize_broker_orders([value])
            BrokerSnapshotInput.from_mapping(candidate)
            capture["tracked_orders"].append(value)
        except PaperTransportError as exc:
            request["http_status"] = exc.http_status
            complete = False
        except (ValueError, TypeError, KeyError, OSError, HTTPException, RecursionError):
            complete = False
        request["completed_at"] = clock()
        capture["tracked_order_requests"].append(request)
        if not complete:
            break
    capture["capture_completed_at"] = clock()
    if complete:
        try:
            from .trading_reconciliation import snapshot_input_from_probe
            snapshot_input_from_probe(json.dumps(capture, allow_nan=False).encode(),
                snapshot_id="complete-capture-validation", evidence_path="broker/validation.json")
        except (ValueError, TypeError, KeyError, RecursionError):
            complete = False
    _validate_paths(source, output_root)
    path, written = _publish(output_root, capture)
    return {"result": "CONFIRMED" if complete else "NOT_CONFIRMED", "evidence_path": str(path),
        "written": written, "orders_submitted": 0, "capture": capture}
