"""Explicit, bounded GET-only Alpaca paper-account confirmation.

Importing this module is offline. This utility does not import Galactica or
Alpaca, start an executor, authorize a desk, or submit/cancel/close orders.
Credentials are parsed as data and retained only in memory. Reports preserve
selected broker facts, never credentials, raw response bodies, or raw errors.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import ssl
import stat
import sys
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener


SCHEMA_VERSION = "blackpod.alpaca_paper_probe.v1"
PAPER_ORIGIN = "https://paper-api.alpaca.markets"
ENDPOINTS = (
    ("account", "/v2/account"),
    ("positions", "/v2/positions"),
    ("open_orders", "/v2/orders?status=open&limit=500&nested=true"),
    ("clock", "/v2/clock"),
)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CREDENTIAL_BYTES = 64 * 1024
MAX_POSITIONS = 1000
MAX_ORDERS = 500
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-_/]{0,31}$")
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?$")
_ENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_NAV_KEYS = frozenset({"APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_PAPER"})
_PAPER_KEYS = frozenset({"ALPACA_KEY_ID_PAPER", "ALPACA_SECRET_KEY_PAPER", "ALPACA_BASE_URL_PAPER"})
_OPEN_STATUSES = frozenset({"new", "partially_filled", "done_for_day", "pending_cancel",
    "pending_replace", "accepted", "pending_new", "accepted_for_bidding", "stopped", "suspended", "calculated", "held"})


class PaperProbeError(ValueError):
    """A local input or selected broker fact could not be verified."""


class PaperTransportError(Exception):
    """A sanitized transport failure; the original exception is not exposed."""
    def __init__(self, code: str, http_status: int | None = None):
        super().__init__(code)
        self.code, self.http_status = code, http_status


@dataclass(frozen=True, repr=False)
class PaperCredentials:
    key_id: str
    secret_key: str


@dataclass(frozen=True)
class PaperResponse:
    status: int
    body: bytes


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _absolute(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise PaperProbeError(label + " must be an absolute path without traversal")
    return path


def _existing_ancestors(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            value = current.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(value.st_mode):
            raise PaperProbeError("output or source ancestor is not a regular directory")


def _open_directory(path: Path, *, create: bool = False) -> int:
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_regular(path: Path, limit: int) -> bytes:
    parent = descriptor = None
    try:
        parent = _open_directory(path.parent)
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise PaperProbeError("source must be a bounded singly linked regular file")
        raw = bytearray()
        while len(raw) <= limit:
            part = os.read(descriptor, min(limit + 1 - len(raw), 65536))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(descriptor)
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        signature = lambda value: tuple(getattr(value, field) for field in fields)
        if len(raw) > limit or len(raw) != before.st_size or signature(before) != signature(after) or signature(before) != signature(current):
            raise PaperProbeError("source changed during bounded read")
        return bytes(raw)
    except OSError as exc:
        raise PaperProbeError("source cannot be read safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def _validate_paths(source: Path, output: Path) -> None:
    _existing_ancestors(source.parent)
    _existing_ancestors(output)
    if (output == Path(output.anchor) or output == source.parent
            or output.is_relative_to(source.parent) or source.parent.is_relative_to(output)):
        raise PaperProbeError("probe output must be separate from credential storage")
    # Check before any network call or output write. Do not repair or modify
    # missions, producer artifacts, journal chains, runtime ledgers or sources.
    forbidden_names = {"src", "tests", "fixtures", "examples", ".git", "missions"}
    for ancestor in (output, *output.parents):
        if ancestor.name in forbidden_names:
            raise PaperProbeError("probe output overlaps source storage")
        for name in ("mission_snapshot.json", "request/mission_request.json", ".journal.lock",
                     "ledger.lock", "blackwell_navigator_trickle.py"):
            if os.path.lexists(ancestor / name):
                raise PaperProbeError("probe output overlaps protected storage")
    if os.path.lexists(output / ".git"):
        raise PaperProbeError("probe output cannot be a repository root")
    if output.exists():
        if len(os.listdir(output)) > 10000:
            raise PaperProbeError("probe output directory is too large")
        for item in output.iterdir():
            value = item.lstat()
            if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
                raise PaperProbeError("probe output contains an unsafe file")


def _credential_literal(value: object) -> str:
    if (not isinstance(value, str) or not value or len(value) > 512 or "$" in value or "`" in value
            or any(ord(char) < 33 or ord(char) > 126 for char in value)):
        raise PaperProbeError("selected credential values must be literal bounded strings")
    return value


def _validate_paper_origin(value: str) -> None:
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname == "paper-api.alpaca.markets"
                 and parsed.port in {None, 443} and parsed.username is None and parsed.password is None
                 and parsed.path in {"", "/", "/v2", "/v2/"} and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise PaperProbeError("PAPER credential origin must be the fixed Alpaca HTTPS paper host")


def _galactica_yaml_credentials(raw: bytes) -> PaperCredentials:
    """Read the legacy alpaca pair without constructing other provider values.

    PyYAML is already a project dependency. Only this explicit format imports
    it. Compose a bounded safe node tree; do not instantiate tagged objects or
    interpolate environment variables. Duplicate selected keys and YAML merges
    cannot silently replace or manufacture the selected credential pair.
    """
    try:
        import yaml
    except ImportError:
        raise PaperProbeError("existing YAML dependency is unavailable") from None
    try:
        root = yaml.compose(raw.decode("utf-8"), Loader=yaml.SafeLoader)
    except (yaml.YAMLError, UnicodeError, ValueError, RecursionError):
        # Parser errors can contain source snippets, including secret values.
        raise PaperProbeError("Galactica credential YAML is invalid") from None
    if not isinstance(root, yaml.MappingNode):
        raise PaperProbeError("Galactica credential YAML requires a root mapping")
    selected = [value for key, value in root.value
                if isinstance(key, yaml.ScalarNode) and key.tag == "tag:yaml.org,2002:str" and key.value == "alpaca"]
    if len(selected) != 1 or not isinstance(selected[0], yaml.MappingNode):
        raise PaperProbeError("Galactica YAML requires one unambiguous alpaca mapping")
    fields = {"key_id", "secret_key", "paper", "mode", "base_url"}
    values = {}
    for key, value in selected[0].value:
        if not isinstance(key, yaml.ScalarNode) or key.tag != "tag:yaml.org,2002:str" or key.value not in fields:
            continue
        if key.value in values:
            raise PaperProbeError("duplicate selected Galactica YAML field")
        values[key.value] = value
    def literal(name):
        value = values.get(name)
        if not isinstance(value, yaml.ScalarNode) or value.tag != "tag:yaml.org,2002:str":
            raise PaperProbeError("Galactica selected credentials must be literal strings")
        return _credential_literal(value.value)
    key, secret = literal("key_id"), literal("secret_key")
    if "paper" in values:
        value = values["paper"]
        if (not isinstance(value, yaml.ScalarNode) or value.tag not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:str"}
                or value.value.lower() not in {"true", "yes", "on"}):
            raise PaperProbeError("Galactica YAML contradicts explicit PAPER-only confirmation")
    if "mode" in values and literal("mode").lower() != "paper":
        raise PaperProbeError("Galactica YAML contradicts explicit PAPER-only confirmation")
    if "base_url" in values:
        _validate_paper_origin(literal("base_url"))
    return PaperCredentials(key, secret)


def parse_credentials(raw: bytes, credential_format: str) -> PaperCredentials:
    """Select literal credentials; never source a shell or native runtime."""
    if not isinstance(raw, bytes) or len(raw) > MAX_CREDENTIAL_BYTES:
        raise PaperProbeError("credential input is not bounded bytes")
    if credential_format == "GALACTICA_YAML":
        return _galactica_yaml_credentials(raw)
    keys = _NAV_KEYS if credential_format == "NAVIGATOR_ENV" else _PAPER_KEYS if credential_format == "PAPER_ENV" else None
    if keys is None:
        raise PaperProbeError("unsupported credential format")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise PaperProbeError("credential input is not UTF-8") from exc
    values: dict[str, str] = {}
    for line in lines:
        match = _ENV_ASSIGNMENT.match(line)
        if match is None or match[1] not in keys:
            continue  # Unrelated provider and LIVE keys are not selected.
        key = match[1]
        if key in values:
            raise PaperProbeError("duplicate selected credential assignment")
        try:
            tokens = shlex.split(line[match.end():], posix=True, comments=True)
        except ValueError as exc:
            raise PaperProbeError("invalid selected credential assignment") from exc
        if len(tokens) != 1:
            raise PaperProbeError("selected credentials require literal KEY=value assignments")
        values[key] = _credential_literal(tokens[0])
    if set(values) != keys:
        raise PaperProbeError("selected PAPER credential keys are incomplete")
    if credential_format == "NAVIGATOR_ENV":
        if values["ALPACA_PAPER"].lower() not in {"true", "1", "yes", "on"}:
            raise PaperProbeError("Navigator credentials do not explicitly select PAPER")
        key, secret = values["APCA_API_KEY_ID"], values["APCA_API_SECRET_KEY"]
    else:
        _validate_paper_origin(values["ALPACA_BASE_URL_PAPER"])
        key, secret = values["ALPACA_KEY_ID_PAPER"], values["ALPACA_SECRET_KEY_PAPER"]
    return PaperCredentials(key, secret)


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise PaperTransportError("REDIRECT_REFUSED", code)


def paper_get(path: str, headers: Mapping[str, str], timeout: float) -> PaperResponse:
    """Fixed host, GET only, no inherited proxies, redirects or insecure TLS."""
    if path not in {item[1] for item in ENDPOINTS}:
        raise PaperTransportError("ENDPOINT_REFUSED")
    url = PAPER_ORIGIN + path
    request = Request(url, headers=dict(headers), method="GET")
    opener = build_opener(ProxyHandler({}), _RefuseRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise PaperTransportError("REDIRECT_REFUSED")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise PaperTransportError("RESPONSE_TOO_LARGE", response.status)
            return PaperResponse(response.status, body)
    except HTTPError as exc:
        # Do not read an HTTP error body, print its URL or retain its message.
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        raise PaperTransportError("HTTP_ERROR", status) from None
    except (TimeoutError, socket.timeout):
        raise PaperTransportError("TIMEOUT") from None
    except URLError:
        raise PaperTransportError("URL_ERROR") from None
    except (OSError, HTTPException):
        raise PaperTransportError("TRANSPORT_ERROR") from None


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise PaperProbeError("duplicate broker JSON key")
        value[key] = item
    return value


def _parse_response(response: PaperResponse):
    if not isinstance(response, PaperResponse) or type(response.status) is not int or not 100 <= response.status <= 599:
        raise PaperTransportError("RESPONSE_INVALID")
    if response.status != 200:
        raise PaperTransportError("HTTP_ERROR", response.status)
    if not isinstance(response.body, bytes) or len(response.body) > MAX_RESPONSE_BYTES:
        raise PaperProbeError("broker response exceeds byte limit")
    try:
        return json.loads(response.body, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(PaperProbeError("nonfinite broker JSON")))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PaperProbeError("broker response is not bounded strict JSON") from exc


def _identifier(value) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise PaperProbeError("broker identifier is invalid")
    return value


def _number(value, *, positive=False, nonnegative=False) -> str:
    if type(value) not in {str, int, float} or len(str(value)) > 128 or not _NUMBER.fullmatch(str(value)):
        raise PaperProbeError("broker numeric field is invalid")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal("1e20") or (positive and number <= 0) or (nonnegative and number < 0):
            raise PaperProbeError("broker numeric field is outside the required range")
        return str(value)
    except InvalidOperation as exc:
        raise PaperProbeError("broker numeric field is invalid") from exc


def _time(value) -> str:
    if not isinstance(value, str) or len(value) > 64 or "T" not in value:
        raise PaperProbeError("broker timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError as exc:
        raise PaperProbeError("broker timestamp is not timezone aware") from exc


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _symbol(value) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise PaperProbeError("broker symbol is invalid")
    return value


def _account(value):
    if not isinstance(value, dict):
        raise PaperProbeError("account response is not an object")
    result = {"id": _identifier(value.get("id")), "status": value.get("status"),
              "trading_blocked": value.get("trading_blocked"),
              "equity": _number(value.get("equity")),
              "cash": _number(value.get("cash"))}
    if (not isinstance(result["status"], str) or not re.fullmatch(r"[A-Z_]{1,64}", result["status"])
            or type(result["trading_blocked"]) is not bool):
        raise PaperProbeError("account status or blocking flag is invalid")
    for key in ("account_blocked", "transfers_blocked", "pattern_day_trader", "shorting_enabled"):
        if key in value:
            if type(value[key]) is not bool:
                raise PaperProbeError("account boolean is invalid")
            result[key] = value[key]
    for key in ("buying_power", "long_market_value", "short_market_value", "last_equity"):
        if key in value:
            result[key] = _number(value[key])
    if "currency" in value:
        if not isinstance(value["currency"], str) or not re.fullmatch(r"[A-Z]{3}", value["currency"]):
            raise PaperProbeError("account currency is invalid")
        result["currency"] = value["currency"]
    return result


def _positions(value):
    if not isinstance(value, list) or len(value) >= MAX_POSITIONS:
        raise PaperProbeError("position response is not a complete bounded list")
    results, symbols = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise PaperProbeError("position is not an object")
        symbol = _symbol(item.get("symbol"))
        if symbol in symbols:
            raise PaperProbeError("duplicate position symbol")
        symbols.add(symbol)
        result = {"symbol": symbol, "qty": _number(item.get("qty")),
                  "market_value": _number(item.get("market_value")),
                  "avg_entry_price": _number(item.get("avg_entry_price"), positive=True)}
        if Decimal(result["qty"]) == 0:
            raise PaperProbeError("open position quantity must be nonzero")
        side = "long" if Decimal(result["qty"]) > 0 else "short"
        if item.get("side") != side or (Decimal(result["market_value"]) > 0) != (side == "long") or Decimal(result["market_value"]) == 0:
            raise PaperProbeError("position side and valuation are inconsistent")
        result["side"] = side
        if "asset_id" in item:
            result["asset_id"] = _identifier(item["asset_id"])
        if "current_price" in item:
            result["current_price"] = _number(item["current_price"], positive=True)
        results.append(result)
    return results


def _orders(value):
    if not isinstance(value, list) or len(value) >= MAX_ORDERS:
        raise PaperProbeError("open-order response may be truncated or is not a list")
    identities: set[str] = set()
    def sanitize(item, depth=0):
        if not isinstance(item, dict) or depth > 4 or len(identities) >= 1000:
            raise PaperProbeError("nested order response exceeds bounds")
        identity = _identifier(item.get("id"))
        if identity in identities:
            raise PaperProbeError("duplicate open-order identity")
        identities.add(identity)
        result = {"id": identity, "symbol": _symbol(item.get("symbol")), "status": item.get("status"),
                  "side": item.get("side"), "type": item.get("type"), "time_in_force": item.get("time_in_force"),
                  "filled_qty": _number(item.get("filled_qty"), nonnegative=True)}
        if (not isinstance(result["status"], str) or result["status"] not in _OPEN_STATUSES
                or not isinstance(result["side"], str) or result["side"] not in {"buy", "sell"}):
            raise PaperProbeError("open order status or side is invalid")
        if not isinstance(result["type"], str) or result["type"] not in {"market", "limit", "stop", "stop_limit", "trailing_stop"}:
            raise PaperProbeError("order type is invalid")
        if not isinstance(result["time_in_force"], str) or result["time_in_force"] not in {"day", "gtc", "opg", "cls", "ioc", "fok"}:
            raise PaperProbeError("order time in force is invalid")
        for key in ("qty", "notional", "filled_avg_price"):
            result[key] = None if item.get(key) is None else _number(item[key], positive=True)
        if result["qty"] is None and result["notional"] is None:
            raise PaperProbeError("order has no quantity or notional")
        if result["qty"] is not None and Decimal(result["filled_qty"]) > Decimal(result["qty"]):
            raise PaperProbeError("order filled quantity exceeds declared quantity")
        for key in ("client_order_id", "replaces", "replaced_by"):
            if key in item:
                result[key] = None if item[key] is None else _identifier(item[key])
        for key in ("submitted_at", "updated_at", "filled_at", "canceled_at", "expired_at", "failed_at", "replaced_at"):
            if key in item:
                result[key] = None if item[key] is None else _time(item[key])
        legs = item.get("legs")
        if legs is None:
            result["legs"] = None
        else:
            if not isinstance(legs, list) or len(legs) >= MAX_ORDERS:
                raise PaperProbeError("order legs exceed bounds")
            result["legs"] = [sanitize(leg, depth + 1) for leg in legs]
        return result
    return [sanitize(item) for item in value]


def _clock(value):
    if not isinstance(value, dict) or type(value.get("is_open")) is not bool:
        raise PaperProbeError("clock response is malformed")
    return {"is_open": value["is_open"], **{key: _time(value.get(key)) for key in ("timestamp", "next_open", "next_close")}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _publish(output: Path, report: dict) -> tuple[Path, bool]:
    raw = _canonical(report)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise PaperProbeError("selected probe evidence exceeds size limit")
    name = "paper-probe-" + hashlib.sha256(raw).hexdigest() + ".json"
    parent = descriptor = None
    temporary = None
    try:
        parent = _open_directory(output, create=True)
        temporary = ".paper-probe-" + secrets.token_hex(16) + ".tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise PaperProbeError("incomplete evidence write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            os.unlink(temporary, dir_fd=parent)
            temporary = None
            if _read_regular(output / name, MAX_RESPONSE_BYTES) != raw:
                raise PaperProbeError("immutable probe evidence identity conflict")
            written = False
        else:
            os.unlink(temporary, dir_fd=parent)
            temporary = None
            written = True
        os.fsync(parent)
        return output / name, written
    except OSError as exc:
        raise PaperProbeError("probe evidence could not be published safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None and parent is not None:
            os.unlink(temporary, dir_fd=parent)
        if parent is not None:
            os.close(parent)


def probe_paper_account(credential_source: Path, credential_format: str, output_root: Path, *,
                        expected_account_id: str | None = None,
                        transport: Callable[[str, Mapping[str, str], float], PaperResponse] | None = None,
                        now: Callable[[], str] | None = None, timeout_seconds: float = 10) -> dict:
    """Capture a non-atomic read-only PAPER snapshot and retain private evidence.

    A valid confirmation proves authentication/account facts at these capture
    times. It grants no execution, ownership, capital or investment authority.
    A failed endpoint stops later calls and also retains sanitized evidence.
    """
    source = _absolute(credential_source, "credential source")
    output = _absolute(output_root, "output root")
    _validate_paths(source, output)
    if expected_account_id is not None:
        _identifier(expected_account_id)
    if type(timeout_seconds) not in {int, float} or not 0 < timeout_seconds <= 30:
        raise PaperProbeError("timeout must be positive and no greater than 30 seconds")
    credentials = parse_credentials(_read_regular(source, MAX_CREDENTIAL_BYTES), credential_format)
    fetch, clock = transport or paper_get, now or _utc_now
    started_at = _time(clock())
    report = {
        "schema_version": SCHEMA_VERSION, "result": "NOT_CONFIRMED", "mode": "PAPER",
        "credential_source": {"path": str(source), "format": credential_format},
        "paper_origin": PAPER_ORIGIN, "expected_account_id": expected_account_id,
        "capture_started_at": started_at, "capture_completed_at": None,
        "account": None, "positions": None, "open_orders": None, "clock": None,
        "requests": [], "complete": False, "snapshot_atomic": False,
        "account_authenticated": False,
        "account_identity_verified": False, "account_ownership_verified": False,
        "runtime_profile_verified": False, "execution_authorized": False,
        "capital_policy_activated": False, "auto_trading_enabled": False,
        "orders_submitted": 0, "orders_cancelled": 0, "positions_closed": 0,
        "realized_pnl_evaluated": False,
        "limitations": ["NON_ATOMIC_BROKER_SNAPSHOT", "DESK_OWNERSHIP_NOT_AUTHENTICATED",
                        "RUNTIME_DEPENDENCIES_AND_PROFILE_NOT_VERIFIED", "NO_EXECUTION_AUTHORITY"],
    }
    headers = {"APCA-API-KEY-ID": credentials.key_id, "APCA-API-SECRET-KEY": credentials.secret_key,
               "Accept": "application/json"}
    validators = {"account": _account, "positions": _positions, "open_orders": _orders, "clock": _clock}
    last_time = started_at
    for name, endpoint in ENDPOINTS:
        request_started = _time(clock())
        if _instant(request_started) < _instant(last_time):
            raise PaperProbeError("capture clock moved backwards")
        result = {"name": name, "method": "GET", "path": endpoint,
                  "started_at": request_started, "completed_at": None,
                  "http_status": None, "result": "NOT_CONFIRMED", "failure_code": None}
        try:
            response = fetch(endpoint, headers, timeout_seconds)
            if isinstance(response, PaperResponse) and type(response.status) is int and 100 <= response.status <= 599:
                result["http_status"] = response.status
            sanitized = validators[name](_parse_response(response))
            if name == "account":
                report["account"] = sanitized
                report["account_authenticated"] = True
                if expected_account_id is not None and sanitized["id"] != expected_account_id:
                    result["failure_code"] = "ACCOUNT_ID_MISMATCH"
                    raise PaperProbeError("account identity did not match")
                report["account_identity_verified"] = True
                if (sanitized["status"] != "ACTIVE" or sanitized["trading_blocked"] is not False
                        or sanitized.get("account_blocked") is True or sanitized.get("currency", "USD") != "USD"
                        or Decimal(sanitized["equity"]) <= 0 or Decimal(sanitized["cash"]) < 0):
                    result["failure_code"] = "ACCOUNT_CONSTRAINTS_UNSUPPORTED"
                    raise PaperProbeError("account facts do not meet supported paper check constraints")
            else:
                report[name] = sanitized
            result["result"] = "VERIFIED_SELECTED_FIELDS"
        except PaperTransportError as exc:
            result["failure_code"] = exc.code if exc.code in {
                "REDIRECT_REFUSED", "HTTP_ERROR", "TIMEOUT", "URL_ERROR", "TRANSPORT_ERROR",
                "ENDPOINT_REFUSED", "RESPONSE_TOO_LARGE", "RESPONSE_INVALID"} else "TRANSPORT_ERROR"
            result["http_status"] = exc.http_status if type(exc.http_status) is int and 100 <= exc.http_status <= 599 else result["http_status"]
        except PaperProbeError:
            result["failure_code"] = result["failure_code"] or "BROKER_DATA_UNVERIFIED"
        except (OSError, TimeoutError):
            result["failure_code"] = "TRANSPORT_ERROR"
        result["completed_at"] = _time(clock())
        if _instant(result["completed_at"]) < _instant(request_started):
            raise PaperProbeError("capture clock moved backwards")
        last_time = result["completed_at"]
        report["requests"].append(result)
        if result["result"] != "VERIFIED_SELECTED_FIELDS":
            break
    report["capture_completed_at"] = _time(clock())
    if _instant(report["capture_completed_at"]) < _instant(last_time):
        raise PaperProbeError("capture clock moved backwards")
    if len(report["requests"]) == len(ENDPOINTS) and all(item["result"] == "VERIFIED_SELECTED_FIELDS" for item in report["requests"]):
        report["result"], report["complete"] = "CONFIRMED", True
    _validate_paths(source, output)
    path, written = _publish(output, report)
    return {"report": report, "evidence_path": str(path), "evidence_sha256": hashlib.sha256(_canonical(report)).hexdigest(),
            "written": written}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Confirm an existing Alpaca PAPER account with GET-only queries; no execution")
    parser.add_argument("--credential-source", type=Path, required=True)
    parser.add_argument("--credential-format", choices=("NAVIGATOR_ENV", "PAPER_ENV", "GALACTICA_YAML"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-account-id")
    args = parser.parse_args(argv)
    try:
        result = probe_paper_account(args.credential_source, args.credential_format, args.output_root.absolute(),
                                     expected_account_id=args.expected_account_id)
        report = result["report"]
        print(json.dumps({"schema_version": SCHEMA_VERSION, "result": report["result"], "mode": "PAPER",
                          "account_id": report["account"]["id"] if report["account"] else None,
                          "account_authenticated": report["account_authenticated"],
                          "complete": report["complete"], "orders_submitted": 0, "auto_trading_enabled": False,
                          "requests": report["requests"], "evidence_path": result["evidence_path"],
                          "evidence_sha256": result["evidence_sha256"], "written": result["written"]}, sort_keys=True))
        return 0 if report["result"] == "CONFIRMED" else 2
    except (PaperProbeError, OSError, TypeError, ValueError):
        print("paper-account: check rejected; verify literal PAPER credentials and separate safe output paths", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
