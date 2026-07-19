"""Narrow, deadline-controlled adapter for Battlestar's rendered Governor flow."""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .contracts import (
    ContractValidationError,
    GovernorTransportKind,
    MissionRequest,
    RunMode,
    StageStatus,
)
from .contracts.mission_request import normalize_rfc3339, parse_strict_json_object_bytes
from .identifiers import IdentifierError, validate_identifier, validate_mission_id


GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION = (
    "blackpod.governor_supporting_context.v1"
)
GOVERNOR_SUPPORTING_CONTEXT_RELATIVE_PATH = (
    "governor/inputs/governor_supporting_context.json"
)
GOVERNOR_RENDERED_DECISION_SCHEMA_VERSION = (
    "blackpod.governor_rendered_decision.v1"
)
GOVERNOR_WARNING_CLASSIFICATION_SCHEMA_VERSION = (
    "blackpod.governor_warning_classification.v1"
)
EXPECTED_GOVERNOR_OUTPUT_FILENAMES = (
    "governor_input_context.json",
    "governor_senate_intake.json",
    "governor_deliberation_prep.json",
    "governor_deliberation.json",
    "governor_decision_readiness.json",
    "governor_decision.json",
    "governor_rendered_decision.json",
    "secretary_outcome_summary.json",
    "warning_classification.json",
)
ALLOWED_GOVERNOR_DISPOSITIONS = frozenset(
    {"PROCEED", "HOLD", "STAND_DOWN", "BLOCKED", "REVIEW_REQUIRED"}
)
ALLOWED_GOVERNOR_READINESS_STATES = frozenset(
    {"READY", "REVIEW_REQUIRED", "BLOCKED", "INVALID"}
)

_REQUIRED_BATTLESTAR_MODULES = (
    Path("blackpod/advisors/mandate.py"),
    Path("blackpod/advisors/oracle_measurement_diagnostics.py"),
    Path("blackpod/advisors/secretary_outcomes.py"),
    Path("blackpod/advisors/senate_candidate_intake.py"),
    Path("blackpod/advisors/senate_deliberation.py"),
    Path("blackpod/advisors/trading_candidate_generator.py"),
    Path("blackpod/governor/governor_senate_intake.py"),
    Path("blackpod/governor/governor_deliberation_prep.py"),
    Path("blackpod/governor/governor_deliberation.py"),
    Path("blackpod/governor/governor_decision_readiness.py"),
    Path("blackpod/governor/governor_decision.py"),
)
_TRANSPORT_RESULT_FIELDS = frozenset(
    {
        "native_disposition",
        "readiness_state",
        "decision_id",
        "allowed_next_step",
        "produced_paths",
        "context_id",
        "warnings",
        "routine_warnings",
        "blocking_reasons",
        "review_requirements",
    }
)
_FORBIDDEN_CONTEXT_TERMS = (
    "buy",
    "sell",
    "enter",
    "exit",
    "forecast",
    "prediction",
    "recommend",
    "recommendation",
    "trade",
    "order",
    "execution",
    "executionintent",
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)


class GovernorReplayContractCase(str, Enum):
    NORMAL = "NORMAL"
    INVALID_STAND_DOWN = "INVALID_STAND_DOWN"


class GovernorAdapterValidationError(ValueError):
    """Raised before execution when adapter-owned configuration is invalid."""


class GovernorMalformedResultError(RuntimeError):
    """Raised when Battlestar returns malformed data or unsafe artifacts."""


class GovernorTransportTimeout(TimeoutError):
    """Raised when the isolated Governor worker exceeds its deadline."""


class GovernorRemoteExecutionError(RuntimeError):
    """A sanitized exception raised by Battlestar inside the worker process."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


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


def _strict_text(value: object, field_name: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank trimmed string")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    return value


@dataclass(frozen=True, slots=True)
class GovernorAccountabilityContext:
    outcomes: tuple[object, ...]
    notes: str

    @classmethod
    def from_mapping(cls, value: object) -> "GovernorAccountabilityContext":
        if not isinstance(value, Mapping):
            raise ContractValidationError("accountability must be an object")
        _require_exact_fields(value, {"outcomes", "notes"}, "accountability")
        outcomes = value["outcomes"]
        if not isinstance(outcomes, list) or outcomes:
            raise ContractValidationError(
                "accountability.outcomes must be an empty array in Phase 4"
            )
        notes = _strict_text(value["notes"], "accountability.notes")
        lowered = notes.lower()
        for term in _FORBIDDEN_CONTEXT_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                raise ContractValidationError(
                    f"accountability.notes contains unsupported Governor language: {term}"
                )
        return cls(outcomes=(), notes=notes)

    def to_dict(self) -> dict[str, object]:
        return {"outcomes": [], "notes": self.notes}


@dataclass(frozen=True, slots=True)
class GovernorSupportingContext:
    schema_version: str
    context_id: str
    mission_id: str
    request_id: str
    run_mode: RunMode
    generated_at: str
    accountability: GovernorAccountabilityContext
    replay_contract_case: GovernorReplayContractCase

    @classmethod
    def from_bytes(cls, payload: bytes) -> "GovernorSupportingContext":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                payload, document_name="Governor supporting context"
            )
        )

    @classmethod
    def from_mapping(cls, value: object) -> "GovernorSupportingContext":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Governor supporting context must be an object")
        _require_exact_fields(
            value,
            {
                "schema_version",
                "context_id",
                "mission_id",
                "request_id",
                "run_mode",
                "generated_at",
                "accountability",
                "replay_contract_case",
            },
            "Governor supporting context",
        )
        if value["schema_version"] != GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION:
            raise ContractValidationError(
                "unsupported Governor supporting context schema_version"
            )
        try:
            context_id = validate_identifier(value["context_id"], "context_id")
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
            run_mode = RunMode(value["run_mode"])
            contract_case = GovernorReplayContractCase(value["replay_contract_case"])
        except (IdentifierError, TypeError, ValueError) as exc:
            raise ContractValidationError(str(exc)) from exc
        if run_mode is RunMode.LIVE and contract_case is not GovernorReplayContractCase.NORMAL:
            raise ContractValidationError(
                "LIVE Governor context supports NORMAL replay_contract_case only"
            )
        return cls(
            schema_version=GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
            context_id=context_id,
            mission_id=mission_id,
            request_id=request_id,
            run_mode=run_mode,
            generated_at=normalize_rfc3339(value["generated_at"], "generated_at"),
            accountability=GovernorAccountabilityContext.from_mapping(
                value["accountability"]
            ),
            replay_contract_case=contract_case,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "context_id": self.context_id,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "run_mode": self.run_mode.value,
            "generated_at": self.generated_at,
            "accountability": self.accountability.to_dict(),
            "replay_contract_case": self.replay_contract_case.value,
        }


ReplayGovernorContext = GovernorSupportingContext


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GovernorAdapterValidationError(
            f"{field_name} must be a relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise GovernorAdapterValidationError(
            f"{field_name} must remain beneath the mission root"
        )
    return value


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class GovernorMissionContext:
    mission_id: str
    mission_root: Path
    oracle_report_path: str = "oracle/attempt-0001/oracle_report_live.json"
    oracle_diagnostics_path: str = (
        "oracle/attempt-0001/oracle_measurement_diagnostics_live.json"
    )
    oracle_readiness_path: str = (
        "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json"
    )
    council_synthesis_path: str = "council/attempt-0001/council_synthesis.json"
    council_summary_path: str = (
        "council/attempt-0001/council_executive_summary.json"
    )
    council_health_path: str = "council/attempt-0001/advisor_health_summary.json"
    candidate_path: str = "council/attempt-0001/trading_candidate_report.json"
    senate_review_path: str = "council/attempt-0001/senate_review_packet.json"
    senate_deliberation_path: str = "council/attempt-0001/senate_deliberation.json"
    mandate_path: str = "council/attempt-0001/mandate_policy.json"
    council_lineage_path: str = "council/attempt-0001/council_lineage_manifest.json"
    output_dir: str = "governor/attempt-0001"

    def __post_init__(self) -> None:
        try:
            mission_id = validate_mission_id(self.mission_id)
        except IdentifierError as exc:
            raise GovernorAdapterValidationError(str(exc)) from exc
        root_input = Path(self.mission_root)
        if not root_input.is_absolute():
            raise GovernorAdapterValidationError("mission_root must be absolute")
        if root_input.is_symlink() or not root_input.is_dir():
            raise GovernorAdapterValidationError(
                "mission_root must be an existing non-symlink directory"
            )
        root = root_input.resolve(strict=True)
        path_fields = (
            "oracle_report_path",
            "oracle_diagnostics_path",
            "oracle_readiness_path",
            "council_synthesis_path",
            "council_summary_path",
            "council_health_path",
            "candidate_path",
            "senate_review_path",
            "senate_deliberation_path",
            "mandate_path",
            "council_lineage_path",
            "output_dir",
        )
        values = {
            name: _validate_relative_path(getattr(self, name), name)
            for name in path_fields
        }
        output = (root / values["output_dir"]).resolve(strict=False)
        for name in path_fields[:-1]:
            candidate = (root / values[name]).resolve(strict=False)
            if not _is_relative_to(candidate, root) or _is_relative_to(candidate, output):
                raise GovernorAdapterValidationError(
                    "Governor input paths must remain beneath the mission root and outside output_dir"
                )
        if not _is_relative_to(output, root):
            raise GovernorAdapterValidationError(
                "Governor output_dir must remain beneath the mission root"
            )
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "mission_root", root)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def absolute(self, relative_path: str) -> Path:
        return self.mission_root.joinpath(*PurePosixPath(relative_path).parts)

    @property
    def input_paths(self) -> tuple[str, ...]:
        return (
            self.oracle_report_path,
            self.oracle_diagnostics_path,
            self.oracle_readiness_path,
            self.council_synthesis_path,
            self.council_summary_path,
            self.candidate_path,
            self.senate_review_path,
            self.senate_deliberation_path,
            self.mandate_path,
            self.council_health_path,
            self.council_lineage_path,
        )

    @property
    def output_absolute(self) -> Path:
        return self.absolute(self.output_dir)


@dataclass(frozen=True, slots=True)
class GovernorTransportRequest:
    battlestar_path: Path
    mission_root: Path
    oracle_report_path: str
    oracle_diagnostics_path: str
    oracle_readiness_path: str
    council_synthesis_path: str
    council_summary_path: str
    council_health_path: str
    candidate_path: str
    senate_review_path: str
    senate_deliberation_path: str
    mandate_path: str
    council_lineage_path: str
    output_dir: str
    supporting_context: dict[str, object]


class GovernorTransport(Protocol):
    def run(
        self, request: GovernorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]: ...


GovernorTransportCallable = Callable[
    [GovernorTransportRequest, float], Mapping[str, object]
]


@dataclass(frozen=True, slots=True)
class GovernorFailure:
    code: str
    error_type: str
    message: str
    resumable: bool


@dataclass(frozen=True, slots=True)
class GovernorExecutionResult:
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    transport: GovernorTransportKind
    status: StageStatus
    native_disposition: str | None
    readiness_state: str | None
    decision_id: str | None
    allowed_next_step: str | None
    produced_paths: tuple[str, ...]
    failure: GovernorFailure | None
    context_id: str
    warnings: tuple[str, ...] = ()
    routine_warnings: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    review_requirements: tuple[str, ...] = ()
    source_lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is StageStatus.SUCCEEDED:
            if (
                self.failure is not None
                or self.native_disposition not in ALLOWED_GOVERNOR_DISPOSITIONS
                or self.readiness_state not in ALLOWED_GOVERNOR_READINESS_STATES
                or not self.decision_id
                or not self.allowed_next_step
            ):
                raise ValueError(
                    "successful Governor result requires canonical native state, IDs, and no failure"
                )
        elif self.status is StageStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed Governor result requires a structured failure")
        else:
            raise ValueError("Governor result status must be SUCCEEDED or FAILED")


class ProcessGovernorTransport:
    """Execute Governor in a terminable spawned process with a hard deadline."""

    def run(
        self, request: GovernorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_governor_worker, args=(sender, request))
        process.start()
        sender.close()
        try:
            if not receiver.poll(deadline_seconds):
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                raise GovernorTransportTimeout(
                    f"Governor exceeded its {deadline_seconds:g}-second deadline"
                )
            try:
                envelope = receiver.recv()
            except EOFError as exc:
                raise GovernorMalformedResultError(
                    f"Governor worker exited without a result (exit code {process.exitcode})"
                ) from exc
        finally:
            receiver.close()
        process.join(timeout=2.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        if not isinstance(envelope, Mapping) or set(envelope) not in (
            {"ok", "result"},
            {"ok", "error_type", "message"},
        ):
            raise GovernorMalformedResultError(
                "Governor worker returned a malformed envelope"
            )
        if envelope["ok"] is True and isinstance(envelope.get("result"), Mapping):
            return envelope["result"]
        if envelope["ok"] is False:
            raise GovernorRemoteExecutionError(
                str(envelope["error_type"]), str(envelope["message"])
            )
        raise GovernorMalformedResultError("Governor worker envelope is malformed")


class GovernorAdapter:
    """Invoke Battlestar's current rendered Governor chain without new policy."""

    def __init__(
        self,
        battlestar_path: Path,
        *,
        transport: GovernorTransport | GovernorTransportCallable | None = None,
        deadline_seconds: float = 60.0,
    ) -> None:
        path_input = Path(battlestar_path)
        if not path_input.is_absolute() or not path_input.is_dir():
            raise GovernorAdapterValidationError(
                "Battlestar path must be an existing absolute directory"
            )
        path = path_input.resolve(strict=True)
        for relative in _REQUIRED_BATTLESTAR_MODULES:
            module = path / relative
            if module.is_symlink() or not module.is_file():
                raise GovernorAdapterValidationError(
                    f"Battlestar Governor module is missing: {relative.as_posix()}"
                )
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise GovernorAdapterValidationError(
                "deadline_seconds must be finite and positive"
            )
        self.battlestar_path = path
        self.transport = transport or ProcessGovernorTransport()
        self.deadline_seconds = float(deadline_seconds)

    def execute(
        self,
        request: MissionRequest,
        context: GovernorMissionContext,
        *,
        supporting_context: GovernorSupportingContext,
    ) -> GovernorExecutionResult:
        if not isinstance(request, MissionRequest):
            raise GovernorAdapterValidationError("request must be a MissionRequest")
        if not isinstance(context, GovernorMissionContext):
            raise GovernorAdapterValidationError(
                "context must be a GovernorMissionContext"
            )
        if not isinstance(supporting_context, GovernorSupportingContext):
            raise GovernorAdapterValidationError(
                "supporting_context must be validated"
            )
        transport_kind = (
            GovernorTransportKind.REPLAY_FIXTURE
            if request.run_mode is RunMode.REPLAY
            else GovernorTransportKind.LIVE_MISSION_INPUTS
        )
        correlation_error = self._correlation_error(
            request, context, supporting_context
        )
        if correlation_error is not None:
            return self._failure(
                request,
                context,
                supporting_context,
                transport_kind,
                code="GOVERNOR_CORRELATION_MISMATCH",
                error_type="CorrelationError",
                message=correlation_error,
                resumable=False,
            )
        if supporting_context.run_mode is not request.run_mode:
            return self._failure(
                request,
                context,
                supporting_context,
                transport_kind,
                code="GOVERNOR_MODE_MISMATCH",
                error_type="RunModeError",
                message="Governor supporting context run mode conflicts with mission",
                resumable=False,
            )
        path_error = self._validate_execution_paths(context)
        if path_error is not None:
            return self._failure(
                request,
                context,
                supporting_context,
                transport_kind,
                code=path_error[0],
                error_type=path_error[1],
                message=path_error[2],
                resumable=False,
            )
        invocation = GovernorTransportRequest(
            battlestar_path=self.battlestar_path,
            mission_root=context.mission_root,
            oracle_report_path=context.oracle_report_path,
            oracle_diagnostics_path=context.oracle_diagnostics_path,
            oracle_readiness_path=context.oracle_readiness_path,
            council_synthesis_path=context.council_synthesis_path,
            council_summary_path=context.council_summary_path,
            council_health_path=context.council_health_path,
            candidate_path=context.candidate_path,
            senate_review_path=context.senate_review_path,
            senate_deliberation_path=context.senate_deliberation_path,
            mandate_path=context.mandate_path,
            council_lineage_path=context.council_lineage_path,
            output_dir=context.output_dir,
            supporting_context=supporting_context.to_dict(),
        )
        try:
            raw = self._run_transport(invocation)
            parsed = self._validate_transport_result(
                raw, context, supporting_context
            )
            produced_paths = self._validate_complete_output_set(context)
            self._validate_committed_native_outputs(context, supporting_context, parsed)
        except GovernorTransportTimeout as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_context,
                transport_kind,
                "GOVERNOR_TIMEOUT",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        except GovernorRemoteExecutionError as exc:
            return self._failure(
                request,
                context,
                supporting_context,
                transport_kind,
                code="GOVERNOR_EXECUTION_FAILED",
                error_type=_safe_error_type(exc.error_type),
                message=_sanitize_message(
                    str(exc), self.battlestar_path, context.mission_root
                ),
                resumable=request.run_mode is RunMode.LIVE,
                produced_paths=self._discover_outputs(context),
            )
        except GovernorMalformedResultError as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_context,
                transport_kind,
                "GOVERNOR_MALFORMED_RESULT",
                exc,
                resumable=False,
            )
        except Exception as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_context,
                transport_kind,
                "GOVERNOR_EXECUTION_FAILED",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        return GovernorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport_kind,
            status=StageStatus.SUCCEEDED,
            native_disposition=parsed["native_disposition"],
            readiness_state=parsed["readiness_state"],
            decision_id=parsed["decision_id"],
            allowed_next_step=parsed["allowed_next_step"],
            produced_paths=produced_paths,
            failure=None,
            context_id=parsed["context_id"],
            warnings=parsed["warnings"],
            routine_warnings=parsed["routine_warnings"],
            blocking_reasons=parsed["blocking_reasons"],
            review_requirements=parsed["review_requirements"],
            source_lineage=(
                *context.input_paths,
                GOVERNOR_SUPPORTING_CONTEXT_RELATIVE_PATH,
            ),
        )

    @staticmethod
    def _correlation_error(
        request: MissionRequest,
        context: GovernorMissionContext,
        supporting: GovernorSupportingContext,
    ) -> str | None:
        if request.mission_id != context.mission_id:
            return "request mission_id does not match Governor context"
        if supporting.mission_id != context.mission_id:
            return "supporting context mission_id does not match Governor context"
        if supporting.request_id != request.request_id:
            return "supporting context request_id does not match mission request"
        return None

    def _run_transport(
        self, request: GovernorTransportRequest
    ) -> Mapping[str, object]:
        runner = getattr(self.transport, "run", None)
        if callable(runner):
            return runner(request, deadline_seconds=self.deadline_seconds)
        if callable(self.transport):
            return self.transport(request, self.deadline_seconds)
        raise GovernorAdapterValidationError("Governor transport is not callable")

    def _validate_execution_paths(
        self, context: GovernorMissionContext
    ) -> tuple[str, str, str] | None:
        for relative in context.input_paths:
            path = context.absolute(relative)
            if (
                path.is_symlink()
                or not path.is_file()
                or not _is_relative_to(path.resolve(strict=True), context.mission_root)
            ):
                return (
                    "GOVERNOR_INPUT_INVALID",
                    "PathValidationError",
                    "Governor requires contained regular mission input artifacts",
                )
        output = context.output_absolute
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                return (
                    "GOVERNOR_OUTPUT_INVALID",
                    "PathValidationError",
                    "Governor output path must be a contained directory",
                )
            try:
                if any(output.iterdir()):
                    return (
                        "GOVERNOR_IMMUTABLE_COLLISION",
                        "ArtifactCollisionError",
                        "Governor output directory contains immutable artifacts",
                    )
            except OSError:
                return (
                    "GOVERNOR_OUTPUT_INVALID",
                    "PathValidationError",
                    "Governor output directory cannot be inspected",
                )
        return None

    def _validate_transport_result(
        self,
        raw: object,
        context: GovernorMissionContext,
        supporting: GovernorSupportingContext,
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise GovernorMalformedResultError("Governor return must be an object")
        if set(raw) != _TRANSPORT_RESULT_FIELDS:
            raise GovernorMalformedResultError(
                "Governor return fields do not match the supported contract"
            )
        parsed: dict[str, Any] = {}
        for name in (
            "native_disposition",
            "readiness_state",
            "decision_id",
            "allowed_next_step",
            "context_id",
        ):
            value = raw[name]
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise GovernorMalformedResultError(
                    f"Governor return {name} must be a nonblank string"
                )
            parsed[name] = value
        if parsed["native_disposition"] not in ALLOWED_GOVERNOR_DISPOSITIONS:
            raise GovernorMalformedResultError(
                "Governor returned an unsupported rendered disposition"
            )
        if parsed["readiness_state"] not in ALLOWED_GOVERNOR_READINESS_STATES:
            raise GovernorMalformedResultError(
                "Governor returned an unsupported readiness state"
            )
        if parsed["context_id"] != supporting.context_id:
            raise GovernorMalformedResultError(
                "Governor returned the wrong supporting context ID"
            )
        paths = raw["produced_paths"]
        if not isinstance(paths, (list, tuple)):
            raise GovernorMalformedResultError(
                "Governor produced_paths must be an array"
            )
        parsed["produced_paths"] = tuple(
            _validate_native_relative_path(item) for item in paths
        )
        expected = tuple(
            f"{context.output_dir}/{name}"
            for name in EXPECTED_GOVERNOR_OUTPUT_FILENAMES
        )
        if parsed["produced_paths"] != expected:
            raise GovernorMalformedResultError(
                "Governor return does not declare the canonical artifact set"
            )
        for name in (
            "warnings",
            "routine_warnings",
            "blocking_reasons",
            "review_requirements",
        ):
            parsed[name] = _text_tuple(raw[name], f"Governor return {name}")
        return parsed

    def _validate_complete_output_set(
        self, context: GovernorMissionContext
    ) -> tuple[str, ...]:
        found = self._discover_outputs(context, reject_unsafe=True)
        expected = tuple(
            f"{context.output_dir}/{name}"
            for name in EXPECTED_GOVERNOR_OUTPUT_FILENAMES
        )
        if set(found) != set(expected):
            raise GovernorMalformedResultError(
                "Governor output set is incomplete or unsupported"
            )
        return expected

    def _validate_committed_native_outputs(
        self,
        context: GovernorMissionContext,
        supporting: GovernorSupportingContext,
        parsed: Mapping[str, Any],
    ) -> None:
        try:
            input_context = _read_json(
                context.output_absolute / "governor_input_context.json"
            )
            prep = _read_json(
                context.output_absolute / "governor_deliberation_prep.json"
            )
            deliberation = _read_json(
                context.output_absolute / "governor_deliberation.json"
            )
            readiness = _read_json(
                context.output_absolute / "governor_decision_readiness.json"
            )
            decision = _read_json(
                context.output_absolute / "governor_decision.json"
            )
            rendered = _read_json(
                context.output_absolute / "governor_rendered_decision.json"
            )
            secretary = _read_json(
                context.output_absolute / "secretary_outcome_summary.json"
            )
            classification = _read_json(
                context.output_absolute / "warning_classification.json"
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise GovernorMalformedResultError(
                "Governor artifacts are not valid JSON objects"
            ) from exc
        checks = (
            (input_context.get("context_id"), supporting.context_id),
            (input_context.get("mission_id"), supporting.mission_id),
            (input_context.get("request_id"), supporting.request_id),
            (prep.get("secretary_summary_id"), secretary.get("summary_id")),
            (deliberation.get("prep_id"), prep.get("prep_id")),
            (readiness.get("deliberation_id"), deliberation.get("deliberation_id")),
            (readiness.get("readiness_state"), parsed["readiness_state"]),
            (decision.get("deliberation_id"), deliberation.get("deliberation_id")),
            (decision.get("readiness_id"), readiness.get("readiness_id")),
            (decision.get("decision_id"), parsed["decision_id"]),
            (decision.get("decision_state"), parsed["native_disposition"]),
            (decision.get("allowed_next_step"), parsed["allowed_next_step"]),
            (decision.get("decision_status"), "RENDERED"),
            (decision.get("warnings"), list(parsed["warnings"])),
            (decision.get("blockers"), list(parsed["blocking_reasons"])),
            (rendered.get("schema_version"), GOVERNOR_RENDERED_DECISION_SCHEMA_VERSION),
            (rendered.get("decision_id"), parsed["decision_id"]),
            (rendered.get("disposition"), parsed["native_disposition"]),
            (rendered.get("mission_id"), supporting.mission_id),
            (rendered.get("request_id"), supporting.request_id),
            (rendered.get("warnings"), list(parsed["warnings"])),
            (rendered.get("routine_warnings"), list(parsed["routine_warnings"])),
            (
                rendered.get("blocking_reasons"),
                list(parsed["blocking_reasons"]),
            ),
            (
                rendered.get("review_requirements"),
                list(parsed["review_requirements"]),
            ),
            (
                classification.get("schema_version"),
                GOVERNOR_WARNING_CLASSIFICATION_SCHEMA_VERSION,
            ),
            (classification.get("routine_warnings"), list(parsed["routine_warnings"])),
            (classification.get("decision_warnings"), list(parsed["warnings"])),
        )
        if any(actual != expected for actual, expected in checks):
            raise GovernorMalformedResultError(
                "Governor native artifact correlation is inconsistent"
            )
        serialized = "\n".join(
            json.dumps(value)
            for value in (
                input_context,
                prep,
                deliberation,
                readiness,
                decision,
                rendered,
                secretary,
                classification,
            )
        )
        if str(context.mission_root) in serialized or str(self.battlestar_path) in serialized:
            raise GovernorMalformedResultError(
                "Governor artifacts leaked an absolute local path"
            )

    def _discover_outputs(
        self, context: GovernorMissionContext, *, reject_unsafe: bool = False
    ) -> tuple[str, ...]:
        output = context.output_absolute
        if not output.is_dir() or output.is_symlink():
            return ()
        found: list[str] = []
        try:
            for candidate in sorted(output.rglob("*"), key=lambda item: item.as_posix()):
                if candidate.is_symlink() or not candidate.is_file():
                    if reject_unsafe and not candidate.is_dir():
                        raise GovernorMalformedResultError(
                            "Governor output contains an unsafe artifact"
                        )
                    continue
                resolved = candidate.resolve(strict=True)
                if not _is_relative_to(resolved, context.mission_root):
                    if reject_unsafe:
                        raise GovernorMalformedResultError(
                            "Governor artifact escaped the mission root"
                        )
                    continue
                found.append(candidate.relative_to(context.mission_root).as_posix())
        except OSError as exc:
            if reject_unsafe:
                raise GovernorMalformedResultError(
                    "Governor outputs cannot be inspected"
                ) from exc
        order = {
            f"{context.output_dir}/{name}": index
            for index, name in enumerate(EXPECTED_GOVERNOR_OUTPUT_FILENAMES)
        }
        return tuple(sorted(found, key=lambda value: order.get(value, 999)))

    def _failure_from_exception(
        self,
        request: MissionRequest,
        context: GovernorMissionContext,
        supporting: GovernorSupportingContext,
        transport: GovernorTransportKind,
        code: str,
        exc: Exception,
        *,
        resumable: bool,
    ) -> GovernorExecutionResult:
        return self._failure(
            request,
            context,
            supporting,
            transport,
            code=code,
            error_type=_safe_error_type(type(exc).__name__),
            message=_sanitize_message(
                str(exc), self.battlestar_path, context.mission_root
            ),
            resumable=resumable,
            produced_paths=self._discover_outputs(context),
        )

    @staticmethod
    def _failure(
        request: MissionRequest,
        context: GovernorMissionContext,
        supporting: GovernorSupportingContext,
        transport: GovernorTransportKind,
        *,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        produced_paths: tuple[str, ...] = (),
    ) -> GovernorExecutionResult:
        return GovernorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport,
            status=StageStatus.FAILED,
            native_disposition=None,
            readiness_state=None,
            decision_id=None,
            allowed_next_step=None,
            produced_paths=produced_paths,
            failure=GovernorFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=message or "Governor execution failed",
                resumable=resumable,
            ),
            context_id=supporting.context_id,
        )


def _governor_worker(sender: Any, request: GovernorTransportRequest) -> None:
    try:
        result = _run_native_governor(request)
        sender.send({"ok": True, "result": result})
    except BaseException as exc:
        try:
            sender.send(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "message": _sanitize_message(
                        str(exc), request.battlestar_path, request.mission_root
                    ),
                }
            )
        except Exception:
            pass
    finally:
        sender.close()


def _run_native_governor(request: GovernorTransportRequest) -> dict[str, object]:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    battlestar_root = request.battlestar_path.resolve(strict=True)
    mission_root = request.mission_root.resolve(strict=True)
    sys.path.insert(0, str(battlestar_root))
    prior_cwd = Path.cwd()
    os.chdir(mission_root)
    try:
        import blackpod.advisors.mandate as mandate_module
        import blackpod.advisors.oracle_measurement_diagnostics as diagnostics_module
        import blackpod.advisors.secretary_outcomes as secretary_module
        import blackpod.advisors.senate_candidate_intake as review_module
        import blackpod.advisors.senate_deliberation as senate_module
        import blackpod.advisors.trading_candidate_generator as candidate_module
        import blackpod.governor.governor_decision as decision_module
        import blackpod.governor.governor_decision_readiness as readiness_module
        import blackpod.governor.governor_deliberation as deliberation_module
        import blackpod.governor.governor_deliberation_prep as prep_module
        import blackpod.governor.governor_senate_intake as intake_module
        from blackpod.advisors.base import AdvisorContext
        from blackpod.contracts import GovernorDeliberation, MandateStatus

        for module in (
            mandate_module,
            diagnostics_module,
            secretary_module,
            review_module,
            senate_module,
            candidate_module,
            decision_module,
            readiness_module,
            deliberation_module,
            prep_module,
            intake_module,
        ):
            _require_module_origin(module, battlestar_root)

        supporting = GovernorSupportingContext.from_mapping(
            request.supporting_context
        )
        output = Path(request.output_dir)
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise GovernorMalformedResultError(
                "reserved Governor output directory is missing or nonempty"
            )

        oracle_payload = _read_json(Path(request.oracle_report_path))
        diagnostics_payload = _read_json(Path(request.oracle_diagnostics_path))
        readiness_payload = _read_json(Path(request.oracle_readiness_path))
        synthesis_payload = _read_json(Path(request.council_synthesis_path))
        summary_payload = _read_json(Path(request.council_summary_path))
        health_payload = _read_json(Path(request.council_health_path))
        lineage_payload = _read_json(Path(request.council_lineage_path))
        oracle_report = senate_module.load_oracle_report(request.oracle_report_path)
        candidate = candidate_module.load_trading_candidate_report(
            request.candidate_path
        )
        review = review_module.load_senate_review_packet(request.senate_review_path)
        senate = senate_module.load_senate_deliberation(
            request.senate_deliberation_path
        )
        _validate_input_correlation(
            supporting,
            oracle_payload,
            diagnostics_payload,
            readiness_payload,
            synthesis_payload,
            summary_payload,
            health_payload,
            lineage_payload,
            candidate,
            review,
            senate,
        )

        advisor_context = AdvisorContext(
            as_of=supporting.generated_at,
            root=Path("."),
            stale_days=0,
        )
        mandate_artifact = mandate_module.MandateAdvisor(
            request.mandate_path
        ).run(advisor_context)
        mandate_module.MandateAdvisor(request.mandate_path).validate(
            mandate_artifact
        )
        mandates = tuple(
            item for item in mandate_artifact.payload if isinstance(item, MandateStatus)
        )
        if len(mandates) != 1:
            raise GovernorMalformedResultError(
                "native Mandate validation did not return one MandateStatus"
            )
        mandate_status = mandates[0]

        secretary = secretary_module.build_secretary_outcome_summary(
            supporting.accountability.outcomes,
            generated_at=supporting.generated_at,
            notes=supporting.accountability.notes,
        )
        secretary_path = output / "secretary_outcome_summary.json"
        _write_json_exclusive(secretary_path, secretary.to_dict())

        routine_warnings, decision_warnings = _classify_oracle_warnings(
            tuple(oracle_report.warnings), diagnostics_module
        )
        filtered_oracle = replace(oracle_report, warnings=decision_warnings)
        filtered_senate = replace(
            senate,
            warnings=tuple(
                warning for warning in senate.warnings if warning not in set(routine_warnings)
            ),
        )
        classification = {
            "schema_version": GOVERNOR_WARNING_CLASSIFICATION_SCHEMA_VERSION,
            "classifier": (
                "blackpod.advisors.oracle_measurement_diagnostics._is_diagnostic_warning"
            ),
            "all_oracle_warnings": list(oracle_report.warnings),
            "routine_warnings": list(routine_warnings),
            "decision_warnings": list(decision_warnings),
            "preserved": True,
        }
        classification_path = output / "warning_classification.json"

        intake = intake_module.build_governor_senate_intake(
            filtered_senate,
            filtered_oracle,
            generated_at=supporting.generated_at,
        )
        intake_path = output / "governor_senate_intake.json"
        _write_json_exclusive(intake_path, intake.to_dict())

        mandate_context = _mandate_context(mandate_status, supporting.context_id)
        council_context = dict(summary_payload)
        council_context["warnings"] = list(
            summary_payload.get("notable_warnings", ()) or ()
        )
        council_context["blockers"] = list(
            summary_payload.get("notable_blockers", ()) or ()
        )
        input_context = {
            "schema_version": "blackpod.governor_input_context.v1",
            "context_id": supporting.context_id,
            "mission_id": supporting.mission_id,
            "request_id": supporting.request_id,
            "run_mode": supporting.run_mode.value,
            "generated_at": supporting.generated_at,
            "replay_contract_case": supporting.replay_contract_case.value,
            "inputs": {
                "oracle_report": request.oracle_report_path,
                "oracle_diagnostics": request.oracle_diagnostics_path,
                "oracle_readiness": request.oracle_readiness_path,
                "council_synthesis": request.council_synthesis_path,
                "council_executive_summary": request.council_summary_path,
                "council_advisor_health": request.council_health_path,
                "candidate_evidence": request.candidate_path,
                "senate_review": request.senate_review_path,
                "senate_deliberation": request.senate_deliberation_path,
                "mandate": request.mandate_path,
                "council_lineage": request.council_lineage_path,
            },
            "native_ids": {
                "oracle_report_id": oracle_report.report_id,
                "council_synthesis_id": synthesis_payload.get("synthesis_id"),
                "council_summary_id": summary_payload.get("summary_id"),
                "candidate_report_id": candidate.report_id,
                "senate_review_packet_id": review.packet_id,
                "senate_deliberation_id": senate.deliberation_id,
                "secretary_summary_id": secretary.summary_id,
                "mandate_id": mandate_context["mandate_id"],
            },
        }
        input_context_path = output / "governor_input_context.json"
        _write_json_exclusive(input_context_path, input_context)

        prep = prep_module.build_governor_deliberation_prep(
            intake,
            filtered_oracle,
            council_executive_summary=council_context,
            secretary_summary=secretary.to_dict(),
            mandate=mandate_context,
            generated_at=supporting.generated_at,
        )
        prep_path = output / "governor_deliberation_prep.json"
        _write_json_exclusive(prep_path, prep.to_dict())
        deliberation = deliberation_module.build_governor_deliberation(
            prep, generated_at=supporting.generated_at
        )
        if supporting.replay_contract_case is GovernorReplayContractCase.INVALID_STAND_DOWN:
            deliberation = GovernorDeliberation(
                deliberation_id=(
                    f"governor-deliberation-invalid-{supporting.context_id}"
                ),
                generated_at=supporting.generated_at,
                prep_id=prep.prep_id,
                deliberation_state="INVALID",
                market_interpretation=deliberation.market_interpretation,
                senate_interpretation=deliberation.senate_interpretation,
                council_interpretation=deliberation.council_interpretation,
                mandate_interpretation=deliberation.mandate_interpretation,
                accountability_interpretation=deliberation.accountability_interpretation,
                governor_reasoning=(
                    "Governor contract-validation replay exercises the current INVALID rendering seam.",
                ),
                unresolved_questions=(),
                warnings=(),
                blockers=(),
                decision_status="NOT_RENDERED",
                dashboard_ready=True,
            )
        deliberation_path = output / "governor_deliberation.json"
        _write_json_exclusive(deliberation_path, deliberation.to_dict())
        governor_readiness = readiness_module.build_governor_decision_readiness(
            deliberation, generated_at=supporting.generated_at
        )
        governor_readiness_path = output / "governor_decision_readiness.json"
        _write_json_exclusive(governor_readiness_path, governor_readiness.to_dict())
        decision = decision_module.build_governor_decision(
            deliberation,
            governor_readiness,
            generated_at=supporting.generated_at,
        )
        decision_path = output / "governor_decision.json"
        _write_json_exclusive(decision_path, decision.to_dict())
        classification["decision_warnings"] = list(decision.warnings)
        _write_json_exclusive(classification_path, classification)

        if decision.decision_state not in ALLOWED_GOVERNOR_DISPOSITIONS:
            raise GovernorMalformedResultError(
                "native Governor returned a legacy or unsupported disposition"
            )
        rendered = {
            "schema_version": GOVERNOR_RENDERED_DECISION_SCHEMA_VERSION,
            "native_contract": "blackpod.contracts.governor_decision.GovernorDecision",
            "mission_id": supporting.mission_id,
            "request_id": supporting.request_id,
            "run_mode": supporting.run_mode.value,
            "context_id": supporting.context_id,
            "decision_id": decision.decision_id,
            "readiness_id": governor_readiness.readiness_id,
            "readiness_state": governor_readiness.readiness_state,
            "disposition": decision.decision_state,
            "decision_status": decision.decision_status,
            "posture": decision.posture,
            "allowed_next_step": decision.allowed_next_step,
            "warnings": list(decision.warnings),
            "routine_warnings": list(routine_warnings),
            "blocking_reasons": list(decision.blockers),
            "review_requirements": list(deliberation.unresolved_questions),
            "rendered_at": decision.generated_at,
        }
        rendered_path = output / "governor_rendered_decision.json"
        _write_json_exclusive(rendered_path, rendered)

        produced = tuple(
            f"{request.output_dir}/{name}"
            for name in EXPECTED_GOVERNOR_OUTPUT_FILENAMES
        )
        _reject_absolute_output_leaks(output, battlestar_root, mission_root)
        return {
            "native_disposition": decision.decision_state,
            "readiness_state": governor_readiness.readiness_state,
            "decision_id": decision.decision_id,
            "allowed_next_step": decision.allowed_next_step,
            "produced_paths": list(produced),
            "context_id": supporting.context_id,
            "warnings": list(decision.warnings),
            "routine_warnings": list(routine_warnings),
            "blocking_reasons": list(decision.blockers),
            "review_requirements": list(deliberation.unresolved_questions),
        }
    finally:
        os.chdir(prior_cwd)


def _validate_input_correlation(
    supporting: GovernorSupportingContext,
    oracle: Mapping[str, Any],
    diagnostics: Mapping[str, Any],
    readiness: Mapping[str, Any],
    synthesis: Mapping[str, Any],
    summary: Mapping[str, Any],
    health: Mapping[str, Any],
    lineage: Mapping[str, Any],
    candidate: Any,
    review: Any,
    senate: Any,
) -> None:
    provenance = oracle.get("provenance")
    if not isinstance(provenance, Mapping):
        raise GovernorMalformedResultError("Oracle report provenance is missing")
    checks = (
        (diagnostics.get("readiness_id"), readiness.get("readiness_id")),
        (provenance.get("readiness_id"), readiness.get("readiness_id")),
        (summary.get("synthesis_id"), synthesis.get("synthesis_id")),
        (health.get("advisor_count"), synthesis.get("advisor_count")),
        (review.candidate_report_id, candidate.report_id),
        (senate.senate_review_packet_id, review.packet_id),
        (senate.oracle_report_id, oracle.get("report_id")),
        (lineage.get("mission_id"), supporting.mission_id),
        (lineage.get("request_id"), supporting.request_id),
        (lineage.get("run_mode"), supporting.run_mode.value),
    )
    if any(actual != expected for actual, expected in checks):
        raise GovernorMalformedResultError(
            "Governor input artifact correlation is inconsistent"
        )
    if health.get("overall_status") not in {"READY", "DEGRADED", "BLOCKED"}:
        raise GovernorMalformedResultError(
            "Council advisor health returned an unsupported state"
        )


def _classify_oracle_warnings(
    warnings: tuple[str, ...], diagnostics_module: Any
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    classifier = getattr(diagnostics_module, "_is_diagnostic_warning", None)
    if not callable(classifier):
        raise GovernorMalformedResultError(
            "native Oracle diagnostic warning classifier is unavailable"
        )
    routine: list[str] = []
    decision: list[str] = []
    for warning in warnings:
        (decision if classifier(warning) else routine).append(warning)
    return tuple(dict.fromkeys(routine)), tuple(dict.fromkeys(decision))


def _mandate_context(mandate: Any, context_id: str) -> dict[str, object]:
    blockers: list[str] = []
    if not mandate.ok:
        blockers.append(f"mandate:{mandate.reason}")
    if mandate.stale:
        blockers.append("mandate:stale")
    return {
        "mandate_id": f"governor-mandate-context-{context_id}",
        "as_of": mandate.as_of,
        "ok": mandate.ok,
        "max_trades": mandate.max_trades,
        "risk_posture": mandate.risk_posture,
        "stale": mandate.stale,
        "warnings": [],
        "blockers": blockers,
    }


def _require_module_origin(module: Any, battlestar_root: Path) -> None:
    source = getattr(module, "__file__", None)
    if not isinstance(source, str):
        raise GovernorMalformedResultError("Battlestar module origin is unavailable")
    resolved = Path(source).resolve(strict=True)
    if not _is_relative_to(resolved, battlestar_root):
        raise GovernorMalformedResultError(
            "Governor imported a module outside BATTLESTAR_PATH"
        )


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON artifact must be an object")
    return value


def _reject_absolute_output_leaks(
    output: Path, battlestar_root: Path, mission_root: Path
) -> None:
    forbidden = (str(battlestar_root), str(mission_root))
    for artifact in output.iterdir():
        if not artifact.is_file() or artifact.suffix != ".json":
            continue
        text = artifact.read_text(encoding="utf-8")
        if (
            any(path in text for path in forbidden)
            or _ABSOLUTE_POSIX_PATH.search(text) is not None
            or _ABSOLUTE_WINDOWS_PATH.search(text) is not None
        ):
            raise GovernorMalformedResultError(
                "Governor artifact contains an absolute local path"
            )


def _validate_native_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GovernorMalformedResultError(
            "Governor artifact path must be relative POSIX"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise GovernorMalformedResultError("Governor artifact path is unsafe")
    return value


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise GovernorMalformedResultError(f"{field_name} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise GovernorMalformedResultError(
                f"{field_name} must contain nonblank strings"
            )
        result.append(item)
    return tuple(result)


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "GovernorError"


def _sanitize_message(message: str, *roots: Path) -> str:
    value = str(message).replace("\n", " ").replace("\r", " ")
    for root in roots:
        value = value.replace(str(root), "<redacted-path>")
    value = _ABSOLUTE_POSIX_PATH.sub("<redacted-path>", value)
    value = _ABSOLUTE_WINDOWS_PATH.sub("<redacted-path>", value)
    value = " ".join(value.split())[:512]
    return value or "Governor execution failed"
