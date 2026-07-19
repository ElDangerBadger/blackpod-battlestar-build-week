"""Harbormaster-owned orchestration for exactly one Phase 3 Council attempt."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import (
    ADVISOR_HEALTH_ENTRY_POINT,
    CANDIDATE_ENTRY_POINT,
    COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT,
    COUNCIL_SYNTHESIS_ENTRY_POINT,
    MANDATE_ENTRY_POINT,
    RUNTIME_VALIDATION_ENTRY_POINT,
    SENATE_DELIBERATION_ENTRY_POINT,
    SENATE_REVIEW_ENTRY_POINT,
    BattlestarConfig,
    load_council_battlestar_config,
)
from .contracts import (
    ArtifactReference,
    ContractValidationError,
    CouncilComponentProvenance,
    CouncilTransportKind,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    RunMode,
    StageError,
    StageStatus,
)
from .contracts.mission_request import format_rfc3339, parse_rfc3339
from .council_adapter import (
    COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
    CouncilAdapter,
    CouncilExecutionResult,
    CouncilFailure,
    CouncilMissionContext,
    CouncilSupportingInput,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .mission_store import MissionPaths, MissionStore
from .mission_transitions import begin_council, complete_council, fail_council


COUNCIL_INPUT_DIRECTORY = "council/inputs"
COUNCIL_ATTEMPT_DIRECTORY = "council/attempt-0001"
COUNCIL_SUPPORTING_INPUT_PATH = (
    f"{COUNCIL_INPUT_DIRECTORY}/council_supporting_input.json"
)
COUNCIL_PROVENANCE_PATH = f"{COUNCIL_ATTEMPT_DIRECTORY}/council_provenance.json"
COUNCIL_LINEAGE_PATH = (
    f"{COUNCIL_ATTEMPT_DIRECTORY}/council_lineage_manifest.json"
)
COUNCIL_PROVENANCE_SCHEMA_VERSION = "blackpod.council_provenance.v1"
COUNCIL_LINEAGE_SCHEMA_VERSION = "blackpod.council_lineage.v1"

REQUIRED_ORACLE_INPUTS: Mapping[str, str] = {
    "oracle_normalized_snapshot": (
        "oracle/attempt-0001/fleet-oracles-vapors-example_normalized.json"
    ),
    "oracle_readiness_report": (
        "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json"
    ),
    "oracle_report": "oracle/attempt-0001/oracle_report_live.json",
    "oracle_assessment": "oracle/attempt-0001/oracle_assessment_live.json",
    "oracle_narrative": "oracle/attempt-0001/oracle_narrative_live.json",
}

COUNCIL_NATIVE_OUTPUT_ARTIFACTS: Mapping[str, tuple[str, str, str]] = {
    "mandate_policy.json": (
        "council_mandate_policy",
        "mandate",
        "blackpod.contracts.MandateStatus",
    ),
    "trading_candidate_report.json": (
        "council_candidate_evidence",
        "candidate",
        "blackpod.contracts.TradingCandidateReport",
    ),
    "senate_review_packet.json": (
        "council_senate_review_evidence",
        "senate",
        "blackpod.contracts.SenateReviewPacket",
    ),
    "senate_deliberation.json": (
        "council_senate_deliberation_evidence",
        "senate",
        "blackpod.contracts.SenateDeliberation",
    ),
    "council_input_packet.json": (
        "council_input_packet",
        "council",
        "blackpod.governor.input_packet.GovernorInputPacket",
    ),
    "council_advisor_runtime_config.json": (
        "council_advisor_runtime_config",
        "council",
        "blackpod.runtime.runtime_config.RuntimeConfig",
    ),
    "council_advisor_runtime_validation.json": (
        "council_advisor_runtime_validation",
        "council",
        "blackpod.council_runtime_validation.v1",
    ),
    "advisor_health_summary.json": (
        "council_advisor_health",
        "council",
        "blackpod.contracts.AdvisorHealthSummary",
    ),
    "council_synthesis.json": (
        "council_synthesis",
        "council",
        "blackpod.contracts.CouncilSynthesis",
    ),
    "council_executive_summary.json": (
        "council_executive_summary",
        "council",
        "blackpod.contracts.CouncilExecutiveSummary",
    ),
}

_ORACLE_NATIVE_CONTRACTS: Mapping[str, str] = {
    "oracle_normalized_snapshot": "blackpod.contracts.NormalizedFleetSnapshot",
    "oracle_readiness_report": "blackpod.contracts.FleetSnapshotReadiness",
    "oracle_report": "blackpod.contracts.OracleReport",
    "oracle_assessment": "blackpod.contracts.OracleAssessment",
    "oracle_narrative": "blackpod.contracts.OracleNarrative",
}


class CouncilWorkflowError(RuntimeError):
    """Base class for Phase 3 orchestration failures."""


class CouncilInvocationError(CouncilWorkflowError):
    """Raised for a transport conflict or malformed supporting input."""


class CouncilPreconditionError(CouncilWorkflowError):
    """Raised when the verified mission is not eligible for Council."""


class CouncilStateConflictError(CouncilWorkflowError):
    """Raised when the one-attempt restart policy blocks execution."""


class CouncilAction(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class CouncilRunSettings:
    mission_id: str
    artifacts_root: Path
    replay_fixture: Path | None = None
    policy_input: Path | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class CouncilWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: CouncilAction
    council_artifact_directory: Path


class CouncilExecutor(Protocol):
    def execute(
        self,
        request: MissionRequest,
        context: CouncilMissionContext,
        *,
        supporting_input: CouncilSupportingInput,
    ) -> CouncilExecutionResult: ...


ConfigLoader = Callable[..., BattlestarConfig]
Clock = Callable[[], datetime]


def run_council(
    settings: CouncilRunSettings,
    *,
    environ: Mapping[str, str] | None = None,
    adapter: CouncilExecutor | None = None,
    config_loader: ConfigLoader = load_council_battlestar_config,
    clock: Clock | None = None,
) -> CouncilWorkflowResult:
    """Run or validate the single supported Council attempt for one mission."""

    _validate_settings(settings)
    # Preflight intentionally precedes MissionStore construction and all writes.
    config = config_loader(
        artifacts_root=settings.artifacts_root,
        environ=environ,
        strict_clean=settings.strict_battlestar_clean,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    supporting_input, supporting_bytes, transport = _load_supporting_input(
        loaded.request,
        replay_fixture=settings.replay_fixture,
        policy_input=settings.policy_input,
    )
    provenance = _build_provenance(
        loaded.request,
        config,
        transport=transport,
        supporting_input=supporting_input,
        supporting_bytes=supporting_bytes,
    )

    council_status = loaded.snapshot.stages["council"].status
    if council_status is StageStatus.SUCCEEDED:
        _validate_completed_invocation(
            loaded.snapshot,
            provenance=provenance,
            supporting_sha256=sha256_bytes(supporting_bytes),
        )
        return CouncilWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            action=CouncilAction.NO_OP_ALREADY_SUCCEEDED,
            council_artifact_directory=(
                loaded.paths.mission_root / COUNCIL_ATTEMPT_DIRECTORY
            ),
        )
    if council_status is StageStatus.RUNNING:
        raise CouncilStateConflictError(
            "Council is already RUNNING; Phase 3 does not overwrite or resume the attempt"
        )
    if council_status is StageStatus.FAILED:
        raise CouncilStateConflictError(
            "Council previously FAILED; Phase 3 has no force or retry option"
        )
    if council_status is not StageStatus.NOT_STARTED:
        raise CouncilStateConflictError(
            f"Council cannot run from status {council_status.value}"
        )

    oracle_inputs = _validate_council_preconditions(loaded.request, loaded.snapshot)

    try:
        executor: CouncilExecutor = adapter or CouncilAdapter(
            config.root,
            deadline_seconds=float(settings.deadline_seconds),
        )
    except Exception as exc:
        raise CouncilWorkflowError("Council adapter could not be prepared") from exc

    begin_observed_at = _observed_at(
        loaded.request.run_mode,
        supporting_input=supporting_input,
        clock=clock,
        not_before=loaded.snapshot.observed_at,
    )
    supporting_artifact = _capture_supporting_input(
        store,
        loaded.request,
        payload=supporting_bytes,
        observed_at=begin_observed_at,
    )
    running = begin_council(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=begin_observed_at,
        provenance=provenance,
        existing_input_names=tuple(REQUIRED_ORACLE_INPUTS),
        input_artifacts=(supporting_artifact,),
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    execution_result: CouncilExecutionResult
    try:
        store.reserve_directory(settings.mission_id, COUNCIL_ATTEMPT_DIRECTORY)
        context = CouncilMissionContext(
            mission_id=settings.mission_id,
            mission_root=loaded.paths.mission_root,
            normalized_path=oracle_inputs["oracle_normalized_snapshot"].path,
            readiness_path=oracle_inputs["oracle_readiness_report"].path,
            oracle_report_path=oracle_inputs["oracle_report"].path,
            oracle_assessment_path=oracle_inputs["oracle_assessment"].path,
            oracle_narrative_path=oracle_inputs["oracle_narrative"].path,
            output_dir=COUNCIL_ATTEMPT_DIRECTORY,
        )
        execution_result = executor.execute(
            loaded.request,
            context,
            supporting_input=supporting_input,
        )
        execution_result = _validate_execution_correlation(
            execution_result,
            loaded.request,
            provenance,
            supporting_input=supporting_input,
        )
    except Exception as exc:
        execution_result = _synthetic_failure(
            loaded.request,
            transport,
            supporting_input=supporting_input,
            code="COUNCIL_ADAPTER_FAILURE",
            error_type=type(exc).__name__,
            message="Council adapter or output reservation failed",
            resumable=False,
        )

    finish_observed_at = _observed_at(
        loaded.request.run_mode,
        supporting_input=supporting_input,
        clock=clock,
        not_before=running.observed_at,
    )
    try:
        native_outputs = _capture_native_outputs(
            store,
            settings.mission_id,
            execution_result.produced_paths,
            observed_at=finish_observed_at,
        )
        provenance_artifact = _write_provenance_artifact(
            store,
            loaded.request,
            provenance=provenance,
            supporting_input=supporting_input,
            observed_at=finish_observed_at,
        )
        lineage_artifact = _write_lineage_artifact(
            store,
            loaded.request,
            oracle_inputs=oracle_inputs,
            supporting_artifact=supporting_artifact,
            native_outputs=native_outputs,
            provenance_artifact=provenance_artifact,
            oracle_revision=_oracle_revision(loaded.snapshot),
            council_revision=config.git_revision,
            observed_at=finish_observed_at,
        )
        output_artifacts = (
            *native_outputs,
            provenance_artifact,
            lineage_artifact,
        )
    except Exception as exc:
        output_artifacts = ()
        execution_result = _synthetic_failure(
            loaded.request,
            transport,
            supporting_input=supporting_input,
            code="COUNCIL_ARTIFACT_CAPTURE_FAILED",
            error_type=type(exc).__name__,
            message="Council artifacts failed containment or integrity validation",
            resumable=False,
        )

    if execution_result.status is StageStatus.SUCCEEDED:
        if execution_result.native_state is None:
            raise AssertionError("validated Council success lacks native state")
        final_snapshot = complete_council(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_state,
            output_artifacts=output_artifacts,
        )
    else:
        failure = execution_result.failure
        if failure is None:
            failure = CouncilFailure(
                code="COUNCIL_MALFORMED_RESULT",
                error_type="ContractValidationError",
                message="Council failed without a structured error",
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
        final_snapshot = fail_council(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_state,
            error=stage_error,
            output_artifacts=output_artifacts,
        )
    store.commit_snapshot(loaded.paths, final_snapshot)
    return CouncilWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        action=CouncilAction.EXECUTED,
        council_artifact_directory=(
            loaded.paths.mission_root / COUNCIL_ATTEMPT_DIRECTORY
        ),
    )


def _validate_settings(settings: CouncilRunSettings) -> None:
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise CouncilInvocationError("deadline_seconds must be finite and positive")


def _load_supporting_input(
    request: MissionRequest,
    *,
    replay_fixture: Path | None,
    policy_input: Path | None,
) -> tuple[CouncilSupportingInput, bytes, CouncilTransportKind]:
    if request.run_mode is RunMode.REPLAY:
        if policy_input is not None:
            raise CouncilInvocationError(
                "REPLAY missions may not receive --policy-input"
            )
        if replay_fixture is None:
            raise CouncilInvocationError(
                "REPLAY missions require --replay-fixture and never fall back to LIVE"
            )
        source = Path(replay_fixture)
        transport = CouncilTransportKind.REPLAY_FIXTURE
    else:
        if replay_fixture is not None:
            raise CouncilInvocationError(
                "LIVE missions may not receive --replay-fixture"
            )
        if policy_input is None:
            raise CouncilInvocationError(
                "LIVE missions require --policy-input and never fall back to REPLAY"
            )
        source = Path(policy_input)
        transport = CouncilTransportKind.LIVE_MISSION_INPUTS
    if source.is_symlink() or not source.is_file():
        raise CouncilInvocationError(
            "Council supporting input must be a regular file"
        )
    try:
        payload = source.read_bytes()
        supporting_input = CouncilSupportingInput.from_bytes(payload)
    except OSError as exc:
        raise CouncilInvocationError(
            "Council supporting input could not be read"
        ) from exc
    except (TypeError, ValueError, ContractValidationError) as exc:
        raise CouncilInvocationError(
            "Council supporting input failed schema validation"
        ) from exc
    if supporting_input.run_mode is not request.run_mode:
        raise CouncilInvocationError(
            "Council supporting input run mode conflicts with the mission"
        )
    return supporting_input, payload, transport


def _validate_council_preconditions(
    request: MissionRequest,
    snapshot: MissionSnapshot,
) -> dict[str, ArtifactReference]:
    if request.mission_id is None or request.mission_id != snapshot.mission_id:
        raise CouncilPreconditionError("mission correlation metadata is inconsistent")
    if request.request_id != snapshot.request_id or request.run_mode is not snapshot.run_mode:
        raise CouncilPreconditionError("mission correlation metadata is inconsistent")
    if snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise CouncilPreconditionError("Harbormaster has not succeeded")
    if snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED:
        raise CouncilPreconditionError("Oracle must be technically successful")
    if snapshot.current_phase is not CurrentPhase.COUNCIL:
        raise CouncilPreconditionError("mission is not in the COUNCIL phase")
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE or snapshot.terminal:
        raise CouncilPreconditionError("Council requires a nonterminal INCOMPLETE mission")
    for stage_name in ("governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise CouncilPreconditionError(
                f"{stage_name} must remain NOT_STARTED before Council"
            )

    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    oracle_output_names = set(snapshot.stages["oracle"].outputs)
    selected: dict[str, ArtifactReference] = {}
    for name, expected_path in REQUIRED_ORACLE_INPUTS.items():
        artifact = artifacts.get(name)
        if (
            artifact is None
            or name not in oracle_output_names
            or artifact.path != expected_path
            or artifact.producer != "oracle"
        ):
            raise CouncilPreconditionError(
                f"required Oracle artifact is missing or noncanonical: {name}"
            )
        selected[name] = artifact
    if "battlestar" not in snapshot.components:
        raise CouncilPreconditionError("Oracle component provenance is missing")
    return selected


def _build_provenance(
    request: MissionRequest,
    config: BattlestarConfig,
    *,
    transport: CouncilTransportKind,
    supporting_input: CouncilSupportingInput,
    supporting_bytes: bytes,
) -> CouncilComponentProvenance:
    replay = transport is CouncilTransportKind.REPLAY_FIXTURE
    return CouncilComponentProvenance.from_mapping(
        {
            "git_revision": config.git_revision,
            "git_branch": config.git_branch,
            "dirty_worktree": config.dirty_worktree,
            "candidate_entry_point": CANDIDATE_ENTRY_POINT,
            "senate_review_entry_point": SENATE_REVIEW_ENTRY_POINT,
            "senate_deliberation_entry_point": SENATE_DELIBERATION_ENTRY_POINT,
            "mandate_entry_point": MANDATE_ENTRY_POINT,
            "runtime_validation_entry_point": RUNTIME_VALIDATION_ENTRY_POINT,
            "advisor_health_entry_point": ADVISOR_HEALTH_ENTRY_POINT,
            "council_synthesis_entry_point": COUNCIL_SYNTHESIS_ENTRY_POINT,
            "council_executive_summary_entry_point": (
                COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT
            ),
            "run_mode": request.run_mode.value,
            "transport": transport.value,
            "replay_fixture_id": supporting_input.input_id if replay else None,
            "replay_fixture_sha256": (
                sha256_bytes(supporting_bytes) if replay else None
            ),
        }
    )


def _capture_supporting_input(
    store: MissionStore,
    request: MissionRequest,
    *,
    payload: bytes,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise CouncilInvocationError("stored mission request lacks mission_id")
    producer = "harbormaster" if request.run_mode is RunMode.REPLAY else "operator"
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=COUNCIL_SUPPORTING_INPUT_PATH,
        payload=payload,
        name="council_supporting_input",
        producer=producer,
        schema_version=COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _capture_native_outputs(
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
        expected_path = f"{COUNCIL_ATTEMPT_DIRECTORY}/{filename}"
        if (
            path.as_posix() != expected_path
            or filename not in COUNCIL_NATIVE_OUTPUT_ARTIFACTS
            or filename in seen
        ):
            raise ContractValidationError(
                "Council reported an unsupported or duplicate artifact path"
            )
        seen.add(filename)
        name, producer, native_contract = COUNCIL_NATIVE_OUTPUT_ARTIFACTS[filename]
        artifacts.append(
            store.reference_existing_artifact(
                mission_id,
                relative_path=expected_path,
                name=name,
                producer=producer,
                # Battlestar's current Council-side models are unversioned. Keep
                # their stable contract identifier in the canonical artifact
                # record until the sibling repository exposes schema versions.
                schema_version=native_contract,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _write_provenance_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    provenance: CouncilComponentProvenance,
    supporting_input: CouncilSupportingInput,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise CouncilInvocationError("stored mission request lacks mission_id")
    payload = canonical_json_bytes(
        {
            "schema_version": COUNCIL_PROVENANCE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "supporting_input_id": supporting_input.input_id,
            "observed_at": observed_at,
            "component": provenance.to_dict(),
        }
    )
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=COUNCIL_PROVENANCE_PATH,
        payload=payload,
        name="council_provenance",
        producer="council",
        schema_version=COUNCIL_PROVENANCE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _write_lineage_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    oracle_inputs: Mapping[str, ArtifactReference],
    supporting_artifact: ArtifactReference,
    native_outputs: tuple[ArtifactReference, ...],
    provenance_artifact: ArtifactReference,
    oracle_revision: str,
    council_revision: str,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise CouncilInvocationError("stored mission request lacks mission_id")
    input_entries = [
        _lineage_entry(
            oracle_inputs[name],
            native_contract=_ORACLE_NATIVE_CONTRACTS[name],
            component_revision=oracle_revision,
            request=request,
        )
        for name in REQUIRED_ORACLE_INPUTS
    ]
    input_entries.append(
        _lineage_entry(
            supporting_artifact,
            native_contract=COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
            component_revision=f"sha256:{supporting_artifact.sha256}",
            request=request,
        )
    )
    native_contract_by_name = {
        artifact_name: native_contract
        for artifact_name, _producer, native_contract in COUNCIL_NATIVE_OUTPUT_ARTIFACTS.values()
    }
    output_entries = [
        _lineage_entry(
            artifact,
            native_contract=native_contract_by_name[artifact.name],
            component_revision=council_revision,
            request=request,
        )
        for artifact in native_outputs
    ]
    output_entries.append(
        _lineage_entry(
            provenance_artifact,
            native_contract=COUNCIL_PROVENANCE_SCHEMA_VERSION,
            component_revision=council_revision,
            request=request,
        )
    )
    oracle_source_names = list(REQUIRED_ORACLE_INPUTS)
    root_source_names = [*oracle_source_names, "council_supporting_input"]
    dependency_names: dict[str, list[str]] = {
        "council_mandate_policy": ["council_supporting_input"],
        "council_candidate_evidence": [
            "oracle_normalized_snapshot",
            "oracle_readiness_report",
        ],
        "council_senate_review_evidence": [
            "council_candidate_evidence",
            "oracle_report",
        ],
        "council_senate_deliberation_evidence": [
            "council_senate_review_evidence",
            "oracle_report",
        ],
        "council_input_packet": [
            *root_source_names,
            "council_mandate_policy",
            "council_candidate_evidence",
            "council_senate_review_evidence",
            "council_senate_deliberation_evidence",
        ],
        "council_advisor_runtime_config": [
            "oracle_report",
            "council_supporting_input",
            "council_mandate_policy",
            "council_candidate_evidence",
            "council_senate_review_evidence",
            "council_senate_deliberation_evidence",
        ],
        "council_advisor_runtime_validation": [
            "council_advisor_runtime_config",
            "oracle_report",
            "council_mandate_policy",
            "council_candidate_evidence",
            "council_senate_review_evidence",
            "council_senate_deliberation_evidence",
        ],
        "council_advisor_health": [
            "council_advisor_runtime_validation",
            "council_input_packet",
        ],
        "council_synthesis": [
            *root_source_names,
            "council_mandate_policy",
            "council_candidate_evidence",
            "council_senate_review_evidence",
            "council_senate_deliberation_evidence",
            "council_input_packet",
            "council_advisor_health",
        ],
        "council_executive_summary": [
            *root_source_names,
            "council_mandate_policy",
            "council_candidate_evidence",
            "council_senate_review_evidence",
            "council_senate_deliberation_evidence",
            "council_input_packet",
            "council_advisor_health",
            "council_synthesis",
        ],
        "council_provenance": root_source_names,
    }
    for entry in output_entries:
        entry["source_input_names"] = dependency_names[entry["name"]]
    payload = canonical_json_bytes(
        {
            "schema_version": COUNCIL_LINEAGE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "observed_at": observed_at,
            "inputs": input_entries,
            "outputs": output_entries,
        }
    )
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=COUNCIL_LINEAGE_PATH,
        payload=payload,
        name="council_lineage_manifest",
        producer="council",
        schema_version=COUNCIL_LINEAGE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _lineage_entry(
    artifact: ArtifactReference,
    *,
    native_contract: str,
    component_revision: str,
    request: MissionRequest,
) -> dict[str, Any]:
    return {
        "name": artifact.name,
        "path": artifact.path,
        "producer": artifact.producer,
        "sha256": artifact.sha256,
        "byte_size": artifact.byte_size,
        "schema_version": artifact.schema_version,
        "observed_at": artifact.observed_at,
        "native_contract": native_contract,
        "originating_component_revision": component_revision,
        "mission_id": request.mission_id,
        "request_id": request.request_id,
    }


def _validate_execution_correlation(
    result: CouncilExecutionResult,
    request: MissionRequest,
    provenance: CouncilComponentProvenance,
    *,
    supporting_input: CouncilSupportingInput,
) -> CouncilExecutionResult:
    if not isinstance(result, CouncilExecutionResult):
        raise ContractValidationError("Council adapter returned an unsupported result")
    if (
        request.mission_id is None
        or result.mission_id != request.mission_id
        or result.request_id != request.request_id
        or result.symbol != request.symbol
        or result.run_mode is not request.run_mode
        or result.transport is not provenance.transport
        or result.input_id != supporting_input.input_id
    ):
        raise ContractValidationError("Council result correlation does not match the mission")
    expected_paths = {
        f"{COUNCIL_ATTEMPT_DIRECTORY}/{filename}"
        for filename in COUNCIL_NATIVE_OUTPUT_ARTIFACTS
    }
    produced_paths = set(result.produced_paths)
    if len(produced_paths) != len(result.produced_paths):
        raise ContractValidationError("Council result contains duplicate artifact paths")
    if result.status is StageStatus.SUCCEEDED:
        expected_source_lineage = (
            *(REQUIRED_ORACLE_INPUTS[name] for name in REQUIRED_ORACLE_INPUTS),
            COUNCIL_SUPPORTING_INPUT_PATH,
        )
        if result.native_state is None:
            raise ContractValidationError(
                "technically successful Council result lacks a native state"
            )
        if result.failure is not None:
            raise ContractValidationError(
                "technically successful Council result contains a failure"
            )
        if produced_paths != expected_paths:
            raise ContractValidationError(
                "technically successful Council result lacks the canonical artifact set"
            )
        if result.source_lineage != expected_source_lineage:
            raise ContractValidationError(
                "technically successful Council result misstates its source lineage"
            )
    elif result.status is StageStatus.FAILED:
        if result.failure is None:
            raise ContractValidationError(
                "failed Council result lacks a structured failure"
            )
        if not produced_paths.issubset(expected_paths):
            raise ContractValidationError(
                "failed Council result contains unsupported artifact paths"
            )
    else:
        raise ContractValidationError(
            "Council result status must be SUCCEEDED or FAILED"
        )
    return result


def _synthetic_failure(
    request: MissionRequest,
    transport: CouncilTransportKind,
    *,
    supporting_input: CouncilSupportingInput,
    code: str,
    error_type: str,
    message: str,
    resumable: bool,
) -> CouncilExecutionResult:
    return CouncilExecutionResult(
        mission_id=request.mission_id or "mission-correlation-missing",
        request_id=request.request_id,
        symbol=request.symbol,
        run_mode=request.run_mode,
        transport=transport,
        status=StageStatus.FAILED,
        native_state=None,
        produced_paths=(),
        failure=CouncilFailure(
            code=code,
            error_type=_safe_error_type(error_type),
            message=message,
            resumable=resumable,
        ),
        input_id=supporting_input.input_id,
    )


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "CouncilWorkflowError"


def _observed_at(
    run_mode: RunMode,
    *,
    supporting_input: CouncilSupportingInput,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        candidate = supporting_input.generated_at
    else:
        current = clock() if clock is not None else datetime.now(UTC)
        candidate = format_rfc3339(current)
    if parse_rfc3339(candidate, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        return not_before
    return candidate


def _oracle_revision(snapshot: MissionSnapshot) -> str:
    component = snapshot.components.get("battlestar")
    revision = getattr(component, "git_revision", None)
    if not isinstance(revision, str):
        raise CouncilPreconditionError("Oracle component revision is missing")
    return revision


def _validate_completed_invocation(
    snapshot: MissionSnapshot,
    *,
    provenance: CouncilComponentProvenance,
    supporting_sha256: str,
) -> None:
    council = snapshot.stages["council"]
    if (
        snapshot.current_phase is not CurrentPhase.GOVERNOR
        or snapshot.mission_outcome is not MissionOutcome.INCOMPLETE
        or snapshot.terminal
        or snapshot.stages["harbormaster"].status is not StageStatus.SUCCEEDED
        or snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED
        or council.status is not StageStatus.SUCCEEDED
        or snapshot.components.get("battlestar_council") != provenance
    ):
        raise CouncilStateConflictError(
            "completed Council state does not match this invocation"
        )
    for stage_name in ("governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise CouncilStateConflictError(
                "a later stage has started; Phase 3 cannot claim a Council no-op"
            )
    artifacts = {item.name: item for item in snapshot.artifacts}
    oracle_outputs = set(snapshot.stages["oracle"].outputs)
    for artifact_name, expected_path in REQUIRED_ORACLE_INPUTS.items():
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact_name not in oracle_outputs
            or artifact.path != expected_path
            or artifact.producer != "oracle"
        ):
            raise CouncilStateConflictError(
                "completed Council Oracle inputs are not canonical"
            )
    supporting = artifacts.get("council_supporting_input")
    expected_supporting_producer = (
        "harbormaster" if snapshot.run_mode is RunMode.REPLAY else "operator"
    )
    if (
        supporting is None
        or supporting.path != COUNCIL_SUPPORTING_INPUT_PATH
        or supporting.sha256 != supporting_sha256
        or supporting.producer != expected_supporting_producer
        or supporting.schema_version != COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION
    ):
        raise CouncilStateConflictError(
            "Council supporting input differs from the completed invocation"
        )
    expected_inputs = {*REQUIRED_ORACLE_INPUTS, "council_supporting_input"}
    if set(council.inputs) != expected_inputs:
        raise CouncilStateConflictError("completed Council inputs are not canonical")
    expected_outputs = {
        *(value[0] for value in COUNCIL_NATIVE_OUTPUT_ARTIFACTS.values()),
        "council_provenance",
        "council_lineage_manifest",
    }
    if set(council.outputs) != expected_outputs:
        raise CouncilStateConflictError("completed Council output set is not canonical")
    for filename, (artifact_name, producer, contract) in (
        COUNCIL_NATIVE_OUTPUT_ARTIFACTS.items()
    ):
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact.path != f"{COUNCIL_ATTEMPT_DIRECTORY}/{filename}"
            or artifact.producer != producer
            or artifact.schema_version != contract
        ):
            raise CouncilStateConflictError(
                "completed Council artifact provenance is not canonical"
            )
    for artifact_name, path in (
        ("council_provenance", COUNCIL_PROVENANCE_PATH),
        ("council_lineage_manifest", COUNCIL_LINEAGE_PATH),
    ):
        artifact = artifacts.get(artifact_name)
        expected_schema = (
            COUNCIL_PROVENANCE_SCHEMA_VERSION
            if artifact_name == "council_provenance"
            else COUNCIL_LINEAGE_SCHEMA_VERSION
        )
        if (
            artifact is None
            or artifact.path != path
            or artifact.producer != "council"
            or artifact.schema_version != expected_schema
        ):
            raise CouncilStateConflictError(
                "completed Council lineage or provenance is not canonical"
            )
