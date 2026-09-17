"""Bounded, resumable capture cache; no providers or canonical imports.

Adoption pins bytes at first observation, not at their original provider
retrieval. The caller owns exclusive locking and the permitted output root.
"""
from __future__ import annotations

import copy
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable


MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 1000
CSV_COLUMNS = ("date", "open", "high", "low", "close", "adj_close", "volume")
EMPTY_CSV = (",".join(CSV_COLUMNS) + "\n").encode()
SCHEMA_VERSION = "blackpod.sentry_history_recovery.v1"
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._+-]{0,31}$")
_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")


class RecoveryError(ValueError):
    """A recovery input, checkpoint, or path cannot be trusted."""


def _day(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (TypeError, ValueError) as exc:
        raise RecoveryError("date must be canonical YYYY-MM-DD") from exc


def _time(value: str) -> str:
    try:
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if "T" not in value or parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        return value
    except (TypeError, ValueError) as exc:
        raise RecoveryError("timestamp must be an aware ISO8601 value") from exc


def validate_csv(data: bytes, start: str, end: str, allow_empty: bool = False) -> list[dict[str, str]]:
    """Validate canonical raw daily CSV while preserving every supplied cell."""
    first, last = _day(start), _day(end)
    if last < first:
        raise RecoveryError("date range is reversed")
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise RecoveryError("CSV must be bounded bytes")
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""), strict=True)
        if next(reader, None) != list(CSV_COLUMNS):
            raise RecoveryError("CSV header does not match canonical daily columns")
        result: list[dict[str, str]] = []
        previous = None
        for cells in reader:
            if len(cells) != len(CSV_COLUMNS) or len(result) >= MAX_ROWS:
                raise RecoveryError("CSV row width or count is invalid")
            record = dict(zip(CSV_COLUMNS, cells))
            day = _day(record["date"])
            if not first <= day <= last or (previous is not None and day <= previous):
                raise RecoveryError("CSV dates must be unique, increasing, and within request")
            previous = day
            for field in CSV_COLUMNS[1:]:
                text = record[field]
                if field == "adj_close" and text == "":
                    continue
                if not text or len(text) > 128 or not _NUMBER.fullmatch(text):
                    raise RecoveryError("CSV numeric cell is invalid")
                number = Decimal(text)
                if not number.is_finite() or not math.isfinite(float(number)):
                    raise RecoveryError("CSV numeric cell must be finite")
                if field == "volume":
                    if number < 0 or number != number.to_integral_value():
                        raise RecoveryError("CSV volume must be a nonnegative integer")
                elif number <= 0 or float(number) <= 0:
                    raise RecoveryError("CSV prices must be positive")
            result.append(record)
        if not result and not allow_empty:
            raise RecoveryError("empty history is not a completed capture")
        return result
    except (UnicodeError, csv.Error, InvalidOperation, OverflowError) as exc:
        raise RecoveryError("invalid canonical daily CSV") from exc


def _path(path: Path) -> Path:
    value = Path(path).absolute()
    if ".." in value.parts:
        raise RecoveryError("path traversal is not permitted")
    return value


def _directory(path: Path, *, create: bool = False) -> int:
    """Return an anchored directory descriptor; never follow an ancestor link."""
    value = _path(path)
    descriptor = os.open(value.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in value.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _regular(value: os.stat_result) -> None:
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise RecoveryError("only singly linked regular files are permitted")


def read_regular(path: Path, max_bytes: int = MAX_BYTES) -> bytes:
    """Read bounded stable bytes, rejecting symlinks, hard links, and devices."""
    parent = source = None
    try:
        value = _path(path)
        parent = _directory(value.parent)
        source = os.open(value.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(source)
        _regular(before)
        if before.st_size > max_bytes:
            raise RecoveryError("file exceeds configured size limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(source, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(source)
        current = os.stat(value.name, dir_fd=parent, follow_symlinks=False)
        if (len(data) != before.st_size or len(data) > max_bytes
                or _signature(before) != _signature(after)
                or _signature(before) != _signature(current)):
            raise RecoveryError("file changed during read")
        return data
    except OSError as exc:
        raise RecoveryError("file cannot be read safely") from exc
    finally:
        if source is not None:
            os.close(source)
        if parent is not None:
            os.close(parent)


def atomic_write(path: Path, data: bytes) -> None:
    """Atomically replace a file through anchored, no-follow parent descriptors."""
    if not isinstance(data, bytes):
        raise RecoveryError("atomic content must be bytes")
    parent = descriptor = None
    temporary = None
    try:
        value = _path(path)
        if value == Path(value.anchor):
            raise RecoveryError("cannot write a filesystem root")
        parent = _directory(value.parent, create=True)
        try:
            original = os.stat(value.name, dir_fd=parent, follow_symlinks=False)
            _regular(original)
        except FileNotFoundError:
            original = None
        temporary = f".sentry-{secrets.token_hex(16)}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RecoveryError("incomplete atomic file write")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        try:
            current = os.stat(value.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if ((original is None) != (current is None)
                or (original is not None and _signature(original) != _signature(current))):
            raise RecoveryError("atomic target changed during write")
        os.replace(temporary, value.name, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = None
        os.fsync(parent)
    except OSError as exc:
        raise RecoveryError("file cannot be written safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None and parent is not None:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        if parent is not None:
            os.close(parent)


def _json_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise RecoveryError("checkpoint metadata must be finite JSON") from exc


def _fingerprint(value: dict, field: str) -> str:
    return hashlib.sha256(_json_bytes({key: item for key, item in value.items() if key != field})).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError("duplicate checkpoint JSON key")
        result[key] = value
    return result


def _load_json(path: Path, limit: int = MAX_BYTES):
    try:
        return json.loads(read_regular(path, limit), object_pairs_hook=_unique_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(RecoveryError("nonfinite checkpoint JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RecoveryError("invalid checkpoint JSON") from exc


def _text(value: str, limit: int, *, optional: bool = False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise RecoveryError("invalid capture metadata text")
    return value


class CheckpointStore:
    """Pinned per-symbol history. Caller must hold the run's exclusive lock."""

    def __init__(self, root: Path, identity: dict, start: str, end: str,
                 symbols: tuple[str, ...], now: Callable[[], str]):
        self.root = _path(root)
        self.start, self.end = start, end
        if _day(end) < _day(start):
            raise RecoveryError("date range is reversed")
        if (not isinstance(symbols, tuple)
                or any(not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in symbols)
                or len(symbols) != len(set(symbols))):
            raise RecoveryError("symbols must be unique canonical strings")
        if not isinstance(identity, dict) or len(_json_bytes(identity)) > 128 * 1024:
            raise RecoveryError("capture identity must be a bounded JSON object")
        self.identity = json.loads(_json_bytes(identity))
        self.symbols = symbols
        self._request_sha256 = hashlib.sha256(_json_bytes({
            "identity": self.identity, "start": start, "end": end, "symbols": list(symbols),
        })).hexdigest()
        self._known = frozenset(symbols)
        self._now = now
        self._state_path = self.root / "state.json"
        self._entries: dict[str, dict] = {}
        try:
            descriptor = _directory(self.root, create=True)
            try:
                try:
                    os.stat("state.json", dir_fd=descriptor, follow_symlinks=False)
                    exists = True
                except FileNotFoundError:
                    exists = False
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise RecoveryError("checkpoint directory cannot be opened safely") from exc
        if exists:
            self._state = _load_json(self._state_path)
            self._validate_state()
        else:
            try:
                pending = _directory(self.root / "entries")
            except FileNotFoundError:
                pending = None
            except OSError as exc:
                raise RecoveryError("entry directory cannot be opened safely") from exc
            if pending is not None:
                try:
                    if os.listdir(pending):
                        raise RecoveryError("capture entries exist without their request checkpoint")
                finally:
                    os.close(pending)
            timestamp = _time(now())
            self._state = {"schema_version": SCHEMA_VERSION, "identity": self.identity,
                           "start": start, "end": end, "symbols": list(symbols),
                           "entry_storage": "per_symbol_v1", "created_at": timestamp}
            self._save(self._state)
        self._load_entries()

    @property
    def entries(self) -> dict[str, dict]:
        return copy.deepcopy(self._entries)

    def _validate_state(self) -> None:
        state = self._state
        expected = {"schema_version", "identity", "start", "end", "symbols", "entry_storage",
                    "created_at", "state_sha256"}
        if not isinstance(state, dict) or set(state) != expected:
            raise RecoveryError("checkpoint schema is invalid")
        if (state["schema_version"] != SCHEMA_VERSION
                or _json_bytes(state["identity"]) != _json_bytes(self.identity)
                or state["start"] != self.start or state["end"] != self.end
                or state["symbols"] != list(self.symbols) or state["entry_storage"] != "per_symbol_v1"):
            raise RecoveryError("checkpoint request identity does not match")
        if state["state_sha256"] != _fingerprint(state, "state_sha256"):
            raise RecoveryError("checkpoint metadata fingerprint changed")
        _time(state["created_at"])

    def _load_entries(self) -> None:
        try:
            descriptor = _directory(self.root / "entries")
        except FileNotFoundError:
            return
        except OSError as exc:
            raise RecoveryError("entry directory cannot be opened safely") from exc
        try:
            names = os.listdir(descriptor)
        finally:
            os.close(descriptor)
        expected = {self._symbol(symbol).replace(".csv", ".json"): symbol for symbol in self.symbols}
        for name in sorted(names):
            # An interrupted atomic write is not a committed observation.
            if re.fullmatch(r"\.sentry-[0-9a-f]{32}\.tmp", name):
                continue
            symbol = expected.get(name)
            if symbol is None:
                raise RecoveryError("entry directory contains an unknown capture identity")
            self._entries[symbol] = _load_json(self.root / "entries" / name, 32 * 1024)
            self.rows(symbol)

    def _symbol(self, symbol: str) -> str:
        if not isinstance(symbol, str) or symbol not in self._known:
            raise RecoveryError("symbol is outside this capture request")
        return hashlib.sha256(symbol.encode("utf-8")).hexdigest() + ".csv"

    def rows(self, symbol: str) -> list[dict[str, str]] | None:
        file_name = self._symbol(symbol)
        entry = self._entries.get(symbol)
        if symbol not in self._entries:
            return None
        on_disk = _load_json(self.root / "entries" / file_name.replace(".csv", ".json"), 32 * 1024)
        if _json_bytes(on_disk) != _json_bytes(entry):
            raise RecoveryError("capture entry changed after checkpoint loading")
        expected = {"status", "symbol", "file_name", "sha256", "byte_size", "row_count", "operation",
                    "source_kind", "source_path", "source_time", "first_seen_at", "reason", "entry_sha256",
                    "request_sha256"}
        if not isinstance(entry, dict) or set(entry) != expected:
            raise RecoveryError("capture entry schema is invalid")
        if entry["entry_sha256"] != _fingerprint(entry, "entry_sha256"):
            raise RecoveryError("capture entry metadata fingerprint changed")
        if (entry["symbol"] != symbol or entry["file_name"] != file_name
                or entry["request_sha256"] != self._request_sha256):
            raise RecoveryError("capture entry symbol identity changed")
        if (not isinstance(entry["status"], str) or entry["status"] not in {"ready", "unavailable"}
                or not isinstance(entry["operation"], str) or entry["operation"] not in {"adopt", "record", "unavailable"}
                or (entry["status"] == "unavailable") != (entry["operation"] == "unavailable")):
            raise RecoveryError("capture entry status is invalid")
        _text(entry["source_kind"], 128)
        _text(entry["source_path"], 4096, optional=True)
        _time(entry["first_seen_at"])
        if entry["source_time"] is not None:
            _time(entry["source_time"])
        unavailable = entry["status"] == "unavailable"
        if unavailable:
            if (entry["source_kind"] != "provider" or entry["source_path"] is not None
                    or not isinstance(entry["reason"], str) or not _CODE.fullmatch(entry["reason"])):
                raise RecoveryError("unavailable reason must be a bounded class code")
        elif entry["reason"] is not None:
            raise RecoveryError("ready capture must not have an unavailable reason")
        data = read_regular(self.root / "cache" / file_name)
        if (type(entry["byte_size"]) is not int or type(entry["row_count"]) is not int
                or entry["byte_size"] != len(data) or entry["sha256"] != hashlib.sha256(data).hexdigest()):
            raise RecoveryError("capture bytes or size fingerprint changed")
        rows = validate_csv(data, self.start, self.end, allow_empty=unavailable)
        if len(rows) != entry["row_count"] or (unavailable and data != EMPTY_CSV):
            raise RecoveryError("capture row count or unavailable payload changed")
        return rows

    def adopt(self, symbol: str, data: bytes, source_kind: str,
              source_path: str | None = None, source_time: str | None = None) -> dict:
        """Pin existing validated bytes; first_seen_at is not provider retrieval time."""
        return self._capture(symbol, data, "adopt", source_kind, source_path, source_time, None)

    def record(self, symbol: str, data: bytes, source_kind: str = "provider",
               source_path: str | None = None, source_time: str | None = None) -> dict:
        return self._capture(symbol, data, "record", source_kind, source_path, source_time, None)

    def record_unavailable(self, symbol: str, reason: str, source_time: str | None = None) -> dict:
        """Caller must first establish repeated explicit provider unavailability."""
        if not isinstance(reason, str) or not _CODE.fullmatch(reason):
            raise RecoveryError("unavailable reason must be a bounded class code")
        return self._capture(symbol, EMPTY_CSV, "unavailable", "provider", None, source_time, reason)

    def _capture(self, symbol, data, operation, source_kind, source_path, source_time, reason):
        file_name = self._symbol(symbol)
        rows = validate_csv(data, self.start, self.end, allow_empty=operation == "unavailable")
        source_kind = _text(source_kind, 128)
        source_path = _text(source_path, 4096, optional=True)
        if source_time is not None:
            _time(source_time)
        timestamp = _time(self._now())
        entry = {"status": "unavailable" if operation == "unavailable" else "ready",
                 "symbol": symbol, "file_name": file_name, "sha256": hashlib.sha256(data).hexdigest(),
                 "byte_size": len(data), "row_count": len(rows), "operation": operation,
                 "source_kind": source_kind, "source_path": source_path, "source_time": source_time,
                 "first_seen_at": timestamp, "reason": reason, "request_sha256": self._request_sha256}
        prior = self._entries.get(symbol)
        if prior is not None:
            self.rows(symbol)
            entry["first_seen_at"] = prior["first_seen_at"]
            entry["entry_sha256"] = _fingerprint(entry, "entry_sha256")
            if entry != prior:
                raise RecoveryError("completed capture or its source cannot be replaced")
            return copy.deepcopy(prior)
        entry["entry_sha256"] = _fingerprint(entry, "entry_sha256")
        atomic_write(self.root / "cache" / file_name, data)
        # The per-symbol metadata is the commit marker. Keep state.json small
        # and immutable instead of rewriting thousands of entries per capture.
        atomic_write(self.root / "entries" / file_name.replace(".csv", ".json"), _json_bytes(entry) + b"\n")
        self._entries[symbol] = entry
        return copy.deepcopy(entry)

    def _save(self, state: dict) -> None:
        state["state_sha256"] = _fingerprint(state, "state_sha256")
        payload = _json_bytes(state) + b"\n"
        if len(payload) > MAX_BYTES:
            raise RecoveryError("checkpoint exceeds configured size limit")
        atomic_write(self._state_path, payload)
