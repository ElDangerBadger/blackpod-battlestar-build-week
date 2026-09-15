"""Loopback-only, read-only transport for the Captain's Cabin.

The configured canonical mission is verified on every current-feed request.
Publications are coherent byte captures in bounded process memory, not another
mission store. This module never invokes mission execution or external services.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import re
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

from .cabin_context import (
    CABIN_CONTEXT_PATH,
    CABIN_CONTEXT_SCHEMA_VERSION,
    CabinContext,
    NavigatorMarket,
    PortfolioSnapshot,
)
from .contracts import (
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    SHADOW_ONLY_DECLARATION,
    ArtifactReference,
    MissionRequest,
    ModelDockCallStatus,
    ModelDockTransportKind,
    RunMode,
)
from .contracts.mission_request import parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .identifiers import validate_mission_id
from .mission_presentation import project_mission_presentation
from .mission_store import LoadedMission, MissionStore, MissionStoreError, UnsafePathError


FEED_SCHEMA_VERSION = "blackpod.cabin_feed.v1"
MANIFEST_SCHEMA_VERSION = "blackpod.presentation_manifest.v1"
MANIFEST_PATH = "presentation/manifest.json"
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PUBLICATION_BYTES = 128 * 1024 * 1024
RETAIN_PUBLICATIONS = 3
_PUBLICATION_ID = re.compile(r"^[0-9a-f]{64}$")
_STATIC_SUFFIXES = frozenset({".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".woff", ".woff2", ".ico"})


class CabinReaderError(RuntimeError):
    """A source is unavailable or cannot be captured safely."""


def _parts(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or "%" in relative
        or any(ord(character) < 32 for character in relative)
        or path.is_absolute()
        or path.as_posix() != relative
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise UnsafePathError("only normalized relative file paths are accepted")
    return path.parts


def _safe_path(root: Path, relative: str) -> Path:
    """Reject symlinks in every path component beneath the explicit root."""

    if root.is_symlink() or not root.is_dir():
        raise UnsafePathError("source root is missing or unsafe")
    target = root
    for part in _parts(relative):
        target = target / part
        if target.is_symlink():
            raise UnsafePathError("symlinks are not presentation sources")
    return target


def _read_file(root: Path, relative: str) -> bytes:
    """Open beneath a directory descriptor, never following a symlink."""

    parts = _parts(relative)
    descriptors: list[int] = []
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            descriptors.append(descriptor)
        file_descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(file_descriptor)
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise CabinReaderError("source is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(file_descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_descriptor)
        payload = b"".join(chunks)
        if len(payload) > MAX_FILE_BYTES or (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise CabinReaderError("source changed during capture")
        return payload
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class _BoundedSourcePath(type(Path())):
    """Let the shared validator read bounded, no-follow bytes, not Path IO.

    MissionStore deliberately retains ownership of request/history validation.
    Only the reader's paths override its byte-read seam; no monkeypatching or
    second implementation of that validator is needed.
    """

    _read_source: Callable[[], bytes]

    def read_bytes(self) -> bytes:
        return self._read_source()


class ReadOnlyMissionStore(MissionStore):
    """Reuse full canonical validation without MissionStore's mkdir behavior."""

    def load_mission(self, mission_id: str) -> LoadedMission:
        self._validation_sizes: dict[str, int] = {}
        return super().load_mission(mission_id)

    def _read_validated_bytes(self, root: Path, relative_path: str) -> bytes:
        payload = _read_file(root, relative_path)
        self._validation_sizes[relative_path] = len(payload)
        if sum(self._validation_sizes.values()) > MAX_PUBLICATION_BYTES:
            raise CabinReaderError("source validation exceeds its memory limit")
        return payload

    def _missions_root(self) -> Path:
        return _safe_path(self.artifacts_root, "missions")

    def mission_root_for(self, mission_id: str) -> Path:
        return _safe_path(self._missions_root(), validate_mission_id(mission_id))

    def _contained_target(self, mission_root: Path, relative_path: str) -> Path:
        target = _BoundedSourcePath(_safe_path(mission_root, relative_path))
        target._read_source = lambda: self._read_validated_bytes(mission_root, relative_path)
        return target

    def _validate_snapshot_artifacts(self, mission_root, snapshot) -> None:
        for artifact in snapshot.artifacts:
            payload = self._read_validated_bytes(mission_root, artifact.path)
            _verify_reference(artifact, payload)

    def _deny_write(self, *args, **kwargs):
        raise CabinReaderError("the Cabin reader cannot mutate mission artifacts")

    initialize = _deny_write
    commit_snapshot = _deny_write
    reserve_directory = _deny_write
    write_immutable_artifact = _deny_write
    write_presentation_artifact = _deny_write


def _verify_reference(reference: ArtifactReference, payload: bytes) -> None:
    if sha256_bytes(payload) != reference.sha256 or (
        reference.byte_size is not None and len(payload) != reference.byte_size
    ):
        raise CabinReaderError("source bytes differ from their canonical reference")


def _reference(path: str, name: str, schema: str, observed_at: str, payload: bytes) -> dict:
    return ArtifactReference.from_mapping({
        "name": name, "path": path, "sha256": sha256_bytes(payload),
        "producer": "harbormaster", "byte_size": len(payload),
        "schema_version": schema, "observed_at": observed_at,
    }).to_dict()


def _validate_live(loaded: LoadedMission) -> None:
    snapshot = loaded.snapshot
    if snapshot.run_mode is not RunMode.LIVE or loaded.request.run_mode is not RunMode.LIVE:
        raise CabinReaderError("REPLAY missions cannot be published as LIVE")
    calls = snapshot.stages["oracle"].modeldock_calls
    if not calls:
        return
    call = calls[-1]
    component = snapshot.components.get("modeldock")
    if (
        call.run_mode is not RunMode.LIVE
        or component is None
        or component.run_mode is not RunMode.LIVE
        or component.transport is not ModelDockTransportKind.LIVE_HTTP
        or component.endpoint != call.endpoint
        or component.expected_provider != "mlx"
    ):
        raise CabinReaderError("ModelDock LIVE provenance is inconsistent")
    if call.status is ModelDockCallStatus.SUCCEEDED and (
        call.provider != "mlx" or call.mocked is not False or not call.trace_id or not call.model
    ):
        raise CabinReaderError("successful LIVE inference requires non-mocked MLX provenance")


def _capture_context(loaded: LoadedMission, files: dict[str, bytes]) -> None:
    root = loaded.paths.mission_root
    target = _safe_path(root, CABIN_CONTEXT_PATH)
    if not target.exists():
        return
    payload = _read_file(root, CABIN_CONTEXT_PATH)
    context = CabinContext.from_mapping(parse_strict_json_object_bytes(payload))
    if (
        context.mission_id != loaded.snapshot.mission_id
        or context.request_id != loaded.snapshot.request_id
        or context.symbol != loaded.request.symbol
        or context.run_mode is not RunMode.LIVE
    ):
        raise CabinReaderError("Cabin context correlation differs from the mission")
    files[CABIN_CONTEXT_PATH] = payload
    if context.market_artifact is not None:
        market = _read_file(root, context.market_artifact.path)
        _verify_reference(context.market_artifact, market)
        NavigatorMarket.from_bytes(market, expected_symbol=loaded.request.symbol, run_mode=RunMode.LIVE)
        files[context.market_artifact.path] = market
    if context.portfolio_artifact is not None:
        portfolio = _read_file(root, context.portfolio_artifact.path)
        _verify_reference(context.portfolio_artifact, portfolio)
        parsed = PortfolioSnapshot.from_bytes(portfolio)
        if parsed.mode.value != "LIVE" or parsed.source_identity != context.capture_provenance.portfolio_source_identity:
            raise CabinReaderError("LIVE portfolio mode or provenance is inconsistent")
        files[context.portfolio_artifact.path] = portfolio


@dataclass(frozen=True, slots=True)
class Publication:
    publication_id: str
    mission_id: str
    observed_at: str
    files: Mapping[str, bytes]


def capture_publication(store: ReadOnlyMissionStore, mission_id: str) -> Publication:
    """Capture and recheck one canonical revision; no partial publication escapes."""

    root = store.mission_root_for(mission_id)
    before = _read_file(root, "mission_snapshot.json")
    loaded = store.load_mission(mission_id)
    _validate_live(loaded)
    if sha256_bytes(before) != loaded.current_snapshot_sha256:
        raise CabinReaderError("source revision changed during validation")
    source_paths = {artifact.path for artifact in loaded.snapshot.artifacts}
    source_paths.update(
        f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json"
        for snapshot in loaded.snapshot_history
    )
    source_paths.update({"mission_snapshot.json", "request/mission_request.json"})
    files: dict[str, bytes] = {}
    total_bytes = 0
    for path in sorted(source_paths):
        payload = _read_file(root, path)
        total_bytes += len(payload)
        if total_bytes > MAX_PUBLICATION_BYTES:
            raise CabinReaderError("source exceeds the publication memory limit")
        files[path] = payload
    if MissionRequest.from_mapping(parse_strict_json_object_bytes(files["request/mission_request.json"])) != loaded.request:
        raise CabinReaderError("request bytes changed during validation")
    _capture_context(loaded, files)
    if sum(map(len, files.values())) > MAX_PUBLICATION_BYTES:
        raise CabinReaderError("source exceeds the publication memory limit")
    projection = project_mission_presentation(loaded, files)
    # Re-read every captured source, not only the mutable current pointer. A
    # concurrently replaced artifact/context must never be mixed into a frame.
    if any(_read_file(root, path) != payload for path, payload in files.items()):
        raise CabinReaderError("source changed during capture")
    after = store.load_mission(mission_id)
    if after.current_snapshot_sha256 != sha256_bytes(before):
        raise CabinReaderError("source revision changed during capture")
    if (CABIN_CONTEXT_PATH in files) != _safe_path(root, CABIN_CONTEXT_PATH).exists():
        raise CabinReaderError("context appeared during capture")
    files.update(projection.files)
    snapshot = loaded.snapshot
    call = snapshot.stages["oracle"].modeldock_calls[-1] if snapshot.stages["oracle"].modeldock_calls else None
    mode = "NOT_RECORDED" if call is None else (
        "LIVE" if call.status is ModelDockCallStatus.SUCCEEDED else call.status.value
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "mission_id": mission_id, "symbol": loaded.request.symbol, "run_mode": "LIVE",
        # Current viewer Git state is not provenance of an executed mission.
        "build_week_revision": None,
        "battlestar_revision": getattr(snapshot.components.get("battlestar"), "git_revision", None),
        "modeldock_mode": mode,
        "modeldock_revision_or_service_identity": None if call is None else call.endpoint,
        "modeldock_provider": None if call is None else call.provider,
        "modeldock_model": None if call is None else call.model,
        "modeldock_trace_id": None if call is None else call.trace_id,
        "final_outcome": snapshot.mission_outcome.value,
        "snapshot_count": len(loaded.snapshot_history),
        "captains_log": _reference(CAPTAINS_LOG_PATH, "captains_log", CAPTAINS_LOG_SCHEMA_VERSION, snapshot.observed_at, files[CAPTAINS_LOG_PATH]),
        "mission_summary": _reference(MISSION_SUMMARY_PATH, "mission_summary", MISSION_SUMMARY_SCHEMA_VERSION, snapshot.observed_at, files[MISSION_SUMMARY_PATH]),
        "final_snapshot": _reference("mission_snapshot.json", "mission_snapshot", MISSION_SNAPSHOT_SCHEMA_VERSION, snapshot.observed_at, files["mission_snapshot.json"]),
        "generated_at": snapshot.observed_at,
        "shadow_only_declaration": SHADOW_ONLY_DECLARATION,
        "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
        "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
    }
    if CABIN_CONTEXT_PATH in files:
        context = CabinContext.from_mapping(parse_strict_json_object_bytes(files[CABIN_CONTEXT_PATH]))
        manifest["cabin_context"] = _reference(
            CABIN_CONTEXT_PATH, "cabin_context", CABIN_CONTEXT_SCHEMA_VERSION,
            context.captured_at, files[CABIN_CONTEXT_PATH],
        )
    manifest_bytes = canonical_json_bytes(manifest)
    files[MANIFEST_PATH] = manifest_bytes
    return Publication(sha256_bytes(manifest_bytes), mission_id, snapshot.observed_at, MappingProxyType(files))


class CabinReader:
    """Serialize capture and keep at most three immutable in-memory publications."""

    def __init__(self, artifacts_root: Path | None = None, mission_id: str | None = None):
        self.store = None if artifacts_root is None else ReadOnlyMissionStore(artifacts_root)
        self.mission_id = mission_id
        self._publications: OrderedDict[str, Publication] = OrderedDict()
        self._lock = threading.Lock()

    def current(self) -> dict:
        with self._lock:
            checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            feed = {"schema_version": FEED_SCHEMA_VERSION, "checked_at": checked_at}
            if self.store is None or not self.mission_id:
                return {**feed, "status": "NOT_CONFIGURED", "message": "Select an explicit artifacts root and mission ID when starting the read-only Cabin."}
            try:
                publication = capture_publication(self.store, self.mission_id)
                existing = self._publications.get(publication.publication_id)
                if existing is not None and existing.files != publication.files:
                    raise CabinReaderError("a publication cannot change its captured bytes")
                self._publications[publication.publication_id] = publication
                self._publications.move_to_end(publication.publication_id)
                while len(self._publications) > RETAIN_PUBLICATIONS:
                    self._publications.popitem(last=False)
            except (OSError, ValueError, MissionStoreError, CabinReaderError, RuntimeError):
                # Neither exception text nor configured local paths go to the UI.
                return {**feed, "status": "UNAVAILABLE", "message": "The configured LIVE mission is missing, changing, or failed evidence validation. No substitute data is shown."}
            return {
                **feed, "status": "READY", "message": "Verified canonical LIVE mission evidence; read-only.",
                "publication_id": publication.publication_id,
                "base_url": f"revisions/{publication.publication_id}/",
                "mission_id": publication.mission_id, "observed_at": publication.observed_at,
            }

    def artifact(self, publication_id: str, relative_path: str) -> bytes | None:
        with self._lock:
            publication = self._publications.get(publication_id)
            return None if publication is None else publication.files.get(relative_path)


class CabinHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, reader: CabinReader, ui_root: Path, port: int = 5174):
        self.reader = reader
        self.ui_root = Path(ui_root)
        super().__init__(("127.0.0.1", port), CabinRequestHandler)


class CabinRequestHandler(BaseHTTPRequestHandler):
    server: CabinHTTPServer
    server_version = "BlackPodCabin"
    sys_version = ""

    def log_message(self, format, *args) -> None:
        # Do not echo arbitrary URLs, headers, or local evidence paths to logs.
        return

    def _local_request(self) -> bool:
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update({"127.0.0.1", "localhost"})
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        return (
            len(hosts) == 1 and hosts[0] in allowed
            and (not origins or origins == [f"http://{hosts[0]}"])
            and self.headers.get("Sec-Fetch-Site") != "cross-site"
        )

    def _send(self, status: int, payload: bytes, content_type: str, *, immutable: bool = False, evidence: bool = False) -> None:
        digest = sha256_bytes(payload)
        not_modified = immutable and self.headers.get("If-None-Match") == f'"{digest}"'
        self.send_response(304 if not_modified else status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable" if immutable else "no-store")
        self.send_header("ETag", f'"{digest}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; sandbox; frame-ancestors 'none'" if evidence else "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; worker-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD" and not not_modified:
            self.wfile.write(payload)

    def _error(self, status: int) -> None:
        self._send(status, b"Read-only resource unavailable.\n", "text/plain; charset=utf-8")

    def do_GET(self) -> None:
        if not self._local_request():
            self._error(403)
            return
        try:
            parsed = urlsplit(self.path)
            allowed_ui_query = parsed.path in {"/", "/index.html"} and parsed.query == "mode=live"
            if parsed.scheme or parsed.netloc or (parsed.query and not allowed_ui_query) or parsed.fragment or not parsed.path.startswith("/"):
                raise UnsafePathError("request target is not a local file")
            relative = unquote(parsed.path, errors="strict")[1:]
            if relative == "":
                relative = "index.html"
            _parts(relative)
            if relative == "live/current.json":
                self._send(200, canonical_json_bytes(self.server.reader.current()), "application/json")
                return
            parts = PurePosixPath(relative).parts
            if len(parts) >= 4 and parts[:2] == ("live", "revisions") and _PUBLICATION_ID.fullmatch(parts[2]):
                artifact_path = "/".join(parts[3:])
                payload = self.server.reader.artifact(parts[2], artifact_path)
                if payload is None:
                    self._error(404)
                    return
                content_type = mimetypes.guess_type(artifact_path)[0] or "application/octet-stream"
                self._send(200, payload, content_type, immutable=True, evidence=True)
                return
            allowed = relative in {"index.html", "captains-cabin-template.png", "favicon.ico"} or (
                len(parts) == 2 and parts[0] == "assets" and Path(parts[-1]).suffix in _STATIC_SUFFIXES
            )
            if not allowed:
                self._error(404)
                return
            payload = _read_file(self.server.ui_root, relative)
            self._send(200, payload, mimetypes.guess_type(relative)[0] or "application/octet-stream")
        except (OSError, ValueError, RuntimeError):
            self._error(404)

    do_HEAD = do_GET

    def _deny_method(self) -> None:
        self._error(405 if self._local_request() else 403)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = do_TRACE = _deny_method


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only Captain's Cabin on 127.0.0.1; no mission execution.")
    parser.add_argument("--artifacts-root", type=Path)
    parser.add_argument("--mission-id")
    parser.add_argument("--ui-root", type=Path, default=Path("ui/dist"))
    parser.add_argument("--port", type=int, default=5174)
    arguments = parser.parse_args(argv)
    if not 1 <= arguments.port <= 65535:
        parser.error("port must be between 1 and 65535")
    server = CabinHTTPServer(CabinReader(arguments.artifacts_root, arguments.mission_id), arguments.ui_root, arguments.port)
    print(f"Read-only Captain's Cabin: http://127.0.0.1:{server.server_port}/", flush=True)
    print("No mission controls, broker/order execution, or source writes.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
