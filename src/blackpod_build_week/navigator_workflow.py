"""Harbormaster orchestration for one immutable Navigator SHADOW attempt."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import (
    NAVIGATOR_HANDOFF_ENTRY_POINT,
    NAVIGATOR_INTAKE_ENTRY_POINT,
    NAVIGATOR_SHADOW_PLAN_ENTRY_POINT,
    BattlestarConfig,
    load_navigator_battlestar_config,
)
from .contracts import (
    ArtifactReference,
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    NavigatorState,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    RunMode,
    StageError,
    StageStatus,
)
from .contracts.mission_request import (
    format_rfc3339,
    load_strict_json_object,
    parse_rfc3339,
)
from .hashing import canonical_json_bytes, sha256_bytes, sha256_file
from .identifiers import IdentifierError, validate_mission_id
from .mission_store import LoadedMission, MissionPaths, MissionStore
from .mission_transitions import begin_navigator, complete_navigator, fail_navigator
from .navigator_adapter import (
    ALLOWED_OPERATIONS,
    NAVIGATOR_REPLAY_SCHEMA_VERSION,
    NATIVE_HANDOFF_SCHEMA_VERSION,
    NATIVE_INTAKE_RECEIPT_SCHEMA_VERSION,
    NATIVE_SHADOW_PLAN_SCHEMA_VERSION,
    NATIVE_STAGING_RECEIPT_SCHEMA_VERSION,
    PROHIBITED_OPERATIONS,
    NavigatorAdapter,
    NavigatorExecutionControl,
    NavigatorExecutionResult,
    NavigatorFailure,
    NavigatorMissionContext,
    NavigatorReplayFixture,
    _validate_output_correlations,
)
from .operator_adapter import (
    NATIVE_OPERATOR_ACTION_FIELDS,
    NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
    OPERATOR_ACTION_PATH,
    OPERATOR_ACTION_SCHEMA_VERSION,
    OPERATOR_LINEAGE_PATH,
    OPERATOR_LINEAGE_SCHEMA_VERSION,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_PROVENANCE_SCHEMA_VERSION,
    OPERATOR_REVIEW_PACKET_PATH,
    OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
)


NAVIGATOR_INPUT_DIRECTORY = "navigator/inputs"
NAVIGATOR_REPLAY_INPUT_PATH = f"{NAVIGATOR_INPUT_DIRECTORY}/navigator_replay.json"
NAVIGATOR_ATTEMPT_DIRECTORY = "navigator/attempt-0001"
NAVIGATOR_PROVENANCE_PATH = f"{NAVIGATOR_ATTEMPT_DIRECTORY}/navigator_provenance.json"
NAVIGATOR_LINEAGE_PATH = f"{NAVIGATOR_ATTEMPT_DIRECTORY}/lineage_manifest.json"
NAVIGATOR_PROVENANCE_SCHEMA_VERSION = "blackpod.navigator_provenance.v1"
NAVIGATOR_LINEAGE_SCHEMA_VERSION = "blackpod.navigator_lineage.v1"

REQUIRED_NAVIGATOR_INPUT_NAMES = (
    "operator_review_packet",
    "operator_action",
    "operator_provenance",
    "operator_lineage_manifest",
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)


class NavigatorWorkflowError(RuntimeError):
    """Base class for Phase 5 Navigator orchestration failures."""


class NavigatorInvocationError(NavigatorWorkflowError):
    """Raised when invocation transport conflicts with the mission."""


class NavigatorPreconditionError(NavigatorWorkflowError):
    """Raised when recorded mission evidence is not eligible."""


class NavigatorStateConflictError(NavigatorWorkflowError):
    """Raised when the immutable one-attempt policy prevents execution."""


class NavigatorAction(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class NavigatorRunSettings:
    mission_id: str
    artifacts_root: Path
    replay_fixture: Path | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class NavigatorWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: NavigatorAction
    navigator_artifact_directory: Path
    handoff_status: NavigatorHandoffStatus | None
    intake_status: NavigatorIntakeStatus | None
    plan_status: NavigatorPlanStatus | None
    mode: NavigatorMode


class NavigatorExecutor(Protocol):
    def execute(
        self,
        request: MissionRequest,
        context: NavigatorMissionContext,
        *,
        control: NavigatorExecutionControl,
    ) -> NavigatorExecutionResult: ...


ConfigLoader = Callable[..., BattlestarConfig]
Clock = Callable[[], datetime]


def run_navigator(
    settings: NavigatorRunSettings,
    *,
    environ: Mapping[str, str] | None = None,
    adapter: NavigatorExecutor | None = None,
    config_loader: ConfigLoader = load_navigator_battlestar_config,
    clock: Clock | None = None,
) -> NavigatorWorkflowResult:
    """Stage, intake, and plan one approved SHADOW handoff."""

    _validate_settings(settings)
    config = config_loader(
        artifacts_root=settings.artifacts_root,
        environ=environ,
        strict_clean=settings.strict_battlestar_clean,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    control, replay_fixture, replay_bytes = _resolve_control(
        loaded.request,
        replay_fixture=settings.replay_fixture,
        clock=clock,
        not_before=loaded.snapshot.observed_at,
    )

    navigator_status = loaded.snapshot.stages["navigator"].status
    if navigator_status is StageStatus.SUCCEEDED:
        _validate_completed_invocation(
            loaded,
            config=config,
            control=control,
            replay_sha256=(sha256_bytes(replay_bytes) if replay_bytes is not None else None),
        )
        state = loaded.snapshot.navigator
        return NavigatorWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            action=NavigatorAction.NO_OP_ALREADY_SUCCEEDED,
            navigator_artifact_directory=(
                loaded.paths.mission_root / NAVIGATOR_ATTEMPT_DIRECTORY
            ),
            handoff_status=state.handoff_status,
            intake_status=state.intake_status,
            plan_status=state.plan_status,
            mode=NavigatorMode.SHADOW,
        )
    if navigator_status is StageStatus.RUNNING:
        raise NavigatorStateConflictError(
            "Navigator is already RUNNING; Phase 5 does not overwrite or resume the attempt"
        )
    if navigator_status is StageStatus.FAILED:
        raise NavigatorStateConflictError(
            "Navigator previously FAILED; Phase 5 has no force or retry option"
        )
    if navigator_status is not StageStatus.NOT_STARTED:
        raise NavigatorStateConflictError(
            f"Navigator cannot run from status {navigator_status.value}"
        )

    inputs, decision_id, action_id = _validate_navigator_preconditions(
        loaded, control=control
    )
    if (loaded.paths.mission_root / NAVIGATOR_ATTEMPT_DIRECTORY).exists():
        raise NavigatorStateConflictError(
            "Navigator immutable attempt directory already exists"
        )
    try:
        executor: NavigatorExecutor = adapter or NavigatorAdapter(
            config.root, deadline_seconds=float(settings.deadline_seconds)
        )
    except Exception as exc:
        raise NavigatorWorkflowError("Navigator adapter could not be prepared") from exc

    replay_artifact: ArtifactReference | None = None
    if replay_bytes is not None:
        replay_artifact = store.write_immutable_artifact(
            settings.mission_id,
            relative_path=NAVIGATOR_REPLAY_INPUT_PATH,
            payload=replay_bytes,
            name="navigator_replay_input",
            producer="harbormaster",
            schema_version=NAVIGATOR_REPLAY_SCHEMA_VERSION,
            observed_at=control.observed_at,
        )
    running = begin_navigator(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=control.observed_at,
        existing_input_names=REQUIRED_NAVIGATOR_INPUT_NAMES,
        input_artifacts=(() if replay_artifact is None else (replay_artifact,)),
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    unvalidated_result: object | None = None
    try:
        store.reserve_directory(settings.mission_id, NAVIGATOR_ATTEMPT_DIRECTORY)
        context = NavigatorMissionContext(
            mission_id=settings.mission_id,
            mission_root=loaded.paths.mission_root,
            decision_id=decision_id,
            action_id=action_id,
            review_packet_path=inputs["operator_review_packet"].path,
            operator_action_path=inputs["operator_action"].path,
            operator_provenance_path=inputs["operator_provenance"].path,
            operator_lineage_path=inputs["operator_lineage_manifest"].path,
            output_dir=NAVIGATOR_ATTEMPT_DIRECTORY,
        )
        unvalidated_result = executor.execute(
            loaded.request, context, control=control
        )
        execution_result = _validate_execution_correlation(
            unvalidated_result,
            loaded.request,
            control=control,
            decision_id=decision_id,
            action_id=action_id,
            review_path=inputs["operator_review_packet"].path,
            action_path=inputs["operator_action"].path,
            provenance_path=inputs["operator_provenance"].path,
            lineage_path=inputs["operator_lineage_manifest"].path,
        )
    except Exception as exc:
        produced_paths = (
            unvalidated_result.produced_paths
            if isinstance(unvalidated_result, NavigatorExecutionResult)
            else ()
        )
        execution_result = _synthetic_failure(
            loaded.request,
            decision_id=decision_id,
            action_id=action_id,
            review_path=inputs["operator_review_packet"].path,
            action_path=inputs["operator_action"].path,
            provenance_path=inputs["operator_provenance"].path,
            lineage_path=inputs["operator_lineage_manifest"].path,
            code="NAVIGATOR_ADAPTER_FAILURE",
            error_type=type(exc).__name__,
            message="Navigator adapter or output reservation failed",
            resumable=False,
            produced_paths=produced_paths,
        )

    finish_observed_at = _finish_observed_at(
        loaded.request.run_mode,
        control=control,
        clock=clock,
        not_before=running.observed_at,
    )
    try:
        native_outputs = _capture_native_outputs(
            store,
            settings.mission_id,
            execution_result.produced_paths,
            handoff_id=execution_result.handoff_id,
            observed_at=finish_observed_at,
        )
        provenance_artifact = _write_provenance_artifact(
            store,
            loaded.request,
            config=config,
            control=control,
            replay_sha256=(sha256_bytes(replay_bytes) if replay_bytes is not None else None),
            decision_id=decision_id,
            action_id=action_id,
            observed_at=finish_observed_at,
        )
        lineage_artifact = _write_lineage_artifact(
            store,
            loaded.request,
            inputs=inputs,
            replay_artifact=replay_artifact,
            native_outputs=native_outputs,
            provenance_artifact=provenance_artifact,
            config=config,
            result=execution_result,
            observed_at=finish_observed_at,
        )
        output_artifacts = (*native_outputs, provenance_artifact, lineage_artifact)
    except Exception as exc:
        output_artifacts = ()
        execution_result = _synthetic_failure(
            loaded.request,
            decision_id=decision_id,
            action_id=action_id,
            review_path=inputs["operator_review_packet"].path,
            action_path=inputs["operator_action"].path,
            provenance_path=inputs["operator_provenance"].path,
            lineage_path=inputs["operator_lineage_manifest"].path,
            code="NAVIGATOR_ARTIFACT_CAPTURE_FAILED",
            error_type=type(exc).__name__,
            message="Navigator artifacts failed containment or integrity validation",
            resumable=False,
        )

    navigator_state = _navigator_state(execution_result)
    if execution_result.status is StageStatus.SUCCEEDED:
        final_snapshot = complete_navigator(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            navigator_state=navigator_state,
            output_artifacts=output_artifacts,
        )
    else:
        failure = execution_result.failure or NavigatorFailure(
            code="NAVIGATOR_MALFORMED_RESULT",
            error_type="ContractValidationError",
            message="Navigator failed without structured failure data",
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
        final_snapshot = fail_navigator(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_state,
            error=stage_error,
            navigator_state=navigator_state,
            output_artifacts=output_artifacts,
        )
    store.commit_snapshot(loaded.paths, final_snapshot)
    return NavigatorWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        action=NavigatorAction.EXECUTED,
        navigator_artifact_directory=(
            loaded.paths.mission_root / NAVIGATOR_ATTEMPT_DIRECTORY
        ),
        handoff_status=execution_result.handoff_status,
        intake_status=execution_result.intake_status,
        plan_status=execution_result.plan_status,
        mode=NavigatorMode.SHADOW,
    )


def _validate_settings(settings: NavigatorRunSettings) -> None:
    try:
        validate_mission_id(settings.mission_id)
    except IdentifierError as exc:
        raise NavigatorInvocationError(str(exc)) from exc
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise NavigatorInvocationError("deadline_seconds must be finite and positive")


def _resolve_control(
    request: MissionRequest,
    *,
    replay_fixture: Path | None,
    clock: Clock | None,
    not_before: str,
) -> tuple[NavigatorExecutionControl, NavigatorReplayFixture | None, bytes | None]:
    if request.run_mode is RunMode.REPLAY:
        if replay_fixture is None:
            raise NavigatorInvocationError(
                "REPLAY Navigator requires --replay-fixture and never falls back to LIVE"
            )
        try:
            payload = Path(replay_fixture).read_bytes()
            fixture = NavigatorReplayFixture.from_bytes(payload)
        except (OSError, ContractValidationError) as exc:
            raise NavigatorInvocationError("Navigator replay fixture is invalid") from exc
        if (
            fixture.mission_id != request.mission_id
            or fixture.request_id != request.request_id
        ):
            raise NavigatorInvocationError(
                "Navigator replay fixture correlation does not match mission"
            )
        if parse_rfc3339(fixture.observed_at, "observed_at") < parse_rfc3339(
            not_before, "previous observed_at"
        ):
            raise NavigatorInvocationError(
                "Navigator replay observed_at precedes current mission state"
            )
        return NavigatorExecutionControl.from_replay_fixture(fixture), fixture, payload
    if replay_fixture is not None:
        raise NavigatorInvocationError(
            "LIVE Navigator cannot consume a replay fixture or fall back to REPLAY"
        )
    current = clock() if clock is not None else datetime.now(UTC)
    observed = format_rfc3339(current)
    if parse_rfc3339(observed, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        observed = not_before
    return (
        NavigatorExecutionControl(run_mode=RunMode.LIVE, observed_at=observed),
        None,
        None,
    )


def _validate_navigator_preconditions(
    loaded: LoadedMission, *, control: NavigatorExecutionControl
) -> tuple[dict[str, ArtifactReference], str, str]:
    request = loaded.request
    snapshot = loaded.snapshot
    if request.run_mode is not control.run_mode:
        raise NavigatorPreconditionError("Navigator transport conflicts with run mode")
    if snapshot.terminal:
        raise NavigatorPreconditionError("terminal mission cannot run Navigator")
    if snapshot.current_phase is not CurrentPhase.NAVIGATOR:
        raise NavigatorPreconditionError("mission is not in the NAVIGATOR phase")
    if snapshot.mission_outcome is not MissionOutcome.HELD:
        raise NavigatorPreconditionError("Navigator requires a HELD mission")
    for stage_name in ("harbormaster", "oracle", "council", "governor"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise NavigatorPreconditionError(
                f"{stage_name} must have succeeded before Navigator"
            )
    if snapshot.stages["governor"].native_state != "PROCEED":
        raise NavigatorPreconditionError("Navigator requires Governor PROCEED")
    operator = snapshot.operator
    if (
        operator.route is not OperatorRoute.PENDING_APPROVAL
        or operator.action_status is not OperatorActionStatus.SUCCEEDED
        or operator.action is not OperatorAction.APPROVE_HANDOFF
        or operator.result is not OperatorResult.APPROVED_FOR_HANDOFF
        or not operator.action_id
        or not operator.operator_id
        or not operator.acted_at
    ):
        raise NavigatorPreconditionError(
            "Navigator requires explicit APPROVED_FOR_HANDOFF operator state"
        )
    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    selected: dict[str, ArtifactReference] = {}
    expected = {
        "operator_review_packet": (
            OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
            OPERATOR_REVIEW_PACKET_PATH,
        ),
        "operator_action": (OPERATOR_ACTION_SCHEMA_VERSION, OPERATOR_ACTION_PATH),
        "operator_provenance": (
            OPERATOR_PROVENANCE_SCHEMA_VERSION,
            OPERATOR_PROVENANCE_PATH,
        ),
        "operator_lineage_manifest": (
            OPERATOR_LINEAGE_SCHEMA_VERSION,
            OPERATOR_LINEAGE_PATH,
        ),
    }
    for name, (schema, canonical_path) in expected.items():
        artifact = artifacts.get(name)
        if (
            artifact is None
            or artifact.producer != "operator"
            or artifact.schema_version != schema
            or artifact.path != canonical_path
        ):
            raise NavigatorPreconditionError(
                f"required Navigator input is missing or noncanonical: {name}"
            )
        target = loaded.paths.mission_root / artifact.path
        try:
            resolved = target.resolve(strict=True)
            contained = resolved.is_relative_to(loaded.paths.mission_root.resolve(strict=True))
            actual_sha256 = sha256_file(target)
            actual_size = target.stat().st_size
        except OSError as exc:
            raise NavigatorPreconditionError(
                f"required Navigator input cannot be read safely: {name}"
            ) from exc
        if (
            target.is_symlink()
            or not target.is_file()
            or not contained
            or actual_sha256 != artifact.sha256
            or artifact.byte_size is None
            or actual_size != artifact.byte_size
        ):
            raise NavigatorPreconditionError(
                f"required Navigator input failed integrity validation: {name}"
            )
        selected[name] = artifact
    packet_path = loaded.paths.mission_root / selected["operator_review_packet"].path
    action_path = loaded.paths.mission_root / selected["operator_action"].path
    try:
        packet = load_strict_json_object(packet_path)
        action = load_strict_json_object(action_path)
        operator_provenance = load_strict_json_object(
            loaded.paths.mission_root / selected["operator_provenance"].path
        )
        operator_lineage = load_strict_json_object(
            loaded.paths.mission_root / selected["operator_lineage_manifest"].path
        )
    except (OSError, ContractValidationError) as exc:
        raise NavigatorPreconditionError("operator Navigator inputs are malformed") from exc
    decision_id = operator_provenance.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise NavigatorPreconditionError("operator provenance decision_id is missing")
    expected_values = (
        (packet.get("run_id"), request.mission_id),
        (packet.get("operator_route"), "PENDING_APPROVAL"),
        (action.get("source_run_id"), request.mission_id),
        (action.get("action_id"), operator.action_id),
        (action.get("action"), "APPROVE_HANDOFF"),
        (action.get("resulting_status"), "APPROVED_FOR_HANDOFF"),
        (action.get("operator_id"), operator.operator_id),
        (action.get("created_at"), operator.acted_at),
        (action.get("packet_path"), selected["operator_review_packet"].path),
        (action.get("packet_sha256"), selected["operator_review_packet"].sha256),
    )
    if any(actual != expected_value for actual, expected_value in expected_values):
        raise NavigatorPreconditionError(
            "operator artifact correlation conflicts with mission state"
        )
    packet_fields = frozenset(packet)
    if packet_fields not in {
        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS
        | NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    } or frozenset(action) != NATIVE_OPERATOR_ACTION_FIELDS:
        raise NavigatorPreconditionError(
            "operator packet or action does not preserve the native contract shape"
        )
    if "unresolved_questions" in packet and not packet["unresolved_questions"]:
        raise NavigatorPreconditionError(
            "native operator packet may not include empty unresolved_questions"
        )
    if (
        operator_provenance.get("mission_id") != request.mission_id
        or operator_provenance.get("request_id") != request.request_id
        or operator_provenance.get("run_mode") != request.run_mode.value
        or operator_provenance.get("decision_id") != decision_id
        or operator_provenance.get("action_id") != operator.action_id
        or operator_provenance.get("action") != OperatorAction.APPROVE_HANDOFF.value
        or operator_provenance.get("result")
        != OperatorResult.APPROVED_FOR_HANDOFF.value
        or operator_provenance.get("operator_id") != operator.operator_id
        or operator_provenance.get("observed_at") != operator.acted_at
        or operator_lineage.get("mission_id") != request.mission_id
        or operator_lineage.get("request_id") != request.request_id
        or operator_lineage.get("run_mode") != request.run_mode.value
        or operator_lineage.get("decision_id") != decision_id
        or operator_lineage.get("action_id") != operator.action_id
        or operator_lineage.get("observed_at") != operator.acted_at
    ):
        raise NavigatorPreconditionError(
            "operator provenance or lineage correlation conflicts with mission"
        )
    outputs = operator_lineage.get("outputs")
    if not isinstance(outputs, list):
        raise NavigatorPreconditionError("operator lineage outputs are malformed")
    by_name = {
        item.get("name"): item
        for item in outputs
        if isinstance(item, Mapping)
    }
    for name in ("operator_review_packet", "operator_action"):
        artifact = selected[name]
        entry = by_name.get(name)
        if not isinstance(entry, Mapping) or any(
            entry.get(field) != expected_value
            for field, expected_value in (
                ("path", artifact.path),
                ("sha256", artifact.sha256),
                ("byte_size", artifact.byte_size),
                ("producer", artifact.producer),
                ("mission_id", request.mission_id),
                ("request_id", request.request_id),
                ("observed_at", operator.acted_at),
            )
        ):
            raise NavigatorPreconditionError(
                f"operator lineage does not validate Navigator input: {name}"
            )
    expires_at = action.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at.strip():
        raise NavigatorPreconditionError("operator approval requires an expiry")
    try:
        # Battlestar's current handoff/intake contracts expire only once now is
        # strictly later than expires_at; equality remains valid.
        expired = parse_rfc3339(control.observed_at, "observed_at") > parse_rfc3339(
            expires_at, "expires_at"
        )
    except ContractValidationError as exc:
        raise NavigatorPreconditionError("operator expiry is malformed") from exc
    if expired:
        raise NavigatorPreconditionError("operator approval has expired")
    for payload, name in (
        (packet_path.read_bytes(), "operator packet"),
        (action_path.read_bytes(), "operator action"),
        (
            (loaded.paths.mission_root / selected["operator_provenance"].path).read_bytes(),
            "operator provenance",
        ),
        (
            (loaded.paths.mission_root / selected["operator_lineage_manifest"].path).read_bytes(),
            "operator lineage",
        ),
    ):
        _reject_absolute_payload(payload, name)
    return selected, decision_id, operator.action_id


def _validate_execution_correlation(
    result: object,
    request: MissionRequest,
    *,
    control: NavigatorExecutionControl,
    decision_id: str,
    action_id: str,
    review_path: str,
    action_path: str,
    provenance_path: str,
    lineage_path: str,
) -> NavigatorExecutionResult:
    if not isinstance(result, NavigatorExecutionResult):
        raise ContractValidationError("Navigator adapter returned unsupported result")
    if (
        result.mission_id != request.mission_id
        or result.request_id != request.request_id
        or result.run_mode is not request.run_mode
        or result.mode is not NavigatorMode.SHADOW
        or result.decision_id != decision_id
        or result.action_id != action_id
        or result.source_lineage
        != (review_path, action_path, provenance_path, lineage_path)
        or result.allowed_operations != ALLOWED_OPERATIONS
        or result.prohibited_operations != PROHIBITED_OPERATIONS
    ):
        raise ContractValidationError("Navigator result correlation does not match mission")
    if result.status is StageStatus.SUCCEEDED:
        if result.failure is not None or not result.produced_paths:
            raise ContractValidationError("successful Navigator result is incomplete")
    elif result.status is StageStatus.FAILED:
        if result.failure is None:
            raise ContractValidationError("failed Navigator lacks structured error")
    else:
        raise ContractValidationError("Navigator technical status is unsupported")
    return result


def _capture_native_outputs(
    store: MissionStore,
    mission_id: str,
    relative_paths: tuple[str, ...],
    *,
    handoff_id: str | None,
    observed_at: str,
) -> tuple[ArtifactReference, ...]:
    if relative_paths and handoff_id is None:
        raise ContractValidationError("Navigator paths require handoff correlation")
    artifacts: list[ArtifactReference] = []
    names_seen: set[str] = set()
    for relative_path in relative_paths:
        path = PurePosixPath(relative_path)
        if not path.as_posix().startswith(f"{NAVIGATOR_ATTEMPT_DIRECTORY}/"):
            raise ContractValidationError("Navigator artifact escaped attempt directory")
        filename = path.name
        parent = path.parent.name
        if parent == "pending" and filename == f"{handoff_id}.json":
            name = "navigator_handoff_envelope"
            try:
                native_schema = load_strict_json_object(
                    store.paths_for(mission_id).mission_root / relative_path
                ).get("schema_version")
            except (OSError, ContractValidationError) as exc:
                raise ContractValidationError(
                    "Navigator handoff envelope is malformed"
                ) from exc
            schema = native_schema if isinstance(native_schema, str) else None
        elif parent == "staging_receipts" and filename == f"{handoff_id}.json":
            name, schema = "navigator_staging_receipt", NATIVE_STAGING_RECEIPT_SCHEMA_VERSION
        elif filename == "handoff_ledger.jsonl":
            name, schema = "navigator_handoff_ledger", None
        elif parent == "intake_receipts" and filename == f"{handoff_id}.json":
            name, schema = "navigator_intake_receipt", NATIVE_INTAKE_RECEIPT_SCHEMA_VERSION
        elif parent == "shadow_plans" and filename == f"{handoff_id}.json":
            name, schema = "navigator_shadow_plan", NATIVE_SHADOW_PLAN_SCHEMA_VERSION
        elif filename == "navigator_ledger.jsonl":
            name, schema = "navigator_ledger_entry", None
        else:
            raise ContractValidationError("Navigator reported unsupported artifact path")
        if name in names_seen:
            raise ContractValidationError("Navigator reported duplicate artifact role")
        names_seen.add(name)
        artifacts.append(
            store.reference_existing_artifact(
                mission_id,
                relative_path=relative_path,
                name=name,
                producer="navigator",
                schema_version=schema,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _write_provenance_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    config: BattlestarConfig,
    control: NavigatorExecutionControl,
    replay_sha256: str | None,
    decision_id: str,
    action_id: str,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise NavigatorInvocationError("stored mission lacks mission_id")
    payload = canonical_json_bytes(
        {
            "schema_version": NAVIGATOR_PROVENANCE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "decision_id": decision_id,
            "action_id": action_id,
            "observed_at": observed_at,
            "component": {
                "git_revision": config.git_revision,
                "git_branch": config.git_branch,
                "dirty_worktree": config.dirty_worktree,
                "handoff_entry_point": NAVIGATOR_HANDOFF_ENTRY_POINT,
                "intake_entry_point": NAVIGATOR_INTAKE_ENTRY_POINT,
                "shadow_plan_entry_point": NAVIGATOR_SHADOW_PLAN_ENTRY_POINT,
                "mode": NavigatorMode.SHADOW.value,
                "transport": (
                    "REPLAY_FIXTURE"
                    if request.run_mode is RunMode.REPLAY
                    else "LIVE_MISSION_INPUTS"
                ),
                "replay_fixture_id": control.fixture_id,
                "replay_fixture_sha256": replay_sha256,
            },
        }
    )
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=NAVIGATOR_PROVENANCE_PATH,
        payload=payload,
        name="navigator_provenance",
        producer="navigator",
        schema_version=NAVIGATOR_PROVENANCE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _write_lineage_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    inputs: Mapping[str, ArtifactReference],
    replay_artifact: ArtifactReference | None,
    native_outputs: tuple[ArtifactReference, ...],
    provenance_artifact: ArtifactReference,
    config: BattlestarConfig,
    result: NavigatorExecutionResult,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise NavigatorInvocationError("stored mission lacks mission_id")
    try:
        operator_provenance = load_strict_json_object(
            store.paths_for(request.mission_id).mission_root
            / inputs["operator_provenance"].path
        )
        operator_revision = operator_provenance.get("battlestar_git_revision")
    except (OSError, ContractValidationError) as exc:
        raise NavigatorPreconditionError("operator provenance is malformed") from exc
    if not isinstance(operator_revision, str) or not operator_revision:
        raise NavigatorPreconditionError(
            "operator provenance component revision is missing"
        )
    input_artifacts = [*inputs.values()]
    if replay_artifact is not None:
        input_artifacts.append(replay_artifact)
    sources_by_output = {
        "navigator_handoff_envelope": ["operator_review_packet", "operator_action"],
        "navigator_staging_receipt": ["navigator_handoff_envelope"],
        "navigator_handoff_ledger": ["navigator_handoff_envelope", "operator_action"],
        "navigator_intake_receipt": [
            "navigator_handoff_envelope",
            "navigator_staging_receipt",
        ],
        "navigator_shadow_plan": [
            "navigator_handoff_envelope",
            "navigator_intake_receipt",
        ],
        "navigator_ledger_entry": [
            "navigator_handoff_envelope",
            "navigator_intake_receipt",
            "navigator_shadow_plan",
        ],
        "navigator_provenance": [artifact.name for artifact in input_artifacts],
    }
    output_artifacts = [*native_outputs, provenance_artifact]
    payload = canonical_json_bytes(
        {
            "schema_version": NAVIGATOR_LINEAGE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "decision_id": result.decision_id,
            "action_id": result.action_id,
            "handoff_id": result.handoff_id,
            "observed_at": observed_at,
            "inputs": [
                _lineage_entry(
                    artifact,
                    request=request,
                    component_revision=(
                        f"sha256:{artifact.sha256}"
                        if artifact.name == "navigator_replay_input"
                        else operator_revision
                    ),
                )
                for artifact in input_artifacts
            ],
            "outputs": [
                {
                    **_lineage_entry(
                        artifact,
                        request=request,
                        component_revision=config.git_revision,
                    ),
                    "source_input_names": sources_by_output[artifact.name],
                }
                for artifact in output_artifacts
            ],
        }
    )
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=NAVIGATOR_LINEAGE_PATH,
        payload=payload,
        name="navigator_lineage_manifest",
        producer="navigator",
        schema_version=NAVIGATOR_LINEAGE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _lineage_entry(
    artifact: ArtifactReference,
    *,
    request: MissionRequest,
    component_revision: str,
) -> dict[str, Any]:
    return {
        "name": artifact.name,
        "path": artifact.path,
        "producer": artifact.producer,
        "sha256": artifact.sha256,
        "byte_size": artifact.byte_size,
        "schema_version": artifact.schema_version,
        "observed_at": artifact.observed_at,
        "originating_component_revision": component_revision,
        "mission_id": request.mission_id,
        "request_id": request.request_id,
    }


def _navigator_state(result: NavigatorExecutionResult) -> NavigatorState:
    return NavigatorState.from_mapping(
        {
            "mode": NavigatorMode.SHADOW.value,
            "handoff_status": (
                None if result.handoff_status is None else result.handoff_status.value
            ),
            "intake_status": (
                None if result.intake_status is None else result.intake_status.value
            ),
            "plan_status": None if result.plan_status is None else result.plan_status.value,
            "handoff_id": result.handoff_id,
            "intake_receipt_id": result.intake_receipt_id,
            "plan_id": result.plan_id,
            "expires_at": result.expires_at,
            "idempotency_key": result.idempotency_key,
            "allowed_operations": list(result.allowed_operations),
            "prohibited_operations": list(result.prohibited_operations),
        }
    )


def _synthetic_failure(
    request: MissionRequest,
    *,
    decision_id: str,
    action_id: str,
    review_path: str,
    action_path: str,
    provenance_path: str,
    lineage_path: str,
    code: str,
    error_type: str,
    message: str,
    resumable: bool,
    produced_paths: tuple[str, ...] = (),
) -> NavigatorExecutionResult:
    return NavigatorExecutionResult(
        mission_id=request.mission_id or "mission-correlation-missing",
        request_id=request.request_id,
        run_mode=request.run_mode,
        status=StageStatus.FAILED,
        native_state=None,
        mode=NavigatorMode.SHADOW,
        handoff_status=None,
        intake_status=None,
        plan_status=None,
        handoff_id=None,
        intake_receipt_id=None,
        plan_id=None,
        allowed_operations=ALLOWED_OPERATIONS,
        prohibited_operations=PROHIBITED_OPERATIONS,
        expires_at=None,
        idempotency_key=None,
        decision_id=decision_id,
        action_id=action_id,
        produced_paths=produced_paths,
        source_lineage=(review_path, action_path, provenance_path, lineage_path),
        failure=NavigatorFailure(
            code=code,
            error_type=_safe_error_type(error_type),
            message=message,
            resumable=resumable,
        ),
    )


def _finish_observed_at(
    run_mode: RunMode,
    *,
    control: NavigatorExecutionControl,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        candidate = control.observed_at
    else:
        candidate = format_rfc3339(clock() if clock is not None else datetime.now(UTC))
    if parse_rfc3339(candidate, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        return not_before
    return candidate


def _validate_completed_invocation(
    loaded: LoadedMission,
    *,
    config: BattlestarConfig,
    control: NavigatorExecutionControl,
    replay_sha256: str | None,
) -> None:
    snapshot = loaded.snapshot
    state = snapshot.navigator
    if (
        snapshot.stages["navigator"].status is not StageStatus.SUCCEEDED
        or snapshot.stages["navigator"].native_state != "CREATED"
        or snapshot.current_phase is not CurrentPhase.COMPLETE
        or snapshot.mission_outcome is not MissionOutcome.APPROVED
        or not snapshot.terminal
        or state.mode is not NavigatorMode.SHADOW
        or state.handoff_status is not NavigatorHandoffStatus.STAGED
        or state.intake_status is not NavigatorIntakeStatus.ACCEPTED
        or state.plan_status is not NavigatorPlanStatus.CREATED
        or state.allowed_operations != ALLOWED_OPERATIONS
        or state.prohibited_operations != PROHIBITED_OPERATIONS
    ):
        raise NavigatorStateConflictError(
            "completed Navigator state is not the canonical SHADOW result"
        )
    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    provenance = artifacts.get("navigator_provenance")
    lineage = artifacts.get("navigator_lineage_manifest")
    replay = artifacts.get("navigator_replay_input")
    if provenance is None or lineage is None:
        raise NavigatorStateConflictError("completed Navigator provenance is missing")
    if not state.handoff_id:
        raise NavigatorStateConflictError("completed Navigator handoff_id is missing")
    expected_native = {
        "navigator_handoff_envelope": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/handoff/pending/{state.handoff_id}.json",
            NATIVE_HANDOFF_SCHEMA_VERSION,
        ),
        "navigator_staging_receipt": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/handoff/staging_receipts/{state.handoff_id}.json",
            NATIVE_STAGING_RECEIPT_SCHEMA_VERSION,
        ),
        "navigator_handoff_ledger": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/handoff/handoff_ledger.jsonl",
            None,
        ),
        "navigator_intake_receipt": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/intake/intake_receipts/{state.handoff_id}.json",
            NATIVE_INTAKE_RECEIPT_SCHEMA_VERSION,
        ),
        "navigator_shadow_plan": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/intake/shadow_plans/{state.handoff_id}.json",
            NATIVE_SHADOW_PLAN_SCHEMA_VERSION,
        ),
        "navigator_ledger_entry": (
            f"{NAVIGATOR_ATTEMPT_DIRECTORY}/intake/navigator_ledger.jsonl",
            None,
        ),
    }
    for name, (path, schema) in expected_native.items():
        artifact = artifacts.get(name)
        if (
            artifact is None
            or artifact.path != path
            or artifact.producer != "navigator"
            or artifact.schema_version != schema
            or artifact.byte_size is None
        ):
            raise NavigatorStateConflictError(
                f"completed Navigator artifact is missing or noncanonical: {name}"
            )
        _reject_absolute_payload(
            (loaded.paths.mission_root / artifact.path).read_bytes(), name
        )
    expected_outputs = {
        *expected_native,
        "navigator_provenance",
        "navigator_lineage_manifest",
    }
    if set(snapshot.stages["navigator"].outputs) != expected_outputs:
        raise NavigatorStateConflictError(
            "completed Navigator stage output set is noncanonical"
        )
    expected_inputs = {*REQUIRED_NAVIGATOR_INPUT_NAMES}
    if loaded.request.run_mode is RunMode.REPLAY:
        expected_inputs.add("navigator_replay_input")
    if set(snapshot.stages["navigator"].inputs) != expected_inputs:
        raise NavigatorStateConflictError(
            "completed Navigator stage input set is noncanonical"
        )
    try:
        payload = load_strict_json_object(loaded.paths.mission_root / provenance.path)
    except (OSError, ContractValidationError) as exc:
        raise NavigatorStateConflictError("Navigator provenance is malformed") from exc
    component = payload.get("component")
    if not isinstance(component, Mapping) or any(
        actual != expected
        for actual, expected in (
            (component.get("git_revision"), config.git_revision),
            (component.get("mode"), "SHADOW"),
            (component.get("replay_fixture_id"), control.fixture_id),
            (component.get("replay_fixture_sha256"), replay_sha256),
        )
    ):
        raise NavigatorStateConflictError(
            "completed Navigator invocation differs from requested invocation"
        )
    if loaded.request.run_mode is RunMode.REPLAY:
        if replay is None or replay.sha256 != replay_sha256:
            raise NavigatorStateConflictError(
                "completed Navigator replay fixture differs"
            )
    elif replay is not None:
        raise NavigatorStateConflictError("LIVE Navigator contains replay input")
    try:
        lineage_payload = load_strict_json_object(
            loaded.paths.mission_root / lineage.path
        )
        if (
            lineage.producer != "navigator"
            or lineage.schema_version != NAVIGATOR_LINEAGE_SCHEMA_VERSION
            or provenance.producer != "navigator"
            or provenance.schema_version != NAVIGATOR_PROVENANCE_SCHEMA_VERSION
            or lineage_payload.get("mission_id") != loaded.request.mission_id
            or lineage_payload.get("request_id") != loaded.request.request_id
            or lineage_payload.get("run_mode") != loaded.request.run_mode.value
            or lineage_payload.get("handoff_id") != state.handoff_id
        ):
            raise NavigatorStateConflictError(
                "completed Navigator lineage or provenance correlation is inconsistent"
            )
        output_entries = lineage_payload.get("outputs")
        if not isinstance(output_entries, list):
            raise NavigatorStateConflictError("completed Navigator lineage outputs are malformed")
        by_name = {
            item.get("name"): item
            for item in output_entries
            if isinstance(item, Mapping)
        }
        for name in {*expected_native, "navigator_provenance"}:
            artifact = artifacts[name]
            entry = by_name.get(name)
            if not isinstance(entry, Mapping) or any(
                entry.get(field) != expected
                for field, expected in (
                    ("path", artifact.path),
                    ("sha256", artifact.sha256),
                    ("byte_size", artifact.byte_size),
                    ("mission_id", loaded.request.mission_id),
                    ("request_id", loaded.request.request_id),
                )
            ):
                raise NavigatorStateConflictError(
                    f"completed Navigator lineage does not validate {name}"
                )
        ordered_paths = tuple(
            expected_native[name][0]
            for name in (
                "navigator_handoff_envelope",
                "navigator_staging_receipt",
                "navigator_handoff_ledger",
                "navigator_intake_receipt",
                "navigator_shadow_plan",
                "navigator_ledger_entry",
            )
        )
        _validate_output_correlations(
            NavigatorMissionContext(
                mission_id=loaded.request.mission_id or "",
                mission_root=loaded.paths.mission_root,
                decision_id=str(lineage_payload.get("decision_id")),
                action_id=str(lineage_payload.get("action_id")),
                review_packet_path=artifacts["operator_review_packet"].path,
                operator_action_path=artifacts["operator_action"].path,
                output_dir=NAVIGATOR_ATTEMPT_DIRECTORY,
            ),
            {
                "status": StageStatus.SUCCEEDED.value,
                "handoff_id": state.handoff_id,
                "intake_receipt_id": state.intake_receipt_id,
                "idempotency_key": state.idempotency_key,
                "expires_at": state.expires_at,
                "plan_id": state.plan_id,
            },
            ordered_paths,
        )
    except NavigatorStateConflictError:
        raise
    except Exception as exc:
        raise NavigatorStateConflictError(
            "completed Navigator native artifacts failed correlation validation"
        ) from exc


def _reject_absolute_payload(payload: bytes, name: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NavigatorPreconditionError(f"{name} is not UTF-8") from exc
    if _ABSOLUTE_POSIX_PATH.search(text) or _ABSOLUTE_WINDOWS_PATH.search(text):
        raise NavigatorPreconditionError(f"{name} contains an absolute path")


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "NavigatorWorkflowError"
