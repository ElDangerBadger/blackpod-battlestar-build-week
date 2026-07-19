"""Pure, validated snapshot transitions for implemented mission stages."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .contracts import (
    MODELDOCK_FAILURE_ARTIFACT_NAMES,
    MODELDOCK_FAILURE_WITH_RESPONSE_ARTIFACT_NAMES,
    MODELDOCK_NARRATIVE_ARTIFACT_NAME,
    MODELDOCK_NARRATIVE_ARTIFACT_PATH,
    MODELDOCK_NARRATIVE_SCHEMA_VERSION,
    MODELDOCK_PROVENANCE_ARTIFACT_NAME,
    MODELDOCK_PROVENANCE_ARTIFACT_PATH,
    MODELDOCK_PROVENANCE_SCHEMA_VERSION,
    MODELDOCK_REQUEST_ARTIFACT_NAME,
    MODELDOCK_REQUEST_ARTIFACT_PATH,
    MODELDOCK_REQUEST_SCHEMA_VERSION,
    MODELDOCK_RESPONSE_ARTIFACT_NAME,
    MODELDOCK_RESPONSE_ARTIFACT_PATH,
    MODELDOCK_RESPONSE_SCHEMA_VERSION,
    MODELDOCK_SUCCESS_ARTIFACT_NAMES,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ApprovalScope,
    ArtifactReference,
    ComponentProvenance,
    ContractValidationError,
    CouncilComponentProvenance,
    CurrentPhase,
    GovernorComponentProvenance,
    MissionOutcome,
    MissionSnapshot,
    ModelDockCall,
    ModelDockCallStatus,
    ModelDockComponentProvenance,
    NavigatorMode,
    NavigatorPlanStatus,
    NavigatorState,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
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


def _existing_artifact_names(
    snapshot: MissionSnapshot,
    names: Iterable[str],
    *,
    stage_name: str = "Council",
) -> tuple[str, ...]:
    selected = tuple(names)
    if len(set(selected)) != len(selected):
        raise MissionTransitionError(
            f"existing {stage_name} input names must be unique"
        )
    known_names = {artifact.name for artifact in snapshot.artifacts}
    for name in selected:
        if name not in known_names:
            raise MissionTransitionError(
                f"{stage_name} references an unknown existing artifact: {name}"
            )
    return selected


def _append_or_reuse_artifacts(
    value: dict[str, Any],
    artifacts: Iterable[ArtifactReference],
    *,
    stage_name: str = "Council",
) -> tuple[str, ...]:
    """Append new artifacts while allowing exact references to existing inputs."""

    additions = tuple(artifacts)
    selected_names: list[str] = []
    existing_by_name = {item["name"]: item for item in value["artifacts"]}
    existing_by_path = {item["path"]: item for item in value["artifacts"]}
    for artifact in additions:
        serialized = artifact.to_dict()
        existing_name = existing_by_name.get(artifact.name)
        if existing_name is not None:
            if existing_name != serialized:
                raise MissionTransitionError(
                    f"existing {stage_name} input metadata changed: {artifact.name}"
                )
            selected_names.append(artifact.name)
            continue
        existing_path = existing_by_path.get(artifact.path)
        if existing_path is not None:
            raise MissionTransitionError(
                f"artifact path already exists under a different name: {artifact.path}"
            )
        value["artifacts"].append(serialized)
        existing_by_name[artifact.name] = serialized
        existing_by_path[artifact.path] = serialized
        selected_names.append(artifact.name)
    if len(set(selected_names)) != len(selected_names):
        raise MissionTransitionError(
            f"{stage_name} input artifact references must be unique"
        )
    return tuple(selected_names)


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


def _require_oracle_enrichment_start(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError(
            "a terminal mission cannot start Oracle narrative enrichment"
        )
    if snapshot.current_phase is not CurrentPhase.COUNCIL:
        raise MissionTransitionError(
            "Oracle narrative enrichment requires the COUNCIL phase"
        )
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE:
        raise MissionTransitionError(
            "Oracle narrative enrichment requires an INCOMPLETE mission"
        )
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Harbormaster must have succeeded")
    oracle = snapshot.stages["oracle"]
    if oracle.status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError(
            "Oracle structured analysis must succeed before narrative enrichment"
        )
    if oracle.error is not None:
        raise MissionTransitionError("successful Oracle state contains an error")
    if oracle.modeldock_calls or "modeldock" in snapshot.components:
        raise MissionTransitionError("ModelDock enrichment is already recorded")
    if "battlestar" not in snapshot.components:
        raise MissionTransitionError("Battlestar Oracle provenance is missing")
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must be NOT_STARTED before Oracle enrichment"
            )


_MODELDOCK_TRANSITION_ARTIFACT_CONTRACTS = {
    MODELDOCK_REQUEST_ARTIFACT_NAME: (
        MODELDOCK_REQUEST_ARTIFACT_PATH,
        "harbormaster",
        MODELDOCK_REQUEST_SCHEMA_VERSION,
    ),
    MODELDOCK_RESPONSE_ARTIFACT_NAME: (
        MODELDOCK_RESPONSE_ARTIFACT_PATH,
        "modeldock",
        MODELDOCK_RESPONSE_SCHEMA_VERSION,
    ),
    MODELDOCK_NARRATIVE_ARTIFACT_NAME: (
        MODELDOCK_NARRATIVE_ARTIFACT_PATH,
        "modeldock",
        MODELDOCK_NARRATIVE_SCHEMA_VERSION,
    ),
    MODELDOCK_PROVENANCE_ARTIFACT_NAME: (
        MODELDOCK_PROVENANCE_ARTIFACT_PATH,
        "modeldock",
        MODELDOCK_PROVENANCE_SCHEMA_VERSION,
    ),
}


def _require_canonical_modeldock_artifact(
    artifact: ArtifactReference,
    *,
    expected_name: str,
) -> None:
    expected_path, expected_producer, expected_schema = (
        _MODELDOCK_TRANSITION_ARTIFACT_CONTRACTS[expected_name]
    )
    if (
        artifact.name != expected_name
        or artifact.path != expected_path
        or artifact.producer != expected_producer
        or artifact.schema_version != expected_schema
        or artifact.byte_size is None
        or artifact.observed_at is None
    ):
        raise MissionTransitionError(
            f"{expected_name} does not match its canonical artifact contract"
        )


def _validate_begin_modeldock_call(
    snapshot: MissionSnapshot,
    *,
    observed_at: str,
    provenance: ModelDockComponentProvenance,
    request_artifact: ArtifactReference,
    call: ModelDockCall,
) -> None:
    _require_canonical_modeldock_artifact(
        request_artifact,
        expected_name=MODELDOCK_REQUEST_ARTIFACT_NAME,
    )
    if provenance.run_mode is not snapshot.run_mode:
        raise MissionTransitionError("ModelDock run mode must match the mission")
    if call.status is not ModelDockCallStatus.RUNNING:
        raise MissionTransitionError("ModelDock call must begin in RUNNING status")
    if (
        call.mission_id != snapshot.mission_id
        or call.request_id != snapshot.request_id
        or call.run_mode is not snapshot.run_mode
    ):
        raise MissionTransitionError("ModelDock call correlation must match the mission")
    if call.endpoint != provenance.endpoint:
        raise MissionTransitionError(
            "ModelDock call endpoint must match component provenance"
        )
    if call.observed_at != observed_at:
        raise MissionTransitionError(
            "ModelDock running call timestamp must match the snapshot"
        )
    if call.artifacts != (MODELDOCK_REQUEST_ARTIFACT_NAME,):
        raise MissionTransitionError(
            "RUNNING ModelDock call must reference exactly its request artifact"
        )
    if call.request_sha256 != request_artifact.sha256:
        raise MissionTransitionError(
            "ModelDock request hash must match the request artifact"
        )


def begin_oracle_enrichment(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    provenance: ModelDockComponentProvenance,
    request_artifact: ArtifactReference,
    call: ModelDockCall,
) -> MissionSnapshot:
    """Return Oracle to RUNNING while ModelDock enriches validated facts."""

    _require_oracle_enrichment_start(snapshot)
    _validate_begin_modeldock_call(
        snapshot,
        observed_at=observed_at,
        provenance=provenance,
        request_artifact=request_artifact,
        call=call,
    )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    _append_artifacts(value, (request_artifact,))
    oracle = snapshot.stages["oracle"]
    value["stages"]["oracle"] = {
        "status": StageStatus.RUNNING.value,
        "native_state": oracle.native_state,
        "inputs": list(oracle.inputs),
        "outputs": list(oracle.outputs),
        "error": None,
        "modeldock_calls": [call.to_dict()],
    }
    value["components"]["modeldock"] = provenance.to_dict()
    value["current_phase"] = CurrentPhase.ORACLE.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def _require_running_oracle_enrichment(
    snapshot: MissionSnapshot,
) -> ModelDockCall:
    oracle = snapshot.stages["oracle"]
    if snapshot.current_phase is not CurrentPhase.ORACLE:
        raise MissionTransitionError(
            "mission is not running Oracle narrative enrichment"
        )
    if oracle.status is not StageStatus.RUNNING:
        raise MissionTransitionError("Oracle enrichment must be RUNNING")
    if len(oracle.modeldock_calls) != 1:
        raise MissionTransitionError(
            "Oracle enrichment requires exactly one ModelDock call"
        )
    running_call = oracle.modeldock_calls[0]
    if running_call.status is not ModelDockCallStatus.RUNNING:
        raise MissionTransitionError("ModelDock call is not RUNNING")
    if "modeldock" not in snapshot.components:
        raise MissionTransitionError("ModelDock component provenance is missing")
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must remain NOT_STARTED during Oracle enrichment"
            )
    return running_call


def _validate_terminal_modeldock_call(
    running_call: ModelDockCall,
    call: ModelDockCall,
    *,
    observed_at: str,
    output_names: tuple[str, ...],
) -> None:
    if (
        call.call_id != running_call.call_id
        or call.mission_id != running_call.mission_id
        or call.request_id != running_call.request_id
        or call.run_mode is not running_call.run_mode
        or call.endpoint != running_call.endpoint
        or call.started_at != running_call.started_at
        or call.request_sha256 != running_call.request_sha256
    ):
        raise MissionTransitionError(
            "terminal ModelDock call changed immutable call identity"
        )
    if call.observed_at != observed_at:
        raise MissionTransitionError(
            "terminal ModelDock call timestamp must match the snapshot"
        )
    if call.artifacts != (*running_call.artifacts, *output_names):
        raise MissionTransitionError(
            "terminal ModelDock call artifacts must extend the RUNNING call exactly"
        )


def complete_oracle_enrichment(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    call: ModelDockCall,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Commit a validated narrative without changing Oracle analytical state."""

    running_call = _require_running_oracle_enrichment(snapshot)
    if call.status is not ModelDockCallStatus.SUCCEEDED:
        raise MissionTransitionError(
            "successful Oracle enrichment requires a SUCCEEDED ModelDock call"
        )
    outputs = tuple(output_artifacts)
    expected_output_names = MODELDOCK_SUCCESS_ARTIFACT_NAMES[1:]
    if tuple(artifact.name for artifact in outputs) != expected_output_names:
        raise MissionTransitionError(
            "successful ModelDock enrichment requires response, narrative, and provenance in canonical order"
        )
    for artifact, expected_name in zip(outputs, expected_output_names, strict=True):
        _require_canonical_modeldock_artifact(
            artifact,
            expected_name=expected_name,
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, outputs)
    if not output_names:
        raise MissionTransitionError(
            "successful ModelDock enrichment produced no artifacts"
        )
    _validate_terminal_modeldock_call(
        running_call,
        call,
        observed_at=observed_at,
        output_names=output_names,
    )
    oracle = snapshot.stages["oracle"]
    value["stages"]["oracle"] = {
        "status": StageStatus.SUCCEEDED.value,
        "native_state": oracle.native_state,
        "inputs": list(oracle.inputs),
        "outputs": [*oracle.outputs, MODELDOCK_NARRATIVE_ARTIFACT_NAME],
        "error": None,
        "modeldock_calls": [call.to_dict()],
    }
    value["current_phase"] = CurrentPhase.COUNCIL.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def fail_oracle_enrichment(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    call: ModelDockCall,
    error: StageError,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Commit a strict-policy ModelDock technical failure without losing facts."""

    running_call = _require_running_oracle_enrichment(snapshot)
    if call.status is not ModelDockCallStatus.FAILED or call.error != error:
        raise MissionTransitionError(
            "failed Oracle enrichment requires a matching FAILED ModelDock call"
        )
    if error.observed_at != observed_at:
        raise MissionTransitionError(
            "ModelDock error timestamp must match the snapshot"
        )
    outputs = tuple(output_artifacts)
    output_names_supplied = tuple(artifact.name for artifact in outputs)
    allowed_failure_outputs = {
        MODELDOCK_FAILURE_ARTIFACT_NAMES[1:],
        MODELDOCK_FAILURE_WITH_RESPONSE_ARTIFACT_NAMES[1:],
    }
    if output_names_supplied not in allowed_failure_outputs:
        raise MissionTransitionError(
            "failed ModelDock enrichment requires provenance, optionally preceded by a safe response, and never a narrative"
        )
    for artifact in outputs:
        _require_canonical_modeldock_artifact(
            artifact,
            expected_name=artifact.name,
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, outputs)
    _validate_terminal_modeldock_call(
        running_call,
        call,
        observed_at=observed_at,
        output_names=output_names,
    )
    oracle = snapshot.stages["oracle"]
    value["stages"]["oracle"] = {
        "status": StageStatus.FAILED.value,
        "native_state": oracle.native_state,
        "inputs": list(oracle.inputs),
        "outputs": list(oracle.outputs),
        "error": error.to_dict(),
        "modeldock_calls": [call.to_dict()],
    }
    value["current_phase"] = CurrentPhase.ORACLE.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)


def _require_oracle_complete_for_council(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError("a terminal mission cannot start Council")
    if snapshot.current_phase is not CurrentPhase.COUNCIL:
        raise MissionTransitionError("mission is not in the COUNCIL phase")
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE:
        raise MissionTransitionError("Council can start only from an INCOMPLETE mission")
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Harbormaster must have succeeded before Council")
    if snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Oracle must have succeeded before Council")
    if snapshot.stages["council"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Council must be NOT_STARTED")
    for stage_name in ("governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must remain NOT_STARTED during Phase 3"
            )
    if "battlestar" not in snapshot.components:
        raise MissionTransitionError("Battlestar Oracle provenance is missing")
    if "battlestar_council" in snapshot.components:
        raise MissionTransitionError("Battlestar Council provenance is already recorded")


def begin_council(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    provenance: CouncilComponentProvenance,
    existing_input_names: Iterable[str] = (),
    input_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable Council RUNNING revision after Oracle success."""

    _require_oracle_complete_for_council(snapshot)
    if provenance.run_mode is not snapshot.run_mode:
        raise MissionTransitionError("Battlestar Council run mode must match the mission")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    selected_existing = _existing_artifact_names(snapshot, existing_input_names)
    selected_artifacts = _append_or_reuse_artifacts(value, input_artifacts)
    input_names = tuple(dict.fromkeys((*selected_existing, *selected_artifacts)))
    if not input_names:
        raise MissionTransitionError("Council requires at least one recorded input")
    value["stages"]["council"] = {
        "status": StageStatus.RUNNING.value,
        "native_state": None,
        "inputs": list(input_names),
        "outputs": [],
        "error": None,
    }
    value["current_phase"] = CurrentPhase.COUNCIL.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    value["components"]["battlestar_council"] = provenance.to_dict()
    return MissionSnapshot.from_mapping(value)


def _require_running_council(snapshot: MissionSnapshot) -> None:
    if snapshot.current_phase is not CurrentPhase.COUNCIL:
        raise MissionTransitionError("mission is not in the COUNCIL phase")
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Harbormaster state changed unexpectedly")
    if snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED:
        raise MissionTransitionError("Oracle state changed unexpectedly")
    if snapshot.stages["council"].status is not StageStatus.RUNNING:
        raise MissionTransitionError("Council must be RUNNING")
    for stage_name in ("governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise MissionTransitionError(
                f"{stage_name} must remain NOT_STARTED during Phase 3"
            )
    if "battlestar" not in snapshot.components:
        raise MissionTransitionError("Battlestar Oracle provenance is missing")
    if "battlestar_council" not in snapshot.components:
        raise MissionTransitionError("Battlestar Council provenance is missing")


def complete_council(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Create the immutable technically-successful Council revision."""

    _require_running_council(snapshot)
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    if not output_names:
        raise MissionTransitionError("successful Council execution produced no artifacts")
    value["stages"]["council"] = {
        "status": StageStatus.SUCCEEDED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["council"].inputs),
        "outputs": list(output_names),
        "error": None,
    }
    value["current_phase"] = CurrentPhase.GOVERNOR.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def fail_council(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str | None,
    error: StageError,
    output_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable technical-failure Council revision."""

    _require_running_council(snapshot)
    if error.observed_at != observed_at:
        raise MissionTransitionError("Council error timestamp must match the snapshot")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    value["stages"]["council"] = {
        "status": StageStatus.FAILED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["council"].inputs),
        "outputs": list(output_names),
        "error": error.to_dict(),
    }
    value["current_phase"] = CurrentPhase.COUNCIL.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)


def _require_council_complete_for_governor(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError("a terminal mission cannot start Governor")
    if snapshot.current_phase is not CurrentPhase.GOVERNOR:
        raise MissionTransitionError("mission is not in the GOVERNOR phase")
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE:
        raise MissionTransitionError(
            "Governor can start only from an INCOMPLETE mission"
        )
    for stage_name in ("harbormaster", "oracle", "council"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} must have succeeded before Governor"
            )
    if snapshot.stages["governor"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Governor must be NOT_STARTED")
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError(
            "Navigator must remain NOT_STARTED during Phase 4"
        )
    if not {"battlestar", "battlestar_council"}.issubset(snapshot.components):
        raise MissionTransitionError(
            "Battlestar Oracle and Council provenance are required"
        )
    if "battlestar_governor" in snapshot.components:
        raise MissionTransitionError(
            "Battlestar Governor provenance is already recorded"
        )
    if snapshot.operator.route is not None:
        raise MissionTransitionError("operator routing must not precede Governor")


def begin_governor(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    provenance: GovernorComponentProvenance,
    existing_input_names: Iterable[str] = (),
    input_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable Governor RUNNING revision after Council success."""

    _require_council_complete_for_governor(snapshot)
    if provenance.run_mode is not snapshot.run_mode:
        raise MissionTransitionError(
            "Battlestar Governor run mode must match the mission"
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    selected_existing = _existing_artifact_names(
        snapshot, existing_input_names, stage_name="Governor"
    )
    selected_artifacts = _append_or_reuse_artifacts(
        value, input_artifacts, stage_name="Governor"
    )
    input_names = tuple(dict.fromkeys((*selected_existing, *selected_artifacts)))
    if not input_names:
        raise MissionTransitionError("Governor requires at least one recorded input")
    value["stages"]["governor"] = {
        "status": StageStatus.RUNNING.value,
        "native_state": None,
        "inputs": list(input_names),
        "outputs": [],
        "error": None,
    }
    value["current_phase"] = CurrentPhase.GOVERNOR.value
    value["mission_outcome"] = MissionOutcome.INCOMPLETE.value
    value["terminal"] = False
    value["components"]["battlestar_governor"] = provenance.to_dict()
    return MissionSnapshot.from_mapping(value)


def _require_running_governor(snapshot: MissionSnapshot) -> None:
    if snapshot.current_phase is not CurrentPhase.GOVERNOR:
        raise MissionTransitionError("mission is not in the GOVERNOR phase")
    for stage_name in ("harbormaster", "oracle", "council"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} state changed unexpectedly"
            )
    if snapshot.stages["governor"].status is not StageStatus.RUNNING:
        raise MissionTransitionError("Governor must be RUNNING")
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError(
            "Navigator must remain NOT_STARTED during Phase 4"
        )
    if not {
        "battlestar",
        "battlestar_council",
        "battlestar_governor",
    }.issubset(snapshot.components):
        raise MissionTransitionError("Governor component provenance is incomplete")
    if snapshot.operator.route is not None:
        raise MissionTransitionError("operator routing must not precede completion")


_GOVERNOR_COMPLETION_STATE: dict[
    str, tuple[CurrentPhase, MissionOutcome, bool, OperatorRoute]
] = {
    "PROCEED": (
        CurrentPhase.OPERATOR,
        MissionOutcome.HELD,
        False,
        OperatorRoute.PENDING_APPROVAL,
    ),
    "HOLD": (
        CurrentPhase.OPERATOR,
        MissionOutcome.HELD,
        False,
        OperatorRoute.PENDING_REVIEW,
    ),
    "REVIEW_REQUIRED": (
        CurrentPhase.OPERATOR,
        MissionOutcome.HELD,
        False,
        OperatorRoute.PENDING_REVIEW,
    ),
    "BLOCKED": (
        CurrentPhase.GOVERNOR,
        MissionOutcome.HELD,
        True,
        OperatorRoute.CLOSED_BLOCKED,
    ),
    "STAND_DOWN": (
        CurrentPhase.COMPLETE,
        MissionOutcome.VETOED,
        True,
        OperatorRoute.CLOSED_NO_ACTION,
    ),
}


def complete_governor(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Create a technically-successful rendered Governor revision."""

    _require_running_governor(snapshot)
    try:
        phase, outcome, terminal, route = _GOVERNOR_COMPLETION_STATE[native_state]
    except (KeyError, TypeError) as exc:
        raise MissionTransitionError(
            "Governor returned an unsupported rendered disposition"
        ) from exc
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    if not output_names:
        raise MissionTransitionError(
            "successful Governor execution produced no artifacts"
        )
    value["stages"]["governor"] = {
        "status": StageStatus.SUCCEEDED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["governor"].inputs),
        "outputs": list(output_names),
        "error": None,
    }
    value["current_phase"] = phase.value
    value["mission_outcome"] = outcome.value
    value["terminal"] = terminal
    value["operator"] = {
        "route": route.value,
        "action": None,
        "result": None,
        "operator_id": None,
        "acted_at": None,
    }
    return MissionSnapshot.from_mapping(value)


def fail_governor(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str | None,
    error: StageError,
    output_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable technical-failure Governor revision."""

    _require_running_governor(snapshot)
    if error.observed_at != observed_at:
        raise MissionTransitionError(
            "Governor error timestamp must match the snapshot"
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    value["stages"]["governor"] = {
        "status": StageStatus.FAILED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["governor"].inputs),
        "outputs": list(output_names),
        "error": error.to_dict(),
    }
    value["current_phase"] = CurrentPhase.GOVERNOR.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)


def _operator_action(value: OperatorAction | str) -> OperatorAction:
    try:
        return value if isinstance(value, OperatorAction) else OperatorAction(value)
    except (TypeError, ValueError) as exc:
        raise MissionTransitionError("operator action is unsupported") from exc


def _operator_result(value: OperatorResult | str) -> OperatorResult:
    try:
        return value if isinstance(value, OperatorResult) else OperatorResult(value)
    except (TypeError, ValueError) as exc:
        raise MissionTransitionError("operator result is unsupported") from exc


def _require_governor_proceed_for_operator(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError("a terminal mission cannot start operator review")
    if snapshot.current_phase is not CurrentPhase.OPERATOR:
        raise MissionTransitionError("mission is not in the OPERATOR phase")
    if snapshot.mission_outcome is not MissionOutcome.HELD:
        raise MissionTransitionError("operator review requires a HELD mission")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} must have succeeded before operator review"
            )
    if snapshot.stages["governor"].native_state != "PROCEED":
        raise MissionTransitionError(
            "operator action is supported only after Governor PROCEED"
        )
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Navigator must be NOT_STARTED")
    if snapshot.operator.route is not OperatorRoute.PENDING_APPROVAL:
        raise MissionTransitionError("operator route must be PENDING_APPROVAL")
    if snapshot.operator.action_status is not OperatorActionStatus.NOT_STARTED:
        raise MissionTransitionError("operator action must be NOT_STARTED")
    if snapshot.navigator != NavigatorState.empty() or snapshot.approval_scope is not None:
        raise MissionTransitionError(
            "Navigator state or approval scope already exists"
        )


def begin_operator_action(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    action: OperatorAction | str,
    operator_id: str,
    input_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Record the immutable RUNNING revision for explicit operator review."""

    _require_governor_proceed_for_operator(snapshot)
    parsed_action = _operator_action(action)
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    _append_or_reuse_artifacts(
        value,
        input_artifacts,
        stage_name="Operator",
    )
    value["operator"] = {
        "route": OperatorRoute.PENDING_APPROVAL.value,
        "action_status": OperatorActionStatus.RUNNING.value,
        "action": parsed_action.value,
        "result": None,
        "action_id": None,
        "operator_id": operator_id,
        "acted_at": None,
        "error": None,
    }
    value["current_phase"] = CurrentPhase.OPERATOR.value
    value["mission_outcome"] = MissionOutcome.HELD.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def _require_running_operator_action(snapshot: MissionSnapshot) -> None:
    if snapshot.current_phase is not CurrentPhase.OPERATOR:
        raise MissionTransitionError("mission is not in the OPERATOR phase")
    if snapshot.mission_outcome is not MissionOutcome.HELD or snapshot.terminal:
        raise MissionTransitionError("operator action requires a nonterminal HELD mission")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} state changed during operator review"
            )
    if snapshot.stages["governor"].native_state != "PROCEED":
        raise MissionTransitionError("Governor disposition changed during operator review")
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Navigator must remain NOT_STARTED")
    if (
        snapshot.operator.route is not OperatorRoute.PENDING_APPROVAL
        or snapshot.operator.action_status is not OperatorActionStatus.RUNNING
    ):
        raise MissionTransitionError("operator action must be RUNNING")


def complete_operator_action(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    result: OperatorResult | str,
    action_id: str,
    operator_id: str,
    acted_at: str,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Commit an explicit operator approval or rejection result."""

    _require_running_operator_action(snapshot)
    parsed_result = _operator_result(result)
    expected_result = {
        OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
        OperatorAction.REJECT: OperatorResult.REJECTED,
    }[snapshot.operator.action]
    if parsed_result is not expected_result:
        raise MissionTransitionError("operator action and result are inconsistent")
    if operator_id != snapshot.operator.operator_id:
        raise MissionTransitionError("operator result actor differs from review actor")
    if not (
        parse_rfc3339(snapshot.observed_at, "operator start observed_at")
        <= parse_rfc3339(acted_at, "operator acted_at")
        <= parse_rfc3339(observed_at, "observed_at")
    ):
        raise MissionTransitionError(
            "operator acted_at must fall within the recorded action attempt"
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    if not output_names:
        raise MissionTransitionError(
            "successful operator action requires an immutable action artifact"
        )
    value["operator"] = {
        "route": OperatorRoute.PENDING_APPROVAL.value,
        "action_status": OperatorActionStatus.SUCCEEDED.value,
        "action": snapshot.operator.action.value,
        "result": parsed_result.value,
        "action_id": action_id,
        "operator_id": operator_id,
        "acted_at": acted_at,
        "error": None,
    }
    if parsed_result is OperatorResult.APPROVED_FOR_HANDOFF:
        value["current_phase"] = CurrentPhase.NAVIGATOR.value
        value["mission_outcome"] = MissionOutcome.HELD.value
        value["terminal"] = False
        value["approval_scope"] = ApprovalScope.NAVIGATOR_SHADOW_HANDOFF.value
    else:
        value["current_phase"] = CurrentPhase.COMPLETE.value
        value["mission_outcome"] = MissionOutcome.VETOED.value
        value["terminal"] = True
        value["approval_scope"] = None
    return MissionSnapshot.from_mapping(value)


def fail_operator_action(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    error: StageError,
    action_id: str | None = None,
    output_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Commit a structured technical failure for operator-action recording."""

    _require_running_operator_action(snapshot)
    if error.observed_at != observed_at:
        raise MissionTransitionError(
            "operator action error timestamp must match the snapshot"
        )
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    _append_artifacts(value, output_artifacts)
    value["operator"] = {
        "route": OperatorRoute.PENDING_APPROVAL.value,
        "action_status": OperatorActionStatus.FAILED.value,
        "action": snapshot.operator.action.value,
        "result": None,
        "action_id": action_id,
        "operator_id": snapshot.operator.operator_id,
        "acted_at": observed_at,
        "error": error.to_dict(),
    }
    value["current_phase"] = CurrentPhase.OPERATOR.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)


def _require_operator_approval_for_navigator(snapshot: MissionSnapshot) -> None:
    if snapshot.terminal:
        raise MissionTransitionError("a terminal mission cannot start Navigator")
    if snapshot.current_phase is not CurrentPhase.NAVIGATOR:
        raise MissionTransitionError("mission is not in the NAVIGATOR phase")
    if snapshot.mission_outcome is not MissionOutcome.HELD:
        raise MissionTransitionError("Navigator requires a HELD approved handoff")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} must have succeeded before Navigator"
            )
    if snapshot.stages["governor"].native_state != "PROCEED":
        raise MissionTransitionError("Navigator requires Governor PROCEED")
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise MissionTransitionError("Navigator must be NOT_STARTED")
    if (
        snapshot.operator.route is not OperatorRoute.PENDING_APPROVAL
        or snapshot.operator.action_status is not OperatorActionStatus.SUCCEEDED
        or snapshot.operator.action is not OperatorAction.APPROVE_HANDOFF
        or snapshot.operator.result is not OperatorResult.APPROVED_FOR_HANDOFF
    ):
        raise MissionTransitionError("Navigator requires explicit operator approval")
    if snapshot.approval_scope is not ApprovalScope.NAVIGATOR_SHADOW_HANDOFF:
        raise MissionTransitionError("Navigator approval scope is missing or unsupported")
    if snapshot.navigator != NavigatorState.empty():
        raise MissionTransitionError("Navigator native state already exists")


def begin_navigator(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    existing_input_names: Iterable[str] = (),
    input_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Create the immutable Navigator RUNNING/SHADOW revision."""

    _require_operator_approval_for_navigator(snapshot)
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    selected_existing = _existing_artifact_names(
        snapshot,
        existing_input_names,
        stage_name="Navigator",
    )
    selected_artifacts = _append_or_reuse_artifacts(
        value,
        input_artifacts,
        stage_name="Navigator",
    )
    input_names = tuple(dict.fromkeys((*selected_existing, *selected_artifacts)))
    if not input_names:
        raise MissionTransitionError("Navigator requires recorded mission inputs")
    value["stages"]["navigator"] = {
        "status": StageStatus.RUNNING.value,
        "native_state": NavigatorMode.SHADOW.value,
        "inputs": list(input_names),
        "outputs": [],
        "error": None,
    }
    value["navigator"] = NavigatorState.shadow_running().to_dict()
    value["current_phase"] = CurrentPhase.NAVIGATOR.value
    value["mission_outcome"] = MissionOutcome.HELD.value
    value["terminal"] = False
    return MissionSnapshot.from_mapping(value)


def _require_running_navigator(snapshot: MissionSnapshot) -> None:
    if snapshot.current_phase is not CurrentPhase.NAVIGATOR:
        raise MissionTransitionError("mission is not in the NAVIGATOR phase")
    if snapshot.mission_outcome is not MissionOutcome.HELD or snapshot.terminal:
        raise MissionTransitionError("Navigator requires a nonterminal HELD mission")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise MissionTransitionError(
                f"{stage_name} state changed during Navigator"
            )
    if (
        snapshot.stages["navigator"].status is not StageStatus.RUNNING
        or snapshot.stages["navigator"].native_state != NavigatorMode.SHADOW.value
        or snapshot.navigator != NavigatorState.shadow_running()
    ):
        raise MissionTransitionError("Navigator must be RUNNING in SHADOW mode")
    if (
        snapshot.operator.action_status is not OperatorActionStatus.SUCCEEDED
        or snapshot.operator.result is not OperatorResult.APPROVED_FOR_HANDOFF
        or snapshot.approval_scope is not ApprovalScope.NAVIGATOR_SHADOW_HANDOFF
    ):
        raise MissionTransitionError("Navigator operator approval changed unexpectedly")


def complete_navigator(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    navigator_state: NavigatorState,
    output_artifacts: Iterable[ArtifactReference],
) -> MissionSnapshot:
    """Commit a non-executing Navigator SHADOW plan as mission approval."""

    _require_running_navigator(snapshot)
    if not isinstance(navigator_state, NavigatorState):
        raise MissionTransitionError("Navigator completion requires typed native state")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    if not output_names:
        raise MissionTransitionError("successful Navigator execution produced no artifacts")
    value["stages"]["navigator"] = {
        "status": StageStatus.SUCCEEDED.value,
        "native_state": NavigatorPlanStatus.CREATED.value,
        "inputs": list(snapshot.stages["navigator"].inputs),
        "outputs": list(output_names),
        "error": None,
    }
    value["navigator"] = navigator_state.to_dict()
    value["current_phase"] = CurrentPhase.COMPLETE.value
    value["mission_outcome"] = MissionOutcome.APPROVED.value
    value["terminal"] = True
    return MissionSnapshot.from_mapping(value)


def fail_navigator(
    snapshot: MissionSnapshot,
    *,
    previous_snapshot_sha256: str,
    observed_at: str,
    native_state: str | None,
    error: StageError,
    navigator_state: NavigatorState | None = None,
    output_artifacts: Iterable[ArtifactReference] = (),
) -> MissionSnapshot:
    """Commit a structured Navigator technical failure and partial native state."""

    _require_running_navigator(snapshot)
    if error.observed_at != observed_at:
        raise MissionTransitionError("Navigator error timestamp must match the snapshot")
    partial_state = navigator_state or snapshot.navigator
    if not isinstance(partial_state, NavigatorState):
        raise MissionTransitionError("Navigator failure requires typed native state")
    value = _base_transition(
        snapshot,
        previous_snapshot_sha256=previous_snapshot_sha256,
        observed_at=observed_at,
    )
    output_names = _append_artifacts(value, output_artifacts)
    value["stages"]["navigator"] = {
        "status": StageStatus.FAILED.value,
        "native_state": native_state,
        "inputs": list(snapshot.stages["navigator"].inputs),
        "outputs": list(output_names),
        "error": error.to_dict(),
    }
    value["navigator"] = partial_state.to_dict()
    value["current_phase"] = CurrentPhase.NAVIGATOR.value
    value["mission_outcome"] = MissionOutcome.FAILED.value
    value["terminal"] = not error.resumable
    return MissionSnapshot.from_mapping(value)
