"""Two fixed read-only market-data endpoints. No account or execution API."""
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import re
import socket
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_account_probe import PaperCredentials, _credential_literal
from .trading_historical_intake import parse_historical_json
from .sentry_catalyst import symbols, clock, stamp

URLS = {"news": "https://data.alpaca.markets/v1beta1/news",
        "snapshots": "https://data.alpaca.markets/v2/stocks/snapshots"}
MAX_BYTES = 1024 * 1024
LEGACY_RECEIPT_VERSION = 'blackpod.sentry_catalyst_get.v1'
CONSOLIDATED_RECEIPT_VERSION = 'blackpod.sentry_catalyst_get.v2'
CONTENT_RECEIPT_VERSION = 'blackpod.sentry_catalyst_get.v3'
SNAPSHOT_FEEDS = ('iex', 'sip', 'delayed_sip')

class CatalystCaptureError(ValueError):
    def __init__(self, code, http_status=None):
        super().__init__(code)
        self.code, self.http_status = code, http_status

def utc_now():
    return stamp(datetime.now(timezone.utc))

def validate_query(kind, query, *, allow_content=False):
    try:
        if kind not in URLS or not isinstance(query, dict):
            raise ValueError()
        symbols(query['symbols'].split(','))
        if kind == 'snapshots':
            if set(query) != {'symbols', 'feed'} or query['feed'] not in SNAPSHOT_FEEDS:
                raise ValueError()
        else:
            if (set(query) != {'symbols', 'start', 'end', 'limit', 'sort', 'include_content'}
                    or type(query['limit']) is not int or query['limit'] != 50
                    or query['sort'] != 'desc' or query['include_content'] not in (('false', 'true') if allow_content else ('false',))
                    or not timedelta(0) < clock(query['end']) - clock(query['start']) <= timedelta(hours=24)):
                raise ValueError()
        return dict(query)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise CatalystCaptureError('QUERY_REFUSED') from None

def validate_receipt(value, kind):
    if (not isinstance(value, dict) or set(value) != {'schema_version','method','url','query','captured_at','status','body_sha256','size_bytes'}
            or value['schema_version'] not in (LEGACY_RECEIPT_VERSION, CONSOLIDATED_RECEIPT_VERSION, CONTENT_RECEIPT_VERSION)
            or value['method'] != 'GET'
            or value['url'] != URLS.get(kind) or type(value['status']) is not int or value['status'] != 200
            or not isinstance(value['body_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['body_sha256'])
            or type(value['size_bytes']) is not int or not 0 < value['size_bytes'] <= MAX_BYTES):
        raise CatalystCaptureError('RECEIPT_REFUSED')
    query = validate_query(kind, value['query'], allow_content=value['schema_version'] == CONTENT_RECEIPT_VERSION)
    if value['schema_version'] != _receipt_version(kind, query):
        raise CatalystCaptureError('RECEIPT_REFUSED')
    clock(value['captured_at'])
    return value

def _receipt_version(kind, query):
    """Preserve old news/IEX receipts; consolidated snapshots have a new contract."""
    if kind == 'news' and query['include_content'] == 'true':
        return CONTENT_RECEIPT_VERSION
    if kind == 'snapshots' and query['feed'] in ('sip', 'delayed_sip'):
        return CONSOLIDATED_RECEIPT_VERSION
    return LEGACY_RECEIPT_VERSION

class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        fp.close()
        raise CatalystCaptureError("REDIRECT_REFUSED", code)


def market_get(kind, query, credentials, *, timeout=20):
    """Fixed HTTPS hosts, GET only, no proxy/redirect/ambient endpoint override."""
    query = validate_query(kind, query, allow_content=isinstance(query, dict) and query.get('include_content') == 'true')
    if (not isinstance(credentials, PaperCredentials) or type(timeout) not in {int, float}
            or not 0 < timeout <= 30):
        raise CatalystCaptureError("INPUT_REFUSED")
    try:
        key, secret = _credential_literal(credentials.key_id), _credential_literal(credentials.secret_key)
    except ValueError:
        raise CatalystCaptureError("INPUT_REFUSED") from None
    url = URLS[kind] + "?" + urlencode(sorted(query.items()))
    request = Request(url, method="GET", headers={"APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret, "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise CatalystCaptureError("REDIRECT_REFUSED")
            if type(response.status) is not int or response.status != 200:
                raise CatalystCaptureError("HTTP_ERROR", response.status)
            chunks, size = [], 0
            reader = getattr(response, "read1", response.read)
            while True:
                if time.monotonic() > deadline:
                    raise CatalystCaptureError("TIMEOUT")
                part = reader(min(65536, MAX_BYTES + 1 - size))
                if not isinstance(part, bytes):
                    raise CatalystCaptureError("INVALID_RESPONSE")
                if not part:
                    break
                chunks.append(part)
                size += len(part)
                if size > MAX_BYTES:
                    raise CatalystCaptureError("RESPONSE_TOO_LARGE")
            raw = b"".join(chunks)
        if not raw or any(value.encode() in raw for value in (key, secret)):
            raise CatalystCaptureError("SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")
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
                raise CatalystCaptureError("SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")
        except CatalystCaptureError:
            raise
        except (ValueError, TypeError, RecursionError):
            raise CatalystCaptureError("INVALID_RESPONSE") from None
        receipt = validate_receipt({"schema_version": _receipt_version(kind, query),
            "method": "GET", "url": URLS[kind], "query": query, "captured_at": utc_now(),
            "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)}, kind)
        return raw, canonical_json_bytes(receipt)
    except CatalystCaptureError:
        raise
    except HTTPError as exc:
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        raise CatalystCaptureError("HTTP_ERROR", status) from None
    except (TimeoutError, socket.timeout):
        raise CatalystCaptureError("TIMEOUT") from None
    except URLError:
        raise CatalystCaptureError("URL_ERROR") from None
    except (OSError, HTTPException):
        raise CatalystCaptureError("TRANSPORT_ERROR") from None
