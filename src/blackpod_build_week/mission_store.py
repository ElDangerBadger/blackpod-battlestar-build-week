"""Contained and durable filesystem storage for Harbormaster missions."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import ArtifactReference, MissionRequest, MissionSnapshot
from .contracts.mission_request import (
    ContractValidationError,
    load_strict_json_object,
)
from .hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .identifiers import IdentifierError, validate_mission_id


class MissionStoreError(RuntimeError):
    """Base class for mission persistence failures."""


class UnsafePathError(MissionStoreError):
    """Raised when a path could escape its configured root."""


class DuplicateMissionError(MissionStoreError):
    """Raised when a mission root already exists."""


class ImmutableArtifactError(MissionStoreError):
    """Raised when code attempts to overwrite immutable mission history."""


class PersistenceError(MissionStoreError):
    """Raised for filesystem write or durability failures."""


class MissionNotFoundError(MissionStoreError):
    """Raised when a requested mission has not been initialized."""


@dataclass(frozen=True, slots=True)
class MissionPaths:
    mission_root: Path
    request_path: Path
    snapshots_dir: Path
    revision_snapshot: Path
    current_snapshot: Path


@dataclass(frozen=True, slots=True)
class MissionInitialization:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedMission:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    current_snapshot_sha256: str


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_immutable_bytes(path: Path, payload: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ImmutableArtifactError(f"immutable artifact already exists: {path}") from exc
    except OSError as exc:
        raise PersistenceError(f"could not write immutable artifact {path}: {exc}") from exc
    _fsync_directory(path.parent)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    descriptor: int | None = None
    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
    except OSError as exc:
        raise PersistenceError(f"could not atomically write {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


class MissionStore:
    """Own the deterministic `artifacts/missions/<mission_id>` layout."""

    def __init__(self, artifacts_root: Path) -> None:
        self.artifacts_root = Path(artifacts_root).expanduser()

    def _missions_root(self) -> Path:
        try:
            self.artifacts_root.mkdir(parents=True, exist_ok=True)
            resolved_artifacts = self.artifacts_root.resolve(strict=True)
        except OSError as exc:
            raise PersistenceError(
                f"could not prepare artifacts root {self.artifacts_root}: {exc}"
            ) from exc

        missions_path = self.artifacts_root / "missions"
        if missions_path.exists() or missions_path.is_symlink():
            try:
                resolved_missions = missions_path.resolve(strict=True)
            except OSError as exc:
                raise UnsafePathError(f"unsafe missions path {missions_path}: {exc}") from exc
            if not _is_relative_to(resolved_missions, resolved_artifacts):
                raise UnsafePathError(
                    f"missions directory escapes artifacts root: {missions_path}"
                )
            if not resolved_missions.is_dir():
                raise PersistenceError(f"missions path is not a directory: {missions_path}")
            return resolved_missions

        try:
            missions_path.mkdir()
            _fsync_directory(resolved_artifacts)
            return missions_path.resolve(strict=True)
        except OSError as exc:
            raise PersistenceError(
                f"could not create missions directory {missions_path}: {exc}"
            ) from exc

    def mission_root_for(self, mission_id: str) -> Path:
        try:
            safe_mission_id = validate_mission_id(mission_id)
        except IdentifierError as exc:
            raise UnsafePathError(str(exc)) from exc
        missions_root = self._missions_root()
        candidate = (missions_root / safe_mission_id).resolve(strict=False)
        if not _is_relative_to(candidate, missions_root):
            raise UnsafePathError(f"mission path escapes missions root: {mission_id}")
        return candidate

    def _contained_target(self, mission_root: Path, relative_path: str) -> Path:
        if "\\" in relative_path:
            raise UnsafePathError("stored paths must use relative POSIX syntax")
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise UnsafePathError(f"path escapes mission root: {relative_path}")
        candidate = mission_root.joinpath(*relative.parts)
        resolved_root = mission_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=False)
        if not _is_relative_to(resolved_candidate, resolved_root):
            raise UnsafePathError(f"path escapes mission root: {relative_path}")
        return candidate

    def paths_for(self, mission_id: str) -> MissionPaths:
        mission_root = self.mission_root_for(mission_id)
        if (
            not mission_root.exists()
            or not mission_root.is_dir()
            or mission_root.is_symlink()
        ):
            raise MissionNotFoundError(f"mission does not exist: {mission_id}")
        return MissionPaths(
            mission_root=mission_root,
            request_path=self._contained_target(
                mission_root, "request/mission_request.json"
            ),
            snapshots_dir=self._contained_target(mission_root, "snapshots"),
            revision_snapshot=self._contained_target(
                mission_root, "snapshots/mission_snapshot-r0001.json"
            ),
            current_snapshot=self._contained_target(
                mission_root, "mission_snapshot.json"
            ),
        )

    def revision_path(self, paths: MissionPaths, revision: int) -> Path:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractValidationError("revision must be greater than zero")
        return self._contained_target(
            paths.mission_root,
            f"snapshots/mission_snapshot-r{revision:04d}.json",
        )

    def load_mission(self, mission_id: str) -> LoadedMission:
        """Load and verify a mission, its full revision chain, and artifacts."""

        paths = self.paths_for(mission_id)
        if paths.current_snapshot.is_symlink() or not paths.current_snapshot.is_file():
            raise PersistenceError("current mission snapshot is missing or unsafe")
        if paths.request_path.is_symlink() or not paths.request_path.is_file():
            raise PersistenceError("mission request artifact is missing or unsafe")

        request = MissionRequest.from_file(paths.request_path)
        if request.mission_id != mission_id:
            raise PersistenceError("stored mission request has the wrong mission_id")
        snapshot = MissionSnapshot.from_mapping(
            load_strict_json_object(paths.current_snapshot)
        )
        if snapshot.mission_id != mission_id:
            raise PersistenceError("current snapshot has the wrong mission_id")
        if snapshot.request_id != request.request_id:
            raise PersistenceError("snapshot request_id does not match stored request")
        if snapshot.run_mode is not request.run_mode:
            raise PersistenceError("snapshot run_mode does not match stored request")

        previous_digest: str | None = None
        baseline: MissionSnapshot | None = None
        latest_bytes: bytes | None = None
        for revision in range(1, snapshot.revision + 1):
            revision_path = self.revision_path(paths, revision)
            if revision_path.is_symlink() or not revision_path.is_file():
                raise PersistenceError(
                    f"immutable snapshot revision is missing or unsafe: r{revision:04d}"
                )
            revision_bytes = revision_path.read_bytes()
            revision_snapshot = MissionSnapshot.from_mapping(
                load_strict_json_object(revision_path)
            )
            if revision_snapshot.revision != revision:
                raise PersistenceError("immutable snapshot revision number mismatch")
            if revision_snapshot.previous_snapshot_sha256 != previous_digest:
                raise PersistenceError("snapshot revision hash chain is invalid")
            if baseline is None:
                baseline = revision_snapshot
            elif (
                revision_snapshot.mission_id != baseline.mission_id
                or revision_snapshot.request_id != baseline.request_id
                or revision_snapshot.run_mode is not baseline.run_mode
                or revision_snapshot.started_at != baseline.started_at
            ):
                raise PersistenceError("snapshot identity changed across revisions")
            previous_digest = sha256_bytes(revision_bytes)
            latest_bytes = revision_bytes

        current_bytes = paths.current_snapshot.read_bytes()
        if latest_bytes is None or current_bytes != latest_bytes:
            raise PersistenceError(
                "current snapshot does not match its immutable revision"
            )
        self._validate_snapshot_artifacts(paths.mission_root, snapshot)
        return LoadedMission(
            request=request,
            snapshot=snapshot,
            paths=paths,
            current_snapshot_sha256=sha256_bytes(current_bytes),
        )

    def reserve_directory(self, mission_id: str, relative_path: str) -> Path:
        """Exclusively reserve a contained directory for one immutable attempt."""

        paths = self.paths_for(mission_id)
        target = self._contained_target(paths.mission_root, relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target = self._contained_target(paths.mission_root, relative_path)
            target.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ImmutableArtifactError(
                f"immutable mission directory already exists: {relative_path}"
            ) from exc
        except OSError as exc:
            raise PersistenceError(
                f"could not reserve mission directory {relative_path}: {exc}"
            ) from exc
        _fsync_directory(target.parent)
        return target

    def write_immutable_artifact(
        self,
        mission_id: str,
        *,
        relative_path: str,
        payload: bytes,
        name: str,
        producer: str,
        schema_version: str | None,
        observed_at: str,
    ) -> ArtifactReference:
        paths = self.paths_for(mission_id)
        target = self._contained_target(paths.mission_root, relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise PersistenceError(
                f"could not create artifact directory for {relative_path}: {exc}"
            ) from exc
        target = self._contained_target(paths.mission_root, relative_path)
        _write_immutable_bytes(target, payload)
        return ArtifactReference.from_mapping(
            {
                "name": name,
                "path": relative_path,
                "sha256": sha256_bytes(payload),
                "producer": producer,
                "byte_size": len(payload),
                "schema_version": schema_version,
                "observed_at": observed_at,
            }
        )

    def reference_existing_artifact(
        self,
        mission_id: str,
        *,
        relative_path: str,
        name: str,
        producer: str,
        schema_version: str | None,
        observed_at: str,
    ) -> ArtifactReference:
        paths = self.paths_for(mission_id)
        target = self._contained_target(paths.mission_root, relative_path)
        if target.is_symlink() or not target.is_file():
            raise UnsafePathError(
                f"Oracle artifact is missing, not regular, or a symlink: {relative_path}"
            )
        return ArtifactReference.from_mapping(
            {
                "name": name,
                "path": relative_path,
                "sha256": sha256_file(target),
                "producer": producer,
                "byte_size": target.stat().st_size,
                "schema_version": schema_version,
                "observed_at": observed_at,
            }
        )

    def _validate_snapshot_artifacts(
        self, mission_root: Path, snapshot: MissionSnapshot
    ) -> None:
        for artifact in snapshot.artifacts:
            artifact_path = self._contained_target(mission_root, artifact.path)
            if artifact_path.is_symlink() or not artifact_path.is_file():
                raise PersistenceError(
                    f"referenced artifact does not exist or is unsafe: {artifact.path}"
                )
            if sha256_file(artifact_path) != artifact.sha256:
                raise PersistenceError(f"artifact hash mismatch: {artifact.path}")
            if (
                artifact.byte_size is not None
                and artifact_path.stat().st_size != artifact.byte_size
            ):
                raise PersistenceError(f"artifact byte size mismatch: {artifact.path}")

    def initialize(
        self,
        request: MissionRequest,
        *,
        mission_id: str,
        started_at: str,
        observed_at: str,
    ) -> MissionInitialization:
        stored_request = request.with_mission_id(mission_id)
        mission_root = self.mission_root_for(mission_id)
        try:
            mission_root.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise DuplicateMissionError(f"mission already exists: {mission_id}") from exc
        except OSError as exc:
            raise PersistenceError(
                f"could not reserve mission directory {mission_root}: {exc}"
            ) from exc

        request_path = self._contained_target(
            mission_root, "request/mission_request.json"
        )
        snapshots_dir = self._contained_target(mission_root, "snapshots")
        revision_snapshot = self._contained_target(
            mission_root, "snapshots/mission_snapshot-r0001.json"
        )
        current_snapshot = self._contained_target(mission_root, "mission_snapshot.json")
        try:
            request_path.parent.mkdir()
            snapshots_dir.mkdir()
        except OSError as exc:
            raise PersistenceError(f"could not create mission layout: {exc}") from exc

        request_bytes = canonical_json_bytes(stored_request.to_dict())
        _write_immutable_bytes(request_path, request_bytes)
        request_digest = sha256_bytes(request_bytes)

        request_artifact = ArtifactReference.from_mapping(
            {
                "name": "mission_request",
                "path": "request/mission_request.json",
                "sha256": request_digest,
                "producer": "harbormaster",
                "byte_size": len(request_bytes),
                "schema_version": stored_request.schema_version,
                "observed_at": observed_at,
            }
        )
        snapshot = MissionSnapshot.create_phase1(
            mission_id=mission_id,
            request_id=stored_request.request_id,
            run_mode=stored_request.run_mode,
            started_at=started_at,
            observed_at=observed_at,
            request_artifact=request_artifact,
        )
        paths = MissionPaths(
            mission_root=mission_root,
            request_path=request_path,
            snapshots_dir=snapshots_dir,
            revision_snapshot=revision_snapshot,
            current_snapshot=current_snapshot,
        )
        snapshot_digest = self.commit_snapshot(paths, snapshot)
        return MissionInitialization(
            request=stored_request,
            snapshot=snapshot,
            paths=paths,
            snapshot_sha256=snapshot_digest,
        )

    def commit_snapshot(self, paths: MissionPaths, snapshot: MissionSnapshot) -> str:
        """Commit an immutable revision, then atomically publish it as current."""

        validated = MissionSnapshot.from_mapping(snapshot.to_dict())
        canonical_mission_root = self.mission_root_for(validated.mission_id)
        try:
            supplied_mission_root = paths.mission_root.resolve(strict=True)
        except OSError as exc:
            raise UnsafePathError(
                f"mission directory cannot be resolved safely: {paths.mission_root}"
            ) from exc
        if supplied_mission_root != canonical_mission_root:
            raise UnsafePathError(
                "snapshot mission directory does not match the configured store"
            )

        canonical_paths = MissionPaths(
            mission_root=canonical_mission_root,
            request_path=self._contained_target(
                canonical_mission_root, "request/mission_request.json"
            ),
            snapshots_dir=self._contained_target(canonical_mission_root, "snapshots"),
            revision_snapshot=self._contained_target(
                canonical_mission_root, "snapshots/mission_snapshot-r0001.json"
            ),
            current_snapshot=self._contained_target(
                canonical_mission_root, "mission_snapshot.json"
            ),
        )
        supplied_and_canonical = (
            ("request_path", paths.request_path, canonical_paths.request_path),
            ("snapshots_dir", paths.snapshots_dir, canonical_paths.snapshots_dir),
            (
                "revision_snapshot",
                paths.revision_snapshot,
                canonical_paths.revision_snapshot,
            ),
            ("current_snapshot", paths.current_snapshot, canonical_paths.current_snapshot),
        )
        for field_name, supplied_path, canonical_path in supplied_and_canonical:
            if supplied_path.resolve(strict=False) != canonical_path.resolve(strict=False):
                raise UnsafePathError(
                    f"{field_name} does not match the canonical mission layout"
                )

        revision_path = self.revision_path(canonical_paths, validated.revision)
        if revision_path.exists() or revision_path.is_symlink():
            raise ImmutableArtifactError(
                f"immutable artifact already exists: {revision_path}"
            )

        if canonical_paths.current_snapshot.exists():
            loaded = self.load_mission(validated.mission_id)
            current = loaded.snapshot
            if validated.revision != current.revision + 1:
                raise PersistenceError("snapshot revision must increment by exactly one")
            if validated.previous_snapshot_sha256 != loaded.current_snapshot_sha256:
                raise PersistenceError("previous snapshot hash does not match current")
            if (
                validated.request_id != current.request_id
                or validated.run_mode is not current.run_mode
                or validated.started_at != current.started_at
            ):
                raise PersistenceError("snapshot identity changed during transition")
            current_artifacts = {item.name: item for item in current.artifacts}
            next_artifacts = {item.name: item for item in validated.artifacts}
            for name, artifact in current_artifacts.items():
                if name not in next_artifacts or next_artifacts[name] != artifact:
                    raise PersistenceError(
                        f"snapshot transition removed or changed artifact: {name}"
                    )
            for name, component in current.components.items():
                if validated.components.get(name) != component:
                    raise PersistenceError(
                        f"snapshot transition changed component provenance: {name}"
                    )
        elif validated.revision != 1 or validated.previous_snapshot_sha256 is not None:
            raise PersistenceError("the first snapshot must be revision 1")

        self._validate_snapshot_artifacts(canonical_mission_root, validated)

        payload = canonical_json_bytes(validated.to_dict())
        _write_immutable_bytes(revision_path, payload)
        _atomic_write_bytes(canonical_paths.current_snapshot, payload)
        return sha256_bytes(payload)
