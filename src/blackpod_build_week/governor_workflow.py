"""Harbormaster-owned orchestration for one immutable Phase 4 Governor attempt."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import (
    GOVERNOR_DELIBERATION_ENTRY_POINT,
    GOVERNOR_PREPARATION_ENTRY_POINT,
    GOVERNOR_READINESS_ENTRY_POINT,
    GOVERNOR_RENDERING_ENTRY_POINT,
    GOVERNOR_SENATE_INTAKE_ENTRY_POINT,
    BattlestarConfig,
    load_governor_battlestar_config,
)
from .contracts import (
    ArtifactReference,
    ContractValidationError,
    CurrentPhase,
    GovernorComponentProvenance,
    GovernorTransportKind,
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
from .governor_adapter import (
    GOVERNOR_SUPPORTING_CONTEXT_RELATIVE_PATH,
    GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
    GovernorAdapter,
    GovernorExecutionResult,
    GovernorFailure,
    GovernorMissionContext,
    GovernorSupportingContext,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .mission_store import MissionPaths, MissionStore
from .mission_transitions import begin_governor, complete_governor, fail_governor


GOVERNOR_INPUT_DIRECTORY = "governor/inputs"
GOVERNOR_ATTEMPT_DIRECTORY = "governor/attempt-0001"
GOVERNOR_SUPPORTING_CONTEXT_PATH = GOVERNOR_SUPPORTING_CONTEXT_RELATIVE_PATH
GOVERNOR_PROVENANCE_PATH = f"{GOVERNOR_ATTEMPT_DIRECTORY}/governor_provenance.json"
GOVERNOR_LINEAGE_PATH = f"{GOVERNOR_ATTEMPT_DIRECTORY}/lineage_manifest.json"
GOVERNOR_PROVENANCE_SCHEMA_VERSION = "blackpod.governor_provenance.v1"
GOVERNOR_LINEAGE_SCHEMA_VERSION = "blackpod.governor_lineage.v1"


REQUIRED_GOVERNOR_INPUTS: Mapping[str, tuple[str, str, str]] = {
    "oracle_report": (
        "oracle/attempt-0001/oracle_report_live.json",
        "oracle",
        "blackpod.contracts.OracleReport",
    ),
    "oracle_measurement_diagnostics": (
        "oracle/attempt-0001/oracle_measurement_diagnostics_live.json",
        "oracle",
        "blackpod.contracts.OracleMeasurementDiagnostics",
    ),
    "oracle_readiness_report": (
        "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json",
        "oracle",
        "blackpod.contracts.FleetSnapshotReadiness",
    ),
    "council_synthesis": (
        "council/attempt-0001/council_synthesis.json",
        "council",
        "blackpod.contracts.CouncilSynthesis",
    ),
    "council_executive_summary": (
        "council/attempt-0001/council_executive_summary.json",
        "council",
        "blackpod.contracts.CouncilExecutiveSummary",
    ),
    "council_candidate_evidence": (
        "council/attempt-0001/trading_candidate_report.json",
        "candidate",
        "blackpod.contracts.TradingCandidateReport",
    ),
    "council_senate_review_evidence": (
        "council/attempt-0001/senate_review_packet.json",
        "senate",
        "blackpod.contracts.SenateReviewPacket",
    ),
    "council_senate_deliberation_evidence": (
        "council/attempt-0001/senate_deliberation.json",
        "senate",
        "blackpod.contracts.SenateDeliberation",
    ),
    "council_mandate_policy": (
        "council/attempt-0001/mandate_policy.json",
        "mandate",
        "blackpod.contracts.MandateStatus",
    ),
    "council_advisor_health": (
        "council/attempt-0001/advisor_health_summary.json",
        "council",
        "blackpod.contracts.AdvisorHealthSummary",
    ),
    "council_lineage_manifest": (
        "council/attempt-0001/council_lineage_manifest.json",
        "council",
        "blackpod.council_lineage.v1",
    ),
}


GOVERNOR_NATIVE_OUTPUT_ARTIFACTS: Mapping[str, tuple[str, str]] = {
    "governor_input_context.json": (
        "governor_input_context",
        "blackpod.governor_input_context.v1",
    ),
    "governor_senate_intake.json": (
        "governor_senate_intake",
        "blackpod.contracts.GovernorSenateIntake",
    ),
    "governor_deliberation_prep.json": (
        "governor_deliberation_prep",
        "blackpod.contracts.GovernorDeliberationPrep",
    ),
    "governor_deliberation.json": (
        "governor_deliberation",
        "blackpod.contracts.GovernorDeliberation",
    ),
    "governor_decision_readiness.json": (
        "governor_decision_readiness",
        "blackpod.contracts.GovernorDecisionReadiness",
    ),
    "governor_decision.json": (
        "governor_decision",
        "blackpod.contracts.governor_decision.GovernorDecision",
    ),
    "governor_rendered_decision.json": (
        "governor_rendered_decision",
        "blackpod.governor_rendered_decision.v1",
    ),
    "secretary_outcome_summary.json": (
        "governor_secretary_accountability",
        "blackpod.contracts.SecretaryOutcomeSummary",
    ),
    "warning_classification.json": (
        "governor_warning_classification",
        "blackpod.governor_warning_classification.v1",
    ),
}


class GovernorWorkflowError(RuntimeError):
    """Base class for Phase 4 orchestration failures."""


class GovernorInvocationError(GovernorWorkflowError):
    """Raised when CLI transport inputs conflict with the mission."""


class GovernorPreconditionError(GovernorWorkflowError):
    """Raised when the mission or its recorded evidence is not eligible."""


class GovernorStateConflictError(GovernorWorkflowError):
    """Raised when the immutable one-attempt policy prevents execution."""


class GovernorAction(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class GovernorRunSettings:
    mission_id: str
    artifacts_root: Path
    replay_fixture: Path | None = None
    context_input: Path | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class GovernorWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: GovernorAction
    governor_artifact_directory: Path
    readiness_state: str | None
    allowed_next_step: str | None


class GovernorExecutor(Protocol):
    def execute(
        self,
        request: MissionRequest,
        context: GovernorMissionContext,
        *,
        supporting_context: GovernorSupportingContext,
    ) -> GovernorExecutionResult: ...


ConfigLoader = Callable[..., BattlestarConfig]
Clock = Callable[[], datetime]


def run_governor(
    settings: GovernorRunSettings,
    *,
    environ: Mapping[str, str] | None = None,
    adapter: GovernorExecutor | None = None,
    config_loader: ConfigLoader = load_governor_battlestar_config,
    clock: Clock | None = None,
) -> GovernorWorkflowResult:
    """Run or validate the single supported Governor attempt for a mission."""

    _validate_settings(settings)
    # Preflight is intentionally read-only and precedes every mission write.
    config = config_loader(
        artifacts_root=settings.artifacts_root,
        environ=environ,
        strict_clean=settings.strict_battlestar_clean,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    supporting_context, supporting_bytes, transport = _load_supporting_context(
        loaded.request,
        replay_fixture=settings.replay_fixture,
        context_input=settings.context_input,
    )
    provenance = _build_provenance(
        loaded.request,
        config,
        transport=transport,
        supporting_context=supporting_context,
        supporting_bytes=supporting_bytes,
    )

    governor_status = loaded.snapshot.stages["governor"].status
    if governor_status is StageStatus.SUCCEEDED:
        readiness_state, allowed_next_step = _validate_completed_invocation(
            loaded,
            provenance=provenance,
            supporting_sha256=sha256_bytes(supporting_bytes),
        )
        return GovernorWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            action=GovernorAction.NO_OP_ALREADY_SUCCEEDED,
            governor_artifact_directory=(
                loaded.paths.mission_root / GOVERNOR_ATTEMPT_DIRECTORY
            ),
            readiness_state=readiness_state,
            allowed_next_step=allowed_next_step,
        )
    if governor_status is StageStatus.RUNNING:
        raise GovernorStateConflictError(
            "Governor is already RUNNING; Phase 4 does not overwrite or resume the attempt"
        )
    if governor_status is StageStatus.FAILED:
        raise GovernorStateConflictError(
            "Governor previously FAILED; Phase 4 has no force or retry option"
        )
    if governor_status is not StageStatus.NOT_STARTED:
        raise GovernorStateConflictError(
            f"Governor cannot run from status {governor_status.value}"
        )

    stage_inputs = _validate_governor_preconditions(
        loaded.request,
        loaded.snapshot,
        loaded.paths.mission_root,
    )
    try:
        executor: GovernorExecutor = adapter or GovernorAdapter(
            config.root,
            deadline_seconds=float(settings.deadline_seconds),
        )
    except Exception as exc:
        raise GovernorWorkflowError("Governor adapter could not be prepared") from exc

    begin_observed_at = _observed_at(
        loaded.request.run_mode,
        supporting_context=supporting_context,
        clock=clock,
        not_before=loaded.snapshot.observed_at,
    )
    supporting_artifact = _capture_supporting_context(
        store,
        loaded.request,
        payload=supporting_bytes,
        observed_at=begin_observed_at,
    )
    running = begin_governor(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=begin_observed_at,
        provenance=provenance,
        existing_input_names=tuple(REQUIRED_GOVERNOR_INPUTS),
        input_artifacts=(supporting_artifact,),
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    # BaseException is intentionally not caught: an interrupt leaves the RUNNING
    # revision as an explicit, inspectable restart conflict.
    unvalidated_result: object | None = None
    try:
        store.reserve_directory(settings.mission_id, GOVERNOR_ATTEMPT_DIRECTORY)
        context = GovernorMissionContext(
            mission_id=settings.mission_id,
            mission_root=loaded.paths.mission_root,
            oracle_report_path=stage_inputs["oracle_report"].path,
            oracle_diagnostics_path=stage_inputs[
                "oracle_measurement_diagnostics"
            ].path,
            oracle_readiness_path=stage_inputs["oracle_readiness_report"].path,
            council_synthesis_path=stage_inputs["council_synthesis"].path,
            council_summary_path=stage_inputs["council_executive_summary"].path,
            candidate_path=stage_inputs["council_candidate_evidence"].path,
            senate_review_path=stage_inputs["council_senate_review_evidence"].path,
            senate_deliberation_path=stage_inputs[
                "council_senate_deliberation_evidence"
            ].path,
            mandate_path=stage_inputs["council_mandate_policy"].path,
            council_health_path=stage_inputs["council_advisor_health"].path,
            council_lineage_path=stage_inputs["council_lineage_manifest"].path,
            output_dir=GOVERNOR_ATTEMPT_DIRECTORY,
        )
        unvalidated_result = executor.execute(
            loaded.request,
            context,
            supporting_context=supporting_context,
        )
        execution_result = _validate_execution_correlation(
            unvalidated_result,
            loaded.request,
            provenance,
            supporting_context=supporting_context,
        )
    except Exception as exc:
        produced_paths = (
            unvalidated_result.produced_paths
            if isinstance(unvalidated_result, GovernorExecutionResult)
            else ()
        )
        execution_result = _synthetic_failure(
            loaded.request,
            transport,
            supporting_context=supporting_context,
            code="GOVERNOR_ADAPTER_FAILURE",
            error_type=type(exc).__name__,
            message="Governor adapter or output reservation failed",
            resumable=False,
            produced_paths=produced_paths,
        )

    finish_observed_at = _observed_at(
        loaded.request.run_mode,
        supporting_context=supporting_context,
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
            supporting_context=supporting_context,
            observed_at=finish_observed_at,
        )
        lineage_artifact = _write_lineage_artifact(
            store,
            loaded.request,
            stage_inputs=stage_inputs,
            supporting_artifact=supporting_artifact,
            native_outputs=native_outputs,
            provenance_artifact=provenance_artifact,
            snapshot=loaded.snapshot,
            governor_revision=config.git_revision,
            observed_at=finish_observed_at,
        )
        output_artifacts = (*native_outputs, provenance_artifact, lineage_artifact)
    except Exception as exc:
        output_artifacts = ()
        execution_result = _synthetic_failure(
            loaded.request,
            transport,
            supporting_context=supporting_context,
            code="GOVERNOR_ARTIFACT_CAPTURE_FAILED",
            error_type=type(exc).__name__,
            message="Governor artifacts failed containment or integrity validation",
            resumable=False,
        )

    if execution_result.status is StageStatus.SUCCEEDED:
        if execution_result.native_disposition is None:
            raise AssertionError("validated Governor success lacks a disposition")
        final_snapshot = complete_governor(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_disposition,
            output_artifacts=output_artifacts,
        )
    else:
        failure = execution_result.failure or GovernorFailure(
            code="GOVERNOR_MALFORMED_RESULT",
            error_type="ContractValidationError",
            message="Governor failed without a structured error",
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
        final_snapshot = fail_governor(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=finish_observed_at,
            native_state=execution_result.native_disposition,
            error=stage_error,
            output_artifacts=output_artifacts,
        )
    store.commit_snapshot(loaded.paths, final_snapshot)
    return GovernorWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        action=GovernorAction.EXECUTED,
        governor_artifact_directory=(
            loaded.paths.mission_root / GOVERNOR_ATTEMPT_DIRECTORY
        ),
        readiness_state=execution_result.readiness_state,
        allowed_next_step=execution_result.allowed_next_step,
    )


def _validate_settings(settings: GovernorRunSettings) -> None:
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise GovernorInvocationError("deadline_seconds must be finite and positive")


def _load_supporting_context(
    request: MissionRequest,
    *,
    replay_fixture: Path | None,
    context_input: Path | None,
) -> tuple[GovernorSupportingContext, bytes, GovernorTransportKind]:
    if request.run_mode is RunMode.REPLAY:
        if context_input is not None:
            raise GovernorInvocationError(
                "REPLAY missions may not receive --context-input"
            )
        if replay_fixture is None:
            raise GovernorInvocationError(
                "REPLAY missions require --replay-fixture and never fall back to LIVE"
            )
        source = Path(replay_fixture)
        transport = GovernorTransportKind.REPLAY_FIXTURE
    else:
        if replay_fixture is not None:
            raise GovernorInvocationError(
                "LIVE missions may not receive --replay-fixture"
            )
        if context_input is None:
            raise GovernorInvocationError(
                "LIVE missions require --context-input and never fall back to REPLAY"
            )
        source = Path(context_input)
        transport = GovernorTransportKind.LIVE_MISSION_INPUTS
    if source.is_symlink() or not source.is_file():
        raise GovernorInvocationError("Governor supporting context must be a regular file")
    try:
        payload = source.read_bytes()
        supporting_context = GovernorSupportingContext.from_bytes(payload)
    except OSError as exc:
        raise GovernorInvocationError(
            "Governor supporting context could not be read"
        ) from exc
    except (TypeError, ValueError, ContractValidationError) as exc:
        raise GovernorInvocationError(
            "Governor supporting context failed schema validation"
        ) from exc
    if supporting_context.run_mode is not request.run_mode:
        raise GovernorInvocationError(
            "Governor supporting context run mode conflicts with the mission"
        )
    if (
        request.mission_id is None
        or supporting_context.mission_id != request.mission_id
        or supporting_context.request_id != request.request_id
    ):
        raise GovernorInvocationError(
            "Governor supporting context correlation conflicts with the mission"
        )
    return supporting_context, payload, transport


def _validate_governor_preconditions(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    mission_root: Path,
) -> dict[str, ArtifactReference]:
    if request.mission_id is None or request.mission_id != snapshot.mission_id:
        raise GovernorPreconditionError("mission correlation metadata is inconsistent")
    if request.request_id != snapshot.request_id or request.run_mode is not snapshot.run_mode:
        raise GovernorPreconditionError("mission correlation metadata is inconsistent")
    for stage_name in ("harbormaster", "oracle", "council"):
        if snapshot.stages[stage_name].status is not StageStatus.SUCCEEDED:
            raise GovernorPreconditionError(
                f"{stage_name.title()} must be technically successful"
            )
    if snapshot.current_phase is not CurrentPhase.GOVERNOR:
        raise GovernorPreconditionError("mission is not in the GOVERNOR phase")
    if snapshot.mission_outcome is not MissionOutcome.INCOMPLETE or snapshot.terminal:
        raise GovernorPreconditionError(
            "Governor requires a nonterminal INCOMPLETE mission"
        )
    if snapshot.stages["governor"].status is not StageStatus.NOT_STARTED:
        raise GovernorPreconditionError("Governor must be NOT_STARTED")
    if snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED:
        raise GovernorPreconditionError("Navigator must remain NOT_STARTED")
    if "battlestar" not in snapshot.components or "battlestar_council" not in snapshot.components:
        raise GovernorPreconditionError("Oracle and Council provenance are required")

    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    oracle_outputs = set(snapshot.stages["oracle"].outputs)
    council_outputs = set(snapshot.stages["council"].outputs)
    selected: dict[str, ArtifactReference] = {}
    for name, (expected_path, producer, _contract) in REQUIRED_GOVERNOR_INPUTS.items():
        artifact = artifacts.get(name)
        expected_stage = oracle_outputs if name.startswith("oracle_") else council_outputs
        if (
            artifact is None
            or name not in expected_stage
            or artifact.path != expected_path
            or artifact.producer != producer
        ):
            raise GovernorPreconditionError(
                f"required Governor input is missing or noncanonical: {name}"
            )
        selected[name] = artifact
    _validate_council_lineage(
        mission_root / selected["council_lineage_manifest"].path,
        request=request,
        selected=selected,
    )
    _validate_native_correlations(mission_root, selected)
    return selected


def _validate_council_lineage(
    path: Path,
    *,
    request: MissionRequest,
    selected: Mapping[str, ArtifactReference],
) -> None:
    try:
        payload = load_strict_json_object(path)
    except (OSError, ContractValidationError) as exc:
        raise GovernorPreconditionError("Council lineage manifest is malformed") from exc
    if (
        payload.get("schema_version") != "blackpod.council_lineage.v1"
        or payload.get("mission_id") != request.mission_id
        or payload.get("request_id") != request.request_id
        or payload.get("run_mode") != request.run_mode.value
    ):
        raise GovernorPreconditionError("Council lineage correlation is inconsistent")
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise GovernorPreconditionError("Council lineage outputs are malformed")
    by_name = {
        entry.get("name"): entry
        for entry in outputs
        if isinstance(entry, Mapping) and isinstance(entry.get("name"), str)
    }
    for name in (
        "council_synthesis",
        "council_executive_summary",
        "council_candidate_evidence",
        "council_senate_review_evidence",
        "council_senate_deliberation_evidence",
        "council_mandate_policy",
        "council_advisor_health",
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
            raise GovernorPreconditionError(
                f"Council lineage does not validate Governor input: {name}"
            )


def _validate_native_correlations(
    mission_root: Path,
    selected: Mapping[str, ArtifactReference],
) -> None:
    try:
        synthesis = load_strict_json_object(
            mission_root / selected["council_synthesis"].path
        )
        summary = load_strict_json_object(
            mission_root / selected["council_executive_summary"].path
        )
        senate = load_strict_json_object(
            mission_root / selected["council_senate_deliberation_evidence"].path
        )
        report = load_strict_json_object(mission_root / selected["oracle_report"].path)
    except (OSError, ContractValidationError) as exc:
        raise GovernorPreconditionError("Governor native input JSON is malformed") from exc
    if (
        not isinstance(synthesis.get("synthesis_id"), str)
        or summary.get("synthesis_id") != synthesis.get("synthesis_id")
    ):
        raise GovernorPreconditionError("Council summary does not correlate to synthesis")
    report_id = report.get("report_id")
    if not isinstance(report_id, str) or not report_id:
        raise GovernorPreconditionError("Oracle report correlation ID is missing")
    items = senate.get("items")
    if not isinstance(senate.get("deliberation_id"), str) or not isinstance(items, list):
        raise GovernorPreconditionError("Senate deliberation correlation is malformed")
    for item in items:
        if not isinstance(item, Mapping):
            raise GovernorPreconditionError("Senate deliberation item is malformed")
        market = item.get("market_context")
        if not isinstance(market, Mapping) or market.get("oracle_report_id") != report_id:
            raise GovernorPreconditionError(
                "Senate evidence does not correlate to the Oracle report"
            )


def _build_provenance(
    request: MissionRequest,
    config: BattlestarConfig,
    *,
    transport: GovernorTransportKind,
    supporting_context: GovernorSupportingContext,
    supporting_bytes: bytes,
) -> GovernorComponentProvenance:
    replay = transport is GovernorTransportKind.REPLAY_FIXTURE
    return GovernorComponentProvenance.from_mapping(
        {
            "git_revision": config.git_revision,
            "git_branch": config.git_branch,
            "dirty_worktree": config.dirty_worktree,
            "senate_intake_entry_point": GOVERNOR_SENATE_INTAKE_ENTRY_POINT,
            "preparation_entry_point": GOVERNOR_PREPARATION_ENTRY_POINT,
            "deliberation_entry_point": GOVERNOR_DELIBERATION_ENTRY_POINT,
            "readiness_entry_point": GOVERNOR_READINESS_ENTRY_POINT,
            "rendering_entry_point": GOVERNOR_RENDERING_ENTRY_POINT,
            "run_mode": request.run_mode.value,
            "transport": transport.value,
            "replay_fixture_id": supporting_context.context_id if replay else None,
            "replay_fixture_sha256": (
                sha256_bytes(supporting_bytes) if replay else None
            ),
        }
    )


def _capture_supporting_context(
    store: MissionStore,
    request: MissionRequest,
    *,
    payload: bytes,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise GovernorInvocationError("stored mission request lacks mission_id")
    producer = "harbormaster" if request.run_mode is RunMode.REPLAY else "operator"
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=GOVERNOR_SUPPORTING_CONTEXT_PATH,
        payload=payload,
        name="governor_supporting_context",
        producer=producer,
        schema_version=GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
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
        expected_path = f"{GOVERNOR_ATTEMPT_DIRECTORY}/{filename}"
        if (
            path.as_posix() != expected_path
            or filename not in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS
            or filename in seen
        ):
            raise ContractValidationError(
                "Governor reported an unsupported or duplicate artifact path"
            )
        seen.add(filename)
        name, native_contract = GOVERNOR_NATIVE_OUTPUT_ARTIFACTS[filename]
        artifacts.append(
            store.reference_existing_artifact(
                mission_id,
                relative_path=expected_path,
                name=name,
                producer="governor",
                schema_version=native_contract,
                observed_at=observed_at,
            )
        )
    return tuple(artifacts)


def _write_provenance_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    provenance: GovernorComponentProvenance,
    supporting_context: GovernorSupportingContext,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise GovernorInvocationError("stored mission request lacks mission_id")
    payload = canonical_json_bytes(
        {
            "schema_version": GOVERNOR_PROVENANCE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "supporting_context_id": supporting_context.context_id,
            "observed_at": observed_at,
            "component": provenance.to_dict(),
        }
    )
    return store.write_immutable_artifact(
        request.mission_id,
        relative_path=GOVERNOR_PROVENANCE_PATH,
        payload=payload,
        name="governor_provenance",
        producer="governor",
        schema_version=GOVERNOR_PROVENANCE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _write_lineage_artifact(
    store: MissionStore,
    request: MissionRequest,
    *,
    stage_inputs: Mapping[str, ArtifactReference],
    supporting_artifact: ArtifactReference,
    native_outputs: tuple[ArtifactReference, ...],
    provenance_artifact: ArtifactReference,
    snapshot: MissionSnapshot,
    governor_revision: str,
    observed_at: str,
) -> ArtifactReference:
    if request.mission_id is None:
        raise GovernorInvocationError("stored mission request lacks mission_id")
    oracle_revision = _component_revision(snapshot, "battlestar")
    council_revision = _component_revision(snapshot, "battlestar_council")
    input_entries: list[dict[str, Any]] = []
    for name, artifact in stage_inputs.items():
        native_contract = REQUIRED_GOVERNOR_INPUTS[name][2]
        revision = oracle_revision if name.startswith("oracle_") else council_revision
        input_entries.append(
            _lineage_entry(
                artifact,
                native_contract=native_contract,
                component_revision=revision,
                request=request,
            )
        )
    input_entries.append(
        _lineage_entry(
            supporting_artifact,
            native_contract=GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
            component_revision=f"sha256:{supporting_artifact.sha256}",
            request=request,
        )
    )
    native_contract_by_name = {
        artifact_name: native_contract
        for artifact_name, native_contract in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS.values()
    }
    output_entries = [
        _lineage_entry(
            artifact,
            native_contract=native_contract_by_name[artifact.name],
            component_revision=governor_revision,
            request=request,
        )
        for artifact in native_outputs
    ]
    output_entries.append(
        _lineage_entry(
            provenance_artifact,
            native_contract=GOVERNOR_PROVENANCE_SCHEMA_VERSION,
            component_revision=governor_revision,
            request=request,
        )
    )
    source_names = [*stage_inputs, "governor_supporting_context"]
    for entry in output_entries:
        entry["source_input_names"] = source_names
    payload = canonical_json_bytes(
        {
            "schema_version": GOVERNOR_LINEAGE_SCHEMA_VERSION,
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
        relative_path=GOVERNOR_LINEAGE_PATH,
        payload=payload,
        name="governor_lineage_manifest",
        producer="governor",
        schema_version=GOVERNOR_LINEAGE_SCHEMA_VERSION,
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


def _component_revision(snapshot: MissionSnapshot, component_name: str) -> str:
    component = snapshot.components.get(component_name)
    revision = getattr(component, "git_revision", None)
    if not isinstance(revision, str):
        raise GovernorPreconditionError(
            f"{component_name} component revision is missing"
        )
    return revision


def _validate_execution_correlation(
    result: GovernorExecutionResult,
    request: MissionRequest,
    provenance: GovernorComponentProvenance,
    *,
    supporting_context: GovernorSupportingContext,
) -> GovernorExecutionResult:
    if not isinstance(result, GovernorExecutionResult):
        raise ContractValidationError("Governor adapter returned an unsupported result")
    if (
        request.mission_id is None
        or result.mission_id != request.mission_id
        or result.request_id != request.request_id
        or result.symbol != request.symbol
        or result.run_mode is not request.run_mode
        or result.transport is not provenance.transport
        or result.context_id != supporting_context.context_id
    ):
        raise ContractValidationError(
            "Governor result correlation does not match the mission"
        )
    expected_paths = {
        f"{GOVERNOR_ATTEMPT_DIRECTORY}/{filename}"
        for filename in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS
    }
    produced_paths = set(result.produced_paths)
    if len(produced_paths) != len(result.produced_paths):
        raise ContractValidationError("Governor result contains duplicate artifact paths")
    if result.status is StageStatus.SUCCEEDED:
        expected_source_lineage = (
            *(REQUIRED_GOVERNOR_INPUTS[name][0] for name in REQUIRED_GOVERNOR_INPUTS),
            GOVERNOR_SUPPORTING_CONTEXT_PATH,
        )
        if result.native_disposition is None or result.failure is not None:
            raise ContractValidationError(
                "technically successful Governor result is incomplete"
            )
        if produced_paths != expected_paths:
            raise ContractValidationError(
                "technically successful Governor result lacks the canonical artifact set"
            )
        if result.source_lineage != expected_source_lineage:
            raise ContractValidationError(
                "technically successful Governor result misstates source lineage"
            )
    elif result.status is StageStatus.FAILED:
        if result.failure is None:
            raise ContractValidationError(
                "failed Governor result lacks a structured failure"
            )
        if not produced_paths.issubset(expected_paths):
            raise ContractValidationError(
                "failed Governor result contains unsupported artifact paths"
            )
    else:
        raise ContractValidationError(
            "Governor result status must be SUCCEEDED or FAILED"
        )
    return result


def _synthetic_failure(
    request: MissionRequest,
    transport: GovernorTransportKind,
    *,
    supporting_context: GovernorSupportingContext,
    code: str,
    error_type: str,
    message: str,
    resumable: bool,
    produced_paths: tuple[str, ...] = (),
) -> GovernorExecutionResult:
    return GovernorExecutionResult(
        mission_id=request.mission_id or "mission-correlation-missing",
        request_id=request.request_id,
        symbol=request.symbol,
        run_mode=request.run_mode,
        transport=transport,
        status=StageStatus.FAILED,
        native_disposition=None,
        readiness_state=None,
        decision_id=None,
        allowed_next_step=None,
        warnings=(),
        blocking_reasons=(),
        review_requirements=(),
        produced_paths=produced_paths,
        source_lineage=(),
        failure=GovernorFailure(
            code=code,
            error_type=_safe_error_type(error_type),
            message=message,
            resumable=resumable,
        ),
        context_id=supporting_context.context_id,
    )


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "GovernorWorkflowError"


def _observed_at(
    run_mode: RunMode,
    *,
    supporting_context: GovernorSupportingContext,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        candidate = supporting_context.generated_at
    else:
        current = clock() if clock is not None else datetime.now(UTC)
        candidate = format_rfc3339(current)
    if parse_rfc3339(candidate, "observed_at") < parse_rfc3339(
        not_before, "previous observed_at"
    ):
        return not_before
    return candidate


def _validate_completed_invocation(
    loaded: Any,
    *,
    provenance: GovernorComponentProvenance,
    supporting_sha256: str,
) -> tuple[str, str]:
    snapshot: MissionSnapshot = loaded.snapshot
    governor = snapshot.stages["governor"]
    disposition = governor.native_state
    expected_state = {
        "PROCEED": (CurrentPhase.OPERATOR, MissionOutcome.HELD, False, "PENDING_APPROVAL"),
        "HOLD": (CurrentPhase.OPERATOR, MissionOutcome.HELD, False, "PENDING_REVIEW"),
        "REVIEW_REQUIRED": (
            CurrentPhase.OPERATOR,
            MissionOutcome.HELD,
            False,
            "PENDING_REVIEW",
        ),
        "BLOCKED": (CurrentPhase.GOVERNOR, MissionOutcome.HELD, True, "CLOSED_BLOCKED"),
        "STAND_DOWN": (
            CurrentPhase.COMPLETE,
            MissionOutcome.VETOED,
            True,
            "CLOSED_NO_ACTION",
        ),
    }.get(disposition)
    if expected_state is None:
        raise GovernorStateConflictError(
            "completed Governor disposition is unsupported"
        )
    phase, outcome, terminal, route = expected_state
    operator = getattr(snapshot, "operator", None)
    if (
        governor.status is not StageStatus.SUCCEEDED
        or snapshot.current_phase is not phase
        or snapshot.mission_outcome is not outcome
        or snapshot.terminal is not terminal
        or snapshot.stages["navigator"].status is not StageStatus.NOT_STARTED
        or snapshot.components.get("battlestar_governor") != provenance
        or operator is None
        or operator.route != route
        or any(
            value is not None
            for value in (
                operator.action,
                operator.result,
                operator.operator_id,
                operator.acted_at,
            )
        )
    ):
        raise GovernorStateConflictError(
            "completed Governor state does not match this invocation"
        )
    artifacts = {item.name: item for item in snapshot.artifacts}
    supporting = artifacts.get("governor_supporting_context")
    expected_supporting_producer = (
        "harbormaster" if snapshot.run_mode is RunMode.REPLAY else "operator"
    )
    if (
        supporting is None
        or supporting.path != GOVERNOR_SUPPORTING_CONTEXT_PATH
        or supporting.sha256 != supporting_sha256
        or supporting.producer != expected_supporting_producer
        or supporting.schema_version != GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION
    ):
        raise GovernorStateConflictError(
            "Governor supporting context differs from the completed invocation"
        )
    expected_inputs = {*REQUIRED_GOVERNOR_INPUTS, "governor_supporting_context"}
    if set(governor.inputs) != expected_inputs:
        raise GovernorStateConflictError("completed Governor inputs are not canonical")
    expected_outputs = {
        *(value[0] for value in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS.values()),
        "governor_provenance",
        "governor_lineage_manifest",
    }
    if set(governor.outputs) != expected_outputs:
        raise GovernorStateConflictError("completed Governor outputs are not canonical")
    for filename, (artifact_name, contract) in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS.items():
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact.path != f"{GOVERNOR_ATTEMPT_DIRECTORY}/{filename}"
            or artifact.producer != "governor"
            or artifact.schema_version != contract
        ):
            raise GovernorStateConflictError(
                "completed Governor artifact provenance is not canonical"
            )
    for artifact_name, path, schema in (
        (
            "governor_provenance",
            GOVERNOR_PROVENANCE_PATH,
            GOVERNOR_PROVENANCE_SCHEMA_VERSION,
        ),
        (
            "governor_lineage_manifest",
            GOVERNOR_LINEAGE_PATH,
            GOVERNOR_LINEAGE_SCHEMA_VERSION,
        ),
    ):
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact.path != path
            or artifact.producer != "governor"
            or artifact.schema_version != schema
        ):
            raise GovernorStateConflictError(
                "completed Governor lineage or provenance is not canonical"
            )
    try:
        decision = load_strict_json_object(
            loaded.paths.mission_root / artifacts["governor_decision"].path
        )
        readiness = load_strict_json_object(
            loaded.paths.mission_root
            / artifacts["governor_decision_readiness"].path
        )
    except (OSError, ContractValidationError) as exc:
        raise GovernorStateConflictError(
            "completed Governor native outputs are malformed"
        ) from exc
    if decision.get("decision_state") != disposition:
        raise GovernorStateConflictError(
            "completed Governor decision disagrees with the snapshot"
        )
    readiness_state = readiness.get("readiness_state")
    allowed_next_step = decision.get("allowed_next_step")
    if not isinstance(readiness_state, str) or not isinstance(allowed_next_step, str):
        raise GovernorStateConflictError(
            "completed Governor summary fields are malformed"
        )
    return readiness_state, allowed_next_step
