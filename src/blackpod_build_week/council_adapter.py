"""Narrow, deadline-controlled adapter for Battlestar's Council interfaces."""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import (
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    CANDIDATE_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    MANDATE_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
)
from .contracts import (
    ContractValidationError,
    CouncilTransportKind,
    MissionRequest,
    RunMode,
    StageStatus,
)
from .contracts.mission_request import (
    normalize_rfc3339,
    parse_strict_json_object_bytes,
)
from .identifiers import IdentifierError, validate_identifier, validate_mission_id


COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION = "blackpod.council_supporting_input.v1"
COUNCIL_SUPPORTING_INPUT_RELATIVE_PATH = (
    "council/inputs/council_supporting_input.json"
)
EXPECTED_COUNCIL_OUTPUT_FILENAMES = (
    "mandate_policy.json",
    "trading_candidate_report.json",
    "senate_review_packet.json",
    "senate_deliberation.json",
    "council_input_packet.json",
    "council_advisor_runtime_config.json",
    "council_advisor_runtime_validation.json",
    "advisor_health_summary.json",
    "council_synthesis.json",
    "council_executive_summary.json",
)
ALLOWED_COUNCIL_NATIVE_STATES = frozenset(
    {"ALIGNED", "MIXED", "CONFLICTED", "DEGRADED", "BLOCKED"}
)
EXPECTED_COUNCIL_ADVISOR_NAMES = (
    "oracle_report",
    "mandate",
    "trading_candidate_report",
    "senate_review_packet",
    "senate_deliberation",
)

_REQUIRED_BATTLESTAR_MODULES = (
    CANDIDATE_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    MANDATE_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
)
_TRANSPORT_RESULT_FIELDS = frozenset(
    {
        "native_state",
        "produced_paths",
        "input_id",
        "candidate_report_id",
        "senate_review_packet_id",
        "senate_deliberation_id",
        "input_packet_id",
        "synthesis_id",
        "summary_id",
        "warnings",
        "blockers",
        "alignments",
        "conflicts",
        "dissent",
    }
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)


class CouncilAdapterValidationError(ValueError):
    """Raised before execution when adapter-owned configuration is invalid."""


class CouncilMalformedResultError(RuntimeError):
    """Raised when Battlestar returns malformed data or an unsafe artifact set."""


class CouncilTransportTimeout(TimeoutError):
    """Raised when the isolated Council worker exceeds its deadline."""


class CouncilRemoteExecutionError(RuntimeError):
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


def _strict_text(value: object, field_name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank trimmed string")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    return value


@dataclass(frozen=True, slots=True)
class CouncilMandateInput:
    as_of: str
    ok: bool
    reason: str
    allowed_sides: tuple[str, ...]
    max_trades: int
    risk_posture: str
    source: str

    @classmethod
    def from_mapping(cls, value: object) -> "CouncilMandateInput":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mandate must be an object")
        _require_exact_fields(
            value,
            {
                "as_of",
                "ok",
                "reason",
                "allowed_sides",
                "max_trades",
                "risk_posture",
                "source",
            },
            "mandate",
        )
        if type(value["ok"]) is not bool:
            raise ContractValidationError("mandate.ok must be a boolean")
        sides_value = value["allowed_sides"]
        if not isinstance(sides_value, list):
            raise ContractValidationError("mandate.allowed_sides must be an array")
        sides: list[str] = []
        for raw_side in sides_value:
            side = _strict_text(raw_side, "mandate.allowed_sides item", max_length=16)
            if side not in {"BUY", "SELL"}:
                raise ContractValidationError(
                    "mandate.allowed_sides supports BUY and SELL only"
                )
            sides.append(side)
        if len(set(sides)) != len(sides):
            raise ContractValidationError("mandate.allowed_sides must be unique")
        max_trades = value["max_trades"]
        if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades < 0:
            raise ContractValidationError(
                "mandate.max_trades must be a nonnegative integer"
            )
        return cls(
            as_of=normalize_rfc3339(value["as_of"], "mandate.as_of"),
            ok=value["ok"],
            reason=_strict_text(value["reason"], "mandate.reason", max_length=128),
            allowed_sides=tuple(sides),
            max_trades=max_trades,
            risk_posture=_strict_text(
                value["risk_posture"], "mandate.risk_posture", max_length=64
            ),
            source=_strict_text(value["source"], "mandate.source", max_length=128),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "ok": self.ok,
            "reason": self.reason,
            "allowed_sides": list(self.allowed_sides),
            "max_trades": self.max_trades,
            "risk_posture": self.risk_posture,
            "source": self.source,
        }

    def native_payload(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "ok": self.ok,
            "reason": self.reason,
            "allowed_sides": list(self.allowed_sides),
            "max_trades": self.max_trades,
            "risk_posture": self.risk_posture,
            "produced_by": self.source,
        }


@dataclass(frozen=True, slots=True)
class CouncilSupportingInput:
    schema_version: str
    input_id: str
    run_mode: RunMode
    generated_at: str
    mandate: CouncilMandateInput

    @classmethod
    def from_bytes(cls, payload: bytes) -> "CouncilSupportingInput":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                payload,
                document_name="Council supporting input",
            )
        )

    @classmethod
    def from_mapping(cls, value: object) -> "CouncilSupportingInput":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Council supporting input must be an object")
        _require_exact_fields(
            value,
            {"schema_version", "input_id", "run_mode", "generated_at", "mandate"},
            "Council supporting input",
        )
        if value["schema_version"] != COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION:
            raise ContractValidationError(
                "unsupported Council supporting input schema_version"
            )
        try:
            input_id = validate_identifier(value["input_id"], "input_id")
            run_mode = RunMode(value["run_mode"])
        except (IdentifierError, TypeError, ValueError) as exc:
            raise ContractValidationError(str(exc)) from exc
        return cls(
            schema_version=COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
            input_id=input_id,
            run_mode=run_mode,
            generated_at=normalize_rfc3339(value["generated_at"], "generated_at"),
            mandate=CouncilMandateInput.from_mapping(value["mandate"]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "input_id": self.input_id,
            "run_mode": self.run_mode.value,
            "generated_at": self.generated_at,
            "mandate": self.mandate.to_dict(),
        }


ReplayCouncilInput = CouncilSupportingInput


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CouncilAdapterValidationError(
            f"{field_name} must be a relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise CouncilAdapterValidationError(
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
class CouncilMissionContext:
    mission_id: str
    mission_root: Path
    normalized_path: str = (
        "oracle/attempt-0001/fleet-oracles-vapors-example_normalized.json"
    )
    readiness_path: str = (
        "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json"
    )
    oracle_report_path: str = "oracle/attempt-0001/oracle_report_live.json"
    oracle_assessment_path: str = "oracle/attempt-0001/oracle_assessment_live.json"
    oracle_narrative_path: str = "oracle/attempt-0001/oracle_narrative_live.json"
    oracle_modeldock_narrative_path: str | None = None
    output_dir: str = "council/attempt-0001"

    def __post_init__(self) -> None:
        try:
            mission_id = validate_mission_id(self.mission_id)
        except IdentifierError as exc:
            raise CouncilAdapterValidationError(str(exc)) from exc
        root_input = Path(self.mission_root)
        if not root_input.is_absolute():
            raise CouncilAdapterValidationError("mission_root must be absolute")
        if root_input.is_symlink() or not root_input.is_dir():
            raise CouncilAdapterValidationError(
                "mission_root must be an existing non-symlink directory"
            )
        root = root_input.resolve(strict=True)
        required_path_fields = (
            "normalized_path",
            "readiness_path",
            "oracle_report_path",
            "oracle_assessment_path",
            "oracle_narrative_path",
            "output_dir",
        )
        values = {
            name: _validate_relative_path(getattr(self, name), name)
            for name in required_path_fields
        }
        if self.oracle_modeldock_narrative_path is not None:
            values["oracle_modeldock_narrative_path"] = _validate_relative_path(
                self.oracle_modeldock_narrative_path,
                "oracle_modeldock_narrative_path",
            )
        output = (root / values["output_dir"]).resolve(strict=False)
        for field_name in (
            "normalized_path",
            "readiness_path",
            "oracle_report_path",
            "oracle_assessment_path",
            "oracle_narrative_path",
            "oracle_modeldock_narrative_path",
        ):
            if field_name not in values:
                continue
            candidate = (root / values[field_name]).resolve(strict=False)
            if not _is_relative_to(candidate, root) or _is_relative_to(candidate, output):
                raise CouncilAdapterValidationError(
                    "Council input paths must remain beneath the mission root and outside output_dir"
                )
        if not _is_relative_to(output, root):
            raise CouncilAdapterValidationError(
                "Council output_dir must remain beneath the mission root"
            )
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "mission_root", root)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def absolute(self, relative_path: str) -> Path:
        return self.mission_root.joinpath(*PurePosixPath(relative_path).parts)

    @property
    def output_absolute(self) -> Path:
        return self.absolute(self.output_dir)


@dataclass(frozen=True, slots=True)
class CouncilTransportRequest:
    battlestar_path: Path
    mission_root: Path
    normalized_path: str
    readiness_path: str
    oracle_report_path: str
    oracle_assessment_path: str
    oracle_narrative_path: str
    output_dir: str
    generated_at: str
    supporting_input: dict[str, object]
    oracle_modeldock_narrative_path: str | None = None


class CouncilTransport(Protocol):
    def run(
        self, request: CouncilTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]: ...


CouncilTransportCallable = Callable[
    [CouncilTransportRequest, float], Mapping[str, object]
]


@dataclass(frozen=True, slots=True)
class CouncilFailure:
    code: str
    error_type: str
    message: str
    resumable: bool


@dataclass(frozen=True, slots=True)
class CouncilExecutionResult:
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    transport: CouncilTransportKind
    status: StageStatus
    native_state: str | None
    produced_paths: tuple[str, ...]
    failure: CouncilFailure | None
    input_id: str
    candidate_report_id: str | None = None
    senate_review_packet_id: str | None = None
    senate_deliberation_id: str | None = None
    input_packet_id: str | None = None
    synthesis_id: str | None = None
    summary_id: str | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    alignments: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    dissent: tuple[dict[str, object], ...] = field(default_factory=tuple)
    source_lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is StageStatus.SUCCEEDED:
            identifiers = (
                self.candidate_report_id,
                self.senate_review_packet_id,
                self.senate_deliberation_id,
                self.input_packet_id,
                self.synthesis_id,
                self.summary_id,
            )
            if (
                self.failure is not None
                or self.native_state not in ALLOWED_COUNCIL_NATIVE_STATES
                or any(not isinstance(value, str) or not value for value in identifiers)
            ):
                raise ValueError(
                    "successful Council result requires native state, native IDs, and no failure"
                )
        elif self.status is StageStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed Council result requires a structured failure")
        else:
            raise ValueError("Council result status must be SUCCEEDED or FAILED")


class ProcessCouncilTransport:
    """Execute Council in a terminable spawned process with a hard deadline."""

    def run(
        self, request: CouncilTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_council_worker, args=(sender, request))
        process.start()
        sender.close()
        try:
            if not receiver.poll(deadline_seconds):
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                raise CouncilTransportTimeout(
                    f"Council exceeded its {deadline_seconds:g}-second deadline"
                )
            try:
                envelope = receiver.recv()
            except EOFError as exc:
                raise CouncilMalformedResultError(
                    f"Council worker exited without a result (exit code {process.exitcode})"
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
            raise CouncilMalformedResultError(
                "Council worker returned a malformed envelope"
            )
        if envelope["ok"] is True and isinstance(envelope.get("result"), Mapping):
            return envelope["result"]
        if envelope["ok"] is False:
            raise CouncilRemoteExecutionError(
                str(envelope["error_type"]), str(envelope["message"])
            )
        raise CouncilMalformedResultError("Council worker envelope is malformed")


class CouncilAdapter:
    """Invoke Battlestar's existing Council chain without duplicating policy."""

    def __init__(
        self,
        battlestar_path: Path,
        *,
        transport: CouncilTransport | CouncilTransportCallable | None = None,
        deadline_seconds: float = 60.0,
    ) -> None:
        path_input = Path(battlestar_path)
        if not path_input.is_absolute() or not path_input.is_dir():
            raise CouncilAdapterValidationError(
                "Battlestar path must be an existing absolute directory"
            )
        path = path_input.resolve(strict=True)
        for relative in _REQUIRED_BATTLESTAR_MODULES:
            module = path / relative
            if module.is_symlink() or not module.is_file():
                raise CouncilAdapterValidationError(
                    f"Battlestar Council module is missing: {relative.as_posix()}"
                )
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise CouncilAdapterValidationError(
                "deadline_seconds must be finite and positive"
            )
        self.battlestar_path = path
        self.transport = transport or ProcessCouncilTransport()
        self.deadline_seconds = float(deadline_seconds)

    def execute(
        self,
        request: MissionRequest,
        context: CouncilMissionContext,
        *,
        supporting_input: CouncilSupportingInput,
    ) -> CouncilExecutionResult:
        if not isinstance(request, MissionRequest):
            raise CouncilAdapterValidationError("request must be a MissionRequest")
        if not isinstance(context, CouncilMissionContext):
            raise CouncilAdapterValidationError(
                "context must be a CouncilMissionContext"
            )
        if not isinstance(supporting_input, CouncilSupportingInput):
            raise CouncilAdapterValidationError(
                "supporting_input must be validated"
            )
        transport_kind = (
            CouncilTransportKind.REPLAY_FIXTURE
            if request.run_mode is RunMode.REPLAY
            else CouncilTransportKind.LIVE_MISSION_INPUTS
        )
        if request.mission_id != context.mission_id:
            return self._failure(
                request,
                context,
                supporting_input,
                transport_kind,
                code="COUNCIL_CORRELATION_MISMATCH",
                error_type="CorrelationError",
                message="request mission_id does not match Council context",
                resumable=False,
            )
        if supporting_input.run_mode is not request.run_mode:
            return self._failure(
                request,
                context,
                supporting_input,
                transport_kind,
                code="COUNCIL_MODE_MISMATCH",
                error_type="RunModeError",
                message="Council supporting input run mode conflicts with mission",
                resumable=False,
            )
        path_error = self._validate_execution_paths(context)
        if path_error is not None:
            return self._failure(
                request,
                context,
                supporting_input,
                transport_kind,
                code=path_error[0],
                error_type=path_error[1],
                message=path_error[2],
                resumable=False,
            )
        transport_request = CouncilTransportRequest(
            battlestar_path=self.battlestar_path,
            mission_root=context.mission_root,
            normalized_path=context.normalized_path,
            readiness_path=context.readiness_path,
            oracle_report_path=context.oracle_report_path,
            oracle_assessment_path=context.oracle_assessment_path,
            oracle_narrative_path=context.oracle_narrative_path,
            output_dir=context.output_dir,
            generated_at=supporting_input.generated_at,
            supporting_input=supporting_input.to_dict(),
            oracle_modeldock_narrative_path=(
                context.oracle_modeldock_narrative_path
            ),
        )
        try:
            raw = self._run_transport(transport_request)
            parsed = self._validate_transport_result(raw, context, supporting_input)
            produced_paths = self._validate_complete_output_set(context)
            self._validate_committed_native_outputs(context, parsed)
        except CouncilTransportTimeout as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_input,
                transport_kind,
                "COUNCIL_TIMEOUT",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        except CouncilRemoteExecutionError as exc:
            return self._failure(
                request,
                context,
                supporting_input,
                transport_kind,
                code="COUNCIL_EXECUTION_FAILED",
                error_type=_safe_error_type(exc.error_type),
                message=_sanitize_message(
                    str(exc), self.battlestar_path, context.mission_root
                ),
                resumable=request.run_mode is RunMode.LIVE,
                produced_paths=self._discover_outputs(context),
            )
        except CouncilMalformedResultError as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_input,
                transport_kind,
                "COUNCIL_MALFORMED_RESULT",
                exc,
                resumable=False,
            )
        except Exception as exc:
            return self._failure_from_exception(
                request,
                context,
                supporting_input,
                transport_kind,
                "COUNCIL_EXECUTION_FAILED",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        return CouncilExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport_kind,
            status=StageStatus.SUCCEEDED,
            native_state=parsed["native_state"],
            produced_paths=produced_paths,
            failure=None,
            input_id=parsed["input_id"],
            candidate_report_id=parsed["candidate_report_id"],
            senate_review_packet_id=parsed["senate_review_packet_id"],
            senate_deliberation_id=parsed["senate_deliberation_id"],
            input_packet_id=parsed["input_packet_id"],
            synthesis_id=parsed["synthesis_id"],
            summary_id=parsed["summary_id"],
            warnings=parsed["warnings"],
            blockers=parsed["blockers"],
            alignments=parsed["alignments"],
            conflicts=parsed["conflicts"],
            dissent=parsed["dissent"],
            source_lineage=(
                context.normalized_path,
                context.readiness_path,
                context.oracle_report_path,
                context.oracle_assessment_path,
                context.oracle_narrative_path,
                *(
                    (context.oracle_modeldock_narrative_path,)
                    if context.oracle_modeldock_narrative_path is not None
                    else ()
                ),
                COUNCIL_SUPPORTING_INPUT_RELATIVE_PATH,
            ),
        )

    def _run_transport(
        self, request: CouncilTransportRequest
    ) -> Mapping[str, object]:
        runner = getattr(self.transport, "run", None)
        if callable(runner):
            return runner(request, deadline_seconds=self.deadline_seconds)
        if callable(self.transport):
            return self.transport(request, self.deadline_seconds)
        raise CouncilAdapterValidationError("Council transport is not callable")

    def _validate_execution_paths(
        self, context: CouncilMissionContext
    ) -> tuple[str, str, str] | None:
        for relative in (
            context.normalized_path,
            context.readiness_path,
            context.oracle_report_path,
            context.oracle_assessment_path,
            context.oracle_narrative_path,
            *(
                (context.oracle_modeldock_narrative_path,)
                if context.oracle_modeldock_narrative_path is not None
                else ()
            ),
        ):
            path = context.absolute(relative)
            if (
                path.is_symlink()
                or not path.is_file()
                or not _is_relative_to(path.resolve(strict=True), context.mission_root)
            ):
                return (
                    "COUNCIL_INPUT_INVALID",
                    "PathValidationError",
                    "Council requires contained regular Oracle input artifacts",
                )
        output = context.output_absolute
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                return (
                    "COUNCIL_OUTPUT_INVALID",
                    "PathValidationError",
                    "Council output path must be a contained directory",
                )
            try:
                if any(output.iterdir()):
                    return (
                        "COUNCIL_IMMUTABLE_COLLISION",
                        "ArtifactCollisionError",
                        "Council output directory contains immutable artifacts",
                    )
            except OSError:
                return (
                    "COUNCIL_OUTPUT_INVALID",
                    "PathValidationError",
                    "Council output directory cannot be inspected",
                )
        return None

    def _validate_transport_result(
        self,
        raw: object,
        context: CouncilMissionContext,
        supporting_input: CouncilSupportingInput,
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise CouncilMalformedResultError("Council return must be an object")
        if set(raw) != _TRANSPORT_RESULT_FIELDS:
            raise CouncilMalformedResultError(
                "Council return fields do not match the supported contract"
            )
        parsed: dict[str, Any] = {}
        for name in (
            "native_state",
            "input_id",
            "candidate_report_id",
            "senate_review_packet_id",
            "senate_deliberation_id",
            "input_packet_id",
            "synthesis_id",
            "summary_id",
        ):
            value = raw[name]
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise CouncilMalformedResultError(
                    f"Council return {name} must be a nonblank string"
                )
            parsed[name] = value
        if parsed["native_state"] not in ALLOWED_COUNCIL_NATIVE_STATES:
            raise CouncilMalformedResultError("Council returned an unsupported native state")
        if parsed["input_id"] != supporting_input.input_id:
            raise CouncilMalformedResultError("Council returned the wrong supporting input ID")
        paths = raw["produced_paths"]
        if not isinstance(paths, (list, tuple)):
            raise CouncilMalformedResultError("Council produced_paths must be an array")
        parsed["produced_paths"] = tuple(
            _validate_native_relative_path(item) for item in paths
        )
        expected_paths = tuple(
            f"{context.output_dir}/{filename}"
            for filename in EXPECTED_COUNCIL_OUTPUT_FILENAMES
        )
        if parsed["produced_paths"] != expected_paths:
            raise CouncilMalformedResultError(
                "Council return does not declare the canonical artifact set"
            )
        for name in ("warnings", "blockers", "alignments", "conflicts"):
            parsed[name] = _text_tuple(raw[name], f"Council return {name}")
        dissent_value = raw["dissent"]
        if not isinstance(dissent_value, (list, tuple)) or not all(
            isinstance(item, Mapping) for item in dissent_value
        ):
            raise CouncilMalformedResultError("Council dissent must be an array of objects")
        parsed["dissent"] = tuple(dict(item) for item in dissent_value)
        return parsed

    def _validate_complete_output_set(
        self, context: CouncilMissionContext
    ) -> tuple[str, ...]:
        found = self._discover_outputs(context, reject_unsafe=True)
        expected = tuple(
            f"{context.output_dir}/{filename}"
            for filename in EXPECTED_COUNCIL_OUTPUT_FILENAMES
        )
        if set(found) != set(expected):
            raise CouncilMalformedResultError(
                "Council output set is incomplete or unsupported"
            )
        return expected

    def _validate_committed_native_outputs(
        self, context: CouncilMissionContext, parsed: Mapping[str, Any]
    ) -> None:
        try:
            synthesis = _read_json(context.output_absolute / "council_synthesis.json")
            summary = _read_json(
                context.output_absolute / "council_executive_summary.json"
            )
            packet = _read_json(context.output_absolute / "council_input_packet.json")
            runtime_config = _read_json(
                context.output_absolute / "council_advisor_runtime_config.json"
            )
            validation = _read_json(
                context.output_absolute
                / "council_advisor_runtime_validation.json"
            )
            health = _read_json(
                context.output_absolute / "advisor_health_summary.json"
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CouncilMalformedResultError(
                "Council native artifacts are not valid JSON objects"
            ) from exc
        checks = (
            (synthesis.get("synthesis_state"), parsed["native_state"]),
            (synthesis.get("synthesis_id"), parsed["synthesis_id"]),
            (synthesis.get("input_packet_id"), parsed["input_packet_id"]),
            (summary.get("summary_id"), parsed["summary_id"]),
            (summary.get("synthesis_id"), parsed["synthesis_id"]),
            (packet.get("packet_id"), parsed["input_packet_id"]),
        )
        if any(actual != expected for actual, expected in checks):
            raise CouncilMalformedResultError(
                "Council native artifact correlation is inconsistent"
            )
        manifest = runtime_config.get("advisor_manifest")
        health_advisors = health.get("advisors")
        if (
            not isinstance(manifest, list)
            or tuple(
                item.get("advisor_name")
                for item in manifest
                if isinstance(item, Mapping)
            )
            != EXPECTED_COUNCIL_ADVISOR_NAMES
            or len(manifest) != len(EXPECTED_COUNCIL_ADVISOR_NAMES)
            or validation.get("readiness_status")
            not in {"READY", "DEGRADED", "BLOCKED"}
            or health.get("overall_status") not in {"READY", "DEGRADED", "BLOCKED"}
            or health.get("advisor_count") != len(EXPECTED_COUNCIL_ADVISOR_NAMES)
            or not isinstance(health_advisors, list)
            or tuple(
                item.get("advisor_name")
                for item in health_advisors
                if isinstance(item, Mapping)
            )
            != EXPECTED_COUNCIL_ADVISOR_NAMES
            or len(health_advisors) != len(EXPECTED_COUNCIL_ADVISOR_NAMES)
        ):
            raise CouncilMalformedResultError(
                "Council advisor-health artifacts are inconsistent"
            )
        for item in health_advisors:
            if (
                not isinstance(item, Mapping)
                or type(item.get("loaded")) is not bool
                or type(item.get("healthy")) is not bool
                or item.get("enabled") is not True
                or item.get("required") is not True
                or item.get("severity") not in {"OK", "INFO", "WARNING", "BLOCKER"}
                or not isinstance(item.get("freshness"), str)
                or re.fullmatch(r"[0-9a-f]{64}", str(item.get("source_sha256", "")))
                is None
            ):
                raise CouncilMalformedResultError(
                    "Council advisor-health evidence is malformed"
                )
            _validate_native_relative_path(item.get("source_path"))
        serialized = "\n".join(
            (
                json.dumps(packet),
                json.dumps(runtime_config),
                json.dumps(validation),
                json.dumps(health),
                json.dumps(synthesis),
                json.dumps(summary),
            )
        )
        if str(context.mission_root) in serialized:
            raise CouncilMalformedResultError(
                "Council artifacts leaked the absolute mission path"
            )

    def _discover_outputs(
        self, context: CouncilMissionContext, *, reject_unsafe: bool = False
    ) -> tuple[str, ...]:
        output = context.output_absolute
        if not output.is_dir() or output.is_symlink():
            return ()
        found: list[str] = []
        try:
            for candidate in sorted(output.rglob("*"), key=lambda item: item.as_posix()):
                if candidate.is_symlink() or not candidate.is_file():
                    if reject_unsafe and not candidate.is_dir():
                        raise CouncilMalformedResultError(
                            "Council output contains an unsafe artifact"
                        )
                    continue
                resolved = candidate.resolve(strict=True)
                if not _is_relative_to(resolved, context.mission_root):
                    if reject_unsafe:
                        raise CouncilMalformedResultError(
                            "Council artifact escaped the mission root"
                        )
                    continue
                found.append(candidate.relative_to(context.mission_root).as_posix())
        except OSError as exc:
            if reject_unsafe:
                raise CouncilMalformedResultError(
                    "Council outputs cannot be inspected"
                ) from exc
        expected_order = {
            f"{context.output_dir}/{name}": index
            for index, name in enumerate(EXPECTED_COUNCIL_OUTPUT_FILENAMES)
        }
        return tuple(sorted(found, key=lambda value: expected_order.get(value, 999)))

    def _failure_from_exception(
        self,
        request: MissionRequest,
        context: CouncilMissionContext,
        supporting_input: CouncilSupportingInput,
        transport: CouncilTransportKind,
        code: str,
        exc: Exception,
        *,
        resumable: bool,
    ) -> CouncilExecutionResult:
        return self._failure(
            request,
            context,
            supporting_input,
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
        context: CouncilMissionContext,
        supporting_input: CouncilSupportingInput,
        transport: CouncilTransportKind,
        *,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        produced_paths: tuple[str, ...] = (),
    ) -> CouncilExecutionResult:
        return CouncilExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport,
            status=StageStatus.FAILED,
            native_state=None,
            produced_paths=produced_paths,
            failure=CouncilFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=message or "Council execution failed",
                resumable=resumable,
            ),
            input_id=supporting_input.input_id,
        )


def _council_worker(sender: Any, request: CouncilTransportRequest) -> None:
    try:
        result = _run_native_council(request)
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


def _run_native_council(request: CouncilTransportRequest) -> dict[str, object]:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    battlestar_root = request.battlestar_path.resolve(strict=True)
    mission_root = request.mission_root.resolve(strict=True)
    sys.path.insert(0, str(battlestar_root))
    prior_cwd = Path.cwd()
    os.chdir(mission_root)
    try:
        import blackpod.advisors.mandate as mandate_module
        import blackpod.advisors.senate_candidate_intake as senate_review_module
        import blackpod.advisors.senate_deliberation as senate_deliberation_module
        import blackpod.advisors.trading_candidate_generator as candidate_module
        import blackpod.governor.council_executive_summary as summary_module
        import blackpod.governor.council_synthesis as synthesis_module
        import blackpod.runtime.advisor_health as advisor_health_module
        import blackpod.runtime.validation_report as validation_module
        from blackpod.advisors.base import AdvisorContext
        from blackpod.advisors.oracle_report import OracleReportAdvisor
        from blackpod.governor.input_packet import build_governor_input_packet
        from blackpod.runtime.advisor_snapshot_gate import (
            load_fleet_snapshot_readiness,
            load_normalized_fleet_snapshot,
        )

        for module in (
            candidate_module,
            senate_review_module,
            senate_deliberation_module,
            mandate_module,
            synthesis_module,
            summary_module,
            advisor_health_module,
            validation_module,
        ):
            _require_module_origin(module, battlestar_root)

        supporting = CouncilSupportingInput.from_mapping(request.supporting_input)
        output = Path(request.output_dir)
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise CouncilMalformedResultError(
                "reserved Council output directory is missing or nonempty"
            )
        normalized = load_normalized_fleet_snapshot(request.normalized_path)
        readiness = load_fleet_snapshot_readiness(request.readiness_path)
        if (
            readiness.normalized_snapshot_id != normalized.normalized_snapshot_id
            or readiness.fleet_id != normalized.fleet_id
        ):
            raise CouncilMalformedResultError(
                "Oracle normalized snapshot and readiness do not correlate"
            )

        oracle_payload = _read_json(Path(request.oracle_report_path))
        assessment_payload = _read_json(Path(request.oracle_assessment_path))
        narrative_payload = _read_json(Path(request.oracle_narrative_path))
        if request.oracle_modeldock_narrative_path is not None:
            modeldock_narrative = _read_json(
                Path(request.oracle_modeldock_narrative_path)
            )
            if modeldock_narrative.get("schema_version") != "blackpod.oracle_narrative.v1":
                raise CouncilMalformedResultError(
                    "ModelDock Oracle narrative uses an unsupported contract"
                )
        oracle_report = senate_deliberation_module.load_oracle_report(
            request.oracle_report_path
        )
        _validate_oracle_lineage(
            normalized,
            readiness,
            oracle_payload,
            assessment_payload,
            narrative_payload,
        )

        mandate_path = output / "mandate_policy.json"
        _write_json_exclusive(mandate_path, supporting.mandate.native_payload())
        advisor_context = AdvisorContext(
            as_of=request.generated_at,
            root=Path("."),
            stale_days=0,
        )
        mandate_artifact = mandate_module.MandateAdvisor(
            mandate_path.as_posix()
        ).run(advisor_context)

        candidate_report = candidate_module.build_trading_candidate_report(
            normalized,
            readiness,
            generated_at=request.generated_at,
        )
        candidate_path = output / "trading_candidate_report.json"
        _write_json_exclusive(candidate_path, candidate_report.to_dict())
        candidate_artifact = candidate_module.TradingCandidateReportAdvisor(
            candidate_path.as_posix()
        ).load(advisor_context)

        review_packet = senate_review_module.build_senate_review_packet(
            candidate_report,
            oracle_report=oracle_payload,
            generated_at=request.generated_at,
        )
        review_path = output / "senate_review_packet.json"
        _write_json_exclusive(review_path, review_packet.to_dict())
        review_artifact = senate_review_module.SenateReviewPacketAdvisor(
            review_path.as_posix()
        ).load(advisor_context)

        deliberation = senate_deliberation_module.build_senate_deliberation(
            review_packet,
            oracle_report,
            generated_at=request.generated_at,
        )
        deliberation_path = output / "senate_deliberation.json"
        _write_json_exclusive(deliberation_path, deliberation.to_dict())
        deliberation_artifact = senate_deliberation_module.SenateDeliberationAdvisor(
            deliberation_path.as_posix()
        ).load(advisor_context)

        oracle_artifact = OracleReportAdvisor(request.oracle_report_path).run(
            advisor_context
        )
        packet = build_governor_input_packet(
            advisor_artifacts=(
                oracle_artifact,
                mandate_artifact,
                candidate_artifact,
                review_artifact,
                deliberation_artifact,
            ),
            generated_at=request.generated_at,
        )
        packet_path = output / "council_input_packet.json"
        _write_json_exclusive(packet_path, packet.to_dict())

        runtime_config_path = output / "council_advisor_runtime_config.json"
        runtime_config = {
            "as_of": request.generated_at,
            "root": "../..",
            "advisor_manifest": [
                {
                    "advisor_name": "oracle_report",
                    "advisor_type": "oracle_report",
                    "enabled": True,
                    "required": True,
                    "artifact_path": request.oracle_report_path,
                    "stale_days": 0,
                },
                {
                    "advisor_name": "mandate",
                    "advisor_type": "mandate",
                    "enabled": True,
                    "required": True,
                    "artifact_path": mandate_path.as_posix(),
                    "stale_days": 0,
                },
                {
                    "advisor_name": "trading_candidate_report",
                    "advisor_type": "trading_candidate_report",
                    "enabled": True,
                    "required": True,
                    "artifact_path": candidate_path.as_posix(),
                    "stale_days": 0,
                },
                {
                    "advisor_name": "senate_review_packet",
                    "advisor_type": "senate_review_packet",
                    "enabled": True,
                    "required": True,
                    "artifact_path": review_path.as_posix(),
                    "stale_days": 0,
                },
                {
                    "advisor_name": "senate_deliberation",
                    "advisor_type": "senate_deliberation",
                    "enabled": True,
                    "required": True,
                    "artifact_path": deliberation_path.as_posix(),
                    "stale_days": 0,
                },
            ],
        }
        _write_json_exclusive(runtime_config_path, runtime_config)
        validation = validation_module.build_runtime_validation_report(
            runtime_config_path
        )
        validation_path = output / "council_advisor_runtime_validation.json"
        _write_json_exclusive(
            validation_path,
            _runtime_validation_evidence(
                validation,
                mission_root=mission_root,
                generated_at=request.generated_at,
                config_path=runtime_config_path.as_posix(),
            ),
        )
        health = advisor_health_module.build_advisor_health_summary(
            validation,
            packet,
            generated_at=request.generated_at,
        )
        _validate_advisor_health_evidence(validation, health, packet)
        health_path = output / "advisor_health_summary.json"
        _write_json_exclusive(
            health_path,
            advisor_health_module.advisor_health_summary_to_dict(health),
        )
        synthesis = synthesis_module.build_council_synthesis(
            packet,
            health,
            decision_report=None,
            oracle_report=oracle_report,
            generated_at=request.generated_at,
        )
        synthesis_path = output / "council_synthesis.json"
        _write_json_exclusive(synthesis_path, synthesis.to_dict())
        summary = summary_module.build_council_executive_summary(
            synthesis=synthesis,
            generated_at=request.generated_at,
        )
        summary_path = output / "council_executive_summary.json"
        _write_json_exclusive(summary_path, summary.to_dict())

        if synthesis.input_packet_id != packet.packet_id:
            raise CouncilMalformedResultError("Council synthesis packet ID mismatch")
        if summary.synthesis_id != synthesis.synthesis_id:
            raise CouncilMalformedResultError("Council summary synthesis ID mismatch")
        dissent = tuple(
            {
                "candidate_id": item.candidate_id,
                "symbol": item.symbol,
                "deliberation_state": item.deliberation_state,
                "senate_reasoning": list(item.senate_reasoning),
                "warnings": list(item.warnings),
                "blockers": list(item.blockers),
            }
            for item in deliberation.items
            if item.deliberation_state in {"UNFAVORABLE", "BLOCKED"}
        )
        warnings = _dedupe(
            (
                *candidate_report.warnings,
                *review_packet.warnings,
                *deliberation.warnings,
                *synthesis.warnings,
                *summary.notable_warnings,
            )
        )
        blockers = _dedupe(
            (
                *candidate_report.blockers,
                *review_packet.blockers,
                *deliberation.blockers,
                *synthesis.blockers,
                *summary.notable_blockers,
            )
        )
        produced_paths = tuple(
            f"{request.output_dir}/{filename}"
            for filename in EXPECTED_COUNCIL_OUTPUT_FILENAMES
        )
        _reject_absolute_output_leaks(output, battlestar_root, mission_root)
        return {
            "native_state": synthesis.synthesis_state,
            "produced_paths": list(produced_paths),
            "input_id": supporting.input_id,
            "candidate_report_id": candidate_report.report_id,
            "senate_review_packet_id": review_packet.packet_id,
            "senate_deliberation_id": deliberation.deliberation_id,
            "input_packet_id": packet.packet_id,
            "synthesis_id": synthesis.synthesis_id,
            "summary_id": summary.summary_id,
            "warnings": list(warnings),
            "blockers": list(blockers),
            "alignments": list(synthesis.key_alignments),
            "conflicts": list(synthesis.key_conflicts),
            "dissent": list(dissent),
        }
    finally:
        os.chdir(prior_cwd)


def _require_module_origin(module: Any, battlestar_root: Path) -> None:
    source = getattr(module, "__file__", None)
    if not isinstance(source, str):
        raise CouncilMalformedResultError("Battlestar module origin is unavailable")
    resolved = Path(source).resolve(strict=True)
    if not _is_relative_to(resolved, battlestar_root):
        raise CouncilMalformedResultError(
            "Council imported a module outside BATTLESTAR_PATH"
        )


def _validate_oracle_lineage(
    normalized: Any,
    readiness: Any,
    report: Mapping[str, Any],
    assessment: Mapping[str, Any],
    narrative: Mapping[str, Any],
) -> None:
    if report.get("assessment_id") != assessment.get("assessment_id"):
        raise CouncilMalformedResultError("Oracle assessment ID mismatch")
    if report.get("narrative_id") != narrative.get("narrative_id"):
        raise CouncilMalformedResultError("Oracle narrative ID mismatch")
    if narrative.get("assessment_id") != assessment.get("assessment_id"):
        raise CouncilMalformedResultError("Oracle narrative assessment mismatch")
    provenance = report.get("provenance")
    if not isinstance(provenance, Mapping):
        raise CouncilMalformedResultError("Oracle report provenance is missing")
    if provenance.get("normalized_snapshot_id") != normalized.normalized_snapshot_id:
        raise CouncilMalformedResultError("Oracle report normalized snapshot mismatch")
    if provenance.get("readiness_id") != readiness.readiness_id:
        raise CouncilMalformedResultError("Oracle report readiness mismatch")


def _runtime_validation_evidence(
    validation: Any,
    *,
    mission_root: Path,
    generated_at: str,
    config_path: str,
) -> dict[str, object]:
    """Materialize the policy-bearing native validation without local paths.

    Battlestar's native report includes resolved absolute paths and a report ID
    derived from them.  Neither affects advisor-health policy.  This adapter
    preserves every policy-bearing entry and item while replacing path-only
    presentation fields with canonical mission-relative values.
    """

    to_dict = getattr(validation, "to_dict", None)
    if not callable(to_dict):
        raise CouncilMalformedResultError(
            "native runtime validation cannot be materialized"
        )
    raw = to_dict()
    if not isinstance(raw, Mapping):
        raise CouncilMalformedResultError(
            "native runtime validation must be an object"
        )
    payload: dict[str, object] = dict(raw)
    payload.pop("report_id", None)
    payload["schema_version"] = "blackpod.council_runtime_validation.v1"
    payload["native_contract"] = (
        "blackpod.runtime.validation_report.RuntimeValidationReport"
    )
    payload["generated_at"] = generated_at
    payload["config_path"] = config_path
    payload["project_root"] = "."

    entries = payload.get("advisor_entries")
    if not isinstance(entries, list):
        raise CouncilMalformedResultError(
            "native runtime validation lacks advisor entries"
        )
    normalized_entries: list[dict[str, object]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            raise CouncilMalformedResultError(
                "native runtime validation advisor entry is malformed"
            )
        entry = dict(item)
        entry["resolved_artifact_path"] = _mission_relative_path_value(
            entry.get("resolved_artifact_path"), mission_root
        )
        normalized_entries.append(entry)
    payload["advisor_entries"] = normalized_entries

    for field_name in ("items", "blockers", "warnings"):
        values = payload.get(field_name)
        if not isinstance(values, list):
            raise CouncilMalformedResultError(
                f"native runtime validation {field_name} is malformed"
            )
        normalized_values: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, Mapping):
                raise CouncilMalformedResultError(
                    f"native runtime validation {field_name} item is malformed"
                )
            entry = dict(item)
            if entry.get("path") is not None:
                entry["path"] = _mission_relative_path_value(
                    entry.get("path"), mission_root
                )
            normalized_values.append(entry)
        payload[field_name] = normalized_values
    return payload


def _validate_advisor_health_evidence(
    validation: Any,
    health: Any,
    packet: Any,
) -> None:
    validation_entries = getattr(validation, "advisor_entries", None)
    health_advisors = getattr(health, "advisors", None)
    source_artifacts = getattr(packet, "source_artifacts", None)
    if not all(
        isinstance(value, tuple)
        for value in (validation_entries, health_advisors, source_artifacts)
    ):
        raise CouncilMalformedResultError(
            "native advisor-health evidence has an unsupported shape"
        )
    validation_names = tuple(
        getattr(entry, "advisor_name", None) for entry in validation_entries
    )
    health_names = tuple(
        getattr(advisor, "advisor_name", None) for advisor in health_advisors
    )
    source_names = tuple(
        getattr(source, "advisor_name", None) for source in source_artifacts
    )
    if not (
        validation_names
        == health_names
        == source_names
        == EXPECTED_COUNCIL_ADVISOR_NAMES
        and getattr(health, "advisor_count", None)
        == len(EXPECTED_COUNCIL_ADVISOR_NAMES)
    ):
        raise CouncilMalformedResultError(
            "native advisor health does not cover the canonical Council evidence set"
        )
    if getattr(validation, "readiness_status", None) not in {
        "READY",
        "DEGRADED",
        "BLOCKED",
    }:
        raise CouncilMalformedResultError(
            "native runtime validation returned an unsupported state"
        )
    if getattr(health, "overall_status", None) not in {
        "READY",
        "DEGRADED",
        "BLOCKED",
    }:
        raise CouncilMalformedResultError(
            "native advisor health returned an unsupported state"
        )
    for advisor, source in zip(health_advisors, source_artifacts, strict=True):
        source_path = getattr(source, "path", None)
        source_sha = getattr(source, "source_sha256", None)
        if (
            getattr(advisor, "enabled", None) is not True
            or getattr(advisor, "required", None) is not True
            or type(getattr(advisor, "loaded", None)) is not bool
            or type(getattr(advisor, "healthy", None)) is not bool
            or getattr(advisor, "severity", None)
            not in {"OK", "INFO", "WARNING", "BLOCKER"}
            or not isinstance(getattr(advisor, "freshness", None), str)
            or getattr(advisor, "source_path", None) != source_path
            or getattr(advisor, "source_sha256", None) != source_sha
            or not isinstance(source_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha) is None
        ):
            raise CouncilMalformedResultError(
                "native advisor health is not correlated to immutable Council evidence"
            )
        _validate_native_relative_path(source_path)


def _mission_relative_path_value(value: object, mission_root: Path) -> str:
    if not isinstance(value, str) or not value:
        raise CouncilMalformedResultError(
            "native runtime validation contains an invalid path"
        )
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise CouncilMalformedResultError(
                "native runtime validation path cannot be resolved"
            ) from exc
        if not _is_relative_to(resolved, mission_root):
            raise CouncilMalformedResultError(
                "native runtime validation path escapes the mission"
            )
        return resolved.relative_to(mission_root).as_posix()
    return _validate_native_relative_path(candidate.as_posix())


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
        if any(path in text for path in forbidden):
            raise CouncilMalformedResultError(
                "Council native artifact contains an absolute local path"
            )


def _validate_native_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CouncilMalformedResultError("Council artifact path must be relative POSIX")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise CouncilMalformedResultError("Council artifact path is unsafe")
    return value


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CouncilMalformedResultError(f"{field_name} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise CouncilMalformedResultError(
                f"{field_name} must contain nonblank strings"
            )
        result.append(item)
    return tuple(result)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "CouncilError"


def _sanitize_message(message: str, *roots: Path) -> str:
    value = str(message).replace("\n", " ").replace("\r", " ")
    for root in roots:
        value = value.replace(str(root), "<redacted-path>")
    value = _ABSOLUTE_POSIX_PATH.sub("<redacted-path>", value)
    value = _ABSOLUTE_WINDOWS_PATH.sub("<redacted-path>", value)
    value = " ".join(value.split())[:512]
    return value or "Council execution failed"
