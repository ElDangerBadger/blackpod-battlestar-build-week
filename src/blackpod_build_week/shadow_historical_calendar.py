"""One explicit historical-calendar GET for the offline reversal baseline.

The frozen prospective capture interface is unchanged. This interface has one
fixed URL, no price/account/order endpoint, and no implicit network activity.
"""
from datetime import date, datetime, timezone
from http.client import HTTPException
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from .contracts.historical_intake import validate_historical_capture
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import PaperCredentials, _credential_literal
from .shadow_experiment_capture import ExperimentCaptureError, _RefuseRedirects
from .trading_historical_intake import _calendar

URL = "https://paper-api.alpaca.markets/v2/calendar"
MAX_BYTES = 4 * 1024 * 1024
MAX_DATE = "2026-03-05"


def calendar_get(start, end, credentials, *, timeout=30):
    """Capture a bounded calendar through the protected development cutoff."""
    try:
        for value in (start, end):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        if not "1998-01-01" <= start <= end <= MAX_DATE:
            raise ValueError()
        if not isinstance(credentials, PaperCredentials) or type(timeout) not in {int, float} or not 0 < timeout <= 30:
            raise ValueError()
        key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
    except (ValueError, TypeError):
        raise ExperimentCaptureError("HISTORICAL_CALENDAR_INPUT_REFUSED") from None
    query = {"start": start, "end": end}
    url = URL + "?" + urlencode(sorted(query.items()))
    request = Request(url, method="GET", headers={"APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise ExperimentCaptureError("REDIRECT_REFUSED")
            if response.status != 200 or type(response.status) is not int:
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
        if not raw or key.encode() in raw or secret.encode() in raw:
            raise ExperimentCaptureError("SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")
        receipt = validate_historical_capture({"schema_version": "blackpod.read_only_historical_capture.v1",
            "method": "GET", "url": URL, "query": query,
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)}, "calendar")
        # Exact calendar schema excludes credential echoes, including escaped
        # strings, unexpected fields and malformed or duplicate source rows.
        _calendar(raw, receipt)
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
    except (ValueError, TypeError, RecursionError):
        raise ExperimentCaptureError("INVALID_RESPONSE") from None
