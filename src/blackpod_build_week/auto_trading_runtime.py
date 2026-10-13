"""Explicit local process control for the guarded Galactica executor.

Importing this module neither imports Alpaca nor starts Galactica. Control
requests and worker receipts are separate from mission and Decision Journal
storage. OFF closes the entry gate, not existing positions or their exits.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
from typing import Callable

from .contracts.mission_request import normalize_rfc3339, parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import _directory, read_regular


PROFILE_SCHEMA = "blackpod.galactica_trading_profile.v1"
LEDGER_SCHEMA = "blackpod.auto_trading_runtime_event.v1"
TRADING_EXECUTION_RECEIPT_V2_SCHEMA = "blackpod.trading_execution_receipt.v2"
MODULE_FILES = (
    "blackwell_navigator_trickle.py", "execution/__init__.py",
    "execution/audit.py", "execution/bias_contract.py", "execution/broker.py",
    "execution/config.py", "execution/indicators.py", "execution/loggers.py",
    "execution/mandate_gate.py", "mandate/enforcer.py",
    "setup/setup_manager.py", "setup/bar_aggregator.py",
)
OPTIONAL_INITIALIZERS = ("mandate/__init__.py", "setup/__init__.py")
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_NATIVE_INT = {"max_positions", "ema_fast", "ema_slow", "max_days", "cooldown_min",
    "cooldown_after_stop_min", "max_trades_per_symbol", "eod_flatten_min",
    "max_consecutive_losses", "flip_flop_limit", "time_lockout_min_if_down",
    "max_orders_per_min", "heartbeat_min", "reload_bias_min", "bias_stale_days"}
_NATIVE_FLOAT = {"min_confidence", "per_trade_usd_cap", "deadband_bps", "stop_loss_pct",
    "take_profit_pct", "daily_stop_pct", "per_symbol_daily_stop_pct",
    "size_reduce_threshold_frac", "size_reduce_factor", "min_conf_for_full_size",
    "min_size_fraction", "mandate_stale_min"}
_NATIVE_BOOL = {"exit_after_close", "position_scale_by_conf", "lock_start_bucket"}


class TradingRuntimeError(ValueError):
    """The declared runtime cannot safely be controlled."""


def _receipt_decimal(value, label, *, positive=False):
    if (not isinstance(value, str) or len(value) > 128
            or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?", value)):
        raise TradingRuntimeError("invalid " + label)
    number = Decimal(value)
    if not number.is_finite() or abs(number) > Decimal("1e20") or (positive and number <= 0):
        raise TradingRuntimeError("invalid " + label)
    return number


def _receipt_broker_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", value):
        raise TradingRuntimeError("invalid " + label)


def validate_execution_receipt_v2(payload, profile, prior):
    """Pure strict v2 validation, shared by runtime replay and offline exporters.

    Post-attempt BLOCKED/AMBIGUOUS observations never erase the original intent.
    Accepted broker IDs are observations, not proof of a realized fill.
    """
    _object(payload, {"schema_version", "session_id", "mode", "recorded_at", "profile_id", "domain", "account_mode",
        "symbol", "side", "qty", "outcome", "reason_code", "order_id", "capital_authorization_id",
        "account_id", "attempt_id", "prior_qty", "client_order_id"}, "v2 broker guard receipt")
    if (payload["schema_version"] != TRADING_EXECUTION_RECEIPT_V2_SCHEMA
            or payload["profile_id"] != profile["profile_id"] or payload["domain"] != "TRADING"
            or payload["mode"] != profile["mode"] or payload["account_mode"] != profile["mode"]
            or payload["account_id"] != profile["account_id"]
            or payload["capital_authorization_id"] != profile["capital_authorization_id"]
            or payload["outcome"] not in {"ATTEMPT", "BLOCKED", "SUBMITTED", "AMBIGUOUS"}
            or payload["side"] not in {"buy", "sell", "close"}
            or not isinstance(payload["symbol"], str) or len(payload["symbol"]) > 64
            or not isinstance(payload["qty"], str) or len(payload["qty"]) > 128
            or not isinstance(payload["reason_code"], str) or not payload["reason_code"] or len(payload["reason_code"]) > 256):
        raise TradingRuntimeError("v2 receipt differs from bound trading profile")
    _identifier(payload["session_id"], "session_id")
    timestamp = parse_rfc3339(payload["recorded_at"], "recorded_at")
    for field in ("order_id", "client_order_id"):
        if payload[field] is not None: _receipt_broker_id(payload[field], field)
    if payload["attempt_id"] is None:
        if (payload["outcome"] != "BLOCKED" or payload["prior_qty"] is not None
                or payload["order_id"] is not None or payload["client_order_id"] is not None):
            raise TradingRuntimeError("only pre-admission BLOCKED may lack an attempt identity")
        return
    _identifier(payload["attempt_id"], "attempt_id")
    prior_qty = _receipt_decimal(payload["prior_qty"], "prior_qty")
    quantity = _receipt_decimal(payload["qty"], "qty", positive=True)
    if ((payload["side"] == "sell" and (prior_qty <= 0 or quantity > prior_qty))
            or (payload["side"] == "buy" and prior_qty < 0 and quantity > -prior_qty)
            or (payload["side"] == "close" and (prior_qty == 0 or quantity != abs(prior_qty)))):
        raise TradingRuntimeError("v2 attempt would reverse or exceed its recorded reduction")
    if payload["symbol"] not in profile["symbols"]:
        raise TradingRuntimeError("admitted attempt must target an owned TRADING symbol")
    related = [event["payload"] for event in prior if event.get("kind") == "BROKER_GUARD"
               and event["payload"].get("schema_version") == TRADING_EXECUTION_RECEIPT_V2_SCHEMA
               and event["payload"].get("attempt_id") == payload["attempt_id"]]
    if payload["outcome"] == "ATTEMPT":
        if related or payload["order_id"] is not None:
            raise TradingRuntimeError("ATTEMPT must be unique and precede broker acceptance")
        return
    originals = [item for item in related if item["outcome"] == "ATTEMPT"]
    if len(originals) != 1:
        raise TradingRuntimeError("v2 result requires one retained original ATTEMPT")
    original = originals[0]
    fixed = ("attempt_id", "session_id", "profile_id", "mode", "account_mode", "account_id", "domain",
             "capital_authorization_id", "symbol", "side", "qty", "prior_qty")
    if any(payload[field] != original[field] for field in fixed):
        raise TradingRuntimeError("v2 result changed the original attempt binding")
    if timestamp < parse_rfc3339(original["recorded_at"], "original recorded_at"):
        raise TradingRuntimeError("v2 result timestamp precedes its original attempt")
    if any(item["outcome"] == payload["outcome"] for item in related):
        raise TradingRuntimeError("duplicate v2 result for the same attempt")
    if payload["outcome"] == "SUBMITTED":
        if payload["order_id"] is None or any(item["outcome"] != "ATTEMPT" for item in related):
            raise TradingRuntimeError("SUBMITTED must record the first result and an exact broker ID")
        if original["client_order_id"] is not None and payload["client_order_id"] != original["client_order_id"]:
            raise TradingRuntimeError("returned client order ID conflicts with precommitted identity")
    for item in related:
        if item["order_id"] is not None and payload["order_id"] != item["order_id"]:
            raise TradingRuntimeError("v2 result cannot discard or replace a known broker ID")
        if item["client_order_id"] is not None and payload["client_order_id"] != item["client_order_id"]:
            raise TradingRuntimeError("v2 result cannot discard or replace a known client order ID")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _object(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise TradingRuntimeError(f"{label} has missing or unknown fields")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise TradingRuntimeError(f"invalid {label}")
    return value


def _absolute(value, label):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise TradingRuntimeError(f"invalid {label}")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise TradingRuntimeError(f"{label} must be an absolute path without traversal")
    return path


def _money(value, label, *, maximum=None):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,8})?", value):
        raise TradingRuntimeError(f"{label} must be a positive decimal string")
    try:
        number = Decimal(value)
        if number <= 0 or number > Decimal("1000000000000") or (maximum is not None and number > maximum):
            raise TradingRuntimeError(f"invalid {label}")
        return number
    except InvalidOperation as exc:
        raise TradingRuntimeError(f"invalid {label}") from exc


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise TradingRuntimeError("duplicate JSON key")
        value[key] = item
    return value


def read_json(path):
    try:
        return json.loads(read_regular(Path(path)), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(TradingRuntimeError("nonfinite JSON")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TradingRuntimeError("invalid JSON") from exc


def source_manifest(root: Path) -> dict[str, str | None]:
    """Read only the blessed executor's import closure; no secret files."""
    root = _absolute(str(root), "galactica_root")
    result = {name: sha256_bytes(read_regular(root / name)) for name in MODULE_FILES}
    for name in OPTIONAL_INITIALIZERS:
        result[name] = sha256_bytes(read_regular(root / name)) if (root / name).exists() else None
        if (root / name).is_symlink():
            raise TradingRuntimeError("source initializer may not be a link")
    return result


def validate_profile(value: dict, *, verify_files: bool = True) -> dict:
    fields = {"schema_version", "profile_id", "mode", "galactica_root", "python_executable",
        "source_hashes", "symbols", "protected_symbols", "account_scope", "account_id",
        "capital_authorization_id", "trading_budget_usd", "max_account_gross_usd",
        "max_order_notional_usd", "price_max_age_seconds", "price_buffer_fraction",
        "authorization_expires_at", "frozen_inputs", "native_settings"}
    _object(value, fields, "runtime profile")
    if value["schema_version"] != PROFILE_SCHEMA or value["mode"] not in {"PAPER", "LIVE"}:
        raise TradingRuntimeError("invalid runtime schema or account mode")
    for field in ("profile_id", "account_id", "capital_authorization_id"):
        _identifier(value[field], field)
    root = _absolute(value["galactica_root"], "galactica_root")
    executable = _absolute(value["python_executable"], "python_executable")
    hashes = _object(value["source_hashes"], (*MODULE_FILES, *OPTIONAL_INITIALIZERS), "source_hashes")
    for path, digest in hashes.items():
        if not (isinstance(digest, str) and _SHA.fullmatch(digest)) and not (path in OPTIONAL_INITIALIZERS and digest is None):
            raise TradingRuntimeError("invalid source hash")
    for field in ("symbols", "protected_symbols"):
        values = value[field]
        if (not isinstance(values, list) or len(values) > 100
                or any(not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in values)
                or len(values) != len(set(values))):
            raise TradingRuntimeError("symbols must be unique uppercase equity symbols")
    if not value["symbols"] or set(value["symbols"]) & set(value["protected_symbols"]):
        raise TradingRuntimeError("trading and investment symbols must be disjoint")
    if value["account_scope"] not in {"DEDICATED_TRADING", "SHARED_DISJOINT"}:
        raise TradingRuntimeError("unsupported account ownership scope")
    if value["account_scope"] == "DEDICATED_TRADING" and value["protected_symbols"]:
        raise TradingRuntimeError("dedicated trading account cannot declare investment holdings")
    budget = _money(value["trading_budget_usd"], "trading_budget_usd")
    gross = _money(value["max_account_gross_usd"], "max_account_gross_usd")
    order = _money(value["max_order_notional_usd"], "max_order_notional_usd")
    if order > budget or budget > gross:
        raise TradingRuntimeError("order cap <= fixed trading budget <= account gross cap required")
    _money(value["price_buffer_fraction"], "price_buffer_fraction", maximum=Decimal("1"))
    if type(value["price_max_age_seconds"]) is not int or not 1 <= value["price_max_age_seconds"] <= 300:
        raise TradingRuntimeError("price freshness must be 1..300 seconds")
    normalize_rfc3339(value["authorization_expires_at"], "authorization_expires_at")
    _object(value["frozen_inputs"], {"bias_csv", "mandate_path"}, "frozen_inputs")
    for name, item in value["frozen_inputs"].items():
        _object(item, {"path", "sha256"}, name)
        path = _absolute(item["path"], name)
        if not isinstance(item["sha256"], str) or not _SHA.fullmatch(item["sha256"]):
            raise TradingRuntimeError("invalid input hash")
        if verify_files and sha256_bytes(read_regular(path)) != item["sha256"]:
            raise TradingRuntimeError("frozen input hash mismatch")
    settings = value["native_settings"]
    if not isinstance(settings, dict) or set(settings) - (_NATIVE_INT | _NATIVE_FLOAT | _NATIVE_BOOL):
        raise TradingRuntimeError("unsupported native settings; execution/credentials/recruits cannot be overridden")
    for key, item in settings.items():
        if key in _NATIVE_INT:
            valid = type(item) is int and 0 <= item <= 100000
        elif key in _NATIVE_BOOL:
            valid = type(item) is bool
        else:
            valid = (type(item) in {int, float} and Decimal(str(item)).is_finite()
                     and 0 < Decimal(str(item)) <= Decimal("1000000000"))
        if not valid:
            raise TradingRuntimeError(f"invalid native setting {key}")
    if settings.get("eod_flatten_min", 15) <= 0 or settings.get("exit_after_close", True) is not True:
        raise TradingRuntimeError("protective EOD behavior must remain enabled")
    if Decimal(str(settings.get("per_trade_usd_cap", 2000))) > order:
        raise TradingRuntimeError("native per-trade cap exceeds guardian cap; supply explicit lower cap")
    if verify_files:
        if source_manifest(root) != hashes:
            raise TradingRuntimeError("Galactica source hash mismatch")
        # Virtualenv executables commonly link to a base interpreter. Never
        # execute here; the explicitly hash-confirmed profile selects it.
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise TradingRuntimeError("declared Python executable is unavailable")
    return json.loads(canonical_json_bytes(value))


def profile_hash(profile) -> str:
    return sha256_bytes(canonical_json_bytes(profile))


def _immutable(path: Path, raw: bytes):
    """Publish a durable new file, never replace an existing identity."""
    parent = _directory(path.parent, create=True)
    try:
        _recover_publication(parent)
    except BaseException:
        os.close(parent)
        raise
    temporary = ".runtime-" + secrets.token_hex(16) + ".tmp"
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        view = memoryview(raw)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise TradingRuntimeError("incomplete runtime write")
            view = view[count:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            os.link(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
        except FileExistsError:
            # Remove temporary before reading: retained targets must have one link.
            os.unlink(temporary, dir_fd=parent)
            temporary = None
            if read_regular(path) != raw:
                raise TradingRuntimeError("immutable runtime identity conflict")
        else:
            os.unlink(temporary, dir_fd=parent)
            temporary = None
        os.fsync(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)


def _recover_publication(parent):
    """Recover our staged writes under the caller's exclusive writer lock.

    A published hard link may survive a crash before its staging link was
    removed. Only that exact same inode is unlinked; arbitrary hard links,
    unexpected files and chain damage are never repaired or overwritten.
    """
    names = os.listdir(parent)
    staged = [name for name in names if re.fullmatch(r"\.runtime-[a-f0-9]{32}\.tmp", name)]
    for name in staged:
        metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink not in {1, 2}:
            raise TradingRuntimeError("unsafe interrupted runtime write")
        linked = [other for other in names if other != name
                  and (lambda current: (current.st_dev, current.st_ino) == (metadata.st_dev, metadata.st_ino))(
                      os.stat(other, dir_fd=parent, follow_symlinks=False))]
        if metadata.st_nlink == 2 and len(linked) != 1:
            raise TradingRuntimeError("interrupted link cannot be recovered safely")
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)


class RuntimeLedger:
    """Local POSIX hash chain; no credentials or raw broker errors retained."""
    def __init__(self, root: Path):
        self.root = _absolute(str(Path(root).absolute()), "runtime_root")
        # Reuse the established read-only path protection, without opening or
        # creating a journal. Runtime output must never inhabit source storage.
        from .decision_journal_store import JournalStoreError, _check_existing_ancestors, _reject_source_storage
        try:
            _check_existing_ancestors(self.root)
            _reject_source_storage(self.root)
        except JournalStoreError as exc:
            raise TradingRuntimeError("runtime root overlaps source storage or is unsafe") from exc
        for ancestor in (self.root, *self.root.parents):
            if (ancestor / ".journal.lock").exists():
                raise TradingRuntimeError("runtime and Decision Journal storage must be separate")
            if (ancestor / "blackwell_navigator_trickle.py").exists():
                raise TradingRuntimeError("runtime cannot write inside Galactica source storage")
        if (self.root / ".git").exists():
            raise TradingRuntimeError("runtime root cannot be a repository root")

    @contextmanager
    def lock(self, name="ledger.lock", *, nonblocking=False):
        parent = _directory(self.root, create=True)
        descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        os.close(parent)
        try:
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise TradingRuntimeError("unsafe runtime lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            yield descriptor
        finally:
            os.close(descriptor)

    def worker_active(self) -> bool:
        # Status is read-only, including when the runtime root is absent.
        try:
            parent = _directory(self.root)
        except FileNotFoundError:
            return False
        descriptor = None
        try:
            try:
                descriptor = os.open("worker.lock", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                return False
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise TradingRuntimeError("unsafe worker lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent)

    def events(self) -> list[dict]:
        path = self.root / "events"
        if not path.exists():
            if path.is_symlink():
                raise TradingRuntimeError("unsafe event directory")
            return []
        parent = _directory(path)
        try:
            names = os.listdir(parent)
        finally:
            os.close(parent)
        names = sorted(name for name in names if not name.startswith(".runtime-"))
        if len(names) > 100000:
            raise TradingRuntimeError("runtime event count exceeds local bound")
        result = []
        previous = None
        for sequence, name in enumerate(names, 1):
            if name != f"{sequence:012d}.json":
                raise TradingRuntimeError("runtime chain gap or unexpected file")
            raw = read_regular(path / name)
            item = read_json(path / name)
            _object(item, {"schema_version", "sequence", "previous_sha256", "event_sha256", "kind", "payload"}, "runtime event")
            unsigned = {key: value for key, value in item.items() if key != "event_sha256"}
            if (item["schema_version"] != LEDGER_SCHEMA or type(item["sequence"]) is not int
                    or item["sequence"] != sequence or item["previous_sha256"] != previous
                    or item["event_sha256"] != sha256_bytes(canonical_json_bytes(unsigned))
                    or item["kind"] not in {"CONTROL", "WORKER_STATUS", "BROKER_GUARD"}
                    or canonical_json_bytes(item) != raw):
                raise TradingRuntimeError("runtime chain hash or structure mismatch")
            self._validate_candidate(item, result)
            result.append(item)
            previous = item["event_sha256"]
        return result

    def recover(self):
        """Explicit writer recovery; status/entry reads never mutate evidence."""
        with self.lock():
            for name in ("profiles", "events"):
                if (self.root / name).exists():
                    parent = _directory(self.root / name)
                    try:
                        _recover_publication(parent)
                    finally:
                        os.close(parent)
            self.events()  # Recovery cannot silently accept other chain damage.

    def append(self, kind, payload):
        with self.lock():
            if (self.root / "events").exists():
                parent = _directory(self.root / "events")
                try:
                    _recover_publication(parent)
                finally:
                    os.close(parent)
            events = self.events()
            unsigned = {"schema_version": LEDGER_SCHEMA, "sequence": len(events) + 1,
                "previous_sha256": events[-1]["event_sha256"] if events else None,
                "kind": kind, "payload": payload}
            event = {**unsigned, "event_sha256": sha256_bytes(canonical_json_bytes(unsigned))}
            if kind not in {"CONTROL", "WORKER_STATUS", "BROKER_GUARD"}:
                raise TradingRuntimeError("unknown runtime event kind")
            # Validate using the same replay path before publication. No live
            # side effect may depend on a structurally invalid control.
            self._validate_candidate(event, events)
            _immutable(self.root / "events" / f"{len(events)+1:012d}.json", canonical_json_bytes(event))
            return event

    def _validate_candidate(self, event, prior):
        payload = event["payload"]
        if event["kind"] == "CONTROL":
            _object(payload, {"action_id", "session_id", "profile_sha256", "entries_enabled", "recorded_at", "operator_id"}, "control")
            for field in ("action_id", "session_id", "operator_id"):
                _identifier(payload[field], field)
            if (type(payload["entries_enabled"]) is not bool or not isinstance(payload["profile_sha256"], str)
                    or not _SHA.fullmatch(payload["profile_sha256"])):
                raise TradingRuntimeError("invalid runtime control")
            normalize_rfc3339(payload["recorded_at"], "recorded_at")
            if any(old["kind"] == "CONTROL" and old["payload"]["action_id"] == payload["action_id"] for old in prior):
                raise TradingRuntimeError("duplicate runtime action identity")
            if payload["entries_enabled"]:
                profile = read_json(self.root / "profiles" / f"{payload['profile_sha256']}.json")
                validate_profile(profile, verify_files=False)
                if profile_hash(profile) != payload["profile_sha256"]:
                    raise TradingRuntimeError("retained profile hash mismatch")
        else:
            if not isinstance(payload, dict):
                raise TradingRuntimeError("invalid runtime receipt")
            _identifier(payload.get("session_id"), "session_id")
            normalize_rfc3339(payload.get("recorded_at"), "recorded_at")
            bound = next((old["payload"] for old in prior if old["kind"] == "CONTROL"
                          and old["payload"]["session_id"] == payload["session_id"] and old["payload"]["entries_enabled"]), None)
            if bound is None:
                raise TradingRuntimeError("worker receipt requires a prior startup request")
            profile = read_json(self.root / "profiles" / f"{bound['profile_sha256']}.json")
            if payload.get("mode") != profile["mode"]:
                raise TradingRuntimeError("worker receipt mode mismatch")
            if event["kind"] == "WORKER_STATUS":
                if (set(payload) - {"session_id", "mode", "recorded_at", "state", "error_type", "manual_position_check_required", "auto_restart_enabled"}
                        or payload.get("state") not in {"STARTING", "RUNNING", "DRAINING", "STOPPED", "FAILED", "START_FAILED"}
                        or payload.get("auto_restart_enabled", False) is not False):
                    raise TradingRuntimeError("invalid worker status")
                states = [old["payload"]["state"] for old in prior if old["kind"] == "WORKER_STATUS"
                          and old["payload"]["session_id"] == payload["session_id"]]
                if states and states[-1] in {"STOPPED", "FAILED", "START_FAILED"}:
                    raise TradingRuntimeError("finished worker cannot restart under the same session")
                allowed = {
                    None: {"STARTING", "START_FAILED"},
                    "STARTING": {"RUNNING", "FAILED"},
                    "RUNNING": {"DRAINING", "STOPPED", "FAILED"},
                    "DRAINING": {"DRAINING", "STOPPED", "FAILED"},
                }
                if payload["state"] not in allowed.get(states[-1] if states else None, set()):
                    raise TradingRuntimeError("invalid worker lifecycle transition")
            else:
                if "schema_version" in payload:
                    validate_execution_receipt_v2(payload, profile, prior)
                    return
                _object(payload, {"session_id", "mode", "recorded_at", "profile_id", "domain", "account_mode",
                    "symbol", "side", "qty", "outcome", "reason_code", "order_id", "capital_authorization_id"}, "broker guard receipt")
                if (payload["profile_id"] != profile["profile_id"] or payload["domain"] != "TRADING"
                        or payload["account_mode"] != profile["mode"]
                        or payload["capital_authorization_id"] != profile["capital_authorization_id"]
                        or payload["outcome"] not in {"ATTEMPT", "BLOCKED", "SUBMITTED"}
                        or payload["side"] not in {"buy", "sell", "close"}
                        or not isinstance(payload["symbol"], str)
                        or not isinstance(payload["qty"], str) or len(payload["qty"]) > 128
                        or not isinstance(payload["reason_code"], str) or len(payload["reason_code"]) > 256
                        or (payload["order_id"] is not None and (not isinstance(payload["order_id"], str) or len(payload["order_id"]) > 128))):
                    raise TradingRuntimeError("broker guard receipt differs from bound trading profile")

    def latest_control(self):
        return next((event["payload"] for event in reversed(self.events()) if event["kind"] == "CONTROL"), None)

    def entries_enabled(self, session_id, profile, *, now: Callable[[], str] = utc_now) -> bool:
        try:
            control = self.latest_control()
            if (not control or not control["entries_enabled"] or control["session_id"] != session_id
                    or control["profile_sha256"] != profile_hash(profile)
                    or parse_rfc3339(now(), "now") >= parse_rfc3339(profile["authorization_expires_at"], "expiry")):
                return False
            validate_profile(profile)
            return True
        except (ValueError, OSError, TypeError):
            return False


def runtime_status(root: Path) -> dict:
    ledger = RuntimeLedger(root)
    control = ledger.latest_control()
    active = ledger.worker_active() if ledger.root.exists() else False
    worker = next((event["payload"] for event in reversed(ledger.events())
                   if event["kind"] == "WORKER_STATUS" and control
                   and event["payload"].get("session_id") == control["session_id"]), None)
    enabled = False
    if active and control and worker and worker.get("state") == "RUNNING":
        profile = read_json(ledger.root / "profiles" / f"{control['profile_sha256']}.json")
        enabled = ledger.entries_enabled(control["session_id"], profile)
    return {"requested_entries_enabled": bool(control and control["entries_enabled"]),
        "entries_enabled": enabled, "worker_active": active,
        "state": "ON" if enabled else "DRAINING" if active else "OFF",
        "session_id": control["session_id"] if control else None,
        "worker_state": worker.get("state") if worker else None,
        "investment_approval_applies": False, "capital_transfers_permitted": False,
        "auto_restart_enabled": False,
        "mode": worker.get("mode") if worker else None,
        "pending_orders_cancelled": False}


def account_lock_name(profile):
    return sha256_bytes(canonical_json_bytes({"mode": profile["mode"], "account_id": profile["account_id"]})) + ".lock"


def snapshot_execution_profile(ledger, session_id, profile):
    """Retain exactly checked source/input bytes before any native import.

    This derived profile changes paths only. The immutable original profile
    remains the control's authorization; its live pins still close entry on
    change. Importing the original mutable source directory is unnecessary.
    """
    snapshot = ledger.root / "sessions" / session_id / "snapshot"
    derived = json.loads(canonical_json_bytes(profile))
    native = snapshot / "native"
    for name, digest in profile["source_hashes"].items():
        if digest is None:
            if (Path(profile["galactica_root"]) / name).exists():
                raise TradingRuntimeError("unapproved source initializer appeared")
            continue
        raw = read_regular(Path(profile["galactica_root"]) / name)
        if sha256_bytes(raw) != digest:
            raise TradingRuntimeError("source changed before snapshot")
        _immutable(native / name, raw)
    derived["galactica_root"] = str(native)
    for name, item in profile["frozen_inputs"].items():
        raw = read_regular(Path(item["path"]))
        if sha256_bytes(raw) != item["sha256"]:
            raise TradingRuntimeError("input changed before snapshot")
        target = snapshot / "inputs" / ("bias.csv" if name == "bias_csv" else "mandate.json")
        _immutable(target, raw)
        derived["frozen_inputs"][name]["path"] = str(target)
    validate_profile(derived)
    _immutable(snapshot / "execution_profile.json", canonical_json_bytes(derived))
    # Pin this checkout's guard implementation as provenance as well.
    implementation = {name: sha256_bytes(read_regular(Path(__file__).parent / name))
                      for name in ("auto_trading_runtime.py", "auto_trading_worker.py", "galactica_trading_adapter.py")}
    _immutable(snapshot / "guard_implementation.json", canonical_json_bytes(implementation))
    return derived


@contextmanager
def account_lock(profile, *, inherited_descriptor=None):
    """One managed worker/account across runtime roots on this local user/host.

    The launch descriptor is inherited by the child so there is no unlocked
    gap between admission and worker startup. External executors cannot be
    coordinated by a local file lock and must not share this owned book.
    """
    path = Path("/private/tmp") / ("blackpod-auto-trading-" + str(os.getuid()))
    parent = _directory(path, create=True)
    descriptor = None
    try:
        metadata = os.fstat(parent)
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise TradingRuntimeError("account-lock root must be private and owned by this user")
        name = account_lock_name(profile)
        if inherited_descriptor is not None:
            descriptor = inherited_descriptor
            expected = os.stat(name, dir_fd=parent, follow_symlinks=False)
            current = os.fstat(descriptor)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_uid != os.getuid()
                    or (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino)):
                raise TradingRuntimeError("invalid inherited account admission lock")
        else:
            descriptor = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or current.st_uid != os.getuid():
                raise TradingRuntimeError("invalid account admission lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TradingRuntimeError("another managed worker already owns this account") from exc
        yield descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def enable_trading(root: Path, profile: dict, *, action_id: str, operator_id: str,
                   confirm_profile_sha256: str, confirm_account_id: str, confirm_mode: str,
                   now: Callable[[], str] = utc_now, spawn: Callable = subprocess.Popen) -> dict:
    """Explicit activation only. Tests inject spawn; normal CLI starts the worker."""
    profile = validate_profile(profile)
    if profile["mode"] != "PAPER":
        raise TradingRuntimeError("funded activation requires a separately governed execution path")
    digest = profile_hash(profile)
    if (confirm_profile_sha256 != digest or confirm_account_id != profile["account_id"]
            or confirm_mode != profile["mode"]):
        raise TradingRuntimeError("confirmation must match exact profile hash, account ID and mode")
    for field, value in (("action_id", action_id), ("operator_id", operator_id)):
        _identifier(value, field)
    if action_id.startswith("runtime-internal-"):
        raise TradingRuntimeError("action ID uses a reserved internal namespace")
    timestamp = normalize_rfc3339(now(), "recorded_at")
    if parse_rfc3339(timestamp, "now") >= parse_rfc3339(profile["authorization_expires_at"], "expiry"):
        raise TradingRuntimeError("capital authorization has expired")
    ledger = RuntimeLedger(root)
    for path in (Path(profile["galactica_root"]), *(Path(item["path"]) for item in profile["frozen_inputs"].values())):
        if ledger.root == path or ledger.root in path.parents or path in ledger.root.parents:
            raise TradingRuntimeError("runtime storage must be separate from source and frozen inputs")
    with ledger.lock("controller.lock"):
        ledger.recover()
        controls = [event["payload"] for event in ledger.events() if event["kind"] == "CONTROL"]
        previous = next((control for control in controls if control["action_id"] == action_id), None)
        if previous:
            if (not previous["entries_enabled"] or previous["profile_sha256"] != digest
                    or previous["operator_id"] != operator_id):
                raise TradingRuntimeError("action identity conflict")
            return {"written": False, "spawned": False, "session_id": previous["session_id"]}
        if ledger.worker_active() or (controls and controls[-1]["entries_enabled"]):
            raise TradingRuntimeError("worker active or prior startup unresolved; request OFF before a new start")
        _immutable(ledger.root / "profiles" / f"{digest}.json", canonical_json_bytes(profile))
        session_id = "session-" + sha256_bytes(canonical_json_bytes({"action_id": action_id, "profile_sha256": digest}))
        ledger.append("CONTROL", {"action_id": action_id, "session_id": session_id, "profile_sha256": digest,
            "entries_enabled": True, "recorded_at": timestamp, "operator_id": operator_id})
        output_root = ledger.root / "sessions" / session_id
        descriptor = _directory(output_root, create=True)
        os.close(descriptor)
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["ALPACA_PAPER"] = "true" if profile["mode"] == "PAPER" else "false"
        # No shell, credentials are inherited directly and never formatted.
        output_parent = _directory(output_root)
        output_fd = os.open("worker.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=output_parent)
        os.close(output_parent)
        try:
            with account_lock(profile) as admission:
                process = spawn([profile["python_executable"], "-P", "-m", "blackpod_build_week.auto_trading_worker",
                    "--runtime-root", str(ledger.root), "--session-id", session_id,
                    "--account-lock-fd", str(admission)],
                    cwd=output_root, env=env, stdin=subprocess.DEVNULL, stdout=output_fd,
                    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                    pass_fds=(admission,))
        except Exception:
            close_session_entry_gate(ledger, session_id)
            ledger.append("WORKER_STATUS", {"session_id": session_id, "state": "START_FAILED", "mode": profile["mode"], "recorded_at": timestamp})
            raise TradingRuntimeError("worker launch failed; entry gate closed") from None
        finally:
            os.close(output_fd)
        return {"written": True, "spawned": True, "session_id": session_id,
                "pid": process.pid, "state": "START_REQUESTED", "mode": profile["mode"]}


def disable_trading(root: Path, *, action_id: str, operator_id: str, now: Callable[[], str] = utc_now) -> dict:
    """Close entries; do not kill exits, submit closes, or cancel pending orders."""
    _identifier(action_id, "action_id")
    if action_id.startswith("runtime-internal-"):
        raise TradingRuntimeError("action ID uses a reserved internal namespace")
    _identifier(operator_id, "operator_id")
    ledger = RuntimeLedger(root)
    with ledger.lock("controller.lock"):
        ledger.recover()
        controls = [event["payload"] for event in ledger.events() if event["kind"] == "CONTROL"]
        previous = next((control for control in controls if control["action_id"] == action_id), None)
        if previous:
            if previous["entries_enabled"] or previous["operator_id"] != operator_id:
                raise TradingRuntimeError("action identity conflict")
            return {"written": False, "state": "OFF_REQUESTED"}
        current = controls[-1] if controls else None
        with ledger.lock("submission.lock"):
            ledger.append("CONTROL", {"action_id": action_id, "operator_id": operator_id,
                "recorded_at": normalize_rfc3339(now(), "recorded_at"), "entries_enabled": False,
                "profile_sha256": current["profile_sha256"] if current else "0"*64,
                "session_id": current["session_id"] if current else "no-session"})
        return {"written": True, "state": "OFF_REQUESTED", "exits_retained": True,
                "pending_orders_cancelled": False, "positions_closed": False}


def close_session_entry_gate(ledger, session_id):
    """Close only this finished session; never disable a later replacement."""
    with ledger.lock("submission.lock"):
        current = ledger.latest_control()
        if not current or current["session_id"] != session_id or not current["entries_enabled"]:
            return
        failure_id = "runtime-internal-" + sha256_bytes(canonical_json_bytes({"finished_session_id": session_id}))
        ledger.append("CONTROL", {**current, "action_id": failure_id, "recorded_at": utc_now(), "entries_enabled": False})
