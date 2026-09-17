"""Optional, read-only presentation of an explicitly selected Sentry archive.

Only Battlestar's pure snapshot contract is loaded. No Sentry engine, data
provider, package initializer, scheduler, or mission runner is imported.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import io
import math
import os
import re
import stat
import sys
import threading
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes


SCHEMA_VERSION = "blackpod.sentry_feed.v1"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_ROW_BYTES = 256 * 1024
MAX_ROWS = 1000
MAX_MODEL_BYTES = 512 * 1024
MAX_JSON_DEPTH = 32
MAX_SAFE_INTEGER = 2**53 - 1
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,14}$")
_MODEL_IMPORTS = frozenset({"__future__", "dataclasses", "datetime", "enum", "math", "typing"})
_CONFIG_MESSAGE = "Sentry requires archive, source kind, source label, and canonical root together."


class SentrySourceError(ValueError):
    """An archive or its canonical contract cannot be read safely."""


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_identity(value: os.stat_result) -> tuple:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_regular(path: Path, limit: int) -> bytes:
    """Capture bounded bytes without following any path-component symlink."""
    absolute = path.absolute()
    if ".." in absolute.parts:
        raise SentrySourceError("source path must be normalized")
    descriptors: list[int] = []
    try:
        descriptor = os.open(absolute.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in absolute.parts[1:-1]:
            descriptor = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        source = os.open(absolute.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(source)
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise SentrySourceError("source is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(source, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(source)
        current = os.stat(absolute.name, dir_fd=descriptor, follow_symlinks=False)
        payload = b"".join(chunks)
        if len(payload) > limit or len(payload) != before.st_size or (
            _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(current)
        ):
            raise SentrySourceError("source changed during capture")
        return payload
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _canonical_validator(root: Path) -> Callable[[dict], object]:
    """Load the explicit canonical pure module, never its package or bytecode.

    The configured canonical checkout is trusted application code, not input
    supplied through HTTP. The import allowlist additionally fails closed if
    this formerly pure contract acquires engine/provider dependencies.
    """
    path = root / "microcap_sentry" / "models.py"
    source = _read_regular(path, MAX_MODEL_BYTES)
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(item.name not in _MODEL_IMPORTS for item in node.names):
                raise SentrySourceError("canonical contract has unsupported dependencies")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in _MODEL_IMPORTS:
                raise SentrySourceError("canonical contract has unsupported dependencies")
    name = "_cabin_canonical_sentry_contract_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(path)
    # dataclasses needs its defining module registered during class creation.
    # compile/exec avoids importlib's bytecode cache and package initialization.
    sys.modules[name] = module
    try:
        exec(compile(tree, str(path), "exec"), module.__dict__)
        validator = module.SentrySnapshot.from_dict
        if module.SNAPSHOT_SCHEMA_VERSION != "microcap_sentry.snapshot.v1" or not callable(validator):
            raise SentrySourceError("canonical snapshot contract is unsupported")
        return validator
    finally:
        sys.modules.pop(name, None)


def _safe_json_tree(value: object, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise SentrySourceError("snapshot is too deeply nested")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > 4000:
            raise SentrySourceError("snapshot text exceeds its display limit")
        value.encode("utf-8", errors="strict")
        return
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise SentrySourceError("snapshot integer cannot be represented safely")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SentrySourceError("snapshot number must be finite")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _safe_json_tree(key, depth + 1)
            _safe_json_tree(item, depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 1000:
            raise SentrySourceError("snapshot sequence exceeds its display limit")
        for item in value:
            _safe_json_tree(item, depth + 1)
        return
    raise SentrySourceError("snapshot has an unsupported value")


def _observed_at(record: dict) -> datetime:
    # Canonical datetime serialization preserves at most microsecond precision.
    return parse_rfc3339(record.get("observed_at"), "observed_at")


class SentryReader:
    """Validate on every poll; never write, synthesize, or retain stale results."""

    def __init__(
        self, archive: Path | None = None, source_kind: str | None = None,
        source_label: str | None = None, canonical_root: Path | None = None,
        *, validator: Callable[[dict], object] | None = None,
    ):
        fields = (archive, source_kind, source_label, canonical_root)
        if any(value is not None for value in fields) and not all(value is not None for value in fields):
            raise ValueError(_CONFIG_MESSAGE)
        if archive is not None:
            if source_kind not in {"research", "recorded"}:
                raise ValueError("Sentry source kind must be research or recorded.")
            if not isinstance(source_label, str) or not source_label.strip() or len(source_label) > 120 or any(
                ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in source_label
            ):
                raise ValueError("Sentry source label must be a short display label, not a path.")
            file_name = Path(archive).name
            if not file_name or len(file_name) > 255 or ".." in file_name or "\\" in file_name or any(
                ord(char) < 32 or ord(char) == 127 for char in file_name
            ):
                raise ValueError("Sentry archive must have a safe file name.")
            file_name.encode("utf-8", errors="strict")
            source_label.encode("utf-8", errors="strict")
        self.archive = None if archive is None else Path(archive)
        self.source_kind = None if source_kind is None else source_kind.upper()
        self.source_label = source_label
        self.canonical_root = None if canonical_root is None else Path(canonical_root)
        self._validator = validator
        self._lock = threading.Lock()

    def current(self) -> dict:
        with self._lock:
            checked_at = datetime.now(timezone.utc)
            envelope = {
                "schema_version": SCHEMA_VERSION,
                "checked_at": _stamp(checked_at),
                "source": None, "observations": [],
            }
            if self.archive is None:
                return {**envelope, "status": "NOT_CONFIGURED", "message": "No Sentry observation archive is configured. No scan is running."}
            try:
                if self._validator is None:
                    self._validator = _canonical_validator(self.canonical_root)
                payload = _read_regular(self.archive, MAX_ARCHIVE_BYTES)
                seen: dict[str, bytes] = {}
                observations: list[tuple[datetime, dict]] = []
                raw_count = 0
                # readline bounds both line allocation and row count, even for
                # an archive consisting entirely of newline characters.
                stream = io.BytesIO(payload)
                while line := stream.readline(MAX_ROW_BYTES + 2):
                    raw_count += 1
                    if raw_count > MAX_ROWS or len(line.rstrip(b"\r\n")) > MAX_ROW_BYTES:
                        raise SentrySourceError("archive exceeds its row limits")
                    record = parse_strict_json_object_bytes(line, document_name="Sentry snapshot")
                    _safe_json_tree(record)
                    if record.get("schema_version") != "microcap_sentry.snapshot.v1":
                        raise SentrySourceError("snapshot schema version is unsupported")
                    if record.get("observation_only") is not True or record.get("order_submission_enabled") is not False:
                        raise SentrySourceError("archive must explicitly declare observation-only safety")
                    self._validator(copy.deepcopy(record))
                    event_id = record.get("event_id")
                    if not isinstance(event_id, str) or not event_id.strip() or event_id != event_id.strip() or len(event_id) > 256:
                        raise SentrySourceError("snapshot event identity is missing")
                    symbol = record.get("symbol")
                    if not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol):
                        raise SentrySourceError("snapshot symbol is unsupported")
                    observed_at = _observed_at(record)
                    if observed_at > checked_at + timedelta(seconds=5):
                        raise SentrySourceError("snapshot observation time is in the future")
                    fingerprint = canonical_json_bytes(record)
                    if event_id in seen:
                        if seen[event_id] != fingerprint:
                            raise SentrySourceError("archive contains conflicting event identities")
                        continue
                    seen[event_id] = fingerprint
                    observations.append((observed_at, record))
                # Stable two-pass ordering makes ties deterministic without
                # inferring which equally-timed observation is more current.
                observations.sort(key=lambda item: item[1]["event_id"])
                observations.sort(key=lambda item: item[0], reverse=True)
                return {
                    **envelope, "status": "READY",
                    "message": "Validated Sentry archive observations; read-only. No scan is running.",
                    "source": {
                        "label": self.source_label, "kind": self.source_kind,
                        "file_name": self.archive.name, "sha256": hashlib.sha256(payload).hexdigest(),
                        "byte_size": len(payload),
                        "latest_observed_at": _stamp(observations[0][0]) if observations else None,
                        "raw_count": raw_count, "duplicate_count": raw_count - len(observations),
                    },
                    "observations": [record for _, record in observations],
                }
            except Exception:
                # Never expose exception text, configured paths, or partial data.
                return {**envelope, "status": "UNAVAILABLE", "message": "The configured Sentry archive or canonical contract is missing, changing, or failed validation. No substitute observations are shown."}
