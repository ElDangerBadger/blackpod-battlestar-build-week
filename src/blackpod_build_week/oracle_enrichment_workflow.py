"""Strict Oracle narrative enrichment through the local ModelDock appliance.

The workflow runs only after Battlestar Oracle has committed its typed facts.
Those immutable facts remain authoritative; ModelDock contributes one bounded,
validated explanatory narrative and provenance, never analytical state.
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .contracts import (
    ArtifactReference,
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    MODELDOCK_NARRATIVE_ARTIFACT_NAME,
    MODELDOCK_NARRATIVE_ARTIFACT_PATH,
    MODELDOCK_PROVENANCE_ARTIFACT_NAME,
    MODELDOCK_PROVENANCE_ARTIFACT_PATH,
    MODELDOCK_PROVENANCE_SCHEMA_VERSION as SNAPSHOT_MODELDOCK_PROVENANCE_SCHEMA_VERSION,
    MODELDOCK_REQUEST_ARTIFACT_NAME,
    MODELDOCK_REQUEST_ARTIFACT_PATH,
    MODELDOCK_REQUEST_SCHEMA_VERSION,
    MODELDOCK_RESPONSE_ARTIFACT_NAME,
    MODELDOCK_RESPONSE_ARTIFACT_PATH,
    MODELDOCK_RESPONSE_SCHEMA_VERSION as SNAPSHOT_MODELDOCK_RESPONSE_SCHEMA_VERSION,
    ModelDockCall,
    ModelDockCallStatus,
    ModelDockComponentProvenance,
    ModelDockTransportKind,
    RunMode,
    StageError,
    StageStatus,
)
from .contracts.mission_request import (
    format_rfc3339,
    parse_strict_json_object_bytes,
    parse_rfc3339,
)
from .contracts.oracle_narrative import (
    MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION,
    MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION,
    MODELDOCK_REPLAY_PACK_SCHEMA_VERSION,
    ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION,
    ORACLE_NARRATIVE_SCHEMA_VERSION,
    ModelDockReplayPack,
    OracleFactCatalog,
    OracleNarrative,
    OracleNarrativeRequest,
    OracleNarrativeSelection,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .mission_store import MissionPaths, MissionStore
from .mission_transitions import (
    begin_oracle_enrichment,
    complete_oracle_enrichment,
    fail_oracle_enrichment,
)
from .modeldock_client import (
    HttpResponse,
    ModelDockCallResult,
    ModelDockClient,
    ModelDockClientError,
)
from .modeldock_config import ModelDockConfig, load_modeldock_config


MODELDOCK_DIRECTORY = "oracle/modeldock"
MODELDOCK_REQUEST_PATH = MODELDOCK_REQUEST_ARTIFACT_PATH
MODELDOCK_RESPONSE_PATH = MODELDOCK_RESPONSE_ARTIFACT_PATH
MODELDOCK_NARRATIVE_PATH = MODELDOCK_NARRATIVE_ARTIFACT_PATH
MODELDOCK_PROVENANCE_PATH = MODELDOCK_PROVENANCE_ARTIFACT_PATH

MODELDOCK_REQUEST_ARTIFACT = MODELDOCK_REQUEST_ARTIFACT_NAME
MODELDOCK_RESPONSE_ARTIFACT = MODELDOCK_RESPONSE_ARTIFACT_NAME
MODELDOCK_NARRATIVE_ARTIFACT = MODELDOCK_NARRATIVE_ARTIFACT_NAME
MODELDOCK_PROVENANCE_ARTIFACT = MODELDOCK_PROVENANCE_ARTIFACT_NAME

MODELDOCK_REQUEST_CONTRACT = MODELDOCK_REQUEST_SCHEMA_VERSION
MODELDOCK_RESPONSE_SCHEMA_VERSION = SNAPSHOT_MODELDOCK_RESPONSE_SCHEMA_VERSION
MODELDOCK_PROVENANCE_SCHEMA_VERSION = SNAPSHOT_MODELDOCK_PROVENANCE_SCHEMA_VERSION
MODELDOCK_FAILURE_POLICY = "STRICT_REQUIRED"

_SAFE_MODELDOCK_METADATA = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$"
)
_SAFE_MODELDOCK_MODEL = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._@+/-]{0,255}$"
)
_MODELDOCK_SECRET_ASSIGNMENT = re.compile(
    r"(?:api[_-]?key|token|secret|password)\s*[:=]",
    re.IGNORECASE,
)

ORACLE_EVIDENCE_ARTIFACTS: Mapping[str, tuple[str, str]] = {
    "measurements": (
        "oracle_measurements",
        "oracle/attempt-0001/oracle_measurements_live.json",
    ),
    "diagnostics": (
        "oracle_measurement_diagnostics",
        "oracle/attempt-0001/oracle_measurement_diagnostics_live.json",
    ),
    "readiness": (
        "oracle_readiness_report",
        "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json",
    ),
    "assessment": (
        "oracle_assessment",
        "oracle/attempt-0001/oracle_assessment_live.json",
    ),
    "report": (
        "oracle_report",
        "oracle/attempt-0001/oracle_report_live.json",
    ),
}

_EVIDENCE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "measurements": (
        "measurement_id",
        "generated_at",
        "as_of",
        "dashboard_ready",
        "breadth_score",
        "cyclical_strength",
        "defensive_strength",
        "leadership_concentration",
        "risk_off_score",
        "risk_on_score",
        "rotation_velocity",
        "sector_dispersion",
        "symbols",
        "warnings",
        "blockers",
    ),
    "diagnostics": (
        "diagnostics_id",
        "measurement_id",
        "readiness_id",
        "normalized_snapshot_id",
        "generated_at",
        "diagnostics_state",
        "dashboard_ready",
        "provenance_complete",
        "symbols_used_count",
        "symbols_missing_count",
        "symbols_excluded_count",
        "fallback_count",
        "summary",
        "warnings",
        "blockers",
    ),
    "readiness": (
        "readiness_id",
        "normalized_snapshot_id",
        "fleet_id",
        "source_snapshot_id",
        "quality_report_id",
        "generated_at",
        "readiness_state",
        "downstream_ready",
        "dashboard_ready",
        "coverage_ok",
        "completeness_ok",
        "freshness_ok",
        "warnings",
        "blockers",
    ),
    "assessment": (
        "assessment_id",
        "measurement_id",
        "generated_at",
        "as_of",
        "breadth_posture",
        "leadership_posture",
        "rotation_posture",
        "risk_regime_posture",
        "confidence",
        "dashboard_ready",
        "warnings",
        "blockers",
    ),
    "report": (
        "report_id",
        "measurement_id",
        "measurements_id",
        "diagnostics_id",
        "assessment_id",
        "generated_at",
        "as_of",
        "headline",
        "summary",
        "breadth_posture",
        "leadership_posture",
        "rotation_posture",
        "risk_regime_posture",
        "diagnostics_state",
        "dashboard_ready",
        "assessment_summary",
        "key_measurements",
        "warnings",
        "blockers",
    ),
}


class OracleEnrichmentWorkflowError(RuntimeError):
    """Base class for Stage 2 Oracle narrative-enrichment failures."""


class OracleEnrichmentInvocationError(OracleEnrichmentWorkflowError):
    """Raised when CLI transport inputs conflict with a mission."""


class OracleEnrichmentPreconditionError(OracleEnrichmentWorkflowError):
    """Raised when authoritative Oracle evidence cannot be consumed safely."""


class OracleEnrichmentStateConflictError(OracleEnrichmentWorkflowError):
    """Raised when the immutable one-attempt restart policy blocks execution."""


class OracleEnrichmentAction(str, Enum):
    EXECUTED = "EXECUTED"
    NO_OP_ALREADY_SUCCEEDED = "NO_OP_ALREADY_SUCCEEDED"


@dataclass(frozen=True, slots=True)
class OracleEnrichmentSettings:
    mission_id: str
    artifacts_root: Path
    replay_fixture: Path | None = None


@dataclass(frozen=True, slots=True)
class OracleEnrichmentWorkflowResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: OracleEnrichmentAction
    modeldock_artifact_directory: Path
    narrative_artifact_path: str | None

    @property
    def call(self) -> ModelDockCall | None:
        calls = self.snapshot.stages["oracle"].modeldock_calls
        return calls[0] if calls else None


class ModelDockExecutor(Protocol):
    def generate_text(
        self,
        request_payload: Mapping[str, Any],
        *,
        mission_id: str,
        request_id: str,
        symbol: str,
        run_mode: object,
        content_validator: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> ModelDockCallResult: ...


ConfigLoader = Callable[..., ModelDockConfig]
Clock = Callable[[], datetime]


class ReplayModelDockTransport:
    """Single-use, network-free transport backed by a validated replay pack."""

    def __init__(
        self,
        *,
        endpoint: str,
        expected_request: Mapping[str, Any],
        response: Mapping[str, Any],
    ) -> None:
        self.endpoint = endpoint
        self.expected_request_bytes = canonical_json_bytes(dict(expected_request))
        self.response_bytes = canonical_json_bytes(dict(response))
        self.calls = 0

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse:
        del timeout_seconds
        self.calls += 1
        if self.calls != 1:
            raise RuntimeError("ModelDock replay transport permits exactly one call")
        if (
            method != "POST"
            or url != self.endpoint
            or headers.get("Content-Type") != "application/json; charset=utf-8"
            or body != self.expected_request_bytes
        ):
            raise RuntimeError("ModelDock replay request differs from its fixture")
        if len(self.response_bytes) > max_response_bytes:
            return HttpResponse(
                status=200,
                headers={"Content-Length": str(len(self.response_bytes))},
                body=self.response_bytes[: max_response_bytes + 1],
                complete=False,
            )
        return HttpResponse(
            status=200,
            headers={"Content-Length": str(len(self.response_bytes))},
            body=self.response_bytes,
            complete=True,
        )


def run_oracle_enrichment(
    settings: OracleEnrichmentSettings,
    *,
    environ: Mapping[str, str] | None = None,
    client: ModelDockExecutor | None = None,
    config_loader: ConfigLoader = load_modeldock_config,
    clock: Clock | None = None,
) -> OracleEnrichmentWorkflowResult:
    """Run or validate one strict ModelDock narrative-enrichment attempt."""

    config = config_loader(environ=environ)
    store = MissionStore(settings.artifacts_root)
    loaded = store.load_mission(settings.mission_id)
    replay_pack, replay_bytes = _load_replay_pack(
        loaded.request,
        settings.replay_fixture,
    )
    source_artifacts, evidence = _load_oracle_evidence(
        loaded.request,
        loaded.snapshot,
        loaded.paths.mission_root,
    )
    narrative_request = _build_narrative_request(
        loaded.request,
        loaded.snapshot,
        source_artifacts=source_artifacts,
        evidence=evidence,
    )
    fact_catalog = OracleFactCatalog.from_request(narrative_request)
    wire_request = _build_wire_request(config, narrative_request)
    if replay_pack is not None:
        _validate_replay_invocation(
            replay_pack,
            narrative_request=narrative_request,
            wire_request=wire_request,
        )
    provenance = _build_component_provenance(
        loaded.request,
        config,
        replay_pack=replay_pack,
        replay_bytes=replay_bytes,
    )

    oracle = loaded.snapshot.stages["oracle"]
    if oracle.modeldock_calls:
        completed = _validate_completed_invocation(
            loaded.request,
            loaded.snapshot,
            loaded.paths.mission_root,
            provenance=provenance,
            narrative_request=narrative_request,
            wire_request=wire_request,
        )
        return OracleEnrichmentWorkflowResult(
            request=loaded.request,
            snapshot=loaded.snapshot,
            paths=loaded.paths,
            action=OracleEnrichmentAction.NO_OP_ALREADY_SUCCEEDED,
            modeldock_artifact_directory=(
                loaded.paths.mission_root / MODELDOCK_DIRECTORY
            ),
            narrative_artifact_path=completed.path,
        )
    _validate_start_preconditions(loaded.request, loaded.snapshot)

    begin_observed_at = _observed_at(
        loaded.request.run_mode,
        replay_pack=replay_pack,
        clock=clock,
        not_before=loaded.snapshot.observed_at,
    )
    request_bytes = canonical_json_bytes(wire_request)
    request_artifact = store.write_immutable_artifact(
        settings.mission_id,
        relative_path=MODELDOCK_REQUEST_PATH,
        payload=request_bytes,
        name=MODELDOCK_REQUEST_ARTIFACT,
        producer="harbormaster",
        schema_version=MODELDOCK_REQUEST_CONTRACT,
        observed_at=begin_observed_at,
    )
    call_id = f"modeldock-call-{request_artifact.sha256[:24]}"
    running_call = ModelDockCall.from_mapping(
        {
            "call_id": call_id,
            "status": ModelDockCallStatus.RUNNING.value,
            "mission_id": loaded.snapshot.mission_id,
            "request_id": loaded.snapshot.request_id,
            "run_mode": loaded.snapshot.run_mode.value,
            "endpoint": config.endpoint("/text/generate"),
            "provider": None,
            "model": None,
            "model_revision": None,
            "trace_id": None,
            "mocked": None,
            "latency_ms": None,
            "request_sha256": request_artifact.sha256,
            "response_sha256": None,
            "response_byte_size": None,
            "started_at": begin_observed_at,
            "observed_at": begin_observed_at,
            "artifacts": [request_artifact.name],
            "error": None,
        }
    )
    running = begin_oracle_enrichment(
        loaded.snapshot,
        previous_snapshot_sha256=loaded.current_snapshot_sha256,
        observed_at=begin_observed_at,
        provenance=provenance,
        request_artifact=request_artifact,
        call=running_call,
    )
    running_digest = store.commit_snapshot(loaded.paths, running)

    try:
        executor = client or _build_client(
            config,
            replay_pack=replay_pack,
        )
        call_result = executor.generate_text(
            wire_request,
            mission_id=loaded.snapshot.mission_id,
            request_id=loaded.snapshot.request_id,
            symbol=loaded.request.symbol,
            run_mode=loaded.snapshot.run_mode,
            content_validator=lambda value: OracleNarrativeSelection.from_mapping(
                value
            ).expand(fact_catalog, narrative_request),
            content_requires_correlation=False,
        )
        _validate_call_result(
            call_result,
            request_artifact=request_artifact,
            narrative_request=narrative_request,
            replay_pack=replay_pack,
        )
    except KeyboardInterrupt:
        raise
    except ModelDockClientError as exc:
        return _commit_client_failure(
            store,
            loaded.request,
            loaded.paths,
            running,
            running_digest=running_digest,
            running_call=running_call,
            failure=exc.failure,
            narrative_request=narrative_request,
            source_artifacts=source_artifacts,
        )
    except Exception as exc:
        return _commit_unexpected_failure(
            store,
            loaded.request,
            loaded.paths,
            running,
            running_digest=running_digest,
            running_call=running_call,
            error_type=type(exc).__name__,
            narrative_request=narrative_request,
            source_artifacts=source_artifacts,
        )

    finish_observed_at = _coherent_timestamp(
        call_result.observed_at,
        not_before=running.observed_at,
    )
    response_artifact = store.write_immutable_artifact(
        settings.mission_id,
        relative_path=MODELDOCK_RESPONSE_PATH,
        payload=call_result.safe_response_bytes,
        name=MODELDOCK_RESPONSE_ARTIFACT,
        producer="modeldock",
        schema_version=MODELDOCK_RESPONSE_SCHEMA_VERSION,
        observed_at=finish_observed_at,
    )
    narrative = call_result.parsed_content
    if not isinstance(narrative, OracleNarrative):
        raise OracleEnrichmentWorkflowError(
            "validated ModelDock result did not preserve the narrative type"
        )
    narrative_artifact = store.write_immutable_artifact(
        settings.mission_id,
        relative_path=MODELDOCK_NARRATIVE_PATH,
        payload=narrative.canonical_json_bytes(),
        name=MODELDOCK_NARRATIVE_ARTIFACT,
        producer="modeldock",
        schema_version=ORACLE_NARRATIVE_SCHEMA_VERSION,
        observed_at=finish_observed_at,
    )
    provenance_payload = _success_provenance_payload(
        loaded.request,
        running_call=running_call,
        result=call_result,
        narrative_request=narrative_request,
        source_artifacts=source_artifacts,
        response_artifact=response_artifact,
        narrative_artifact=narrative_artifact,
        observed_at=finish_observed_at,
    )
    provenance_artifact = store.write_immutable_artifact(
        settings.mission_id,
        relative_path=MODELDOCK_PROVENANCE_PATH,
        payload=canonical_json_bytes(provenance_payload),
        name=MODELDOCK_PROVENANCE_ARTIFACT,
        producer="modeldock",
        schema_version=MODELDOCK_PROVENANCE_SCHEMA_VERSION,
        observed_at=finish_observed_at,
    )
    output_artifacts = (
        response_artifact,
        narrative_artifact,
        provenance_artifact,
    )
    succeeded_call = ModelDockCall.from_mapping(
        {
            **running_call.to_dict(),
            "status": ModelDockCallStatus.SUCCEEDED.value,
            "provider": call_result.provider,
            "model": call_result.model,
            "model_revision": call_result.model_revision,
            "trace_id": call_result.trace_id,
            "mocked": call_result.mocked,
            "latency_ms": call_result.latency_ms,
            "response_sha256": call_result.raw_response_sha256,
            "response_byte_size": call_result.response_byte_size,
            "observed_at": finish_observed_at,
            "artifacts": [
                request_artifact.name,
                *(artifact.name for artifact in output_artifacts),
            ],
            "error": None,
        }
    )
    final_snapshot = complete_oracle_enrichment(
        running,
        previous_snapshot_sha256=running_digest,
        observed_at=finish_observed_at,
        call=succeeded_call,
        output_artifacts=output_artifacts,
    )
    store.commit_snapshot(loaded.paths, final_snapshot)
    _validate_expected_snapshot(replay_pack, final_snapshot)
    return OracleEnrichmentWorkflowResult(
        request=loaded.request,
        snapshot=final_snapshot,
        paths=loaded.paths,
        action=OracleEnrichmentAction.EXECUTED,
        modeldock_artifact_directory=(
            loaded.paths.mission_root / MODELDOCK_DIRECTORY
        ),
        narrative_artifact_path=narrative_artifact.path,
    )


def _load_replay_pack(
    request: MissionRequest,
    fixture_path: Path | None,
) -> tuple[ModelDockReplayPack | None, bytes | None]:
    if request.run_mode is RunMode.LIVE:
        if fixture_path is not None:
            raise OracleEnrichmentInvocationError(
                "LIVE ModelDock enrichment rejects --replay-fixture"
            )
        return None, None
    if fixture_path is None:
        raise OracleEnrichmentInvocationError(
            "REPLAY ModelDock enrichment requires --replay-fixture and never calls LIVE"
        )
    path = Path(fixture_path)
    if path.is_symlink() or not path.is_file():
        raise OracleEnrichmentInvocationError(
            "ModelDock replay fixture must be a regular file"
        )
    try:
        payload = path.read_bytes()
        replay_pack = ModelDockReplayPack.from_json_bytes(payload)
    except OSError as exc:
        raise OracleEnrichmentInvocationError(
            "ModelDock replay fixture could not be read"
        ) from exc
    except ContractValidationError as exc:
        raise OracleEnrichmentInvocationError(
            "ModelDock replay fixture failed schema validation"
        ) from exc
    return replay_pack, payload


def _load_oracle_evidence(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    mission_root: Path,
) -> tuple[dict[str, ArtifactReference], dict[str, dict[str, Any]]]:
    try:
        resolved_mission_root = mission_root.resolve(strict=True)
    except OSError as exc:
        raise OracleEnrichmentPreconditionError(
            "mission root cannot be resolved safely"
        ) from exc
    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    output_names = set(snapshot.stages["oracle"].outputs)
    references: dict[str, ArtifactReference] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for evidence_name, (artifact_name, expected_path) in ORACLE_EVIDENCE_ARTIFACTS.items():
        artifact = artifacts.get(artifact_name)
        if (
            artifact is None
            or artifact_name not in output_names
            or artifact.path != expected_path
            or artifact.producer != "oracle"
            or artifact.byte_size is None
            or artifact.observed_at is None
        ):
            raise OracleEnrichmentPreconditionError(
                f"required Oracle artifact is missing or noncanonical: {artifact_name}"
            )
        target = mission_root / artifact.path
        try:
            resolved_target = target.resolve(strict=True)
            if (
                target.is_symlink()
                or not resolved_target.is_file()
                or not resolved_target.is_relative_to(resolved_mission_root)
            ):
                raise OSError("unsafe Oracle artifact path")
            payload = resolved_target.read_bytes()
        except OSError as exc:
            raise OracleEnrichmentPreconditionError(
                f"required Oracle artifact cannot be read safely: {artifact_name}"
            ) from exc
        if (
            len(payload) != artifact.byte_size
            or sha256_bytes(payload) != artifact.sha256
        ):
            raise OracleEnrichmentPreconditionError(
                f"required Oracle artifact failed integrity validation: {artifact_name}"
            )
        try:
            document = parse_strict_json_object_bytes(
                payload,
                document_name=artifact_name,
            )
        except ContractValidationError as exc:
            raise OracleEnrichmentPreconditionError(
                f"required Oracle artifact is malformed: {artifact_name}"
            ) from exc
        references[evidence_name] = artifact
        evidence[evidence_name] = _project_evidence(
            document,
            _EVIDENCE_FIELDS[evidence_name],
            artifact_name,
        )
    _validate_evidence_lineage(request, snapshot, evidence)
    return references, evidence


def _project_evidence(
    document: Mapping[str, Any],
    fields: tuple[str, ...],
    artifact_name: str,
) -> dict[str, Any]:
    missing = set(fields) - set(document)
    if missing:
        raise OracleEnrichmentPreconditionError(
            f"{artifact_name} lacks required fields: {', '.join(sorted(missing))}"
        )
    return {field: copy.deepcopy(document[field]) for field in fields}


def _validate_evidence_lineage(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    evidence: Mapping[str, Mapping[str, Any]],
) -> None:
    measurements = evidence["measurements"]
    diagnostics = evidence["diagnostics"]
    readiness = evidence["readiness"]
    assessment = evidence["assessment"]
    report = evidence["report"]
    measurement_id = measurements["measurement_id"]
    checks = (
        (diagnostics["measurement_id"], measurement_id),
        (assessment["measurement_id"], measurement_id),
        (report["measurement_id"], measurement_id),
        (report["measurements_id"], measurement_id),
        (report["diagnostics_id"], diagnostics["diagnostics_id"]),
        (report["assessment_id"], assessment["assessment_id"]),
        (diagnostics["readiness_id"], readiness["readiness_id"]),
        (
            diagnostics["normalized_snapshot_id"],
            readiness["normalized_snapshot_id"],
        ),
        (report["diagnostics_state"], diagnostics["diagnostics_state"]),
    )
    if any(actual != expected for actual, expected in checks):
        raise OracleEnrichmentPreconditionError(
            "Oracle narrative evidence lineage is inconsistent"
        )
    if (
        request.mission_id != snapshot.mission_id
        or request.request_id != snapshot.request_id
        or request.run_mode is not snapshot.run_mode
    ):
        raise OracleEnrichmentPreconditionError(
            "Oracle narrative mission correlation is inconsistent"
        )


def _build_narrative_request(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    *,
    source_artifacts: Mapping[str, ArtifactReference],
    evidence: Mapping[str, Mapping[str, Any]],
) -> OracleNarrativeRequest:
    native_state = snapshot.stages["oracle"].native_state
    if native_state is None:
        raise OracleEnrichmentPreconditionError(
            "successful Oracle stage lacks its native state"
        )
    warnings: list[str] = []
    for document in evidence.values():
        raw = document.get("warnings", [])
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise OracleEnrichmentPreconditionError(
                "Oracle warning evidence is malformed"
            )
        for warning in raw:
            if warning not in warnings:
                warnings.append(warning)
    return OracleNarrativeRequest.from_mapping(
        {
            "schema_version": ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION,
            "mission_id": snapshot.mission_id,
            "request_id": snapshot.request_id,
            "symbol": request.symbol,
            "run_mode": snapshot.run_mode.value,
            "oracle_native_state": native_state,
            **{name: copy.deepcopy(dict(value)) for name, value in evidence.items()},
            "warnings": warnings,
            "source_artifacts": {
                name: source_artifacts[name].to_dict()
                for name in ORACLE_EVIDENCE_ARTIFACTS
            },
        }
    )


def _build_wire_request(
    config: ModelDockConfig,
    narrative_request: OracleNarrativeRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "profile": config.profile,
        "model": config.model,
        "capabilities": ["text"],
        "response_format": {"type": "json"},
        "timeout": max(1, math.ceil(config.timeout_seconds)),
        "metadata": {
            "blackpod_correlation": {
                "mission_id": narrative_request.mission_id,
                "request_id": narrative_request.request_id,
                "symbol": narrative_request.symbol,
                "run_mode": narrative_request.run_mode.value,
            }
        },
        "prompt": narrative_request.build_prompt(),
        "max_tokens": 2048,
    }
    return payload


def _validate_replay_invocation(
    pack: ModelDockReplayPack,
    *,
    narrative_request: OracleNarrativeRequest,
    wire_request: Mapping[str, Any],
) -> None:
    if pack.oracle_input.to_dict() != narrative_request.to_dict():
        raise OracleEnrichmentInvocationError(
            "ModelDock replay Oracle input differs from this mission"
        )
    if pack.request != dict(wire_request):
        raise OracleEnrichmentInvocationError(
            "ModelDock replay wire request differs from this configuration"
        )


def _build_component_provenance(
    request: MissionRequest,
    config: ModelDockConfig,
    *,
    replay_pack: ModelDockReplayPack | None,
    replay_bytes: bytes | None,
) -> ModelDockComponentProvenance:
    replay = request.run_mode is RunMode.REPLAY
    return ModelDockComponentProvenance.from_mapping(
        {
            "endpoint": config.endpoint("/text/generate"),
            "profile": config.profile,
            "expected_provider": config.provider,
            "requested_model": config.model,
            "timeout_seconds": config.timeout_seconds,
            "max_response_bytes": config.max_response_bytes,
            "run_mode": request.run_mode.value,
            "transport": (
                ModelDockTransportKind.REPLAY_FIXTURE.value
                if replay
                else ModelDockTransportKind.LIVE_HTTP.value
            ),
            "replay_fixture_id": replay_pack.fixture_id if replay_pack else None,
            "replay_fixture_sha256": (
                sha256_bytes(replay_bytes) if replay_bytes is not None else None
            ),
            "failure_policy": MODELDOCK_FAILURE_POLICY,
        }
    )


def _validate_start_preconditions(
    request: MissionRequest,
    snapshot: MissionSnapshot,
) -> None:
    if request.mission_id != snapshot.mission_id:
        raise OracleEnrichmentPreconditionError(
            "mission correlation metadata is inconsistent"
        )
    oracle = snapshot.stages["oracle"]
    if oracle.status is not StageStatus.SUCCEEDED:
        if oracle.status is StageStatus.RUNNING:
            raise OracleEnrichmentStateConflictError(
                "Oracle is already RUNNING"
            )
        if oracle.status is StageStatus.FAILED:
            raise OracleEnrichmentStateConflictError(
                "Oracle previously FAILED and cannot be enriched"
            )
        raise OracleEnrichmentPreconditionError(
            "Oracle structured analysis must succeed before ModelDock"
        )
    if (
        snapshot.current_phase is not CurrentPhase.COUNCIL
        or snapshot.mission_outcome is not MissionOutcome.INCOMPLETE
        or snapshot.terminal
    ):
        raise OracleEnrichmentPreconditionError(
            "ModelDock enrichment requires the nonterminal COUNCIL boundary"
        )
    for stage_name in ("council", "governor", "navigator"):
        if snapshot.stages[stage_name].status is not StageStatus.NOT_STARTED:
            raise OracleEnrichmentPreconditionError(
                "ModelDock enrichment may not run after a downstream stage starts"
            )


def _build_client(
    config: ModelDockConfig,
    *,
    replay_pack: ModelDockReplayPack | None,
) -> ModelDockClient:
    if replay_pack is None:
        return ModelDockClient(config)
    timestamp = parse_rfc3339(replay_pack.observed_at, "replay observed_at")
    transport = ReplayModelDockTransport(
        endpoint=config.endpoint("/text/generate"),
        expected_request=replay_pack.request,
        response=replay_pack.response,
    )
    return ModelDockClient(
        config,
        transport=transport,
        monotonic=lambda: 0.0,
        now=lambda: timestamp,
    )


def _validate_call_result(
    result: ModelDockCallResult,
    *,
    request_artifact: ArtifactReference,
    narrative_request: OracleNarrativeRequest,
    replay_pack: ModelDockReplayPack | None,
) -> None:
    if not isinstance(result, ModelDockCallResult):
        raise ContractValidationError("ModelDock client returned an unsupported result")
    if result.request_sha256 != request_artifact.sha256:
        raise ContractValidationError("ModelDock request hash changed during transport")
    if not isinstance(result.parsed_content, OracleNarrative):
        raise ContractValidationError("ModelDock result lacks a typed narrative")
    result.parsed_content.validate_against(narrative_request)
    if replay_pack is not None:
        if result.parsed_content.to_dict() != replay_pack.expected_narrative.to_dict():
            raise ContractValidationError(
                "ModelDock replay narrative differs from the expected artifact"
            )
        actual_provenance = {
            "schema_version": MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION,
            "provider": result.provider,
            "model": result.model,
            "model_revision": result.model_revision,
            "trace_id": result.trace_id,
            "mocked": result.mocked,
        }
        if replay_pack.expected_provenance != actual_provenance:
            raise ContractValidationError(
                "ModelDock replay provenance differs from the expected result"
            )


def _success_provenance_payload(
    request: MissionRequest,
    *,
    running_call: ModelDockCall,
    result: ModelDockCallResult,
    narrative_request: OracleNarrativeRequest,
    source_artifacts: Mapping[str, ArtifactReference],
    response_artifact: ArtifactReference,
    narrative_artifact: ArtifactReference,
    observed_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": MODELDOCK_PROVENANCE_SCHEMA_VERSION,
        "mission_id": running_call.mission_id,
        "request_id": running_call.request_id,
        "symbol": request.symbol,
        "run_mode": running_call.run_mode.value,
        "call_id": running_call.call_id,
        "endpoint": running_call.endpoint,
        "status": ModelDockCallStatus.SUCCEEDED.value,
        "failure_policy": MODELDOCK_FAILURE_POLICY,
        "provider": result.provider,
        "model": result.model,
        "model_revision": result.model_revision,
        "trace_id": result.trace_id,
        "mocked": result.mocked,
        "latency_ms": result.latency_ms,
        "request_sha256": result.request_sha256,
        "raw_response_sha256": result.raw_response_sha256,
        "raw_response_byte_size": result.response_byte_size,
        "safe_response_sha256": response_artifact.sha256,
        "safe_response_byte_size": response_artifact.byte_size,
        "oracle_narrative_request_sha256": sha256_bytes(
            narrative_request.canonical_json_bytes()
        ),
        "started_at": running_call.started_at,
        "observed_at": observed_at,
        "source_artifacts": [
            source_artifacts[name].to_dict() for name in ORACLE_EVIDENCE_ARTIFACTS
        ],
        "output_artifacts": [
            response_artifact.to_dict(),
            narrative_artifact.to_dict(),
        ],
        "error": None,
    }


def _commit_client_failure(
    store: MissionStore,
    request: MissionRequest,
    paths: MissionPaths,
    running: MissionSnapshot,
    *,
    running_digest: str,
    running_call: ModelDockCall,
    failure: Any,
    narrative_request: OracleNarrativeRequest,
    source_artifacts: Mapping[str, ArtifactReference],
) -> OracleEnrichmentWorkflowResult:
    observed_at = _coherent_timestamp(
        failure.observed_at,
        not_before=running.observed_at,
    )
    response_artifacts: list[ArtifactReference] = []
    if failure.safe_response_bytes is not None:
        response_artifacts.append(
            store.write_immutable_artifact(
                running.mission_id,
                relative_path=MODELDOCK_RESPONSE_PATH,
                payload=failure.safe_response_bytes,
                name=MODELDOCK_RESPONSE_ARTIFACT,
                producer="modeldock",
                schema_version=MODELDOCK_RESPONSE_SCHEMA_VERSION,
                observed_at=observed_at,
            )
        )
    stage_error = StageError.from_mapping(
        {
            "code": _error_code(failure.code),
            "error_type": _safe_identifier(failure.error_type),
            "message": failure.message,
            "resumable": failure.resumable,
            "observed_at": observed_at,
        }
    )
    provenance_artifact = _write_failure_provenance(
        store,
        request,
        running_call=running_call,
        observed_at=observed_at,
        latency_ms=failure.latency_ms,
        raw_response_sha256=failure.raw_response_sha256,
        raw_response_byte_size=failure.response_byte_size,
        response_artifacts=tuple(response_artifacts),
        error=stage_error,
        narrative_request=narrative_request,
        source_artifacts=source_artifacts,
        safe_response=failure.safe_response,
    )
    outputs = (*response_artifacts, provenance_artifact)
    safe_response = failure.safe_response
    provider = _optional_safe_text(safe_response, "provider")
    model = _optional_safe_text(safe_response, "model")
    trace_id = _optional_safe_text(safe_response, "trace_id")
    mocked = (
        safe_response.get("mocked")
        if isinstance(safe_response, Mapping)
        and isinstance(safe_response.get("mocked"), bool)
        else None
    )
    failed_call = ModelDockCall.from_mapping(
        {
            **running_call.to_dict(),
            "status": ModelDockCallStatus.FAILED.value,
            "provider": provider,
            "model": model,
            "model_revision": None,
            "trace_id": trace_id,
            "mocked": mocked,
            "latency_ms": failure.latency_ms,
            "response_sha256": failure.raw_response_sha256,
            "response_byte_size": failure.response_byte_size,
            "observed_at": observed_at,
            "artifacts": [
                *running_call.artifacts,
                *(artifact.name for artifact in outputs),
            ],
            "error": stage_error.to_dict(),
        }
    )
    failed = fail_oracle_enrichment(
        running,
        previous_snapshot_sha256=running_digest,
        observed_at=observed_at,
        call=failed_call,
        error=stage_error,
        output_artifacts=outputs,
    )
    store.commit_snapshot(paths, failed)
    return OracleEnrichmentWorkflowResult(
        request=request,
        snapshot=failed,
        paths=paths,
        action=OracleEnrichmentAction.EXECUTED,
        modeldock_artifact_directory=paths.mission_root / MODELDOCK_DIRECTORY,
        narrative_artifact_path=None,
    )


def _commit_unexpected_failure(
    store: MissionStore,
    request: MissionRequest,
    paths: MissionPaths,
    running: MissionSnapshot,
    *,
    running_digest: str,
    running_call: ModelDockCall,
    error_type: str,
    narrative_request: OracleNarrativeRequest,
    source_artifacts: Mapping[str, ArtifactReference],
) -> OracleEnrichmentWorkflowResult:
    class SyntheticFailure:
        code = "workflow_failure"
        message = "ModelDock enrichment failed strict validation"
        resumable = False
        latency_ms = 0.0
        raw_response_sha256 = None
        response_byte_size = None
        safe_response = None
        safe_response_bytes = None
        observed_at = running.observed_at

    synthetic = SyntheticFailure()
    synthetic.error_type = error_type
    return _commit_client_failure(
        store,
        request,
        paths,
        running,
        running_digest=running_digest,
        running_call=running_call,
        failure=synthetic,
        narrative_request=narrative_request,
        source_artifacts=source_artifacts,
    )


def _write_failure_provenance(
    store: MissionStore,
    request: MissionRequest,
    *,
    running_call: ModelDockCall,
    observed_at: str,
    latency_ms: float,
    raw_response_sha256: str | None,
    raw_response_byte_size: int | None,
    response_artifacts: tuple[ArtifactReference, ...],
    error: StageError,
    narrative_request: OracleNarrativeRequest,
    source_artifacts: Mapping[str, ArtifactReference],
    safe_response: Mapping[str, Any] | None,
) -> ArtifactReference:
    provider = _optional_safe_text(safe_response, "provider")
    model = _optional_safe_text(safe_response, "model")
    trace_id = _optional_safe_text(safe_response, "trace_id")
    mocked = (
        safe_response.get("mocked")
        if isinstance(safe_response, Mapping)
        and isinstance(safe_response.get("mocked"), bool)
        else None
    )
    payload = canonical_json_bytes(
        {
            "schema_version": MODELDOCK_PROVENANCE_SCHEMA_VERSION,
            "mission_id": running_call.mission_id,
            "request_id": running_call.request_id,
            "symbol": request.symbol,
            "run_mode": running_call.run_mode.value,
            "call_id": running_call.call_id,
            "endpoint": running_call.endpoint,
            "status": ModelDockCallStatus.FAILED.value,
            "failure_policy": MODELDOCK_FAILURE_POLICY,
            "provider": provider,
            "model": model,
            "model_revision": None,
            "trace_id": trace_id,
            "mocked": mocked,
            "latency_ms": latency_ms,
            "request_sha256": running_call.request_sha256,
            "raw_response_sha256": raw_response_sha256,
            "raw_response_byte_size": raw_response_byte_size,
            "safe_response_sha256": (
                response_artifacts[0].sha256 if response_artifacts else None
            ),
            "safe_response_byte_size": (
                response_artifacts[0].byte_size if response_artifacts else None
            ),
            "oracle_narrative_request_sha256": sha256_bytes(
                narrative_request.canonical_json_bytes()
            ),
            "started_at": running_call.started_at,
            "observed_at": observed_at,
            "source_artifacts": [
                source_artifacts[name].to_dict()
                for name in ORACLE_EVIDENCE_ARTIFACTS
            ],
            "output_artifacts": [item.to_dict() for item in response_artifacts],
            "error": error.to_dict(),
        }
    )
    return store.write_immutable_artifact(
        running_call.mission_id,
        relative_path=MODELDOCK_PROVENANCE_PATH,
        payload=payload,
        name=MODELDOCK_PROVENANCE_ARTIFACT,
        producer="modeldock",
        schema_version=MODELDOCK_PROVENANCE_SCHEMA_VERSION,
        observed_at=observed_at,
    )


def _validate_completed_invocation(
    request: MissionRequest,
    snapshot: MissionSnapshot,
    mission_root: Path,
    *,
    provenance: ModelDockComponentProvenance,
    narrative_request: OracleNarrativeRequest,
    wire_request: Mapping[str, Any],
) -> ArtifactReference:
    calls = snapshot.stages["oracle"].modeldock_calls
    if len(calls) != 1:
        raise OracleEnrichmentStateConflictError(
            "completed enrichment lacks exactly one ModelDock call"
        )
    call = calls[0]
    if call.status is ModelDockCallStatus.RUNNING:
        raise OracleEnrichmentStateConflictError(
            "ModelDock enrichment is already RUNNING; it is not resumed or overwritten"
        )
    if call.status is ModelDockCallStatus.FAILED:
        raise OracleEnrichmentStateConflictError(
            "ModelDock enrichment previously FAILED; there is no retry option"
        )
    if (
        snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED
        or snapshot.current_phase is not CurrentPhase.COUNCIL
        or snapshot.stages["council"].status is not StageStatus.NOT_STARTED
        or snapshot.mission_outcome is not MissionOutcome.INCOMPLETE
        or snapshot.terminal
        or snapshot.components.get("modeldock") != provenance
    ):
        raise OracleEnrichmentStateConflictError(
            "completed ModelDock state does not match this invocation"
        )
    artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
    canonical = {
        MODELDOCK_REQUEST_ARTIFACT: (
            MODELDOCK_REQUEST_PATH,
            "harbormaster",
            MODELDOCK_REQUEST_CONTRACT,
        ),
        MODELDOCK_RESPONSE_ARTIFACT: (
            MODELDOCK_RESPONSE_PATH,
            "modeldock",
            MODELDOCK_RESPONSE_SCHEMA_VERSION,
        ),
        MODELDOCK_NARRATIVE_ARTIFACT: (
            MODELDOCK_NARRATIVE_PATH,
            "modeldock",
            ORACLE_NARRATIVE_SCHEMA_VERSION,
        ),
        MODELDOCK_PROVENANCE_ARTIFACT: (
            MODELDOCK_PROVENANCE_PATH,
            "modeldock",
            MODELDOCK_PROVENANCE_SCHEMA_VERSION,
        ),
    }
    for name, (path, producer, schema) in canonical.items():
        artifact = artifacts.get(name)
        if (
            artifact is None
            or artifact.path != path
            or artifact.producer != producer
            or artifact.schema_version != schema
            or name not in call.artifacts
        ):
            raise OracleEnrichmentStateConflictError(
                "completed ModelDock artifact set is not canonical"
            )
    request_artifact = artifacts[MODELDOCK_REQUEST_ARTIFACT]
    if (
        request_artifact.sha256 != sha256_bytes(canonical_json_bytes(dict(wire_request)))
        or request_artifact.sha256 != call.request_sha256
    ):
        raise OracleEnrichmentStateConflictError(
            "completed ModelDock request differs from this invocation"
        )
    narrative_artifact = artifacts[MODELDOCK_NARRATIVE_ARTIFACT]
    try:
        narrative = OracleNarrative.from_file(mission_root / narrative_artifact.path)
        narrative.validate_against(narrative_request)
    except (ContractValidationError, OSError) as exc:
        raise OracleEnrichmentStateConflictError(
            "completed ModelDock narrative failed revalidation"
        ) from exc
    return narrative_artifact


def _validate_expected_snapshot(
    replay_pack: ModelDockReplayPack | None,
    snapshot: MissionSnapshot,
) -> None:
    if replay_pack is None:
        return
    actual = {
        "schema_version": MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION,
        "oracle_status": snapshot.stages["oracle"].status.value,
        "modeldock_call_status": (
            snapshot.stages["oracle"].modeldock_calls[0].status.value
        ),
        "current_phase": snapshot.current_phase.value,
        "mission_outcome": snapshot.mission_outcome.value,
        "terminal": snapshot.terminal,
        "narrative_output": MODELDOCK_NARRATIVE_ARTIFACT,
    }
    if replay_pack.expected_snapshot_changes != actual:
        raise OracleEnrichmentWorkflowError(
            "ModelDock replay snapshot differs from its validated expectations"
        )


def _observed_at(
    run_mode: RunMode,
    *,
    replay_pack: ModelDockReplayPack | None,
    clock: Clock | None,
    not_before: str,
) -> str:
    if run_mode is RunMode.REPLAY:
        if replay_pack is None:
            raise AssertionError("REPLAY timestamp requires a replay pack")
        candidate = replay_pack.observed_at
    else:
        current = clock() if clock is not None else datetime.now(UTC)
        candidate = format_rfc3339(current)
    return _coherent_timestamp(candidate, not_before=not_before)


def _coherent_timestamp(value: str, *, not_before: str) -> str:
    candidate = parse_rfc3339(value, "observed_at")
    floor = parse_rfc3339(not_before, "previous observed_at")
    return format_rfc3339(floor if candidate < floor else candidate)


def _error_code(value: object) -> str:
    return _safe_identifier(f"MODELDOCK_{str(value).upper()}")


def _safe_identifier(value: object) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "ModelDockWorkflowError"


def _optional_safe_text(
    value: object,
    key: str,
) -> str | None:
    if not isinstance(value, Mapping):
        return None
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate or candidate != candidate.strip():
        return None
    pattern = _SAFE_MODELDOCK_MODEL if key == "model" else _SAFE_MODELDOCK_METADATA
    if not pattern.fullmatch(candidate):
        return None
    normalized = candidate.replace("\\", "/")
    parts = normalized.split("/")
    lowered = candidate.lower()
    if (
        candidate.startswith(("/", "~"))
        or "\\" in candidate
        or any(part in {"", ".", ".."} for part in parts)
        or "://" in candidate
        or re.match(r"^[A-Za-z]:", candidate)
        or lowered.startswith(("sk-", "sk_", "bearer"))
        or "-----begin" in lowered
        or _MODELDOCK_SECRET_ASSIGNMENT.search(candidate)
    ):
        return None
    return candidate


if MODELDOCK_REPLAY_PACK_SCHEMA_VERSION != "blackpod.modeldock_replay_pack.v1":
    raise RuntimeError("unexpected ModelDock replay contract version")
