"""Pure, validated snapshot transitions for the Phase 2 Oracle stage."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import (
    ArtifactReference,
    ComponentProvenance,
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionSnapshot,
    StageError,
    StageStatus,
)
from .contracts.mission_request import parse_rfc3339


class MissionTransitionError(ContractValidationError):
    """Raised when a requested stage transition is not legal."""


def _base_transition(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
) -> dict[str, Any]:
    if parse_rfc3339(observed_at, "observed_at") < parse_rfc3339(
        snapshot.observed_at, "previous observed_at"
    ):
        raise MissionTransitionError("observed_at may not move backwards")
    value = snapshot.to_dict()
    next_revision = snapshot.revision + 1
    value.update(
        {
            "snapshot_id": f"{snapshot.mission_id}-r{next_revision:04d}",
            "revision": next_revision,
            "previous_snapshot_sha256": previous_snapshot_sha256,
            "observed_at": observed_at,
        }
    )
    return value


def _append_artifacts(
    value: dict[str, Any], artifacts: Iterable[ArtifactReference]
) -> tuple[str, ...]:
    additions = tuple(artifacts)
    existing_names = {item["name"] for item in value["artifacts"]}
    existing_paths = {item["path"] for item in value["artifacts"]}
    for artifact in additions:
        if artifact.name in existing_names:
            raise MissionTransitionError(
                f"artifact name already exists: {artifact.name}"
            )
        if artifact.path in existing_paths:
            raise MissionTransitionError(
                f"artifact path already exists: {artifact.path}"
            )
        value["artifacts"].append(artifact.to_dict())
        existing_names.add(artifact.name)
        existing_paths.add(artifact.path)
    return tuple(item.name for item in additions)


def _require_phase1_oracle_start(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError("a terminal mission cannot start Oracle")
    if snapshot.current_phase is not CurrentPhase.ORACLE:
        raise MissionTransitionError("mission is not in the ORACLE phase")
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Harbormaster must have succeeded before Oracle")
    if snapshot.stages["oracle"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Oracle must be NOT_STARTED")
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must remain NOT_STARTED during Phase 2"
            )
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE:
        raise MissionTransitionError("Oracle can start only from an INCOMPLETE mission")
    if "battlestar" in snapshot.components:
        raise MissionTransitionError("Battlestar provenance is already recorded")


def begin_oracle(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    provenance: ComponentProvenance,
    input_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Create the immutable Oracle RUNNING revision from Phase 1."""

    _require_phase1_oracle_start(snapshot)
    if provenance.run_mode is not snapshot.run_mode:
        raise MissionTransitionError("Battlestar run mode must match the mission")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    input_names = _append_artifacts(value, input_artifacts)
    if not input_names:
        raise MissionTransitionError("Oracle requires at least one captured input")
    value["stages"]["oracle"] = {
        "status": StageStatus.RUNNING.value,
        "native_state": None,
        "inputs": list(input_names),
        "outputs": [],
        "error": None,
    }
    value["current_phase"] = CurrentPhase.ORACLE.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    value["components"] = {"battlestar": provenance.to_dict()}
    return MissionSnapshot.from_mapping(value)


def _require_running_oracle(snapshot: MissionSnapshot) -> None:
    if snapshot.current_phase is not CurrentPhase.ORACLE:
        raise MissionTransitionError("mission is not in the ORACLE phase")
    if snapshot.stages["oracle"].status is not StageStatus.RUNNING:
        raise MissionTransitionError("Oracle must be RUNNING")
    if "battlestar" not in snapshot.components:
        raise MissionTransitionError("Battlestar provenance is missing")
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Harbormaster state changed unexpectedly")
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must remain NOT_STARTED during Phase 2"
            )


def complete_oracle(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Create the immutable technically-successful Oracle revision."""

    _require_running_oracle(snapshot)
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    if not output_names:
        raise MissionTransitionError("successful Oracle execution produced no artifacts")
    value["stages"]["oracle"] = {
        "status": StageStatus.SUCCEEDED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["oracle"].inputs),
        "outputs": list(output_names),
        "error": None,
    }
    value["current_phase"] = CurrentPhase.COUNCIL.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def fail_oracle(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str | None,
    error: StageError,
    output_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable technical-failure Oracle revision."""

    _require_running_oracle(snapshot)
    if error.observed_at != observed_at:
        raise MissionTransitionError("Oracle error timestamp must match the snapshot")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    value["stages"]["oracle"] = {
        "status": StageStatus.FAILED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["oracle"].inputs),
        "outputs": list(output_names),
        "error": error.to_dict(),
    }
    value["current_phase"] = CurrentPhase.ORACLE.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)
