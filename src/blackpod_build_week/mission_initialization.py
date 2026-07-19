"""Mission initialization shared by stage-level and unified Harbormaster flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from .contracts import MissionRequest, MissionSnapshot, RunMode
from .contracts.mission_request import format_rfc3339
from .hashing import sha256_bytes
from .identifiers import allocate_mission_id
from .mission_store import (
    DuplicateMissionError,
    MissionInitialization,
    MissionPaths,
    MissionStore,
)


@dataclass(frozen=True, slots=True)
class HarbormasterSettings:
    request_path: Path
    artifacts_root: Path


class MissionInitializationAction(str, Enum):
    INITIALIZED = "INITIALIZED"
    NO_OP_EXISTING_VALIDATED = "NO_OP_EXISTING_VALIDATED"


class ExistingMissionConflictError(DuplicateMissionError):
    """Raised when a deterministic mission ID belongs to another request."""


@dataclass(frozen=True, slots=True)
class MissionInitializationResolution:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    snapshot_sha256: str
    action: MissionInitializationAction


def allocate_request_mission_id(request: MissionRequest) -> str:
    """Allocate the same stable mission ID used by the Phase 1 command."""

    return allocate_mission_id(
        request.identity_payload(),
        request_id=request.request_id,
        run_mode=request.run_mode.value,
        supplied_mission_id=request.mission_id,
    )


def initialize_mission(
    settings: HarbormasterSettings,
    *,
    now: datetime | None = None,
) -> MissionInitialization:
    """Validate one request and persist its Phase 1 mission spine."""

    request = MissionRequest.from_file(settings.request_path)
    mission_id = allocate_request_mission_id(request)

    if request.run_mode is RunMode.REPLAY:
        initialization_time = request.requested_at
    else:
        clock_value = now if now is not None else datetime.now(UTC)
        initialization_time = format_rfc3339(clock_value)

    store = MissionStore(settings.artifacts_root)
    return store.initialize(
        request,
        mission_id=mission_id,
        started_at=initialization_time,
        observed_at=initialization_time,
    )


def initialize_or_validate_existing(
    settings: HarbormasterSettings,
    *,
    now: datetime | None = None,
) -> MissionInitializationResolution:
    """Initialize a mission, or validate the identical existing request.

    A repeated unified command is idempotent only when the deterministic mission
    ID resolves to byte-equivalent canonical request data.  Existing mission
    integrity, including its snapshot chain and artifacts, is verified by
    :meth:`MissionStore.load_mission` before the no-op is returned.
    """

    incoming = MissionRequest.from_file(settings.request_path)
    mission_id = allocate_request_mission_id(incoming)
    expected = incoming.with_mission_id(mission_id)
    try:
        initialized = initialize_mission(settings, now=now)
    except DuplicateMissionError:
        loaded = MissionStore(settings.artifacts_root).load_mission(mission_id)
        if loaded.request.to_dict() != expected.to_dict():
            raise ExistingMissionConflictError(
                "existing mission request differs from this invocation"
            )
        return MissionInitializationResolution(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            snapshot_sha256=loaded.current_snapshot_sha256,
            action=MissionInitializationAction.NO_OP_EXISTING_VALIDATED,
        )

    # MissionInitialization already carries the committed digest.  Recompute
    # only as a defensive compatibility fallback for older test doubles.
    digest = getattr(initialized, "snapshot_sha256", None)
    if not isinstance(digest, str):
        digest = sha256_bytes(initialized.paths.current_snapshot.read_bytes())
    return MissionInitializationResolution(
        request=initialized.request,
        snapshot=initialized.snapshot,
        paths=initialized.paths,
        snapshot_sha256=digest,
        action=MissionInitializationAction.INITIALIZED,
    )
