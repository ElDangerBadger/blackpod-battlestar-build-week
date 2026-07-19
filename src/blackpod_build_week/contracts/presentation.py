"""Strict deterministic presentation contracts for one canonical mission."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_request import ContractValidationError, RunMode, normalize_rfc3339
from .mission_snapshot import (
    STAGE_NAMES,
    ApprovalScope,
    ArtifactReference,
    CurrentPhase,
    MissionOutcome,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    StageStatus,
)


CAPTAINS_LOG_SCHEMA_VERSION = "blackpod.captains_log.v1"
MISSION_SUMMARY_SCHEMA_VERSION = "blackpod.mission_summary.v1"
CAPTAINS_LOG_PATH = "presentation/captains_log.json"
CAPTAINS_LOG_MARKDOWN_PATH = "presentation/captains_log.md"
MISSION_SUMMARY_PATH = "presentation/mission_summary.json"
CANONICAL_SNAPSHOT_PATH = "mission_snapshot.json"

PRESENTATION_STAGES = (
    "HARBORMASTER",
    "ORACLE",
    "MODELDOCK",
    "COUNCIL",
    "GOVERNOR",
    "OPERATOR",
    "NAVIGATOR",
    "MISSION",
)

_STATUS_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SNAPSHOT_PATH_PATTERN = re.compile(
    r"^snapshots/mission_snapshot-r([0-9]{4,})\.json$"
)


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], name: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _text(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
    max_length: int = 1024,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank string")
    if value != value.strip():
        raise ContractValidationError(
            f"{field_name} may not have surrounding whitespace"
        )
    if len(value) > max_length:
        raise ContractValidationError(
            f"{field_name} exceeds {max_length} characters"
        )
    if any(ord(character) < 32 for character in value):
        raise ContractValidationError(f"{field_name} contains control characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(
            f"{field_name} must contain valid Unicode text"
        ) from exc
    return value


def _optional_token(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    token = str(_text(value, field_name, max_length=128))
    if not _STATUS_PATTERN.fullmatch(token):
        raise ContractValidationError(
            f"{field_name} must be an uppercase underscore-delimited token"
        )
    return token


def _enum_or_none(enum_type: type[Any], value: object, field_name: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be null or a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ContractValidationError(f"unsupported {field_name}: {value!r}") from exc


def _symbol(value: object) -> str:
    symbol = str(_text(value, "symbol", max_length=64))
    return symbol


def _snapshot_reference(
    value: object, *, mission_id: str, snapshot_count: int | None = None
) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise ContractValidationError("generated_from_snapshot must be an object")
    reference = ArtifactReference.from_mapping(value)
    match = _SNAPSHOT_PATH_PATTERN.fullmatch(reference.path)
    if (
        match is None
        or reference.name != f"mission_snapshot_r{int(match.group(1)):04d}"
        or reference.producer != "harbormaster"
        or reference.schema_version != "blackpod.mission_snapshot.v1"
        or reference.byte_size is None
        or reference.observed_at is None
    ):
        raise ContractValidationError(
            "generated_from_snapshot must reference one immutable canonical snapshot"
        )
    revision = int(match.group(1))
    if revision < 1 or (snapshot_count is not None and revision != snapshot_count):
        raise ContractValidationError(
            "generated snapshot revision must match snapshot_count"
        )
    expected_name = f"mission_snapshot_r{revision:04d}"
    if reference.name != expected_name or not mission_id:
        raise ContractValidationError("generated snapshot identity is inconsistent")
    return reference


@dataclass(frozen=True, slots=True)
class CaptainsLogEntry:
    stage: str
    timestamp: str
    status: str
    summary: str
    source_artifacts: tuple[ArtifactReference, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CaptainsLogEntry":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Captain's Log entry must be an object")
        _require_exact_fields(
            value,
            {"stage", "timestamp", "status", "summary", "source_artifacts"},
            "Captain's Log entry",
        )
        stage = value["stage"]
        if stage not in PRESENTATION_STAGES:
            raise ContractValidationError(f"unsupported Captain's Log stage: {stage!r}")
        status = _optional_token(value["status"], "Captain's Log status")
        if status is None:
            raise ContractValidationError("Captain's Log status may not be null")
        sources_value = value["source_artifacts"]
        if not isinstance(sources_value, list) or not sources_value:
            raise ContractValidationError(
                "Captain's Log entry requires at least one source artifact"
            )
        sources = tuple(ArtifactReference.from_mapping(item) for item in sources_value)
        if len({source.path for source in sources}) != len(sources):
            raise ContractValidationError(
                "Captain's Log source artifact paths must be unique per entry"
            )
        return cls(
            stage=stage,
            timestamp=normalize_rfc3339(
                value["timestamp"], "Captain's Log timestamp"
            ),
            status=status,
            summary=str(_text(value["summary"], "Captain's Log summary")),
            source_artifacts=sources,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "timestamp": self.timestamp,
            "status": self.status,
            "summary": self.summary,
            "source_artifacts": [source.to_dict() for source in self.source_artifacts],
        }


@dataclass(frozen=True, slots=True)
class CaptainsLog:
    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    generated_at: str
    generated_from_snapshot: ArtifactReference
    entries: tuple[CaptainsLogEntry, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CaptainsLog":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Captain's Log must be an object")
        _require_exact_fields(
            value,
            {
                "schema_version",
                "mission_id",
                "request_id",
                "symbol",
                "run_mode",
                "generated_at",
                "generated_from_snapshot",
                "entries",
            },
            "Captain's Log",
        )
        if value["schema_version"] != CAPTAINS_LOG_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported Captain's Log schema_version: {value['schema_version']!r}"
            )
        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        try:
            run_mode = RunMode(value["run_mode"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported Captain's Log run_mode") from exc
        entries_value = value["entries"]
        if not isinstance(entries_value, list) or len(entries_value) != len(
            PRESENTATION_STAGES
        ):
            raise ContractValidationError(
                "Captain's Log must contain each presentation stage exactly once"
            )
        entries = tuple(CaptainsLogEntry.from_mapping(item) for item in entries_value)
        if tuple(item.stage for item in entries) != PRESENTATION_STAGES:
            raise ContractValidationError(
                "Captain's Log entries must use canonical presentation order"
            )
        generated_at = normalize_rfc3339(
            value["generated_at"], "Captain's Log generated_at"
        )
        reference = _snapshot_reference(
            value["generated_from_snapshot"], mission_id=mission_id
        )
        if reference.observed_at != generated_at:
            raise ContractValidationError(
                "Captain's Log generated_at must equal its source snapshot timestamp"
            )
        return cls(
            schema_version=CAPTAINS_LOG_SCHEMA_VERSION,
            mission_id=mission_id,
            request_id=request_id,
            symbol=_symbol(value["symbol"]),
            run_mode=run_mode,
            generated_at=generated_at,
            generated_from_snapshot=reference,
            entries=entries,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "run_mode": self.run_mode.value,
            "generated_at": self.generated_at,
            "generated_from_snapshot": self.generated_from_snapshot.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class PresentationStageState:
    technical_status: StageStatus
    native_state: str | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], stage_name: str
    ) -> "PresentationStageState":
        if not isinstance(value, Mapping):
            raise ContractValidationError(f"summary stage {stage_name} must be an object")
        _require_exact_fields(
            value, {"technical_status", "native_state"}, f"summary stage {stage_name}"
        )
        try:
            status = StageStatus(value["technical_status"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                f"unsupported summary status for {stage_name}"
            ) from exc
        native_state = _text(
            value["native_state"],
            f"summary stage {stage_name} native_state",
            allow_none=True,
            max_length=128,
        )
        return cls(status, native_state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "technical_status": self.technical_status.value,
            "native_state": self.native_state,
        }


@dataclass(frozen=True, slots=True)
class PresentationModelDockState:
    status: str
    provider: str | None
    model: str | None
    trace_id: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PresentationModelDockState":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission summary ModelDock state must be an object")
        _require_exact_fields(
            value, {"status", "provider", "model", "trace_id"}, "ModelDock summary"
        )
        status = _optional_token(value["status"], "ModelDock summary status")
        if status not in {"NOT_RECORDED", "RUNNING", "SUCCEEDED", "FAILED"}:
            raise ContractValidationError("unsupported ModelDock summary status")
        provider = _text(value["provider"], "ModelDock provider", allow_none=True, max_length=256)
        model = _text(value["model"], "ModelDock model", allow_none=True, max_length=256)
        trace_id = _text(value["trace_id"], "ModelDock trace_id", allow_none=True, max_length=256)
        if status == "NOT_RECORDED" and any(
            item is not None for item in (provider, model, trace_id)
        ):
            raise ContractValidationError(
                "unrecorded ModelDock state may not contain response identity"
            )
        return cls(status, provider, model, trace_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True, slots=True)
class PresentationOperatorState:
    route: OperatorRoute | None
    action_status: OperatorActionStatus
    action: OperatorAction | None
    result: OperatorResult | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PresentationOperatorState":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission summary operator state must be an object")
        _require_exact_fields(
            value, {"route", "action_status", "action", "result"}, "operator summary"
        )
        try:
            action_status = OperatorActionStatus(value["action_status"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported operator action_status") from exc
        return cls(
            route=_enum_or_none(OperatorRoute, value["route"], "operator route"),
            action_status=action_status,
            action=_enum_or_none(OperatorAction, value["action"], "operator action"),
            result=_enum_or_none(OperatorResult, value["result"], "operator result"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": None if self.route is None else self.route.value,
            "action_status": self.action_status.value,
            "action": None if self.action is None else self.action.value,
            "result": None if self.result is None else self.result.value,
        }


@dataclass(frozen=True, slots=True)
class PresentationNavigatorState:
    technical_status: StageStatus
    native_state: str | None
    mode: NavigatorMode | None
    handoff_status: NavigatorHandoffStatus | None
    intake_status: NavigatorIntakeStatus | None
    plan_status: NavigatorPlanStatus | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PresentationNavigatorState":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission summary Navigator state must be an object")
        _require_exact_fields(
            value,
            {
                "technical_status",
                "native_state",
                "mode",
                "handoff_status",
                "intake_status",
                "plan_status",
            },
            "Navigator summary",
        )
        try:
            technical_status = StageStatus(value["technical_status"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported Navigator technical status") from exc
        return cls(
            technical_status=technical_status,
            native_state=_text(
                value["native_state"],
                "Navigator native_state",
                allow_none=True,
                max_length=128,
            ),
            mode=_enum_or_none(NavigatorMode, value["mode"], "Navigator mode"),
            handoff_status=_enum_or_none(
                NavigatorHandoffStatus, value["handoff_status"], "Navigator handoff_status"
            ),
            intake_status=_enum_or_none(
                NavigatorIntakeStatus, value["intake_status"], "Navigator intake_status"
            ),
            plan_status=_enum_or_none(
                NavigatorPlanStatus, value["plan_status"], "Navigator plan_status"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "technical_status": self.technical_status.value,
            "native_state": self.native_state,
            "mode": None if self.mode is None else self.mode.value,
            "handoff_status": (
                None if self.handoff_status is None else self.handoff_status.value
            ),
            "intake_status": (
                None if self.intake_status is None else self.intake_status.value
            ),
            "plan_status": None if self.plan_status is None else self.plan_status.value,
        }


@dataclass(frozen=True, slots=True)
class MissionSummary:
    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    generated_at: str
    generated_from_snapshot: ArtifactReference
    current_phase: CurrentPhase
    terminal: bool
    stages: dict[str, PresentationStageState]
    modeldock: PresentationModelDockState
    governor_disposition: str | None
    operator: PresentationOperatorState
    navigator: PresentationNavigatorState
    approval_scope: ApprovalScope | None
    final_outcome: MissionOutcome
    important_warnings: tuple[str, ...]
    snapshot_count: int
    canonical_snapshot_path: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionSummary":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission summary must be an object")
        fields = {
            "schema_version",
            "mission_id",
            "request_id",
            "symbol",
            "run_mode",
            "generated_at",
            "generated_from_snapshot",
            "current_phase",
            "terminal",
            "stages",
            "modeldock",
            "governor_disposition",
            "operator",
            "navigator",
            "approval_scope",
            "final_outcome",
            "important_warnings",
            "snapshot_count",
            "canonical_snapshot_path",
        }
        _require_exact_fields(value, fields, "mission summary")
        if value["schema_version"] != MISSION_SUMMARY_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported mission summary schema_version: {value['schema_version']!r}"
            )
        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
            run_mode = RunMode(value["run_mode"])
            current_phase = CurrentPhase(value["current_phase"])
            final_outcome = MissionOutcome(value["final_outcome"])
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("mission summary contains an unsupported enum") from exc
        snapshot_count = value["snapshot_count"]
        if (
            isinstance(snapshot_count, bool)
            or not isinstance(snapshot_count, int)
            or snapshot_count < 1
        ):
            raise ContractValidationError("snapshot_count must be a positive integer")
        stages_value = value["stages"]
        if not isinstance(stages_value, Mapping) or set(stages_value) != set(STAGE_NAMES):
            raise ContractValidationError("mission summary requires all five canonical stages")
        stages = {
            name: PresentationStageState.from_mapping(stages_value[name], name)
            for name in STAGE_NAMES
        }
        terminal = value["terminal"]
        if type(terminal) is not bool:
            raise ContractValidationError("mission summary terminal must be a boolean")
        warnings_value = value["important_warnings"]
        if not isinstance(warnings_value, list):
            raise ContractValidationError("important_warnings must be an array")
        warnings = tuple(
            str(_text(item, "important warning", max_length=512))
            for item in warnings_value
        )
        if len(set(warnings)) != len(warnings):
            raise ContractValidationError("important_warnings must be unique")
        if value["canonical_snapshot_path"] != CANONICAL_SNAPSHOT_PATH:
            raise ContractValidationError(
                "canonical_snapshot_path must be mission-relative mission_snapshot.json"
            )
        generated_at = normalize_rfc3339(
            value["generated_at"], "mission summary generated_at"
        )
        reference = _snapshot_reference(
            value["generated_from_snapshot"],
            mission_id=mission_id,
            snapshot_count=snapshot_count,
        )
        if reference.observed_at != generated_at:
            raise ContractValidationError(
                "mission summary generated_at must equal its source snapshot timestamp"
            )
        return cls(
            schema_version=MISSION_SUMMARY_SCHEMA_VERSION,
            mission_id=mission_id,
            request_id=request_id,
            symbol=_symbol(value["symbol"]),
            run_mode=run_mode,
            generated_at=generated_at,
            generated_from_snapshot=reference,
            current_phase=current_phase,
            terminal=terminal,
            stages=stages,
            modeldock=PresentationModelDockState.from_mapping(value["modeldock"]),
            governor_disposition=_text(
                value["governor_disposition"],
                "governor_disposition",
                allow_none=True,
                max_length=128,
            ),
            operator=PresentationOperatorState.from_mapping(value["operator"]),
            navigator=PresentationNavigatorState.from_mapping(value["navigator"]),
            approval_scope=_enum_or_none(
                ApprovalScope, value["approval_scope"], "approval_scope"
            ),
            final_outcome=final_outcome,
            important_warnings=warnings,
            snapshot_count=snapshot_count,
            canonical_snapshot_path=CANONICAL_SNAPSHOT_PATH,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "run_mode": self.run_mode.value,
            "generated_at": self.generated_at,
            "generated_from_snapshot": self.generated_from_snapshot.to_dict(),
            "current_phase": self.current_phase.value,
            "terminal": self.terminal,
            "stages": {name: self.stages[name].to_dict() for name in STAGE_NAMES},
            "modeldock": self.modeldock.to_dict(),
            "governor_disposition": self.governor_disposition,
            "operator": self.operator.to_dict(),
            "navigator": self.navigator.to_dict(),
            "approval_scope": (
                None if self.approval_scope is None else self.approval_scope.value
            ),
            "final_outcome": self.final_outcome.value,
            "important_warnings": list(self.important_warnings),
            "snapshot_count": self.snapshot_count,
            "canonical_snapshot_path": self.canonical_snapshot_path,
        }
