"""Contained and durable filesystem storage for Harbormaster missions."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contracts import ArtifactReference, MissionRequest, MissionSnapshot
from .contracts.mission_request import ContractValidationError
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

        for artifact in validated.artifacts:
            artifact_path = self._contained_target(canonical_mission_root, artifact.path)
            if not artifact_path.is_file():
                raise PersistenceError(f"referenced artifact does not exist: {artifact.path}")
            if sha256_file(artifact_path) != artifact.sha256:
                raise PersistenceError(f"artifact hash mismatch: {artifact.path}")

        if validated.revision > 1:
            previous_path = self._contained_target(
                canonical_mission_root,
                f"snapshots/mission_snapshot-r{validated.revision - 1:04d}.json",
            )
            if not previous_path.is_file():
                raise PersistenceError("previous immutable snapshot does not exist")
            if sha256_file(previous_path) != validated.previous_snapshot_sha256:
                raise PersistenceError("previous snapshot hash does not match")

        revision_path = self._contained_target(
            canonical_mission_root,
            f"snapshots/mission_snapshot-r{validated.revision:04d}.json",
        )
        payload = canonical_json_bytes(validated.to_dict())
        _write_immutable_bytes(revision_path, payload)
        _atomic_write_bytes(canonical_paths.current_snapshot, payload)
        return sha256_bytes(payload)
