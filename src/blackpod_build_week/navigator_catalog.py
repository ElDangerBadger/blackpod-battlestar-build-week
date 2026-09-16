"""Explicit, immutable Navigator captures; no browser-driven data acquisition.

The catalog supplements an existing Cabin context. Its original market remains
the default and is never overwritten or recalculated by this module.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from .cabin_context import (
    ALLOWED_MA_PERIODS, ALLOWED_TIMEFRAMES, CABIN_CONTEXT_PATH,
    NAVIGATOR_MARKET_CONTRACT_VERSION, CabinContext, CabinContextConflictError,
    CabinContextError, CaptureTransport, NavigatorMarket, _require_fields,
    _source_identity, _text, fetch_navigator_market, inspect_git_revision,
)
from .contracts import ArtifactReference, RunMode
from .contracts.mission_request import (
    ContractValidationError, normalize_rfc3339, parse_strict_json_object_bytes,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_store import MissionStore, UnsafePathError


NAVIGATOR_CATALOG_SCHEMA_VERSION = "blackpod.navigator_catalog.v1"
NAVIGATOR_CATALOG_PATH = "presentation/navigator_catalog.json"
NAVIGATOR_VARIANTS_DIRECTORY = "presentation/navigator_variants"
ALL_NAVIGATOR_PAIRS = tuple(
    (timeframe, period) for timeframe in ("1h", "1d", "1wk")
    for period in sorted(ALLOWED_MA_PERIODS)
)
MAX_VARIANT_BYTES = 16 * 1024 * 1024
MAX_CATALOG_CAPTURE_BYTES = 96 * 1024 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def variant_path(timeframe: str, ma_period: int) -> str:
    return f"{NAVIGATOR_VARIANTS_DIRECTORY}/{timeframe}-ma{ma_period}.json"


def _pair(timeframe: object, ma_period: object) -> tuple[str, int]:
    if not isinstance(timeframe, str) or timeframe not in ALLOWED_TIMEFRAMES:
        raise ContractValidationError("unsupported Navigator variant timeframe")
    if isinstance(ma_period, bool) or not isinstance(ma_period, int) or ma_period not in ALLOWED_MA_PERIODS:
        raise ContractValidationError("unsupported Navigator variant ma_period")
    return timeframe, ma_period


@dataclass(frozen=True, slots=True)
class NavigatorCatalogEntry:
    timeframe: str
    ma_period: int
    captured_at: str
    transport: CaptureTransport
    source_identity: str
    navigator_git_revision: str
    artifact: ArtifactReference

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NavigatorCatalogEntry":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator catalog entry must be an object")
        _require_fields(value, required={
            "timeframe", "ma_period", "captured_at", "transport", "source_identity",
            "navigator_git_revision", "artifact",
        }, name="Navigator catalog entry")
        timeframe, period = _pair(value["timeframe"], value["ma_period"])
        observed_at = normalize_rfc3339(value["captured_at"], "Navigator entry captured_at")
        try:
            transport = CaptureTransport(value["transport"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported Navigator entry transport") from exc
        identity = _source_identity(value["source_identity"], "Navigator entry source_identity")
        revision = value["navigator_git_revision"]
        if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
            raise ContractValidationError("Navigator entry revision must be 40 lowercase hex characters")
        artifact = ArtifactReference.from_mapping(value["artifact"])
        if (
            artifact.name != "navigator_market_variant"
            or artifact.path != variant_path(timeframe, period)
            or artifact.producer != "navigator"
            or artifact.schema_version != NAVIGATOR_MARKET_CONTRACT_VERSION
            or artifact.observed_at != observed_at or artifact.byte_size is None
        ):
            raise ContractValidationError("Navigator variant artifact reference is inconsistent")
        return cls(timeframe, period, observed_at, transport, identity, revision, artifact)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe, "ma_period": self.ma_period,
            "captured_at": self.captured_at, "transport": self.transport.value,
            "source_identity": self.source_identity,
            "navigator_git_revision": self.navigator_git_revision,
            "artifact": self.artifact.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class NavigatorCatalog:
    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    captured_at: str
    entries: tuple[NavigatorCatalogEntry, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NavigatorCatalog":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator catalog must be an object")
        _require_fields(value, required={
            "schema_version", "mission_id", "request_id", "symbol", "run_mode",
            "captured_at", "entries",
        }, name="Navigator catalog")
        if value["schema_version"] != NAVIGATOR_CATALOG_SCHEMA_VERSION:
            raise ContractValidationError("unsupported Navigator catalog schema")
        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if value["run_mode"] != RunMode.LIVE.value:
            raise ContractValidationError("Navigator catalog requires LIVE evidence")
        symbol = _text(value["symbol"], "Navigator catalog symbol", max_length=64)
        captured_at = normalize_rfc3339(value["captured_at"], "Navigator catalog captured_at")
        raw_entries = value["entries"]
        if not isinstance(raw_entries, list) or not 1 <= len(raw_entries) <= 15:
            raise ContractValidationError("Navigator catalog requires between 1 and 15 entries")
        entries = tuple(NavigatorCatalogEntry.from_mapping(entry) for entry in raw_entries)
        if len({(entry.timeframe, entry.ma_period) for entry in entries}) != len(entries):
            raise ContractValidationError("Navigator catalog has duplicate timeframe/MA pairs")
        return cls(NAVIGATOR_CATALOG_SCHEMA_VERSION, mission_id, request_id, symbol,
                   RunMode.LIVE, captured_at, entries)

    def validate_context(self, context: CabinContext, default: NavigatorMarket) -> None:
        if (
            self.mission_id != context.mission_id or self.request_id != context.request_id
            or self.symbol != context.symbol or self.run_mode is not context.run_mode
        ):
            raise ContractValidationError("Navigator catalog correlation differs from Cabin context")
        default_pair = (default.value["timeframe"], default.value["ma_period"])
        if any((entry.timeframe, entry.ma_period) == default_pair for entry in self.entries):
            raise ContractValidationError("Navigator catalog conflicts with the original default market")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "mission_id": self.mission_id,
            "request_id": self.request_id, "symbol": self.symbol,
            "run_mode": self.run_mode.value, "captured_at": self.captured_at,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def validate_variant(entry: NavigatorCatalogEntry, payload: bytes, *, symbol: str) -> NavigatorMarket:
    if len(payload) != entry.artifact.byte_size or sha256_bytes(payload) != entry.artifact.sha256:
        raise ContractValidationError("Navigator variant bytes differ from their capture reference")
    market = NavigatorMarket.from_bytes(payload, expected_symbol=symbol, run_mode=RunMode.LIVE)
    if (market.value["timeframe"], market.value["ma_period"]) != (entry.timeframe, entry.ma_period):
        raise ContractValidationError("Navigator variant response differs from its requested pair")
    return market


@dataclass(frozen=True, slots=True)
class NavigatorVariantCapture:
    timeframe: str
    ma_period: int
    captured_at: str
    transport: CaptureTransport | str
    source_identity: str
    navigator_git_revision: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class NavigatorCatalogCapture:
    catalog: NavigatorCatalog
    catalog_path: Path
    written: bool


def _baseline(artifacts_root: Path, mission_id: str):
    # Lazy imports prevent a reader dependency cycle. Acquisition is invoked
    # only by an explicit capture command; the reader imports validators only.
    from .cabin_reader import ReadOnlyMissionStore, capture_publication

    store = ReadOnlyMissionStore(artifacts_root)
    publication = capture_publication(store, mission_id)
    raw_context = publication.files.get(CABIN_CONTEXT_PATH)
    if raw_context is None:
        raise CabinContextError("Navigator catalog requires the original captured Cabin context")
    context = CabinContext.from_mapping(parse_strict_json_object_bytes(raw_context))
    if context.market_artifact is None:
        raise CabinContextError("Navigator catalog requires the original default market")
    default = NavigatorMarket.from_bytes(publication.files[context.market_artifact.path],
                                         expected_symbol=context.symbol, run_mode=RunMode.LIVE)
    return store, publication, context, default


def _publish_catalog_files(root: Path, payloads: Sequence[tuple[str, bytes]], baseline: Mapping[str, bytes]) -> bool:
    """Stage complete bytes, link without replacement, publish the catalog last.

    Directory descriptors prevent symlink traversal; an advisory directory lock
    serializes cooperating capture commands. Failure removes only links created
    by this attempt, while the catalog is the sole publication commit marker.
    """
    from .cabin_reader import _read_file, _safe_path

    with contextlib.ExitStack() as stack:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, root_fd)
        presentation_fd = os.open("presentation", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        stack.callback(os.close, presentation_fd)
        fcntl.flock(presentation_fd, fcntl.LOCK_EX)
        stack.callback(fcntl.flock, presentation_fd, fcntl.LOCK_UN)
        for relative, original in baseline.items():
            if _read_file(root, relative, max_bytes=len(original)) != original:
                raise CabinContextConflictError("original mission or default context changed during capture")
        existing: set[str] = set()
        for relative, payload in payloads:
            target = _safe_path(root, relative)
            if target.exists():
                if _read_file(root, relative, max_bytes=len(payload)) != payload:
                    raise CabinContextConflictError("Navigator capture already exists with different content")
                existing.add(relative)
        if len(existing) == len(payloads):
            return False
        stage_name = f".navigator-catalog-{uuid.uuid4().hex}"
        os.mkdir(stage_name, mode=0o700, dir_fd=presentation_fd)
        stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=presentation_fd)
        staged_names: list[str] = []
        created: list[tuple[int, str, int]] = []
        variants_fd = None
        created_variants = False
        committed = False
        try:
            for index, (_, payload) in enumerate(payloads):
                name = f"payload-{index}"
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o644, dir_fd=stage_fd)
                staged_names.append(name)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
            try:
                os.mkdir("navigator_variants", mode=0o755, dir_fd=presentation_fd)
                created_variants = True
            except FileExistsError:
                pass
            variants_fd = os.open("navigator_variants", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=presentation_fd)
            for index, (relative, payload) in enumerate(payloads):
                if relative in existing:
                    continue
                destination_fd = presentation_fd if relative == NAVIGATOR_CATALOG_PATH else variants_fd
                destination_name = relative.rsplit("/", 1)[1]
                try:
                    os.link(staged_names[index], destination_name, src_dir_fd=stage_fd,
                            dst_dir_fd=destination_fd, follow_symlinks=False)
                except FileExistsError as exc:
                    raise CabinContextConflictError("Navigator capture target appeared during publication") from exc
                inode = os.stat(destination_name, dir_fd=destination_fd, follow_symlinks=False).st_ino
                created.append((destination_fd, destination_name, inode))
                os.fsync(destination_fd)
            committed = True
            return True
        finally:
            if not committed:
                for directory_fd, name, inode in reversed(created):
                    try:
                        if os.stat(name, dir_fd=directory_fd, follow_symlinks=False).st_ino == inode:
                            os.unlink(name, dir_fd=directory_fd)
                    except FileNotFoundError:
                        pass
            if variants_fd is not None:
                os.close(variants_fd)
            if not committed and created_variants:
                try:
                    os.rmdir("navigator_variants", dir_fd=presentation_fd)
                except OSError:
                    pass
            for name in staged_names:
                os.unlink(name, dir_fd=stage_fd)
            os.close(stage_fd)
            os.rmdir(stage_name, dir_fd=presentation_fd)


def capture_navigator_catalog(
    store: MissionStore, *, mission_id: str, captured_at: str,
    captures: Sequence[NavigatorVariantCapture],
) -> NavigatorCatalogCapture:
    read_store, publication, context, default = _baseline(store.artifacts_root, mission_id)
    if not 1 <= len(captures) <= 15:
        raise ContractValidationError("Navigator capture requires between 1 and 15 variants")
    entries = []
    payloads = []
    total = 0
    for capture in captures:
        timeframe, period = _pair(capture.timeframe, capture.ma_period)
        if not isinstance(capture.payload, bytes) or len(capture.payload) > MAX_VARIANT_BYTES:
            raise ContractValidationError("Navigator variant must be bounded exact bytes")
        total += len(capture.payload)
        if total > MAX_CATALOG_CAPTURE_BYTES:
            raise ContractValidationError("Navigator catalog exceeds its capture byte limit")
        observed_at = normalize_rfc3339(capture.captured_at, "Navigator entry captured_at")
        entry = NavigatorCatalogEntry.from_mapping({
            "timeframe": timeframe, "ma_period": period, "captured_at": observed_at,
            "transport": capture.transport, "source_identity": capture.source_identity,
            "navigator_git_revision": capture.navigator_git_revision,
            "artifact": {"name": "navigator_market_variant", "path": variant_path(timeframe, period),
                         "sha256": sha256_bytes(capture.payload), "byte_size": len(capture.payload),
                         "producer": "navigator", "schema_version": NAVIGATOR_MARKET_CONTRACT_VERSION,
                         "observed_at": observed_at},
        })
        validate_variant(entry, capture.payload, symbol=context.symbol)
        entries.append(entry.to_dict())
        payloads.append((entry.artifact.path, capture.payload))
    catalog = NavigatorCatalog.from_mapping({
        "schema_version": NAVIGATOR_CATALOG_SCHEMA_VERSION, "mission_id": context.mission_id,
        "request_id": context.request_id, "symbol": context.symbol, "run_mode": "LIVE",
        "captured_at": captured_at, "entries": entries,
    })
    catalog.validate_context(context, default)
    payloads.append((NAVIGATOR_CATALOG_PATH, canonical_json_bytes(catalog.to_dict())))
    from .cabin_reader import MANIFEST_PATH, MAX_PUBLICATION_BYTES, _reference
    # Account for the existing default/mission evidence before staging any file.
    prospective = dict(publication.files)
    prospective.update(payloads)
    # The catalog adds a hash-bound manifest reference. Include the exact new
    # manifest, not the smaller pre-capture one, in the publication byte budget.
    manifest = parse_strict_json_object_bytes(publication.files[MANIFEST_PATH])
    manifest["navigator_catalog"] = _reference(
        NAVIGATOR_CATALOG_PATH, "navigator_catalog", NAVIGATOR_CATALOG_SCHEMA_VERSION,
        catalog.captured_at, prospective[NAVIGATOR_CATALOG_PATH],
    )
    prospective[MANIFEST_PATH] = canonical_json_bytes(manifest)
    if sum(map(len, prospective.values())) > MAX_PUBLICATION_BYTES:
        raise CabinContextError("Navigator catalog exceeds the publication byte limit")
    baseline = {path: publication.files[path] for path in (
        "mission_snapshot.json", "request/mission_request.json",
        CABIN_CONTEXT_PATH, context.market_artifact.path,
    )}
    root = read_store.mission_root_for(mission_id)
    written = _publish_catalog_files(root, payloads, baseline)
    return NavigatorCatalogCapture(catalog, root / NAVIGATOR_CATALOG_PATH, written)


def capture_navigator_catalog_from_http(
    *, artifacts_root: Path, mission_id: str, navigator_base_url: str,
    navigator_repository: Path, pairs: Sequence[tuple[str, int]] | None = None,
    source_identity: str = "navigator-local-api", timeout_seconds: float = 30.0,
    fetcher: Callable[..., bytes] = fetch_navigator_market,
    clock: Callable[[], str] | None = None,
) -> NavigatorCatalogCapture:
    store, publication, context, default = _baseline(artifacts_root, mission_id)
    if NAVIGATOR_CATALOG_PATH in publication.files:
        raise CabinContextConflictError("Navigator catalog is already captured; existing evidence is not replaced")
    revision = inspect_git_revision(navigator_repository)
    if not _REVISION.fullmatch(revision):
        raise CabinContextError("Navigator repository must expose its complete 40-character revision")
    identity = _source_identity(source_identity, "Navigator source_identity")
    base = urlsplit(navigator_base_url)
    if base.path not in {"", "/"} or base.query or base.fragment:
        raise CabinContextError("Navigator base URL must contain only a loopback origin")
    default_pair = (default.value["timeframe"], default.value["ma_period"])
    selected = tuple(pair for pair in ALL_NAVIGATOR_PAIRS if pair != default_pair) if pairs is None else tuple(pairs)
    if not selected or len(selected) > 15 or len(set(selected)) != len(selected) or default_pair in selected:
        raise CabinContextError("Navigator requested pairs must be unique and exclude the original default")
    for timeframe, period in selected:
        _pair(timeframe, period)
    now = clock or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    captures = []
    total = 0
    for timeframe, period in selected:
        endpoint = navigator_base_url.rstrip("/") + "/api/ohlc?" + urlencode({
            "symbol": context.symbol, "timeframe": timeframe, "ma": period,
        })
        remaining = MAX_CATALOG_CAPTURE_BYTES - total
        if remaining < 1:
            raise CabinContextError("Navigator capture exceeds its byte limit")
        payload = fetcher(endpoint, expected_symbol=context.symbol, timeout_seconds=timeout_seconds,
                          max_response_bytes=min(MAX_VARIANT_BYTES, remaining))
        total += len(payload)
        if total > MAX_CATALOG_CAPTURE_BYTES:
            raise CabinContextError("Navigator capture exceeds its byte limit")
        captures.append(NavigatorVariantCapture(timeframe, period, now(), CaptureTransport.HTTP,
                                                identity, revision, payload))
    return capture_navigator_catalog(store, mission_id=mission_id, captured_at=now(), captures=captures)
