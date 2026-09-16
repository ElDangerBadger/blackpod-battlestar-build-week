"""Immutable multi-symbol Navigator references, separate from mission authority."""
from __future__ import annotations

import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from .cabin_context import (
    CABIN_CONTEXT_PATH, NAVIGATOR_MARKET_CONTRACT_VERSION, CabinContext,
    CabinContextConflictError, CabinContextError, CaptureTransport, NavigatorMarket,
    _require_fields, _source_identity, _text, _validate_navigator_url, fetch_navigator_market,
    inspect_git_revision,
)
from .contracts import ArtifactReference, RunMode
from .contracts.mission_request import ContractValidationError, normalize_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_store import MissionStore
from .navigator_catalog import (
    ALL_NAVIGATOR_PAIRS, MAX_CATALOG_CAPTURE_BYTES, MAX_VARIANT_BYTES,
    _pair, _publish_catalog_files,
)

NAVIGATOR_FLEET_CATALOG_SCHEMA = "blackpod.navigator_fleet_catalog.v1"
NAVIGATOR_FLEET_CATALOG_PATH = "presentation/navigator_fleet_catalog.json"
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,19}$")


def safe_symbol(value: object) -> str:
    if not isinstance(value, str) or not _SYMBOL.fullmatch(value):
        raise ContractValidationError("fleet symbol must be a safe uppercase recorded label")
    return value


def fleet_market_path(symbol: str, timeframe: str, ma_period: int) -> str:
    safe_symbol(symbol)
    _pair(timeframe, ma_period)
    return f"presentation/navigator_fleet/{symbol}-{timeframe}-ma{ma_period}.json"


def fleet_symbols(payload: bytes) -> tuple[str, ...]:
    value = parse_strict_json_object_bytes(payload)
    rows = value.get("symbols")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ContractValidationError("normalized fleet must contain 1 to 100 symbol records")
    symbols = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ContractValidationError("normalized fleet symbol record must be an object")
        symbols.append(safe_symbol(row.get("symbol")))
    if len(set(symbols)) != len(symbols):
        raise ContractValidationError("normalized fleet contains duplicate symbols")
    if "symbol_count" in value and (
        isinstance(value["symbol_count"], bool) or not isinstance(value["symbol_count"], int)
        or value["symbol_count"] != len(symbols)
    ):
        raise ContractValidationError("normalized fleet symbol_count disagrees with recorded rows")
    return tuple(symbols)


def validate_navigator_source(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("Navigator source must be an object")
    _require_fields(value, required={"git_revision", "backend_sha256", "worktree_dirty"}, name="Navigator source")
    for field, size in (("git_revision", 40), ("backend_sha256", 64)):
        if not isinstance(value[field], str) or re.fullmatch(f"[0-9a-f]{{{size}}}", value[field]) is None:
            raise ContractValidationError(f"Navigator source {field} is invalid")
    if not isinstance(value["worktree_dirty"], bool):
        raise ContractValidationError("Navigator source worktree_dirty must be a boolean")
    return dict(value)


def inspect_navigator_source(repository: Path) -> dict[str, Any]:
    """Fingerprint runtime Python bytes without importing canonical modules.

    Digest input is canonical JSON of sorted {path, sha256} records relative to
    the explicitly selected Navigator repository, including the backend/ prefix.
    """
    from .cabin_reader import _read_file, _safe_path

    root = Path(repository)
    backend = _safe_path(root, "backend")
    if not backend.is_dir():
        raise CabinContextError("selected Navigator repository has no backend directory")
    excluded = {"tests", "test", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"}
    records = []
    total = 0
    for directory, dirs, files in os.walk(backend, followlinks=False):
        for name in dirs + files:
            if (Path(directory) / name).is_symlink():
                raise CabinContextError("Navigator backend fingerprint does not follow symlinks")
        dirs[:] = sorted(name for name in dirs if name not in excluded)
        for name in sorted(files):
            if not name.endswith(".py") or name.startswith("test_") or name.endswith("_test.py"):
                continue
            relative = (Path(directory) / name).relative_to(root).as_posix()
            payload = _read_file(root, relative, max_bytes=min(8 * 1024 * 1024, 64 * 1024 * 1024 - total))
            total += len(payload)
            records.append({"path": relative, "sha256": sha256_bytes(payload)})
            if len(records) > 5000:
                raise CabinContextError("Navigator backend fingerprint exceeds its file limit")
    if not records:
        raise CabinContextError("Navigator backend has no runtime Python source")
    revision = inspect_git_revision(root)
    try:
        result = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
                                check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CabinContextError("could not inspect Navigator working-tree provenance") from exc
    return validate_navigator_source({
        "git_revision": revision,
        "backend_sha256": sha256_bytes(canonical_json_bytes(sorted(records, key=lambda item: item["path"]))),
        "worktree_dirty": bool(result.stdout.strip()),
    })


@dataclass(frozen=True, slots=True)
class NavigatorFleetEntry:
    symbol: str
    timeframe: str
    ma_period: int
    captured_at: str
    transport: CaptureTransport
    source_identity: str
    artifact: ArtifactReference

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NavigatorFleetEntry":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator fleet entry must be an object")
        _require_fields(value, required={"symbol", "timeframe", "ma_period", "captured_at", "transport", "source_identity", "artifact"}, name="Navigator fleet entry")
        symbol = safe_symbol(value["symbol"])
        timeframe, period = _pair(value["timeframe"], value["ma_period"])
        captured = normalize_rfc3339(value["captured_at"], "Navigator fleet entry captured_at")
        try:
            transport = CaptureTransport(value["transport"])
        except (ValueError, TypeError) as exc:
            raise ContractValidationError("unsupported Navigator fleet transport") from exc
        identity = _source_identity(value["source_identity"], "Navigator fleet source identity")
        reference = ArtifactReference.from_mapping(value["artifact"])
        if (
            reference.name != "navigator_fleet_market" or reference.producer != "navigator"
            or reference.path != fleet_market_path(symbol, timeframe, period)
            or reference.schema_version != NAVIGATOR_MARKET_CONTRACT_VERSION
            or reference.observed_at != captured or reference.byte_size is None
        ):
            raise ContractValidationError("Navigator fleet artifact reference is inconsistent")
        return cls(symbol, timeframe, period, captured, transport, identity, reference)

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "timeframe": self.timeframe, "ma_period": self.ma_period,
                "captured_at": self.captured_at, "transport": self.transport.value,
                "source_identity": self.source_identity, "artifact": self.artifact.to_dict()}


@dataclass(frozen=True, slots=True)
class NavigatorFleetCatalog:
    mission_id: str
    request_id: str
    mission_symbol: str
    captured_at: str
    fleet_snapshot: ArtifactReference
    navigator_source: Mapping[str, Any]
    entries: tuple[NavigatorFleetEntry, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NavigatorFleetCatalog":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator fleet catalog must be an object")
        _require_fields(value, required={"schema_version", "mission_id", "request_id", "mission_symbol", "run_mode", "captured_at", "fleet_snapshot", "navigator_source", "entries"}, name="Navigator fleet catalog")
        if value["schema_version"] != NAVIGATOR_FLEET_CATALOG_SCHEMA or value["run_mode"] != "LIVE":
            raise ContractValidationError("Navigator fleet catalog requires supported LIVE schema")
        try:
            mission = validate_mission_id(value["mission_id"])
            request = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        symbol = _text(value["mission_symbol"], "Navigator fleet mission_symbol", max_length=64)
        captured = normalize_rfc3339(value["captured_at"], "Navigator fleet captured_at")
        reference = ArtifactReference.from_mapping(value["fleet_snapshot"])
        if reference.name != "oracle_normalized_snapshot" or reference.byte_size is None:
            raise ContractValidationError("Navigator fleet requires a full normalized snapshot reference")
        source = validate_navigator_source(value["navigator_source"])
        rows = value["entries"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 1500:
            raise ContractValidationError("Navigator fleet requires 1 to 1500 captured entries")
        entries = tuple(NavigatorFleetEntry.from_mapping(row) for row in rows)
        if len({(entry.symbol, entry.timeframe, entry.ma_period) for entry in entries}) != len(entries):
            raise ContractValidationError("Navigator fleet contains duplicate symbol/timeframe/MA entries")
        if len({entry.symbol for entry in entries}) > 100:
            raise ContractValidationError("Navigator fleet exceeds 100 symbols")
        return cls(mission, request, symbol, captured, reference, source, entries)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": NAVIGATOR_FLEET_CATALOG_SCHEMA, "mission_id": self.mission_id,
                "request_id": self.request_id, "mission_symbol": self.mission_symbol, "run_mode": "LIVE",
                "captured_at": self.captured_at, "fleet_snapshot": self.fleet_snapshot.to_dict(),
                "navigator_source": dict(self.navigator_source), "entries": [entry.to_dict() for entry in self.entries]}

    def validate_membership(self, *, mission_id: str, request_id: str, mission_symbol: str,
                            fleet_reference: ArtifactReference, fleet_payload: bytes,
                            excluded_symbols: Sequence[str] = ()) -> None:
        if (self.mission_id, self.request_id, self.mission_symbol) != (mission_id, request_id, mission_symbol):
            raise ContractValidationError("Navigator fleet mission correlation differs from canonical evidence")
        if self.fleet_snapshot != fleet_reference:
            raise ContractValidationError("Navigator fleet snapshot reference differs from canonical evidence")
        if sha256_bytes(fleet_payload) != fleet_reference.sha256 or len(fleet_payload) != fleet_reference.byte_size:
            raise ContractValidationError("Navigator fleet snapshot bytes differ from their reference")
        members = set(fleet_symbols(fleet_payload))
        if any(entry.symbol not in members or entry.symbol in excluded_symbols for entry in self.entries):
            raise ContractValidationError("Navigator fleet entries must be observed members and cannot replace the original market symbol")


def validate_fleet_market(entry: NavigatorFleetEntry, payload: bytes) -> NavigatorMarket:
    if len(payload) != entry.artifact.byte_size or sha256_bytes(payload) != entry.artifact.sha256:
        raise ContractValidationError("Navigator fleet market differs from referenced bytes")
    market = NavigatorMarket.from_bytes(payload, expected_symbol=entry.symbol, run_mode=RunMode.LIVE)
    if (market.value["timeframe"], market.value["ma_period"]) != (entry.timeframe, entry.ma_period):
        raise ContractValidationError("Navigator fleet market differs from requested timeframe/MA")
    return market


def canonical_fleet_reference(artifacts: Sequence[ArtifactReference]) -> ArtifactReference:
    matches = [reference for reference in artifacts if reference.name == "oracle_normalized_snapshot"]
    if len(matches) != 1 or matches[0].byte_size is None:
        raise ContractValidationError("one full canonical normalized fleet reference is required")
    return matches[0]


def original_market_symbols(files: Mapping[str, bytes]) -> tuple[str, ...]:
    if CABIN_CONTEXT_PATH not in files:
        return ()
    context = CabinContext.from_mapping(parse_strict_json_object_bytes(files[CABIN_CONTEXT_PATH]))
    return (context.symbol,) if context.market_artifact is not None else ()


def _baseline(artifacts_root: Path, mission_id: str):
    from .cabin_reader import ReadOnlyMissionStore, capture_publication
    store = ReadOnlyMissionStore(artifacts_root)
    publication = capture_publication(store, mission_id)
    loaded = store.load_mission(mission_id)
    if sha256_bytes(publication.files["mission_snapshot.json"]) != loaded.current_snapshot_sha256:
        raise CabinContextError("mission changed during fleet capture preparation")
    reference = canonical_fleet_reference(loaded.snapshot.artifacts)
    members = fleet_symbols(publication.files[reference.path])
    return store, publication, loaded, reference, members


def _publication_source_files(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Retain actual source bytes, excluding the reader's generated documents."""
    generated = {
        "presentation/manifest.json", "presentation/mission_summary.json",
        "presentation/captains_log.json", "presentation/captains_log.md",
        "presentation/mission_brief.html",
    }
    return {path: payload for path, payload in files.items() if path not in generated}


@dataclass(frozen=True, slots=True)
class NavigatorFleetCapture:
    symbol: str
    timeframe: str
    ma_period: int
    captured_at: str
    transport: CaptureTransport | str
    source_identity: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class NavigatorFleetCaptureResult:
    catalog: NavigatorFleetCatalog
    catalog_path: Path
    written: bool


def capture_navigator_fleet(store: MissionStore, *, mission_id: str, captured_at: str,
                            navigator_source: Mapping[str, Any], captures: Sequence[NavigatorFleetCapture]) -> NavigatorFleetCaptureResult:
    return _capture_navigator_fleet(_baseline(store.artifacts_root, mission_id), mission_id=mission_id,
        captured_at=captured_at, navigator_source=navigator_source, captures=captures)


def _capture_navigator_fleet(acquisition_baseline, *, mission_id: str, captured_at: str,
                            navigator_source: Mapping[str, Any], captures: Sequence[NavigatorFleetCapture]) -> NavigatorFleetCaptureResult:
    """Publish against the same mission bytes that authorized the acquisition."""
    read_store, publication, loaded, fleet_reference, _ = acquisition_baseline
    if not 1 <= len(captures) <= 1500:
        raise ContractValidationError("fleet capture requires 1 to 1500 entries")
    payloads = []
    entries = []
    total = 0
    for capture in captures:
        if not isinstance(capture.payload, bytes) or len(capture.payload) > MAX_VARIANT_BYTES:
            raise ContractValidationError("fleet market must be bounded exact bytes")
        total += len(capture.payload)
        if total > MAX_CATALOG_CAPTURE_BYTES:
            raise ContractValidationError("fleet capture exceeds its byte limit")
        observed = normalize_rfc3339(capture.captured_at, "fleet entry captured_at")
        entry = NavigatorFleetEntry.from_mapping({
            "symbol": capture.symbol, "timeframe": capture.timeframe, "ma_period": capture.ma_period,
            "captured_at": observed, "transport": capture.transport, "source_identity": capture.source_identity,
            "artifact": {"name": "navigator_fleet_market", "path": fleet_market_path(capture.symbol, capture.timeframe, capture.ma_period),
                         "sha256": sha256_bytes(capture.payload), "byte_size": len(capture.payload), "producer": "navigator",
                         "schema_version": NAVIGATOR_MARKET_CONTRACT_VERSION, "observed_at": observed},
        })
        validate_fleet_market(entry, capture.payload)
        entries.append(entry.to_dict())
        payloads.append((entry.artifact.path, capture.payload))
    catalog = NavigatorFleetCatalog.from_mapping({
        "schema_version": NAVIGATOR_FLEET_CATALOG_SCHEMA, "mission_id": mission_id,
        "request_id": loaded.request.request_id, "mission_symbol": loaded.request.symbol, "run_mode": "LIVE",
        "captured_at": captured_at, "fleet_snapshot": fleet_reference.to_dict(), "navigator_source": navigator_source,
        "entries": entries,
    })
    catalog.validate_membership(mission_id=mission_id, request_id=loaded.request.request_id,
        mission_symbol=loaded.request.symbol, fleet_reference=fleet_reference,
        fleet_payload=publication.files[fleet_reference.path], excluded_symbols=original_market_symbols(publication.files))
    catalog_bytes = canonical_json_bytes(catalog.to_dict())
    payloads.append((NAVIGATOR_FLEET_CATALOG_PATH, catalog_bytes))
    from .cabin_reader import MANIFEST_PATH, MAX_PUBLICATION_BYTES, _reference
    prospective = dict(publication.files)
    prospective.update(payloads)
    manifest = parse_strict_json_object_bytes(prospective[MANIFEST_PATH])
    manifest["navigator_fleet_catalog"] = _reference(NAVIGATOR_FLEET_CATALOG_PATH, "navigator_fleet_catalog",
        NAVIGATOR_FLEET_CATALOG_SCHEMA, catalog.captured_at, catalog_bytes)
    prospective[MANIFEST_PATH] = canonical_json_bytes(manifest)
    if sum(map(len, prospective.values())) > MAX_PUBLICATION_BYTES:
        raise CabinContextError("fleet capture exceeds the publication byte limit")
    baseline = _publication_source_files(publication.files)
    root = read_store.mission_root_for(mission_id)
    written = _publish_catalog_files(root, payloads, baseline, catalog_path=NAVIGATOR_FLEET_CATALOG_PATH,
                                     variants_directory="navigator_fleet")
    return NavigatorFleetCaptureResult(catalog, root / NAVIGATOR_FLEET_CATALOG_PATH, written)


def capture_navigator_fleet_from_http(*, artifacts_root: Path, mission_id: str,
    navigator_base_url: str, navigator_repository: Path, pairs: Sequence[tuple[str, int]] = (("1d", 250),),
    source_identity: str = "navigator-local-api", timeout_seconds: float = 30.0, pace_seconds: float = 1.1,
    fetcher: Callable[..., bytes] = fetch_navigator_market, sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], str] | None = None, progress: Callable[[str], None] | None = None,
) -> NavigatorFleetCaptureResult:
    acquisition_baseline = _baseline(artifacts_root, mission_id)
    _, publication, loaded, _, members = acquisition_baseline
    if NAVIGATOR_FLEET_CATALOG_PATH in publication.files:
        raise CabinContextConflictError("Navigator fleet catalog already exists and will not be replaced")
    if isinstance(pace_seconds, bool) or not isinstance(pace_seconds, (int, float)) or not math.isfinite(pace_seconds) or pace_seconds < 1.1 or pace_seconds > 60:
        raise CabinContextError("Navigator request pacing must be between 1.1 and 60 seconds")
    selected_pairs = tuple(_pair(*pair) for pair in pairs)
    if not selected_pairs or len(selected_pairs) > 15 or len(set(selected_pairs)) != len(selected_pairs):
        raise CabinContextError("Navigator requested pairs must be nonempty and unique")
    symbols = tuple(symbol for symbol in members if symbol not in original_market_symbols(publication.files))
    if not symbols:
        raise CabinContextError("no additional observed fleet symbols are available")
    identity = _source_identity(source_identity, "Navigator fleet source identity")
    base = urlsplit(navigator_base_url)
    if base.path not in {"", "/"} or base.query or base.fragment:
        raise CabinContextError("Navigator base URL must be a loopback origin")
    requests = [(symbol, timeframe, period, navigator_base_url.rstrip("/") + "/api/ohlc?" + urlencode({
        "symbol": symbol, "timeframe": timeframe, "ma": period,
    })) for symbol in symbols for timeframe, period in selected_pairs]
    for symbol, _, _, endpoint in requests:
        _validate_navigator_url(endpoint, symbol)
    source = inspect_navigator_source(navigator_repository)
    now = clock or (lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    captures = []
    total = 0
    for index, (symbol, timeframe, period, endpoint) in enumerate(requests):
        if index:
            sleeper(pace_seconds)
        remaining = MAX_CATALOG_CAPTURE_BYTES - total
        if remaining < 1:
            raise CabinContextError("Navigator fleet capture exceeds its byte limit")
        payload = fetcher(endpoint, expected_symbol=symbol, timeout_seconds=timeout_seconds,
                          max_response_bytes=min(remaining, MAX_VARIANT_BYTES))
        market = NavigatorMarket.from_bytes(payload, expected_symbol=symbol, run_mode=RunMode.LIVE)
        if (market.value["timeframe"], market.value["ma_period"]) != (timeframe, period):
            raise ContractValidationError("Navigator fleet response differs from requested pair")
        total += len(payload)
        if len(payload) > MAX_VARIANT_BYTES or total > MAX_CATALOG_CAPTURE_BYTES:
            raise CabinContextError("Navigator fleet response exceeds its byte limit")
        captures.append(NavigatorFleetCapture(symbol, timeframe, period, now(), "HTTP", identity, payload))
        if progress:
            progress(f"Captured {symbol} {timeframe} MA{period} ({index + 1}/{len(requests)})")
    if inspect_navigator_source(navigator_repository) != source:
        raise CabinContextConflictError("Navigator runtime source changed during capture")
    # Freeze the original mission and old supplements across the entire HTTP run.
    from .cabin_reader import _read_file
    for path, payload in _publication_source_files(publication.files).items():
        if _read_file(loaded.paths.mission_root, path, max_bytes=len(payload)) != payload:
            raise CabinContextConflictError("original mission evidence changed during fleet acquisition")
    return _capture_navigator_fleet(acquisition_baseline, mission_id=mission_id, captured_at=now(),
        navigator_source=source, captures=captures)
