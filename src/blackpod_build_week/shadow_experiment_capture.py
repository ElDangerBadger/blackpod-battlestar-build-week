"""Two bounded market-data GETs for the prospective observational pilot.

Importing this module is offline. There is no account, order, quote, model or
execution interface. Native response bytes and exact GET receipts are retained
by the experiment journal; credentials remain in memory.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts.historical_intake import validate_historical_capture
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import PaperCredentials, _credential_literal
from .trading_historical_intake import parse_historical_json

URLS = {"calendar": "https://paper-api.alpaca.markets/v2/calendar",
        "bars": "https://data.alpaca.markets/v2/stocks/bars"}
MAX_BYTES = 1024 * 1024


class ExperimentCaptureError(ValueError):
    """Sanitized transport/input failure: never include native error bodies."""
    def __init__(self, code, http_status=None):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_query(kind, query):
    if kind not in URLS:
        raise ExperimentCaptureError("ENDPOINT_REFUSED")
    try:
        receipt = validate_historical_capture({"schema_version": "blackpod.read_only_historical_capture.v1",
            "method": "GET", "url": URLS[kind], "query": query, "captured_at": "2026-01-01T00:00:00Z",
            "status": 200, "body_sha256": "0" * 64, "size_bytes": 1}, kind)
        query = receipt["query"]
        if kind == "bars":
            if query["symbols"] != "QQQ,SPY" or query["limit"] != 1000:
                raise ValueError()
            start, end = (parse_rfc3339(query[key], key) for key in ("start", "end"))
        else:
            start, end = (datetime.fromisoformat(query[key]) for key in ("start", "end"))
        if end - start > timedelta(days=100):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ExperimentCaptureError("QUERY_REFUSED") from None
    return query


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise ExperimentCaptureError("REDIRECT_REFUSED", code)


def market_get(kind, query, credentials, *, timeout=20):
    """Fixed HTTPS hosts, GET only, no proxy/redirect/ambient endpoint override."""
    query = validate_query(kind, query)
    if (not isinstance(credentials, PaperCredentials) or type(timeout) not in {int, float}
            or not 0 < timeout <= 30):
        raise ExperimentCaptureError("INPUT_REFUSED")
    try:
        key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
    except ValueError:
        raise ExperimentCaptureError("INPUT_REFUSED") from None
    url = URLS[kind] + "?" + urlencode(sorted(query.items()))
    request = Request(url, method="GET", headers={"APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise ExperimentCaptureError("REDIRECT_REFUSED")
            if type(response.status) is not int or response.status != 200:
                raise ExperimentCaptureError("HTTP_ERROR", response.status)
            chunks, size = [], 0
            reader = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() > deadline:
                    raise ExperimentCaptureError("TIMEOUT")
                part = reader(min(65536, MAX_BYTES + 1 - size))
                if not isinstance(part, bytes):
                    raise ExperimentCaptureError("INVALID_RESPONSE")
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                if size > MAX_BYTES:
                    raise ExperimentCaptureError("RESPONSE_TOO_LARGE")
            raw = b"".join(chunks)
        if not raw or any(value.encode() in raw for value in (key, secret)):
            raise ExperimentCaptureError("SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")
        try:
            decoded = parse_historical_json(raw)
            def contains_secret(value, depth=0):
                if depth > 16:
                    raise ValueError()
                if isinstance(value, str):
                    return key in value or secret in value
                if isinstance(value, list):
                    return any(contains_secret(item, depth + 1) for item in value)
                if isinstance(value, dict):
                    return any(contains_secret(name, depth + 1) or contains_secret(item, depth + 1)
                               for name, item in value.items())
                return False
            if contains_secret(decoded):
                raise ExperimentCaptureError("SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")
        except ExperimentCaptureError:
            raise
        except (ValueError, TypeError, RecursionError):
            raise ExperimentCaptureError("INVALID_RESPONSE") from None
        receipt = validate_historical_capture({"schema_version": "blackpod.read_only_historical_capture.v1",
            "method": "GET", "url": URLS[kind], "query": query, "captured_at": utc_now(),
            "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)}, kind)
        return raw, canonical_json_bytes(receipt)
    except ExperimentCaptureError:
        raise
    except HTTPError as exc:
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        raise ExperimentCaptureError("HTTP_ERROR", status) from None
    except (TimeoutError, socket.timeout):
        raise ExperimentCaptureError("TIMEOUT") from None
    except URLError:
        raise ExperimentCaptureError("URL_ERROR") from None
    except (OSError, HTTPException):
        raise ExperimentCaptureError("TRANSPORT_ERROR") from None
