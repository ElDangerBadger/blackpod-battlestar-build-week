"""Harbormaster-owned orchestration for exactly one Phase 2 Oracle attempt."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Protocol

from .battlestar_config import (
    ORACLE_ENTRY_POINT,
    BattlestarConfig,
    load_battlestar_config,
)
from .contracts import (
    ArtifactReference,
    ComponentProvenance,
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    OracleTransportKind,
    RunMode,
    StageError,
    StageStatus,
)
from .contracts.mission_request import format_rfc3339, parse_rfc3339
from .hashing import sha256_bytes
from .mission_store import MissionPaths, MissionStore
from .mission_transitions import begin_oracle, complete_oracle, fail_oracle
from .oracle_adapter import (
    EXPECTED_ORACLE_OUTPUT_FILENAMES,
    ORACLE_REPLAY_SCHEMA_VERSION,
    OracleAdapter,
    OracleExecutionResult,
    OracleFailure,
    OracleMissionContext,
    ReplayOracleInput,
)


ORACLE_INPUT_DIRECTORY = "oracle/inputs"
ORACLE_ATTEMPT_DIRECTORY = "oracle/attempt-0001"
ORACLE_FLEET_INPUT_PATH = f"{ORACLE_INPUT_DIRECTORY}/oracles_vapors.example.yaml"
ORACLE_REPLAY_INPUT_PATH = f"{ORACLE_INPUT_DIRECTORY}/oracle_replay_input.json"

ORACLE_OUTPUT_ARTIFACT_NAMES: Mapping[str, str] = {
    "fleet-oracles-vapors-example_snapshot.json": "oracle_provider_snapshot",
    "fleet-oracles-vapors-example_provider_run_manifest.json": (
        "oracle_provider_run_manifest"
    ),
    "fleet-oracles-vapors-example_normalized.json": "oracle_normalized_snapshot",
    "fleet-oracles-vapors-example_quality.json": "oracle_quality_report",
    "fleet-oracles-vapors-example_readiness.json": "oracle_readiness_report",
    "oracle_advisor_snapshot_input.json": "oracle_advisor_snapshot_input",
    "oracle_measurements_live.json": "oracle_measurements",
    "oracle_measurement_diagnostics_live.json": "oracle_measurement_diagnostics",
    "oracle_assessment_live.json": "oracle_assessment",
    "oracle_narrative_live.json": "oracle_narrative",
    "oracle_report_live.json": "oracle_report",
    "provider_run_ledger.jsonl": "oracle_provider_run_ledger",
    "oracle_pipeline_run_manifest.json": "oracle_pipeline_run_manifest",
    "oracle_pipeline_run_ledger.jsonl": "oracle_pipeline_run_ledger",
}


class OracleWorkflowError(RuntimeError):
    """Base class for Phase 2 orchestration failures."""


class OracleInvocationError(OracleWorkflowError):
    """Raised when CLI inputs conflict with the initialized mission."""


class OracleStateConflictError(OracleWorkflowError):
    """Raised when the one-attempt Phase 2 restart policy blocks execution."""


class OracleAction(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class OracleRunSettings:
    mission_id: str
    artifacts_root: Path
    replay_fixture: Path | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class OracleWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: OracleAction
    oracle_artifact_directory: Path


class OracleExecutor(Protocol):
    def execute(
        self,
        request: MissionRequest,
        context: OracleMissionContext,
        *,
        replay_input: ReplayOracleInput | None = None,
    ) -> OracleExecutionResult: ...


ConfigLoader = Callable[..., BattlestarConfig]
Clock = Callable[[], datetime]


def run_oracle(
    settings: OracleRunSettings,
    *,
    environ: Mapping[str, str] | None = None,
    adapter: OracleExecutor | None = None,
    config_loader: ConfigLoader = load_battlestar_config,
    clock: Clock | None = None,
) -> OracleWorkflowResult:
    """Run or validate the single supported Oracle attempt for one mission."""

    _validate_settings(settings)
    config = config_loader(
        artifacts_root=settings.artifacts_root,
        environ=environ,
        strict_clean=settings.strict_battlestar_clean,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    replay_input, replay_bytes = _load_transport_input(
        loaded.request, settings.replay_fixture
    )
    try:
        fleet_bytes = config.fleet_path.read_bytes()
    except OSError as exc:
        raise OracleWorkflowError(
            "Battlestar Oracle fleet input could not be read"
        ) from exc

    provenance = _build_provenance(
        loaded.request,
        config,
        replay_input=replay_input,
        replay_bytes=replay_bytes,
    )
    oracle_status = loaded.snapshot.stages["oracle"].status
    if oracle_status is StageStatus.SUCCEEDED:
        _validate_completed_invocation(
            loaded.snapshot,
            provenance=provenance,
            fleet_sha256=sha256_bytes(fleet_bytes),
            replay_sha256=(
                None if replay_bytes is None else sha256_bytes(replay_bytes)
            ),
        )
        return OracleWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            action=OracleAction.NO_OP_ALREADY_SUCCEEDED,
            oracle_artifact_directory=(
                loaded.paths.mission_root / ORACLE_ATTEMPT_DIRECTORY
            ),
        )
    if oracle_status is StageStatus.RUNNING:
        raise OracleStateConflictError(
            "Oracle is already RUNNING; Phase 2 does not overwrite or resume the attempt"
        )
    if oracle_status is StageStatus.FAILED:
        raise OracleStateConflictError(
            "Oracle previously FAILED; Phase 2 has no force or retry option"
        )
    if oracle_status is not StageStatus.NOT_STARTED:
        raise OracleStateConflictError(
            f"Oracle cannot run from status {oracle_status.value}"
        )

    try:
        executor: OracleExecutor = adapter or OracleAdapter(
            config.root,
            deadline_seconds=float(settings.deadline_seconds),
        )
    except Exception as exc:
        raise OracleWorkflowError("Oracle adapter could not be prepared") from exc
    begin_observed_at = _observed_at(
        loaded.request.run_mode,
        replay_input=replay_input,
        clock=clock,
        not_before=loaded.snapshot.observed_at,
    )
    input_artifacts = _capture_inputs(
        store,
        loaded.request,
        fleet_bytes=fleet_bytes,
        replay_bytes=replay_bytes,
        observed_at=begin_observed_at,
    )
    running = begin_oracle(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=begin_observed_at,
        provenance=provenance,
        input_artifacts=input_artifacts,
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    execution_result: OracleExecutionResult
    try:
        store.reserve_directory(settings.mission_id, ORACLE_ATTEMPT_DIRECTORY)
        context = OracleMissionContext(
            mission_id=settings.mission_id,
            mission_root=loaded.paths.mission_root,
            fleet_path=ORACLE_FLEET_INPUT_PATH,
            output_dir=ORACLE_ATTEMPT_DIRECTORY,
        )
        execution_result = executor.execute(
            loaded.request,
            context,
            replay_input=replay_input,
        )
        execution_result = _validate_execution_correlation(
            execution_result, loaded.request, provenance
        )
    except Exception as exc:
        execution_result = _synthetic_failure(
            loaded.request,
            provenance.transport,
            code="ORACLE_ADAPTER_FAILURE",
            error_type=type(exc).__name__,
            message="Oracle adapter or output reservation failed",
            resumable=False,
        )

    finish_observed_at = _observed_at(
        loaded.request.run_mode,
        replay_input=replay_input,
        clock=clock,
        not_before=running.observed_at,
    )
    try:
        output_artifacts = _capture_outputs(
            store,
            settings.mission_id,
            execution_result.produced_paths,
            observed_at=finish_observed_at,
        )
    except Exception as exc:
        output_artifacts = ()
        execution_result = _synthetic_failure(
            loaded.request,
            provenance.transport,
            code="ORACLE_ARTIFACT_CAPTURE_FAILED",
            error_type=type(exc).__name__,
            message="Oracle artifacts failed containment or integrity validation",
            resumable=False,
        )

    if execution_result.status is StageStatus.SUCCEEDED:
        if execution_result.native_state is None:
            raise AssertionError("validated Oracle success lacks native state")
        final_snapshot = complete_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_state,
            output_artifacts=output_artifacts,
        )
    else:
        failure = execution_result.failure
        if failure is None:
            failure = OracleFailure(
                code="ORACLE_MALFORMED_RESULT",
                error_type="ContractValidationError",
                message="Oracle failed without a structured error",
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
        final_snapshot = fail_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_state,
            error=stage_error,
            output_artifacts=output_artifacts,
        )
    store.commit_snapshot(loaded.paths, final_snapshot)
    return OracleWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        action=OracleAction.EXECUTED,
        oracle_artifact_directory=(
            loaded.paths.mission_root / ORACLE_ATTEMPT_DIRECTORY
        ),
    )


def _validate_settings(settings: OracleRunSettings) -> None:
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise OracleInvocationError("deadline_seconds must be finite and positive")


def _load_transport_input(
    request: MissionRequest, fixture_path: Path | None
) -> tuple[ReplayOracleInput | None, bytes | None]:
    if request.run_mode is RunMode.LIVE:
        if fixture_path is not None:
            raise OracleInvocationError(
                "LIVE missions may not receive --replay-fixture"
            )
        return None, None
    if fixture_path is None:
        raise OracleInvocationError(
            "REPLAY missions require --replay-fixture and never fall back to LIVE"
        )
    path = Path(fixture_path)
    if path.is_symlink() or not path.is_file():
        raise OracleInvocationError("Oracle replay fixture must be a regular file")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise OracleInvocationError("Oracle replay fixture could not be read") from exc
    replay_input = ReplayOracleInput.from_bytes(payload)
    return replay_input, payload


def _build_provenance(
    request: MissionRequest,
    config: BattlestarConfig,
    *,
    replay_input: ReplayOracleInput | None,
    replay_bytes: bytes | None,
) -> ComponentProvenance:
    transport = (
        OracleTransportKind.REPLAY_FIXTURE
        if request.run_mode is RunMode.REPLAY
        else OracleTransportKind.LIVE_YFINANCE
    )
    return ComponentProvenance.from_mapping(
        {
            "git_revision": config.git_revision,
            "git_branch": config.git_branch,
            "dirty_worktree": config.dirty_worktree,
            "oracle_entry_point": ORACLE_ENTRY_POINT,
            "run_mode": request.run_mode.value,
            "transport": transport.value,
            "replay_fixture_id": (
                None if replay_input is None else replay_input.fixture_id
            ),
            "replay_fixture_sha256": (
                None if replay_bytes is None else sha256_bytes(replay_bytes)
            ),
        }
    )


def _capture_inputs(
    store: MissionStore,
    request: MissionRequest,
    *,
    fleet_bytes: bytes,
    replay_bytes: bytes | None,
    observed_at: str,
) -> tuple[ArtifactReference, ...]:
    if request.mission_id is None:
        raise OracleInvocationError("stored mission request lacks mission_id")
    artifacts = [
        store.write_immutable_artifact(
            request.mission_id,
            relative_path=ORACLE_FLEET_INPUT_PATH,
            payload=fleet_bytes,
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=observed_at,
        )
    ]
    if request.run_mode is RunMode.REPLAY:
        if replay_bytes is None:
            raise AssertionError("validated REPLAY invocation lacks fixture bytes")
        artifacts.append(
            store.write_immutable_artifact(
                request.mission_id,
                relative_path=ORACLE_REPLAY_INPUT_PATH,
                payload=replay_bytes,
                name="oracle_replay_input",
                producer="harbormaster",
                schema_version=ORACLE_REPLAY_SCHEMA_VERSION,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _capture_outputs(
    store: MissionStore,
    mission_id: str,
    relative_paths: tuple[str, ...],
    *,
    observed_at: str,
) -> tuple[ArtifactReference, ...]:
    artifacts: list[ArtifactReference] = []
    seen: set[str] = set()
    for relative_path in relative_paths:
        path = PurePosixPath(relative_path)
        filename = path.name
        expected_path = f"{ORACLE_ATTEMPT_DIRECTORY}/{filename}"
        if (
            path.as_posix() != expected_path
            or filename not in ORACLE_OUTPUT_ARTIFACT_NAMES
            or filename in seen
        ):
            raise ContractValidationError(
                "Oracle reported an unsupported or duplicate artifact path"
            )
        seen.add(filename)
        artifacts.append(
            store.reference_existing_artifact(
                mission_id,
                relative_path=expected_path,
                name=ORACLE_OUTPUT_ARTIFACT_NAMES[filename],
                producer="oracle",
                schema_version=None,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _validate_execution_correlation(
    result: OracleExecutionResult,
    request: MissionRequest,
    provenance: ComponentProvenance,
) -> OracleExecutionResult:
    if not isinstance(result, OracleExecutionResult):
        raise ContractValidationError("Oracle adapter returned an unsupported result")
    if (
        request.mission_id is None
        or result.mission_id != request.mission_id
        or result.request_id != request.request_id
        or result.symbol != request.symbol
        or result.run_mode is not request.run_mode
        or result.transport is not provenance.transport
    ):
        raise ContractValidationError("Oracle result correlation does not match the mission")
    expected_paths = {
        f"{ORACLE_ATTEMPT_DIRECTORY}/{filename}"
        for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES
    }
    produced_paths = set(result.produced_paths)
    if len(produced_paths) != len(result.produced_paths):
        raise ContractValidationError("Oracle result contains duplicate artifact paths")
    if result.status is StageStatus.SUCCEEDED and produced_paths != expected_paths:
        raise ContractValidationError(
            "technically successful Oracle result lacks the canonical artifact set"
        )
    if result.status is StageStatus.FAILED and not produced_paths.issubset(expected_paths):
        raise ContractValidationError(
            "failed Oracle result contains unsupported artifact paths"
        )
    return result


def _synthetic_failure(
    request: MissionRequest,
    transport: OracleTransportKind,
    *,
    code: str,
    error_type: str,
    message: str,
    resumable: bool,
) -> OracleExecutionResult:
    return OracleExecutionResult(
        mission_id=request.mission_id or "mission-correlation-missing",
        request_id=request.request_id,
        symbol=request.symbol,
        run_mode=request.run_mode,
        transport=transport,
        status=StageStatus.FAILED,
        native_state=None,
        produced_paths=(),
        failure=OracleFailure(
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
    return filtered if filtered and filtered[0].isalnum() else "OracleWorkflowError"


def _observed_at(
    run_mode: RunMode,
    *,
    replay_input: ReplayOracleInput | None,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        if replay_input is None:
            raise AssertionError("REPLAY timestamp requires replay input")
        candidate = replay_input.generated_at
    else:
        current = clock() if clock is not None else datetime.now(UTC)
        candidate = format_rfc3339(current)
    if parse_rfc3339(candidate, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        return not_before
    return candidate


def _validate_completed_invocation(
    snapshot: MissionSnapshot,
    *,
    provenance: ComponentProvenance,
    fleet_sha256: str,
    replay_sha256: str | None,
) -> None:
    oracle = snapshot.stages["oracle"]
    if (
        snapshot.current_phase is not CurrentPhase.COUNCIL
        or snapshot.mission_outcome is not MissionOutcome.INCOMPLETE
        or snapshot.terminal
        or oracle.status is not StageStatus.SUCCEEDED
        or snapshot.components.get("battlestar") != provenance
    ):
        raise OracleStateConflictError(
            "completed Oracle state does not match this invocation"
        )
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise OracleStateConflictError(
                "a later stage has started; Phase 2 cannot claim an Oracle no-op"
            )
    artifacts = {item.name: item for item in snapshot.artifacts}
    fleet = artifacts.get("oracle_fleet_input")
    if fleet is None or fleet.sha256 != fleet_sha256:
        raise OracleStateConflictError(
            "Battlestar fleet input differs from the completed invocation"
        )
    expected_inputs = {"oracle_fleet_input"}
    if provenance.run_mode is RunMode.REPLAY:
        fixture = artifacts.get("oracle_replay_input")
        if fixture is None or fixture.sha256 != replay_sha256:
            raise OracleStateConflictError(
                "replay fixture differs from the completed invocation"
            )
        expected_inputs.add("oracle_replay_input")
    if set(oracle.inputs) != expected_inputs:
        raise OracleStateConflictError("completed Oracle inputs are not canonical")
    expected_outputs = set(ORACLE_OUTPUT_ARTIFACT_NAMES.values())
    if set(oracle.outputs) != expected_outputs:
        raise OracleStateConflictError("completed Oracle output set is not canonical")
    for filename, artifact_name in ORACLE_OUTPUT_ARTIFACT_NAMES.items():
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact.path != f"{ORACLE_ATTEMPT_DIRECTORY}/{filename}"
            or artifact.producer != "oracle"
        ):
            raise OracleStateConflictError(
                "completed Oracle artifact provenance is not canonical"
            )


if set(ORACLE_OUTPUT_ARTIFACT_NAMES) != set(EXPECTED_ORACLE_OUTPUT_FILENAMES):
    raise RuntimeError("Oracle artifact mapping does not match the adapter contract")
