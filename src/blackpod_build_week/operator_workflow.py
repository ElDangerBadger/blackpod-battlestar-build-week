"""Harbormaster-owned orchestration for one immutable Phase 5 operator action."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import BattlestarConfig, load_operator_battlestar_config
from .contracts import (
    ArtifactReference,
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    RunMode,
    StageError,
    StageStatus,
)
from .contracts.mission_request import (
    format_rfc3339,
    load_strict_json_object,
    parse_rfc3339,
)
from .contracts.mission_snapshot import (
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
)
from .hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .identifiers import IdentifierError, validate_identifier
from .mission_store import LoadedMission, MissionPaths, MissionStore
from .mission_transitions import (
    begin_operator_action,
    complete_operator_action,
    fail_operator_action,
)
from .operator_adapter import (
    EXPECTED_OPERATOR_OUTPUT_PATHS,
    GOVERNOR_DECISION_PATH,
    GOVERNOR_DELIBERATION_PATH,
    GOVERNOR_LINEAGE_PATH,
    GOVERNOR_PROVENANCE_PATH,
    GOVERNOR_READINESS_PATH,
    GOVERNOR_RENDERED_PATH,
    OPERATOR_ACTION_PATH,
    OPERATOR_ACTION_SCHEMA_VERSION,
    OPERATOR_ATTEMPT_DIRECTORY,
    OPERATOR_LEDGER_ENTRY_PATH,
    OPERATOR_LEDGER_SCHEMA_VERSION,
    OPERATOR_LINEAGE_PATH,
    OPERATOR_LINEAGE_SCHEMA_VERSION,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_PROVENANCE_SCHEMA_VERSION,
    OPERATOR_RECEIPT_PATH,
    OPERATOR_RECEIPT_SCHEMA_VERSION,
    OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
    OPERATOR_REPLAY_INPUT_PATH,
    OPERATOR_REVIEW_PACKET_PATH,
    OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
    NATIVE_OPERATOR_ACTION_FIELDS,
    NATIVE_OPERATOR_LEDGER_FIELDS,
    NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
    NATIVE_OPERATOR_RECEIPT_FIELDS,
    OperatorActionInput,
    OperatorAdapter,
    OperatorExecutionResult,
    OperatorFailure,
    OperatorMissionContext,
)


REQUIRED_OPERATOR_INPUTS: Mapping[str, tuple[str, str, str]] = {
    "governor_decision": (
        GOVERNOR_DECISION_PATH,
        "governor",
        "blackpod.contracts.governor_decision.GovernorDecision",
    ),
    "governor_decision_readiness": (
        GOVERNOR_READINESS_PATH,
        "governor",
        "blackpod.contracts.GovernorDecisionReadiness",
    ),
    "governor_deliberation": (
        GOVERNOR_DELIBERATION_PATH,
        "governor",
        "blackpod.contracts.GovernorDeliberation",
    ),
    "governor_rendered_decision": (
        GOVERNOR_RENDERED_PATH,
        "governor",
        "blackpod.governor_rendered_decision.v1",
    ),
    "governor_provenance": (
        GOVERNOR_PROVENANCE_PATH,
        "governor",
        "blackpod.governor_provenance.v1",
    ),
    "governor_lineage_manifest": (
        GOVERNOR_LINEAGE_PATH,
        "governor",
        "blackpod.governor_lineage.v1",
    ),
}

OPERATOR_OUTPUT_ARTIFACTS: Mapping[str, tuple[str, str | None]] = {
    OPERATOR_REVIEW_PACKET_PATH: (
        "operator_review_packet",
        OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
    ),
    OPERATOR_ACTION_PATH: ("operator_action", OPERATOR_ACTION_SCHEMA_VERSION),
    OPERATOR_RECEIPT_PATH: ("operator_receipt", OPERATOR_RECEIPT_SCHEMA_VERSION),
    OPERATOR_LEDGER_ENTRY_PATH: (
        "operator_ledger_entry",
        OPERATOR_LEDGER_SCHEMA_VERSION,
    ),
    OPERATOR_PROVENANCE_PATH: (
        "operator_provenance",
        OPERATOR_PROVENANCE_SCHEMA_VERSION,
    ),
    OPERATOR_LINEAGE_PATH: (
        "operator_lineage_manifest",
        OPERATOR_LINEAGE_SCHEMA_VERSION,
    ),
}


class OperatorWorkflowError(RuntimeError):
    """Base class for Phase 5 orchestration failures."""


class OperatorInvocationError(OperatorWorkflowError):
    """Raised when explicit action inputs conflict with the mission transport."""


class OperatorPreconditionError(OperatorWorkflowError):
    """Raised when the Governor mission is not eligible for operator review."""


class OperatorStateConflictError(OperatorWorkflowError):
    """Raised when the immutable one-action policy prevents execution."""


class OperatorWorkflowDisposition(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class OperatorRunSettings:
    mission_id: str
    artifacts_root: Path
    action: OperatorAction | str
    operator_id: str
    reason: str
    replay_fixture: Path | None = None
    expires_in_minutes: int | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class OperatorWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    disposition: OperatorWorkflowDisposition
    operator_artifact_directory: Path
    technical_status: OperatorActionStatus
    route: OperatorRoute
    action: OperatorAction
    result: OperatorResult | None
    action_id: str | None
    operator_id: str
    acted_at: str | None


class OperatorExecutor(Protocol):
    def execute(
        self,
        request: MissionRequest,
        context: OperatorMissionContext,
        *,
        action_input: OperatorActionInput,
    ) -> OperatorExecutionResult: ...


ConfigLoader = Callable[..., BattlestarConfig]
Clock = Callable[[], datetime]


def run_operator_action(
    settings: OperatorRunSettings,
    *,
    environ: Mapping[str, str] | None = None,
    adapter: OperatorExecutor | None = None,
    config_loader: ConfigLoader = load_operator_battlestar_config,
    clock: Clock | None = None,
) -> OperatorWorkflowResult:
    """Record the mission's one explicit approval or rejection action."""

    parsed_action, parsed_operator, parsed_reason = _validate_settings(settings)
    config = config_loader(
        artifacts_root=settings.artifacts_root,
        environ=environ,
        strict_clean=settings.strict_battlestar_clean,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    action_not_before = loaded.snapshot.observed_at
    if (
        loaded.snapshot.operator.action_status is OperatorActionStatus.SUCCEEDED
        and loaded.snapshot.operator.acted_at is not None
    ):
        # A completed operator action may be replay-verified after Navigator has
        # advanced the mission clock. Its immutable fixture is bound to the
        # recorded action time, not the latest downstream snapshot time.
        action_not_before = loaded.snapshot.operator.acted_at
    action_input, replay_bytes = _resolve_action_input(
        loaded.request,
        action=parsed_action,
        operator_id=parsed_operator,
        reason=parsed_reason,
        replay_fixture=settings.replay_fixture,
        expires_in_minutes=settings.expires_in_minutes,
        clock=clock,
        not_before=action_not_before,
    )

    status = loaded.snapshot.operator.action_status
    if status is OperatorActionStatus.SUCCEEDED:
        _validate_completed_invocation(
            loaded,
            config=config,
            action_input=action_input,
            replay_bytes=replay_bytes,
        )
        operator = loaded.snapshot.operator
        return OperatorWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            disposition=OperatorWorkflowDisposition.NO_OP_ALREADY_SUCCEEDED,
            operator_artifact_directory=(
                loaded.paths.mission_root / OPERATOR_ATTEMPT_DIRECTORY
            ),
            technical_status=OperatorActionStatus.SUCCEEDED,
            route=operator.route or OperatorRoute.PENDING_APPROVAL,
            action=operator.action or parsed_action,
            result=operator.result,
            action_id=operator.action_id,
            operator_id=operator.operator_id or parsed_operator,
            acted_at=operator.acted_at,
        )
    if status is OperatorActionStatus.RUNNING:
        raise OperatorStateConflictError(
            "operator action is already RUNNING; Phase 5 does not overwrite or resume it"
        )
    if status is OperatorActionStatus.FAILED:
        raise OperatorStateConflictError(
            "operator action previously FAILED; Phase 5 has no force or retry option"
        )
    if status is not OperatorActionStatus.NOT_STARTED:
        raise OperatorStateConflictError(
            f"operator action cannot run from status {status.value}"
        )

    stage_inputs = _validate_operator_preconditions(
        loaded.request,
        loaded.snapshot,
        loaded.paths.mission_root,
    )
    try:
        executor: OperatorExecutor = adapter or OperatorAdapter(
            config.root,
            deadline_seconds=float(settings.deadline_seconds),
        )
    except Exception as exc:
        raise OperatorWorkflowError("operator adapter could not be prepared") from exc

    input_artifacts: tuple[ArtifactReference, ...] = ()
    if replay_bytes is not None:
        input_artifacts = (
            store.write_immutable_artifact(
                settings.mission_id,
                relative_path=OPERATOR_REPLAY_INPUT_PATH,
                payload=replay_bytes,
                name="operator_replay_action",
                producer="harbormaster",
                schema_version=OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
                observed_at=action_input.acted_at,
            ),
        )

    running = begin_operator_action(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=action_input.acted_at,
        action=action_input.action,
        operator_id=action_input.operator_id,
        input_artifacts=input_artifacts,
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    unvalidated_result: object | None = None
    try:
        store.reserve_directory(settings.mission_id, OPERATOR_ATTEMPT_DIRECTORY)
        context = OperatorMissionContext(
            mission_id=settings.mission_id,
            mission_root=loaded.paths.mission_root,
            governor_decision_path=stage_inputs["governor_decision"].path,
            governor_readiness_path=stage_inputs[
                "governor_decision_readiness"
            ].path,
            governor_deliberation_path=stage_inputs["governor_deliberation"].path,
            governor_rendered_path=stage_inputs[
                "governor_rendered_decision"
            ].path,
            governor_provenance_path=stage_inputs["governor_provenance"].path,
            governor_lineage_path=stage_inputs[
                "governor_lineage_manifest"
            ].path,
            output_dir=OPERATOR_ATTEMPT_DIRECTORY,
            battlestar_git_revision=config.git_revision,
            battlestar_git_branch=config.git_branch,
            battlestar_dirty_worktree=config.dirty_worktree,
        )
        unvalidated_result = executor.execute(
            loaded.request,
            context,
            action_input=action_input,
        )
        execution_result = _validate_execution_correlation(
            unvalidated_result,
            loaded.request,
            action_input=action_input,
        )
    except Exception as exc:
        produced_paths = (
            unvalidated_result.produced_paths
            if isinstance(unvalidated_result, OperatorExecutionResult)
            else ()
        )
        execution_result = _synthetic_failure(
            loaded.request,
            action_input,
            code="OPERATOR_ADAPTER_FAILURE",
            error_type=type(exc).__name__,
            message="operator adapter or output reservation failed",
            resumable=False,
            produced_paths=produced_paths,
        )

    finish_observed_at = _finish_observed_at(
        loaded.request.run_mode,
        action_input=action_input,
        clock=clock,
        not_before=running.observed_at,
    )
    try:
        output_artifacts = _capture_operator_outputs(
            store,
            settings.mission_id,
            execution_result.produced_paths,
            observed_at=finish_observed_at,
        )
    except Exception as exc:
        output_artifacts = ()
        execution_result = _synthetic_failure(
            loaded.request,
            action_input,
            code="OPERATOR_ARTIFACT_CAPTURE_FAILED",
            error_type=type(exc).__name__,
            message="operator artifacts failed containment or integrity validation",
            resumable=False,
        )

    if execution_result.technical_status is OperatorActionStatus.SUCCEEDED:
        if execution_result.result is None or execution_result.action_id is None:
            raise AssertionError("validated operator success lacks result identity")
        final_snapshot = complete_operator_action(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            result=execution_result.result,
            action_id=execution_result.action_id,
            operator_id=execution_result.operator_id,
            acted_at=execution_result.acted_at,
            output_artifacts=output_artifacts,
        )
    else:
        failure = execution_result.failure or OperatorFailure(
            code="OPERATOR_MALFORMED_RESULT",
            error_type="ContractValidationError",
            message="operator action failed without a structured error",
            resumable=False,
        )
        stage_error = StageError.from_mapping(
            {
                "code": failure.code,
                "error_type": failure.error_type,
                "message": failure.message,
                "resumable": failure.resumable,
                "observed_at": finish_observed_at,
            }
        )
        final_snapshot = fail_operator_action(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            error=stage_error,
            action_id=execution_result.action_id,
            output_artifacts=output_artifacts,
        )
    store.commit_snapshot(loaded.paths, final_snapshot)
    return OperatorWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        disposition=OperatorWorkflowDisposition.EXECUTED,
        operator_artifact_directory=(
            loaded.paths.mission_root / OPERATOR_ATTEMPT_DIRECTORY
        ),
        technical_status=execution_result.technical_status,
        route=execution_result.route,
        action=execution_result.action,
        result=execution_result.result,
        action_id=execution_result.action_id,
        operator_id=execution_result.operator_id,
        acted_at=execution_result.acted_at,
    )


def _validate_settings(
    settings: OperatorRunSettings,
) -> tuple[OperatorAction, str, str]:
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise OperatorInvocationError("deadline_seconds must be finite and positive")
    try:
        action = (
            settings.action
            if isinstance(settings.action, OperatorAction)
            else OperatorAction(settings.action)
        )
        operator_id = validate_identifier(settings.operator_id, "operator_id")
    except (IdentifierError, TypeError, ValueError) as exc:
        raise OperatorInvocationError(str(exc)) from exc
    if not isinstance(settings.reason, str) or not settings.reason.strip():
        raise OperatorInvocationError("reason must be a nonblank string")
    if settings.reason != settings.reason.strip() or len(settings.reason) > 1024:
        raise OperatorInvocationError("reason must be trimmed and at most 1024 characters")
    if settings.expires_in_minutes is not None and (
        isinstance(settings.expires_in_minutes, bool)
        or not isinstance(settings.expires_in_minutes, int)
        or settings.expires_in_minutes <= 0
    ):
        raise OperatorInvocationError(
            "expires_in_minutes must be null or a positive integer"
        )
    return action, operator_id, settings.reason


def _resolve_action_input(
    request: MissionRequest,
    *,
    action: OperatorAction,
    operator_id: str,
    reason: str,
    replay_fixture: Path | None,
    expires_in_minutes: int | None,
    clock: Clock | None,
    not_before: str,
) -> tuple[OperatorActionInput, bytes | None]:
    if request.run_mode is RunMode.REPLAY:
        if replay_fixture is None:
            raise OperatorInvocationError(
                "REPLAY operator action requires --replay-fixture"
            )
        source = Path(replay_fixture)
        if source.is_symlink() or not source.is_file():
            raise OperatorInvocationError(
                "operator replay action fixture must be a regular file"
            )
        try:
            payload = source.read_bytes()
            effective = OperatorActionInput.from_replay_bytes(payload)
        except (OSError, ValueError, ContractValidationError) as exc:
            raise OperatorInvocationError(
                "operator replay action fixture failed schema validation"
            ) from exc
        if (
            effective.action is not action
            or effective.operator_id != operator_id
            or effective.reason != reason
            or (
                expires_in_minutes is not None
                and effective.expires_in_minutes != expires_in_minutes
            )
        ):
            raise OperatorInvocationError(
                "CLI operator action inputs conflict with the replay fixture"
            )
        if parse_rfc3339(effective.acted_at, "acted_at") < parse_rfc3339(
            not_before, "previous observed_at"
        ):
            raise OperatorInvocationError(
                "operator replay acted_at precedes the Governor snapshot"
            )
        return effective, payload

    if replay_fixture is not None:
        raise OperatorInvocationError("LIVE operator action forbids replay fixtures")
    current = clock() if clock is not None else datetime.now(UTC)
    acted_at = format_rfc3339(current)
    if parse_rfc3339(acted_at, "acted_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        acted_at = not_before
    try:
        return (
            OperatorActionInput.live(
                action=action,
                operator_id=operator_id,
                reason=reason,
                acted_at=acted_at,
                expires_in_minutes=expires_in_minutes,
            ),
            None,
        )
    except ContractValidationError as exc:
        raise OperatorInvocationError(str(exc)) from exc


def _validate_operator_preconditions(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    mission_root: Path,
) -> dict[str, ArtifactReference]:
    if request.mission_id != snapshot.mission_id or request.request_id != snapshot.request_id:
        raise OperatorPreconditionError("mission correlation metadata is inconsistent")
    if request.run_mode is not snapshot.run_mode:
        raise OperatorPreconditionError("mission run mode is inconsistent")
    if snapshot.revision != 7:
        raise OperatorPreconditionError("operator action requires the Phase 4 r0007 snapshot")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise OperatorPreconditionError(
                f"{stage_name.title()} must be technically successful"
            )
    if (
        snapshot.stages["governor"].native_state != "PROCEED"
        or snapshot.current_phase is not CurrentPhase.OPERATOR
        or snapshot.mission_outcome is not MissionOutcome.HELD
        or snapshot.terminal
        or snapshot.operator.route is not OperatorRoute.PENDING_APPROVAL
        or snapshot.operator.action_status is not OperatorActionStatus.NOT_STARTED
        or snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED
    ):
        raise OperatorPreconditionError(
            "operator action requires Governor PROCEED / PENDING_APPROVAL / HELD"
        )

    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    governor_outputs = set(snapshot.stages["governor"].outputs)
    selected: dict[str, ArtifactReference] = {}
    for name, (expected_path, producer, _schema) in REQUIRED_OPERATOR_INPUTS.items():
        artifact = artifacts.get(name)
        if (
            artifact is None
            or name not in governor_outputs
            or artifact.path != expected_path
            or artifact.producer != producer
        ):
            raise OperatorPreconditionError(
                f"required operator input is missing or noncanonical: {name}"
            )
        path = mission_root / artifact.path
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256_file(path) != artifact.sha256
            or path.stat().st_size != artifact.byte_size
        ):
            raise OperatorPreconditionError(
                f"required operator input failed integrity: {name}"
            )
        selected[name] = artifact
    _validate_governor_lineage(
        mission_root / selected["governor_lineage_manifest"].path,
        request=request,
        selected=selected,
    )
    _validate_governor_correlation(mission_root, request=request, selected=selected)
    return selected


def _validate_governor_lineage(
    path: Path,
    *,
    request: MissionRequest,
    selected: Mapping[str, ArtifactReference],
) -> None:
    try:
        payload = load_strict_json_object(path)
    except (OSError, ContractValidationError) as exc:
        raise OperatorPreconditionError("Governor lineage manifest is malformed") from exc
    if (
        payload.get("schema_version") != "blackpod.governor_lineage.v1"
        or payload.get("mission_id") != request.mission_id
        or payload.get("request_id") != request.request_id
        or payload.get("run_mode") != request.run_mode.value
    ):
        raise OperatorPreconditionError("Governor lineage correlation is inconsistent")
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise OperatorPreconditionError("Governor lineage outputs are malformed")
    by_name = {
        item.get("name"): item
        for item in outputs
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    for name in (
        "governor_decision",
        "governor_decision_readiness",
        "governor_deliberation",
        "governor_rendered_decision",
    ):
        artifact = selected[name]
        entry = by_name.get(name)
        if not isinstance(entry, Mapping) or any(
            entry.get(field) != expected
            for field, expected in (
                ("path", artifact.path),
                ("producer", artifact.producer),
                ("sha256", artifact.sha256),
                ("byte_size", artifact.byte_size),
                ("mission_id", request.mission_id),
                ("request_id", request.request_id),
            )
        ):
            raise OperatorPreconditionError(
                f"Governor lineage does not validate operator input: {name}"
            )


def _validate_governor_correlation(
    mission_root: Path,
    *,
    request: MissionRequest,
    selected: Mapping[str, ArtifactReference],
) -> None:
    try:
        decision = load_strict_json_object(mission_root / selected["governor_decision"].path)
        readiness = load_strict_json_object(
            mission_root / selected["governor_decision_readiness"].path
        )
        deliberation = load_strict_json_object(
            mission_root / selected["governor_deliberation"].path
        )
        rendered = load_strict_json_object(
            mission_root / selected["governor_rendered_decision"].path
        )
    except (OSError, ContractValidationError) as exc:
        raise OperatorPreconditionError("Governor operator inputs are malformed") from exc
    checks = (
        (decision.get("decision_state"), "PROCEED"),
        (decision.get("decision_status"), "RENDERED"),
        (decision.get("allowed_next_step"), "OPERATOR_REVIEW"),
        (readiness.get("readiness_state"), "READY"),
        (decision.get("deliberation_id"), deliberation.get("deliberation_id")),
        (readiness.get("deliberation_id"), deliberation.get("deliberation_id")),
        (decision.get("readiness_id"), readiness.get("readiness_id")),
        (rendered.get("mission_id"), request.mission_id),
        (rendered.get("request_id"), request.request_id),
        (rendered.get("run_mode"), request.run_mode.value),
        (rendered.get("decision_id"), decision.get("decision_id")),
        (rendered.get("disposition"), "PROCEED"),
    )
    if any(actual != expected for actual, expected in checks):
        raise OperatorPreconditionError("Governor operator input correlation is inconsistent")


def _capture_operator_outputs(
    store: MissionStore,
    mission_id: str,
    relative_paths: tuple[str, ...],
    *,
    observed_at: str,
) -> tuple[ArtifactReference, ...]:
    seen: set[str] = set()
    artifacts: list[ArtifactReference] = []
    for relative_path in relative_paths:
        path = PurePosixPath(relative_path)
        if path.as_posix() not in OPERATOR_OUTPUT_ARTIFACTS or relative_path in seen:
            raise ContractValidationError(
                "operator reported an unsupported or duplicate artifact path"
            )
        seen.add(relative_path)
        name, schema = OPERATOR_OUTPUT_ARTIFACTS[relative_path]
        artifacts.append(
            store.reference_existing_artifact(
                mission_id,
                relative_path=relative_path,
                name=name,
                producer="operator",
                schema_version=schema,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _validate_execution_correlation(
    result: object,
    request: MissionRequest,
    *,
    action_input: OperatorActionInput,
) -> OperatorExecutionResult:
    if not isinstance(result, OperatorExecutionResult):
        raise ContractValidationError("operator adapter returned an unsupported result")
    if (
        result.mission_id != request.mission_id
        or result.request_id != request.request_id
        or result.run_mode is not request.run_mode
        or result.route is not OperatorRoute.PENDING_APPROVAL
        or result.action is not action_input.action
        or result.operator_id != action_input.operator_id
        or result.acted_at != action_input.acted_at
        or result.fixture_id != action_input.fixture_id
    ):
        raise ContractValidationError("operator result correlation does not match mission")
    if result.technical_status is OperatorActionStatus.SUCCEEDED:
        if (
            result.failure is not None
            or result.result is None
            or result.action_id is None
            or result.produced_paths != EXPECTED_OPERATOR_OUTPUT_PATHS
            or result.source_lineage != (
                *REQUIRED_OPERATOR_INPUTS_PATHS,
                *(
                    (OPERATOR_REPLAY_INPUT_PATH,)
                    if request.run_mode is RunMode.REPLAY
                    else ()
                ),
            )
        ):
            raise ContractValidationError("successful operator result is incomplete")
    elif result.technical_status is OperatorActionStatus.FAILED:
        if result.failure is None or not set(result.produced_paths).issubset(
            OPERATOR_OUTPUT_ARTIFACTS
        ):
            raise ContractValidationError("failed operator result is malformed")
    else:
        raise ContractValidationError("operator result status is unsupported")
    return result


REQUIRED_OPERATOR_INPUTS_PATHS = tuple(
    value[0] for value in REQUIRED_OPERATOR_INPUTS.values()
)


def _synthetic_failure(
    request: MissionRequest,
    action_input: OperatorActionInput,
    *,
    code: str,
    error_type: str,
    message: str,
    resumable: bool,
    produced_paths: tuple[str, ...] = (),
) -> OperatorExecutionResult:
    return OperatorExecutionResult(
        mission_id=request.mission_id or "mission-correlation-missing",
        request_id=request.request_id,
        run_mode=request.run_mode,
        technical_status=OperatorActionStatus.FAILED,
        route=OperatorRoute.PENDING_APPROVAL,
        action=action_input.action,
        result=None,
        native_status=None,
        action_id=None,
        operator_id=action_input.operator_id,
        acted_at=action_input.acted_at,
        warnings=(),
        review_packet_path=(
            OPERATOR_REVIEW_PACKET_PATH
            if OPERATOR_REVIEW_PACKET_PATH in produced_paths
            else None
        ),
        produced_paths=produced_paths,
        source_lineage=(
            *REQUIRED_OPERATOR_INPUTS_PATHS,
            *((OPERATOR_REPLAY_INPUT_PATH,) if request.run_mode is RunMode.REPLAY else ()),
        ),
        fixture_id=action_input.fixture_id,
        failure=OperatorFailure(
            code=code,
            error_type=_safe_error_type(error_type),
            message=message,
            resumable=resumable,
        ),
    )


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "OperatorWorkflowError"


def _finish_observed_at(
    run_mode: RunMode,
    *,
    action_input: OperatorActionInput,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        candidate = action_input.acted_at
    else:
        current = clock() if clock is not None else datetime.now(UTC)
        candidate = format_rfc3339(current)
    if parse_rfc3339(candidate, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        return not_before
    return candidate


def _validate_completed_invocation(
    loaded: LoadedMission,
    *,
    config: BattlestarConfig,
    action_input: OperatorActionInput,
    replay_bytes: bytes | None,
) -> None:
    operator = loaded.snapshot.operator
    expected_result = {
        OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
        OperatorAction.REJECT: OperatorResult.REJECTED,
    }[action_input.action]
    if (
        operator.action is not action_input.action
        or operator.result is not expected_result
        or operator.operator_id != action_input.operator_id
        or (
            loaded.request.run_mode is RunMode.REPLAY
            and operator.acted_at != action_input.acted_at
        )
        or operator.action_id is None
    ):
        raise OperatorStateConflictError(
            "completed operator action conflicts with this invocation"
        )
    artifacts = {item.name: item for item in loaded.snapshot.artifacts}
    for path, (name, schema) in OPERATOR_OUTPUT_ARTIFACTS.items():
        artifact = artifacts.get(name)
        target = loaded.paths.mission_root / path
        if (
            artifact is None
            or artifact.path != path
            or artifact.producer != "operator"
            or artifact.schema_version != schema
            or artifact.byte_size is None
            or target.is_symlink()
            or not target.is_file()
            or sha256_file(target) != artifact.sha256
            or target.stat().st_size != artifact.byte_size
        ):
            raise OperatorStateConflictError(
                "completed operator action lacks canonical immutable artifacts"
            )
    if replay_bytes is not None:
        fixture = artifacts.get("operator_replay_action")
        fixture_path = loaded.paths.mission_root / OPERATOR_REPLAY_INPUT_PATH
        if (
            fixture is None
            or fixture.path != OPERATOR_REPLAY_INPUT_PATH
            or fixture.producer != "harbormaster"
            or fixture.schema_version != OPERATOR_REPLAY_ACTION_SCHEMA_VERSION
            or fixture.byte_size != len(replay_bytes)
            or fixture.sha256 != sha256_bytes(replay_bytes)
            or fixture_path.is_symlink()
            or not fixture_path.is_file()
            or fixture_path.read_bytes() != replay_bytes
        ):
            raise OperatorStateConflictError(
                "completed operator replay fixture conflicts with this invocation"
            )
    try:
        packet = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_REVIEW_PACKET_PATH
        )
        action = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_ACTION_PATH
        )
        receipt = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_RECEIPT_PATH
        )
        ledger = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_LEDGER_ENTRY_PATH
        )
        provenance = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_PROVENANCE_PATH
        )
        lineage = load_strict_json_object(
            loaded.paths.mission_root / OPERATOR_LINEAGE_PATH
        )
    except (OSError, ContractValidationError) as exc:
        raise OperatorStateConflictError(
            "completed operator artifact bundle is malformed"
        ) from exc
    recorded_acted_at = operator.acted_at
    if recorded_acted_at is None:
        raise OperatorStateConflictError("completed operator action lacks acted_at")
    packet_fields = frozenset(packet)
    if packet_fields not in {
        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS
        | NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    } or (
        "unresolved_questions" in packet and not packet["unresolved_questions"]
    ):
        raise OperatorStateConflictError(
            "completed operator packet does not preserve the native contract"
        )
    packet_sha256 = sha256_file(
        loaded.paths.mission_root / OPERATOR_REVIEW_PACKET_PATH
    )
    if (
        frozenset(action) != NATIVE_OPERATOR_ACTION_FIELDS
        or action.get("action_id") != operator.action_id
        or action.get("action") != action_input.action.value
        or action.get("resulting_status") != expected_result.value
        or action.get("operator_id") != action_input.operator_id
        or action.get("created_at") != recorded_acted_at
        or action.get("reason") != action_input.reason
        or action.get("packet_path") != OPERATOR_REVIEW_PACKET_PATH
        or action.get("packet_sha256") != packet_sha256
        or action.get("packet_id") != packet.get("packet_id")
        or action.get("decision_input_hash") != packet.get("decision_input_hash")
        or action.get("source_run_id") != loaded.snapshot.mission_id
    ):
        raise OperatorStateConflictError(
            "completed operator action artifact conflicts with this invocation"
        )
    expected_expiry = _expiry_from_minutes(
        recorded_acted_at, action_input.expires_in_minutes
    )
    if action.get("expires_at") not in (None, expected_expiry) or (
        action_input.action is OperatorAction.APPROVE_HANDOFF
        and action.get("expires_at") != expected_expiry
    ):
        raise OperatorStateConflictError(
            "completed operator action expiry conflicts with this invocation"
        )
    decision_id = provenance.get("decision_id")
    audit_expected = (
        ("event_timestamp", recorded_acted_at),
        ("run_id", loaded.snapshot.mission_id),
        ("decision_input_hash", packet.get("decision_input_hash")),
        ("operator_route", OperatorRoute.PENDING_APPROVAL.value),
        ("packet_path", OPERATOR_REVIEW_PACKET_PATH),
        ("result_status", "CONSUMED"),
    )
    for label, document in (("receipt", receipt), ("ledger", ledger)):
        expected_fields = (
            NATIVE_OPERATOR_RECEIPT_FIELDS
            if label == "receipt"
            else NATIVE_OPERATOR_LEDGER_FIELDS
        )
        if frozenset(document) != expected_fields or any(
            document.get(field) != value for field, value in audit_expected
        ):
            raise OperatorStateConflictError(
                f"completed operator {label} correlation is inconsistent"
            )
    if any(
        provenance.get(field) != value
        for field, value in (
            ("mission_id", loaded.snapshot.mission_id),
            ("request_id", loaded.snapshot.request_id),
            ("run_mode", loaded.snapshot.run_mode.value),
            ("observed_at", recorded_acted_at),
            ("decision_id", decision_id),
            ("action_id", operator.action_id),
            ("action", action_input.action.value),
            ("result", expected_result.value),
            ("operator_id", action_input.operator_id),
            ("battlestar_git_revision", config.git_revision),
            ("battlestar_git_branch", config.git_branch),
            ("battlestar_dirty_worktree", config.dirty_worktree),
        )
    ):
        raise OperatorStateConflictError(
            "completed operator provenance conflicts with this invocation"
        )
    if any(
        lineage.get(field) != value
        for field, value in (
            ("mission_id", loaded.snapshot.mission_id),
            ("request_id", loaded.snapshot.request_id),
            ("run_mode", loaded.snapshot.run_mode.value),
            ("observed_at", recorded_acted_at),
            ("decision_id", decision_id),
            ("action_id", operator.action_id),
        )
    ):
        raise OperatorStateConflictError(
            "completed operator lineage correlation is inconsistent"
        )


def _expiry_from_minutes(acted_at: str, minutes: int | None) -> str | None:
    if minutes is None:
        return None
    from datetime import timedelta

    return format_rfc3339(
        parse_rfc3339(acted_at, "operator acted_at") + timedelta(minutes=minutes)
    )
