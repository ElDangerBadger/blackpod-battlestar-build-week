"""Narrow SHADOW-only adapter for Battlestar Navigator handoff and intake."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .contracts import (
    ContractValidationError,
    MissionRequest,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    RunMode,
    StageStatus,
)
from .contracts.mission_request import (
    normalize_rfc3339,
    parse_rfc3339,
    parse_strict_json_object_bytes,
)
from .hashing import sha256_bytes, sha256_file
from .identifiers import IdentifierError, validate_identifier, validate_mission_id
from .operator_adapter import (
    NATIVE_OPERATOR_ACTION_FIELDS,
    NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
)


NAVIGATOR_REPLAY_SCHEMA_VERSION = "blackpod.navigator_replay.v1"
NATIVE_HANDOFF_SCHEMA_VERSION = "navigator_shadow_handoff_envelope.v1"
NATIVE_STAGING_RECEIPT_SCHEMA_VERSION = "navigator_handoff_staging_receipt.v1"
NATIVE_INTAKE_RECEIPT_SCHEMA_VERSION = "navigator_intake_receipt.v1"
NATIVE_SHADOW_PLAN_SCHEMA_VERSION = "navigator_shadow_plan.v1"

ALLOWED_OPERATIONS = ("VALIDATE", "PLAN_ONLY")
PROHIBITED_OPERATIONS = (
    "SUBMIT_ORDER",
    "CANCEL_ORDER",
    "MODIFY_PORTFOLIO",
    "BROKER_CALL",
)

_REQUIRED_BATTLESTAR_MODULES = (
    Path("blackpod/runtime/navigator_handoff.py"),
    Path("blackpod/runtime/navigator_intake.py"),
    Path("blackpod/runtime/governor_decision_consumer.py"),
    Path("blackpod/runtime/operator_inbox_action.py"),
)
_TRANSPORT_RESULT_FIELDS = frozenset(
    {
        "status",
        "native_state",
        "handoff_status",
        "intake_status",
        "plan_status",
        "handoff_id",
        "intake_receipt_id",
        "plan_id",
        "allowed_operations",
        "prohibited_operations",
        "expires_at",
        "idempotency_key",
        "decision_id",
        "action_id",
        "produced_paths",
        "failure",
    }
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)


class NavigatorFailureInjection(str, Enum):
    NONE = "NONE"
    UNSUPPORTED_HANDOFF_SCHEMA = "UNSUPPORTED_HANDOFF_SCHEMA"


class NavigatorAdapterValidationError(ValueError):
    """Raised when adapter-owned inputs cannot be invoked safely."""


class NavigatorMalformedResultError(RuntimeError):
    """Raised when Navigator returns malformed data or unsafe artifacts."""


class NavigatorTransportTimeout(TimeoutError):
    """Raised when the isolated Navigator worker exceeds its deadline."""


class NavigatorRemoteExecutionError(RuntimeError):
    """Sanitized exception raised by Battlestar in the worker process."""

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


def _strict_text(value: object, field_name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank trimmed string")
    if len(value) > maximum:
        raise ContractValidationError(f"{field_name} exceeds {maximum} characters")
    return value


@dataclass(frozen=True, slots=True)
class NavigatorReplayFixture:
    schema_version: str
    fixture_id: str
    mission_id: str
    request_id: str
    run_mode: RunMode
    observed_at: str
    mode: NavigatorMode
    failure_injection: NavigatorFailureInjection

    @classmethod
    def from_bytes(cls, payload: bytes) -> "NavigatorReplayFixture":
        return cls.from_mapping(
            parse_strict_json_object_bytes(payload, document_name="Navigator replay fixture")
        )

    @classmethod
    def from_mapping(cls, value: object) -> "NavigatorReplayFixture":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator replay fixture must be an object")
        _require_exact_fields(
            value,
            {
                "schema_version",
                "fixture_id",
                "mission_id",
                "request_id",
                "run_mode",
                "observed_at",
                "mode",
                "failure_injection",
            },
            "Navigator replay fixture",
        )
        if value["schema_version"] != NAVIGATOR_REPLAY_SCHEMA_VERSION:
            raise ContractValidationError(
                "unsupported Navigator replay fixture schema_version"
            )
        try:
            fixture_id = validate_identifier(value["fixture_id"], "fixture_id")
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
            run_mode = RunMode(value["run_mode"])
            mode = NavigatorMode(value["mode"])
            injection = NavigatorFailureInjection(value["failure_injection"])
        except (IdentifierError, TypeError, ValueError) as exc:
            raise ContractValidationError(str(exc)) from exc
        if run_mode is not RunMode.REPLAY:
            raise ContractValidationError("Navigator replay fixture requires REPLAY mode")
        return cls(
            schema_version=NAVIGATOR_REPLAY_SCHEMA_VERSION,
            fixture_id=fixture_id,
            mission_id=mission_id,
            request_id=request_id,
            run_mode=run_mode,
            observed_at=normalize_rfc3339(value["observed_at"], "observed_at"),
            mode=mode,
            failure_injection=injection,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "run_mode": self.run_mode.value,
            "observed_at": self.observed_at,
            "mode": self.mode.value,
            "failure_injection": self.failure_injection.value,
        }


@dataclass(frozen=True, slots=True)
class NavigatorExecutionControl:
    run_mode: RunMode
    observed_at: str
    mode: NavigatorMode = NavigatorMode.SHADOW
    fixture_id: str | None = None
    failure_injection: NavigatorFailureInjection = NavigatorFailureInjection.NONE

    def __post_init__(self) -> None:
        observed = normalize_rfc3339(self.observed_at, "observed_at")
        fixture_id = self.fixture_id
        if fixture_id is not None:
            try:
                fixture_id = validate_identifier(fixture_id, "fixture_id")
            except IdentifierError as exc:
                raise NavigatorAdapterValidationError(str(exc)) from exc
        if self.mode is not NavigatorMode.SHADOW:
            raise NavigatorAdapterValidationError("Navigator supports SHADOW mode only")
        if self.run_mode is RunMode.LIVE:
            if fixture_id is not None or self.failure_injection is not NavigatorFailureInjection.NONE:
                raise NavigatorAdapterValidationError(
                    "LIVE Navigator cannot use replay fixture controls"
                )
        elif fixture_id is None:
            raise NavigatorAdapterValidationError(
                "REPLAY Navigator requires an identified replay fixture"
            )
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "fixture_id", fixture_id)

    @classmethod
    def from_replay_fixture(cls, fixture: NavigatorReplayFixture) -> "NavigatorExecutionControl":
        return cls(
            run_mode=fixture.run_mode,
            observed_at=fixture.observed_at,
            mode=fixture.mode,
            fixture_id=fixture.fixture_id,
            failure_injection=fixture.failure_injection,
        )


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise NavigatorAdapterValidationError(
            f"{field_name} must be a relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise NavigatorAdapterValidationError(
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
class NavigatorMissionContext:
    mission_id: str
    mission_root: Path
    decision_id: str
    action_id: str
    review_packet_path: str = "operator/attempt-0001/review_packet.json"
    operator_action_path: str = "operator/attempt-0001/operator_action.json"
    operator_provenance_path: str = "operator/attempt-0001/operator_provenance.json"
    operator_lineage_path: str = "operator/attempt-0001/lineage_manifest.json"
    output_dir: str = "navigator/attempt-0001"

    def __post_init__(self) -> None:
        try:
            mission_id = validate_mission_id(self.mission_id)
            decision_id = validate_identifier(self.decision_id, "decision_id")
            action_id = validate_identifier(self.action_id, "action_id")
        except IdentifierError as exc:
            raise NavigatorAdapterValidationError(str(exc)) from exc
        root_input = Path(self.mission_root)
        if not root_input.is_absolute():
            raise NavigatorAdapterValidationError("mission_root must be absolute")
        if root_input.is_symlink() or not root_input.is_dir():
            raise NavigatorAdapterValidationError(
                "mission_root must be an existing non-symlink directory"
            )
        root = root_input.resolve(strict=True)
        packet = _validate_relative_path(self.review_packet_path, "review_packet_path")
        action = _validate_relative_path(self.operator_action_path, "operator_action_path")
        provenance = _validate_relative_path(
            self.operator_provenance_path, "operator_provenance_path"
        )
        lineage = _validate_relative_path(
            self.operator_lineage_path, "operator_lineage_path"
        )
        output = _validate_relative_path(self.output_dir, "output_dir")
        output_absolute = (root / output).resolve(strict=False)
        for relative in (packet, action, provenance, lineage):
            candidate = (root / relative).resolve(strict=False)
            if not _is_relative_to(candidate, root) or _is_relative_to(
                candidate, output_absolute
            ):
                raise NavigatorAdapterValidationError(
                    "Navigator inputs must remain beneath mission_root and outside output_dir"
                )
        if not _is_relative_to(output_absolute, root):
            raise NavigatorAdapterValidationError(
                "Navigator output_dir must remain beneath mission_root"
            )
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "mission_root", root)
        object.__setattr__(self, "decision_id", decision_id)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "review_packet_path", packet)
        object.__setattr__(self, "operator_action_path", action)
        object.__setattr__(self, "operator_provenance_path", provenance)
        object.__setattr__(self, "operator_lineage_path", lineage)
        object.__setattr__(self, "output_dir", output)

    def absolute(self, relative_path: str) -> Path:
        return self.mission_root.joinpath(*PurePosixPath(relative_path).parts)

    @property
    def output_absolute(self) -> Path:
        return self.absolute(self.output_dir)


@dataclass(frozen=True, slots=True)
class NavigatorTransportRequest:
    battlestar_path: Path
    mission_root: Path
    mission_id: str
    request_id: str
    decision_id: str
    action_id: str
    review_packet_path: str
    operator_action_path: str
    output_dir: str
    observed_at: str
    mode: str
    failure_injection: str


class NavigatorTransport(Protocol):
    def run(
        self, request: NavigatorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]: ...


NavigatorTransportCallable = Callable[
    [NavigatorTransportRequest, float], Mapping[str, object]
]


@dataclass(frozen=True, slots=True)
class NavigatorFailure:
    code: str
    error_type: str
    message: str
    resumable: bool


@dataclass(frozen=True, slots=True)
class NavigatorExecutionResult:
    mission_id: str
    request_id: str
    run_mode: RunMode
    status: StageStatus
    native_state: str | None
    mode: NavigatorMode
    handoff_status: NavigatorHandoffStatus | None
    intake_status: NavigatorIntakeStatus | None
    plan_status: NavigatorPlanStatus | None
    handoff_id: str | None
    intake_receipt_id: str | None
    plan_id: str | None
    allowed_operations: tuple[str, ...]
    prohibited_operations: tuple[str, ...]
    expires_at: str | None
    idempotency_key: str | None
    decision_id: str
    action_id: str
    produced_paths: tuple[str, ...]
    source_lineage: tuple[str, ...]
    failure: NavigatorFailure | None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.mode is not NavigatorMode.SHADOW:
            raise ValueError("Navigator result mode must be SHADOW")
        if self.allowed_operations != ALLOWED_OPERATIONS:
            raise ValueError("Navigator result allowed operations are unsupported")
        if self.prohibited_operations != PROHIBITED_OPERATIONS:
            raise ValueError("Navigator result prohibited operations are unsupported")
        if self.status is StageStatus.SUCCEEDED:
            if (
                self.failure is not None
                or self.native_state != NavigatorPlanStatus.CREATED.value
                or self.handoff_status is not NavigatorHandoffStatus.STAGED
                or self.intake_status is not NavigatorIntakeStatus.ACCEPTED
                or self.plan_status is not NavigatorPlanStatus.CREATED
                or not all(
                    (
                        self.handoff_id,
                        self.intake_receipt_id,
                        self.plan_id,
                        self.expires_at,
                        self.idempotency_key,
                    )
                )
            ):
                raise ValueError("successful Navigator result is incomplete")
        elif self.status is StageStatus.FAILED:
            if self.failure is None or self.plan_status is not None or self.plan_id is not None:
                raise ValueError("failed Navigator result requires failure data and no plan")
            no_native_progress = all(
                item is None
                for item in (
                    self.native_state,
                    self.handoff_status,
                    self.intake_status,
                    self.handoff_id,
                    self.intake_receipt_id,
                    self.expires_at,
                    self.idempotency_key,
                )
            )
            rejected_intake = (
                self.native_state == "REJECTED"
                and self.handoff_status is NavigatorHandoffStatus.STAGED
                and self.intake_status is NavigatorIntakeStatus.REJECTED
                and all(
                    (
                        self.handoff_id,
                        self.intake_receipt_id,
                        self.expires_at,
                        self.idempotency_key,
                    )
                )
            )
            if not (no_native_progress or rejected_intake):
                raise ValueError(
                    "failed Navigator result has inconsistent partial native state"
                )
        else:
            raise ValueError("Navigator result status must be SUCCEEDED or FAILED")


class ProcessNavigatorTransport:
    """Execute the native handoff/intake path in a terminable spawned process."""

    def run(
        self, request: NavigatorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_navigator_worker, args=(sender, request))
        process.start()
        sender.close()
        try:
            if not receiver.poll(deadline_seconds):
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                raise NavigatorTransportTimeout(
                    f"Navigator exceeded its {deadline_seconds:g}-second deadline"
                )
            try:
                envelope = receiver.recv()
            except EOFError as exc:
                raise NavigatorMalformedResultError(
                    f"Navigator worker exited without a result (exit code {process.exitcode})"
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
            raise NavigatorMalformedResultError(
                "Navigator worker returned a malformed envelope"
            )
        if envelope["ok"] is True and isinstance(envelope.get("result"), Mapping):
            return envelope["result"]
        if envelope["ok"] is False:
            raise NavigatorRemoteExecutionError(
                str(envelope["error_type"]), str(envelope["message"])
            )
        raise NavigatorMalformedResultError("Navigator worker envelope is malformed")


class NavigatorAdapter:
    """Invoke current Navigator staging and intake; never invoke execution APIs."""

    def __init__(
        self,
        battlestar_path: Path,
        *,
        transport: NavigatorTransport | NavigatorTransportCallable | None = None,
        deadline_seconds: float = 60.0,
    ) -> None:
        raw_path = Path(battlestar_path)
        if not raw_path.is_absolute() or not raw_path.is_dir():
            raise NavigatorAdapterValidationError(
                "Battlestar path must be an existing absolute directory"
            )
        path = raw_path.resolve(strict=True)
        for relative in _REQUIRED_BATTLESTAR_MODULES:
            module = path / relative
            if module.is_symlink() or not module.is_file():
                raise NavigatorAdapterValidationError(
                    f"Battlestar Navigator module is missing: {relative.as_posix()}"
                )
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise NavigatorAdapterValidationError(
                "deadline_seconds must be finite and positive"
            )
        self.battlestar_path = path
        self.transport = transport or ProcessNavigatorTransport()
        self.deadline_seconds = float(deadline_seconds)

    def execute(
        self,
        request: MissionRequest,
        context: NavigatorMissionContext,
        *,
        control: NavigatorExecutionControl,
    ) -> NavigatorExecutionResult:
        if not isinstance(request, MissionRequest):
            raise NavigatorAdapterValidationError("request must be a MissionRequest")
        if not isinstance(context, NavigatorMissionContext):
            raise NavigatorAdapterValidationError(
                "context must be a NavigatorMissionContext"
            )
        if not isinstance(control, NavigatorExecutionControl):
            raise NavigatorAdapterValidationError(
                "control must be a NavigatorExecutionControl"
            )
        if request.run_mode is not control.run_mode:
            return self._failure(
                request,
                context,
                code="NAVIGATOR_MODE_MISMATCH",
                error_type="RunModeError",
                message="Navigator control run mode conflicts with mission",
                resumable=False,
            )
        if request.mission_id != context.mission_id:
            return self._failure(
                request,
                context,
                code="NAVIGATOR_CORRELATION_MISMATCH",
                error_type="CorrelationError",
                message="Navigator mission_id does not match mission request",
                resumable=False,
            )
        path_error = self._validate_execution_paths(context)
        if path_error is not None:
            return self._failure(
                request,
                context,
                code=path_error[0],
                error_type=path_error[1],
                message=path_error[2],
                resumable=False,
            )
        input_error = self._validate_input_contracts(request, context, control)
        if input_error is not None:
            return self._failure(
                request,
                context,
                code=input_error[0],
                error_type=input_error[1],
                message=input_error[2],
                resumable=False,
            )
        invocation = NavigatorTransportRequest(
            battlestar_path=self.battlestar_path,
            mission_root=context.mission_root,
            mission_id=context.mission_id,
            request_id=request.request_id,
            decision_id=context.decision_id,
            action_id=context.action_id,
            review_packet_path=context.review_packet_path,
            operator_action_path=context.operator_action_path,
            output_dir=context.output_dir,
            observed_at=control.observed_at,
            mode=control.mode.value,
            failure_injection=control.failure_injection.value,
        )
        try:
            raw = self._run_transport(invocation)
            parsed = self._validate_transport_result(raw, context)
            produced = self._validate_native_outputs(context, parsed)
        except NavigatorTransportTimeout as exc:
            return self._failure_from_exception(
                request,
                context,
                "NAVIGATOR_TIMEOUT",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        except NavigatorRemoteExecutionError as exc:
            return self._failure(
                request,
                context,
                code="NAVIGATOR_EXECUTION_FAILED",
                error_type=_safe_error_type(exc.error_type),
                message=_sanitize_message(
                    str(exc), self.battlestar_path, context.mission_root
                ),
                resumable=request.run_mode is RunMode.LIVE,
                produced_paths=self._discover_outputs(context),
            )
        except NavigatorMalformedResultError as exc:
            return self._failure_from_exception(
                request,
                context,
                "NAVIGATOR_MALFORMED_RESULT",
                exc,
                resumable=False,
            )
        except Exception as exc:
            return self._failure_from_exception(
                request,
                context,
                "NAVIGATOR_EXECUTION_FAILED",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )

        status = StageStatus(parsed["status"])
        failure_value = parsed["failure"]
        failure = None
        if failure_value is not None:
            failure = NavigatorFailure(
                code=failure_value["code"],
                error_type=failure_value["error_type"],
                message=failure_value["message"],
                resumable=failure_value["resumable"],
            )
        return NavigatorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode,
            status=status,
            native_state=parsed["native_state"],
            mode=NavigatorMode.SHADOW,
            handoff_status=(
                None
                if parsed["handoff_status"] is None
                else NavigatorHandoffStatus(parsed["handoff_status"])
            ),
            intake_status=(
                None
                if parsed["intake_status"] is None
                else NavigatorIntakeStatus(parsed["intake_status"])
            ),
            plan_status=(
                None
                if parsed["plan_status"] is None
                else NavigatorPlanStatus(parsed["plan_status"])
            ),
            handoff_id=parsed["handoff_id"],
            intake_receipt_id=parsed["intake_receipt_id"],
            plan_id=parsed["plan_id"],
            allowed_operations=parsed["allowed_operations"],
            prohibited_operations=parsed["prohibited_operations"],
            expires_at=parsed["expires_at"],
            idempotency_key=parsed["idempotency_key"],
            decision_id=parsed["decision_id"],
            action_id=parsed["action_id"],
            produced_paths=produced,
            source_lineage=(
                context.review_packet_path,
                context.operator_action_path,
                context.operator_provenance_path,
                context.operator_lineage_path,
            ),
            failure=failure,
        )

    def _run_transport(
        self, request: NavigatorTransportRequest
    ) -> Mapping[str, object]:
        runner = getattr(self.transport, "run", None)
        if callable(runner):
            return runner(request, deadline_seconds=self.deadline_seconds)
        if callable(self.transport):
            return self.transport(request, self.deadline_seconds)
        raise NavigatorAdapterValidationError("Navigator transport is not callable")

    def _validate_execution_paths(
        self, context: NavigatorMissionContext
    ) -> tuple[str, str, str] | None:
        for relative in (
            context.review_packet_path,
            context.operator_action_path,
            context.operator_provenance_path,
            context.operator_lineage_path,
        ):
            path = context.absolute(relative)
            if (
                path.is_symlink()
                or not path.is_file()
                or not _is_relative_to(path.resolve(strict=True), context.mission_root)
            ):
                return (
                    "NAVIGATOR_INPUT_INVALID",
                    "PathValidationError",
                    "Navigator requires contained regular mission input artifacts",
                )
        output = context.output_absolute
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                return (
                    "NAVIGATOR_OUTPUT_INVALID",
                    "PathValidationError",
                    "Navigator output path must be a contained directory",
                )
            if any(output.iterdir()):
                return (
                    "NAVIGATOR_IMMUTABLE_COLLISION",
                    "ArtifactCollisionError",
                    "Navigator output directory contains immutable artifacts",
                )
        return None

    def _validate_input_contracts(
        self,
        request: MissionRequest,
        context: NavigatorMissionContext,
        control: NavigatorExecutionControl,
    ) -> tuple[str, str, str] | None:
        try:
            packet = _read_object(context.absolute(context.review_packet_path))
            action = _read_object(context.absolute(context.operator_action_path))
            provenance = _read_object(
                context.absolute(context.operator_provenance_path)
            )
            lineage = _read_object(context.absolute(context.operator_lineage_path))
            if packet.get("schema_version") != "operator_review_packet.v1":
                raise NavigatorMalformedResultError(
                    "operator review packet schema is unsupported"
                )
            if action.get("schema_version") != "operator_inbox_action.v1":
                raise NavigatorMalformedResultError(
                    "operator action schema is unsupported"
                )
            packet_fields = frozenset(packet)
            if packet_fields not in {
                NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
                NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS
                | NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
            }:
                raise NavigatorMalformedResultError(
                    "operator review packet does not preserve its native shape"
                )
            if "unresolved_questions" in packet and not packet["unresolved_questions"]:
                raise NavigatorMalformedResultError(
                    "native operator packet may not include empty unresolved_questions"
                )
            if frozenset(action) != NATIVE_OPERATOR_ACTION_FIELDS:
                raise NavigatorMalformedResultError(
                    "operator action does not preserve its native shape"
                )
            if packet.get("run_id") != context.mission_id:
                raise NavigatorMalformedResultError(
                    "operator packet run_id does not match mission_id"
                )
            if packet.get("operator_route") != "PENDING_APPROVAL":
                raise NavigatorMalformedResultError(
                    "operator packet is not routed for approval"
                )
            if action.get("action") != "APPROVE_HANDOFF" or action.get(
                "resulting_status"
            ) != "APPROVED_FOR_HANDOFF":
                raise NavigatorMalformedResultError(
                    "operator action is not approved for Navigator handoff"
                )
            if action.get("action_id") != context.action_id:
                raise NavigatorMalformedResultError(
                    "operator action_id does not match mission state"
                )
            if action.get("source_run_id") != context.mission_id:
                raise NavigatorMalformedResultError(
                    "operator action source_run_id does not match mission"
                )
            if action.get("packet_path") != context.review_packet_path:
                raise NavigatorMalformedResultError(
                    "operator action packet_path is not the recorded mission artifact"
                )
            packet_hash = sha256_file(context.absolute(context.review_packet_path))
            if action.get("packet_sha256") != packet_hash:
                raise NavigatorMalformedResultError(
                    "operator action packet SHA-256 does not match"
                )
            if action.get("decision_input_hash") != packet.get("decision_input_hash"):
                raise NavigatorMalformedResultError(
                    "operator decision input hashes do not match"
                )
            expires = action.get("expires_at")
            if not isinstance(expires, str) or not expires.strip():
                raise NavigatorMalformedResultError(
                    "operator action requires a valid expiry"
                )
            expires_at = normalize_rfc3339(expires, "operator expires_at")
            if parse_rfc3339(control.observed_at, "observed_at") > parse_rfc3339(
                expires_at, "operator expires_at"
            ):
                raise NavigatorMalformedResultError("operator action is expired")
            _validate_packet_sources(packet, context.mission_root)
            if (
                provenance.get("schema_version") != "blackpod.operator_provenance.v1"
                or provenance.get("mission_id") != context.mission_id
                or provenance.get("request_id") != request.request_id
                or provenance.get("run_mode") != request.run_mode.value
                or provenance.get("decision_id") != context.decision_id
                or provenance.get("action_id") != context.action_id
                or provenance.get("action") != "APPROVE_HANDOFF"
                or provenance.get("result") != "APPROVED_FOR_HANDOFF"
                or provenance.get("operator_id") != action.get("operator_id")
                or provenance.get("observed_at") != action.get("created_at")
                or lineage.get("schema_version") != "blackpod.operator_lineage.v1"
                or lineage.get("mission_id") != context.mission_id
                or lineage.get("request_id") != request.request_id
                or lineage.get("run_mode") != request.run_mode.value
                or lineage.get("decision_id") != context.decision_id
                or lineage.get("action_id") != context.action_id
                or lineage.get("observed_at") != action.get("created_at")
            ):
                raise NavigatorMalformedResultError(
                    "operator provenance or lineage correlation is invalid"
                )
            _validate_operator_lineage(
                lineage,
                context=context,
                request_id=request.request_id,
                observed_at=str(action.get("created_at")),
                packet_sha256=packet_hash,
                action_sha256=sha256_file(
                    context.absolute(context.operator_action_path)
                ),
            )
            _reject_absolute_leaks(
                context.absolute(context.review_packet_path).read_bytes(),
                "operator review packet",
            )
            _reject_absolute_leaks(
                context.absolute(context.operator_action_path).read_bytes(),
                "operator action",
            )
            _reject_absolute_leaks(
                context.absolute(context.operator_provenance_path).read_bytes(),
                "operator provenance",
            )
            _reject_absolute_leaks(
                context.absolute(context.operator_lineage_path).read_bytes(),
                "operator lineage",
            )
        except (OSError, ContractValidationError, NavigatorMalformedResultError) as exc:
            return (
                "NAVIGATOR_INPUT_INVALID",
                type(exc).__name__,
                _sanitize_message(str(exc), self.battlestar_path, context.mission_root),
            )
        return None

    def _validate_transport_result(
        self, raw: object, context: NavigatorMissionContext
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping) or set(raw) != _TRANSPORT_RESULT_FIELDS:
            raise NavigatorMalformedResultError(
                "Navigator return fields do not match the supported contract"
            )
        status = raw["status"]
        if status not in {StageStatus.SUCCEEDED.value, StageStatus.FAILED.value}:
            raise NavigatorMalformedResultError("Navigator status is unsupported")
        parsed: dict[str, Any] = {"status": status}
        for name in ("decision_id", "action_id"):
            value = _transport_identifier(raw[name], name)
            expected = context.decision_id if name == "decision_id" else context.action_id
            if value != expected:
                raise NavigatorMalformedResultError(
                    f"Navigator returned the wrong {name}"
                )
            parsed[name] = value
        for name in ("handoff_id", "intake_receipt_id", "plan_id", "idempotency_key"):
            value = raw[name]
            parsed[name] = None if value is None else _transport_identifier(value, name)
        expires = raw["expires_at"]
        parsed["expires_at"] = (
            None if expires is None else normalize_rfc3339(expires, "expires_at")
        )
        parsed["allowed_operations"] = _operation_tuple(
            raw["allowed_operations"], "allowed_operations"
        )
        parsed["prohibited_operations"] = _operation_tuple(
            raw["prohibited_operations"], "prohibited_operations"
        )
        if parsed["allowed_operations"] != ALLOWED_OPERATIONS:
            raise NavigatorMalformedResultError(
                "Navigator allowed operations are not the SHADOW boundary"
            )
        if parsed["prohibited_operations"] != PROHIBITED_OPERATIONS:
            raise NavigatorMalformedResultError(
                "Navigator prohibited operations are not the SHADOW boundary"
            )
        paths = raw["produced_paths"]
        if not isinstance(paths, (list, tuple)):
            raise NavigatorMalformedResultError("Navigator produced_paths must be an array")
        parsed["produced_paths"] = tuple(
            _validate_native_relative_path(item, context.output_dir) for item in paths
        )
        if len(set(parsed["produced_paths"])) != len(parsed["produced_paths"]):
            raise NavigatorMalformedResultError("Navigator produced duplicate paths")

        failure = raw["failure"]
        if status == StageStatus.SUCCEEDED.value:
            if failure is not None:
                raise NavigatorMalformedResultError(
                    "successful Navigator result contains failure data"
                )
            expected = {
                "native_state": "CREATED",
                "handoff_status": "STAGED",
                "intake_status": "ACCEPTED",
                "plan_status": "CREATED",
            }
            for name, expected_value in expected.items():
                if raw[name] != expected_value:
                    raise NavigatorMalformedResultError(
                        f"successful Navigator {name} is unsupported"
                    )
                parsed[name] = expected_value
            if any(
                parsed[name] is None
                for name in (
                    "handoff_id",
                    "intake_receipt_id",
                    "plan_id",
                    "idempotency_key",
                )
            ):
                raise NavigatorMalformedResultError(
                    "successful Navigator result lacks correlation identifiers"
                )
        else:
            if not isinstance(failure, Mapping) or set(failure) != {
                "code",
                "error_type",
                "message",
                "resumable",
            }:
                raise NavigatorMalformedResultError(
                    "failed Navigator result lacks structured failure data"
                )
            parsed["failure"] = {
                "code": _transport_identifier(failure["code"], "failure code"),
                "error_type": _safe_error_type(str(failure["error_type"])),
                "message": _sanitize_message(
                    _strict_transport_message(failure["message"]),
                    self.battlestar_path,
                    context.mission_root,
                ),
                "resumable": _strict_bool(failure["resumable"], "failure resumable"),
            }
            if raw["native_state"] not in {None, "REJECTED"}:
                raise NavigatorMalformedResultError(
                    "failed Navigator native_state is unsupported"
                )
            parsed["native_state"] = raw["native_state"]
            if raw["handoff_status"] not in {None, "STAGED"}:
                raise NavigatorMalformedResultError("failed handoff status is unsupported")
            if raw["intake_status"] not in {None, "REJECTED"}:
                raise NavigatorMalformedResultError("failed intake status is unsupported")
            if raw["plan_status"] is not None or parsed["plan_id"] is not None:
                raise NavigatorMalformedResultError(
                    "failed Navigator must not create a SHADOW plan"
                )
            parsed["handoff_status"] = raw["handoff_status"]
            parsed["intake_status"] = raw["intake_status"]
            parsed["plan_status"] = None
        if status == StageStatus.SUCCEEDED.value:
            parsed["failure"] = None
        return parsed

    def _validate_native_outputs(
        self, context: NavigatorMissionContext, parsed: Mapping[str, Any]
    ) -> tuple[str, ...]:
        handoff_id = parsed.get("handoff_id")
        if not isinstance(handoff_id, str):
            raise NavigatorMalformedResultError("Navigator result lacks handoff_id")
        success = parsed["status"] == StageStatus.SUCCEEDED.value
        expected = _expected_paths(context.output_dir, handoff_id, success=success)
        if tuple(parsed["produced_paths"]) != expected:
            raise NavigatorMalformedResultError(
                "Navigator return does not declare the canonical native artifact set"
            )
        found = self._discover_outputs(context, reject_unsafe=True)
        if set(found) != set(expected):
            raise NavigatorMalformedResultError(
                "Navigator output set is incomplete or unsupported"
            )
        for relative in expected:
            _reject_absolute_leaks(
                context.absolute(relative).read_bytes(),
                f"Navigator artifact {relative}",
            )
        _validate_output_correlations(context, parsed, expected)
        return expected

    def _discover_outputs(
        self, context: NavigatorMissionContext, *, reject_unsafe: bool = False
    ) -> tuple[str, ...]:
        output = context.output_absolute
        if not output.exists() or not output.is_dir() or output.is_symlink():
            return ()
        paths: list[str] = []
        try:
            for candidate in sorted(output.rglob("*")):
                if candidate.is_symlink():
                    if reject_unsafe:
                        raise NavigatorMalformedResultError(
                            "Navigator output contains a symlink"
                        )
                    continue
                if candidate.is_file():
                    resolved = candidate.resolve(strict=True)
                    if not _is_relative_to(resolved, context.mission_root):
                        if reject_unsafe:
                            raise NavigatorMalformedResultError(
                                "Navigator output escaped mission_root"
                            )
                        continue
                    paths.append(candidate.relative_to(context.mission_root).as_posix())
        except OSError as exc:
            if reject_unsafe:
                raise NavigatorMalformedResultError(
                    "Navigator outputs cannot be inspected safely"
                ) from exc
        return tuple(paths)

    def _failure_from_exception(
        self,
        request: MissionRequest,
        context: NavigatorMissionContext,
        code: str,
        exc: Exception,
        *,
        resumable: bool,
    ) -> NavigatorExecutionResult:
        return self._failure(
            request,
            context,
            code=code,
            error_type=_safe_error_type(type(exc).__name__),
            message=_sanitize_message(str(exc), self.battlestar_path, context.mission_root),
            resumable=resumable,
            produced_paths=self._discover_outputs(context),
        )

    @staticmethod
    def _failure(
        request: MissionRequest,
        context: NavigatorMissionContext,
        *,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        produced_paths: tuple[str, ...] = (),
    ) -> NavigatorExecutionResult:
        return NavigatorExecutionResult(
            mission_id=context.mission_id,
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
            decision_id=context.decision_id,
            action_id=context.action_id,
            produced_paths=produced_paths,
            source_lineage=(
                context.review_packet_path,
                context.operator_action_path,
                context.operator_provenance_path,
                context.operator_lineage_path,
            ),
            failure=NavigatorFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=message or "Navigator technical failure",
                resumable=resumable,
            ),
        )


class _UnsupportedSchemaSink:
    """Replay-only seam used to exercise the real intake rejection path."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def stage(self, envelope: dict[str, object], *, staged_at: str | None = None) -> Any:
        mutated = dict(envelope)
        mutated["schema_version"] = "navigator_shadow_handoff_envelope.unsupported"
        return self.delegate.stage(mutated, staged_at=staged_at)


def _navigator_worker(sender: Any, invocation: NavigatorTransportRequest) -> None:
    try:
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.dont_write_bytecode = True
        os.chdir(invocation.mission_root)
        sys.path.insert(0, str(invocation.battlestar_path))
        from blackpod.runtime import navigator_handoff, navigator_intake

        _require_module_origin(
            navigator_handoff,
            invocation.battlestar_path / "blackpod/runtime/navigator_handoff.py",
        )
        _require_module_origin(
            navigator_intake,
            invocation.battlestar_path / "blackpod/runtime/navigator_intake.py",
        )
        handoff_root = f"{invocation.output_dir}/handoff"
        intake_root = f"{invocation.output_dir}/intake"
        injection = NavigatorFailureInjection(invocation.failure_injection)
        sink = None
        if injection is NavigatorFailureInjection.UNSUPPORTED_HANDOFF_SCHEMA:
            sink = _UnsupportedSchemaSink(
                navigator_handoff.FilesystemNavigatorHandoffSink(handoff_root)
            )
        receipt = navigator_handoff.stage_navigator_handoff(
            packet_path=invocation.review_packet_path,
            operator_action_path=invocation.operator_action_path,
            handoff_root=handoff_root,
            mode=invocation.mode,
            created_at=invocation.observed_at,
            sink=sink,
        )
        envelope_path = Path(receipt.envelope_path)
        envelope = _read_object(envelope_path)
        handoff_id = str(receipt.handoff_id)
        staging_receipt_path = (
            Path(handoff_root) / "staging_receipts" / f"{handoff_id}.json"
        )
        handoff_ledger_path = Path(handoff_root) / "handoff_ledger.jsonl"
        base_paths = (
            envelope_path.as_posix(),
            staging_receipt_path.as_posix(),
            handoff_ledger_path.as_posix(),
        )
        try:
            intake = navigator_intake.accept_handoff_envelope(
                envelope_path,
                navigator_root=intake_root,
                accepted_at=invocation.observed_at,
            )
        except navigator_intake.NavigatorIntakeError as exc:
            intake_receipt_path = (
                Path(intake_root) / "intake_receipts" / f"{handoff_id}.json"
            )
            receipt_id = _intake_receipt_id(handoff_id, str(receipt.envelope_sha256))
            result = {
                "status": StageStatus.FAILED.value,
                "native_state": "REJECTED",
                "handoff_status": "STAGED",
                "intake_status": "REJECTED",
                "plan_status": None,
                "handoff_id": handoff_id,
                "intake_receipt_id": receipt_id,
                "plan_id": None,
                "allowed_operations": list(ALLOWED_OPERATIONS),
                "prohibited_operations": list(PROHIBITED_OPERATIONS),
                "expires_at": envelope.get("expires_at"),
                "idempotency_key": _idempotency_key(
                    handoff_id, str(receipt.envelope_sha256)
                ),
                "decision_id": invocation.decision_id,
                "action_id": invocation.action_id,
                "produced_paths": [*base_paths, intake_receipt_path.as_posix()],
                "failure": {
                    "code": "NAVIGATOR_INTAKE_REJECTED",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "resumable": False,
                },
            }
        else:
            intake_receipt = _read_object(Path(intake.intake_receipt_path))
            plan = _read_object(Path(intake.shadow_plan_path))
            receipt_id = _intake_receipt_id(handoff_id, str(intake.envelope_sha256))
            result = {
                "status": StageStatus.SUCCEEDED.value,
                "native_state": "CREATED",
                "handoff_status": "STAGED",
                "intake_status": "ACCEPTED",
                "plan_status": "CREATED",
                "handoff_id": handoff_id,
                "intake_receipt_id": receipt_id,
                "plan_id": plan.get("plan_id"),
                "allowed_operations": list(ALLOWED_OPERATIONS),
                "prohibited_operations": list(PROHIBITED_OPERATIONS),
                "expires_at": envelope.get("expires_at"),
                "idempotency_key": _idempotency_key(
                    handoff_id, str(intake.envelope_sha256)
                ),
                "decision_id": invocation.decision_id,
                "action_id": invocation.action_id,
                "produced_paths": [
                    *base_paths,
                    Path(intake.intake_receipt_path).as_posix(),
                    Path(intake.shadow_plan_path).as_posix(),
                    (Path(intake_root) / "navigator_ledger.jsonl").as_posix(),
                ],
                "failure": None,
            }
            if intake_receipt.get("status") != "ACCEPTED":
                raise NavigatorMalformedResultError(
                    "native intake receipt did not preserve ACCEPTED"
                )
        sender.send({"ok": True, "result": result})
    except Exception as exc:
        sender.send(
            {
                "ok": False,
                "error_type": _safe_error_type(type(exc).__name__),
                "message": _sanitize_message(
                    str(exc), invocation.battlestar_path, invocation.mission_root
                ),
            }
        )
    finally:
        sender.close()


def _expected_paths(
    output_dir: str, handoff_id: str, *, success: bool
) -> tuple[str, ...]:
    common = (
        f"{output_dir}/handoff/pending/{handoff_id}.json",
        f"{output_dir}/handoff/staging_receipts/{handoff_id}.json",
        f"{output_dir}/handoff/handoff_ledger.jsonl",
        f"{output_dir}/intake/intake_receipts/{handoff_id}.json",
    )
    if not success:
        return common
    return (
        *common,
        f"{output_dir}/intake/shadow_plans/{handoff_id}.json",
        f"{output_dir}/intake/navigator_ledger.jsonl",
    )


def _validate_output_correlations(
    context: NavigatorMissionContext,
    parsed: Mapping[str, Any],
    paths: tuple[str, ...],
) -> None:
    handoff_id = str(parsed["handoff_id"])
    packet_path = context.absolute(context.review_packet_path)
    action_path = context.absolute(context.operator_action_path)
    packet = _read_object(packet_path)
    action = _read_object(action_path)
    packet_sha256 = sha256_file(packet_path)
    action_sha256 = sha256_file(action_path)
    decision_input_hash = packet.get("decision_input_hash")
    expires_at = action.get("expires_at")
    envelope = _read_object(context.absolute(paths[0]))
    staging = _read_object(context.absolute(paths[1]))
    handoff_ledger = _read_jsonl_single(context.absolute(paths[2]))
    intake_receipt = _read_object(context.absolute(paths[3]))
    envelope_sha = sha256_file(context.absolute(paths[0]))
    envelope_schema = envelope.get("schema_version")
    controlled_unsupported_schema = (
        parsed["status"] == StageStatus.FAILED.value
        and parsed.get("intake_status") == NavigatorIntakeStatus.REJECTED.value
        and envelope_schema == "navigator_shadow_handoff_envelope.unsupported"
    )
    staging_timestamp = staging.get("staged_at")
    try:
        normalized_staging_timestamp = normalize_rfc3339(
            staging_timestamp, "Navigator staged_at"
        )
    except ContractValidationError as exc:
        raise NavigatorMalformedResultError(
            "Navigator staging receipt timestamp is malformed"
        ) from exc
    if (
        (
            envelope_schema != NATIVE_HANDOFF_SCHEMA_VERSION
            and not controlled_unsupported_schema
        )
        or envelope.get("handoff_id") != handoff_id
        or envelope.get("source_run_id") != context.mission_id
        or envelope.get("operator_action_id") != context.action_id
        or envelope.get("source_packet_id") != packet.get("packet_id")
        or envelope.get("source_packet_path") != context.review_packet_path
        or envelope.get("source_packet_sha256") != packet_sha256
        or envelope.get("operator_action_path") != context.operator_action_path
        or envelope.get("operator_action_sha256") != action_sha256
        or envelope.get("decision_input_hash") != decision_input_hash
        or envelope.get("expires_at") != expires_at
        or envelope.get("operator_id") != action.get("operator_id")
        or envelope.get("mode") != NavigatorMode.SHADOW.value
        or tuple(envelope.get("allowed_operations", ())) != ALLOWED_OPERATIONS
        or tuple(envelope.get("prohibited_operations", ())) != PROHIBITED_OPERATIONS
    ):
        raise NavigatorMalformedResultError(
            "Navigator handoff envelope correlation is malformed"
        )
    if (
        parsed.get("expires_at") != expires_at
        or parsed.get("intake_receipt_id")
        != _intake_receipt_id(handoff_id, envelope_sha)
        or parsed.get("idempotency_key") != _idempotency_key(handoff_id, envelope_sha)
    ):
        raise NavigatorMalformedResultError(
            "Navigator derived receipt, expiry, or idempotency correlation is malformed"
        )
    if (
        staging.get("schema_version") != NATIVE_STAGING_RECEIPT_SCHEMA_VERSION
        or staging.get("handoff_id") != handoff_id
        or staging.get("source_run_id") != context.mission_id
        or staging.get("envelope_path") != paths[0]
        or staging.get("envelope_sha256") != envelope_sha
        or staging.get("staged_at") != normalized_staging_timestamp
        or staging.get("status") != "STAGED"
        or staging.get("mode") != NavigatorMode.SHADOW.value
    ):
        raise NavigatorMalformedResultError(
            "Navigator staging receipt correlation is malformed"
        )
    if (
        handoff_ledger.get("event_timestamp") != normalized_staging_timestamp
        or handoff_ledger.get("handoff_id") != handoff_id
        or handoff_ledger.get("source_run_id") != context.mission_id
        or handoff_ledger.get("operator_action_id") != context.action_id
        or handoff_ledger.get("mode") != NavigatorMode.SHADOW.value
        or handoff_ledger.get("envelope_sha256") != envelope_sha
        or handoff_ledger.get("pending_path") != paths[0]
        or handoff_ledger.get("status") != "STAGED"
    ):
        raise NavigatorMalformedResultError("Navigator handoff ledger is malformed")
    expected_intake = (
        "ACCEPTED"
        if parsed["status"] == StageStatus.SUCCEEDED.value
        else "REJECTED"
    )
    if (
        intake_receipt.get("schema_version") != NATIVE_INTAKE_RECEIPT_SCHEMA_VERSION
        or intake_receipt.get("handoff_id") != handoff_id
        or intake_receipt.get("source_run_id") != context.mission_id
        or intake_receipt.get("envelope_path") != paths[0]
        or intake_receipt.get("envelope_sha256") != envelope_sha
        or intake_receipt.get("accepted_at") != normalized_staging_timestamp
        or intake_receipt.get("status") != expected_intake
        or intake_receipt.get("mode") != NavigatorMode.SHADOW.value
    ):
        raise NavigatorMalformedResultError("Navigator intake receipt is malformed")
    if parsed["status"] == StageStatus.SUCCEEDED.value:
        plan = _read_object(context.absolute(paths[4]))
        navigator_ledger = _read_jsonl_single(context.absolute(paths[5]))
        expected_plan_id = _shadow_plan_id(handoff_id, context.mission_id, envelope_sha)
        if (
            plan.get("schema_version") != NATIVE_SHADOW_PLAN_SCHEMA_VERSION
            or plan.get("plan_id") != expected_plan_id
            or parsed["plan_id"] != expected_plan_id
            or plan.get("handoff_id") != handoff_id
            or plan.get("source_run_id") != context.mission_id
            or plan.get("created_at") != normalized_staging_timestamp
            or plan.get("expires_at") != expires_at
            or plan.get("planning_status") != "CREATED"
            or not isinstance(plan.get("validated_constraints"), Mapping)
            or plan.get("validated_constraints", {}).get("mode")
            != NavigatorMode.SHADOW.value
            or tuple(
                plan.get("validated_constraints", {}).get("allowed_operations", ())
                if isinstance(plan.get("validated_constraints"), Mapping)
                else ()
            )
            != ALLOWED_OPERATIONS
            or tuple(
                plan.get("validated_constraints", {}).get(
                    "prohibited_operations", ()
                )
                if isinstance(plan.get("validated_constraints"), Mapping)
                else ()
            )
            != PROHIBITED_OPERATIONS
            or tuple(plan.get("prohibited_operations", ())) != PROHIBITED_OPERATIONS
            or intake_receipt.get("shadow_plan_path") != paths[4]
        ):
            raise NavigatorMalformedResultError("Navigator SHADOW plan is malformed")
        plan_hashes = plan.get("source_artifact_hashes")
        plan_refs = plan.get("source_artifact_refs")
        if not isinstance(plan_hashes, Mapping) or not isinstance(plan_refs, Mapping) or any(
            actual != expected
            for actual, expected in (
                (plan_hashes.get("handoff_envelope"), envelope_sha),
                (plan_hashes.get("source_packet"), packet_sha256),
                (plan_hashes.get("operator_action"), action_sha256),
                (plan_refs.get("handoff_envelope"), paths[0]),
                (plan_refs.get("source_packet"), context.review_packet_path),
                (plan_refs.get("operator_action"), context.operator_action_path),
            )
        ):
            raise NavigatorMalformedResultError(
                "Navigator SHADOW plan source lineage is malformed"
            )
        if (
            navigator_ledger.get("event_timestamp") != normalized_staging_timestamp
            or navigator_ledger.get("handoff_id") != handoff_id
            or navigator_ledger.get("source_run_id") != context.mission_id
            or navigator_ledger.get("envelope_sha256") != envelope_sha
            or navigator_ledger.get("intake_receipt_path") != paths[3]
            or navigator_ledger.get("shadow_plan_path") != paths[4]
            or navigator_ledger.get("status") != "ACCEPTED"
        ):
            raise NavigatorMalformedResultError("Navigator intake ledger is malformed")


def _shadow_plan_id(
    handoff_id: str, source_run_id: str, envelope_sha256: str
) -> str:
    seed = {
        "handoff_id": handoff_id,
        "source_run_id": source_run_id,
        "envelope_sha256": envelope_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"navigator-shadow-plan-{digest}"


def _validate_packet_sources(packet: Mapping[str, Any], mission_root: Path) -> None:
    paths = packet.get("source_artifact_paths")
    hashes = packet.get("source_artifact_hashes")
    if not isinstance(paths, Mapping) or not isinstance(hashes, Mapping) or not paths:
        raise NavigatorMalformedResultError(
            "operator packet source artifact paths and hashes are required"
        )
    if set(paths) != set(hashes):
        raise NavigatorMalformedResultError(
            "operator packet source artifact mappings are inconsistent"
        )
    for name, relative in paths.items():
        if not isinstance(name, str):
            raise NavigatorMalformedResultError("operator packet source name is invalid")
        safe = _validate_relative_path(relative, f"source artifact {name}")
        candidate = mission_root / safe
        if candidate.is_symlink():
            raise NavigatorMalformedResultError(
                "operator packet source artifact integrity validation failed"
            )
        path = candidate.resolve(strict=False)
        if (
            not _is_relative_to(path, mission_root)
            or not path.is_file()
            or hashes[name] != sha256_file(path)
        ):
            raise NavigatorMalformedResultError(
                "operator packet source artifact integrity validation failed"
            )
    run_id = packet.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise NavigatorMalformedResultError("operator packet run_id is missing")
    expected_hash = hashlib.sha256(
        json.dumps(
            {
                "run_id": run_id,
                "source_hashes": {str(key): str(value) for key, value in hashes.items()},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if packet.get("decision_input_hash") != expected_hash:
        raise NavigatorMalformedResultError(
            "operator packet decision_input_hash does not match source hashes"
        )


def _validate_operator_lineage(
    lineage: Mapping[str, Any],
    *,
    context: NavigatorMissionContext,
    request_id: str,
    observed_at: str,
    packet_sha256: str,
    action_sha256: str,
) -> None:
    outputs = lineage.get("outputs")
    if not isinstance(outputs, list):
        raise NavigatorMalformedResultError("operator lineage outputs are malformed")
    by_name = {
        item.get("name"): item
        for item in outputs
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    expected = {
        "operator_review_packet": (context.review_packet_path, packet_sha256),
        "operator_action": (context.operator_action_path, action_sha256),
    }
    for name, (path, digest) in expected.items():
        entry = by_name.get(name)
        if not isinstance(entry, Mapping) or any(
            entry.get(field) != wanted
            for field, wanted in (
                ("path", path),
                ("sha256", digest),
                ("producer", "operator"),
                ("mission_id", context.mission_id),
                ("request_id", request_id),
                ("observed_at", observed_at),
            )
        ):
            raise NavigatorMalformedResultError(
                f"operator lineage does not validate {name}"
            )


def _validate_native_relative_path(value: object, output_dir: str) -> str:
    if not isinstance(value, str):
        raise NavigatorMalformedResultError("Navigator artifact path must be a string")
    try:
        path = _validate_relative_path(value, "Navigator artifact path")
    except NavigatorAdapterValidationError as exc:
        raise NavigatorMalformedResultError(str(exc)) from exc
    if not path.startswith(f"{output_dir}/"):
        raise NavigatorMalformedResultError(
            "Navigator artifact path must remain beneath output_dir"
        )
    return path


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = parse_strict_json_object_bytes(
            path.read_bytes(), document_name=f"JSON artifact {path.name}"
        )
    except (OSError, ContractValidationError) as exc:
        raise NavigatorMalformedResultError(f"malformed JSON artifact: {path.name}") from exc
    return dict(payload)


def _read_jsonl_single(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise NavigatorMalformedResultError(f"could not read ledger {path.name}") from exc
    if len(lines) != 1:
        raise NavigatorMalformedResultError(
            f"Navigator ledger {path.name} must contain exactly one immutable entry"
        )
    return _read_json_bytes(lines[0], path.name)


def _read_json_bytes(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NavigatorMalformedResultError(f"malformed JSON artifact: {name}") from exc
    if not isinstance(value, dict):
        raise NavigatorMalformedResultError(f"JSON artifact {name} must be an object")
    return value


def _reject_absolute_leaks(payload: bytes, name: str) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NavigatorMalformedResultError(f"{name} is not UTF-8") from exc
    if _ABSOLUTE_POSIX_PATH.search(text) or _ABSOLUTE_WINDOWS_PATH.search(text):
        raise NavigatorMalformedResultError(f"{name} contains an absolute path")


def _transport_identifier(value: object, name: str) -> str:
    try:
        return validate_identifier(value, name)
    except IdentifierError as exc:
        raise NavigatorMalformedResultError(str(exc)) from exc


def _operation_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise NavigatorMalformedResultError(f"Navigator {name} must be an array")
    operations: list[str] = []
    for item in value:
        operations.append(_transport_identifier(item, name))
    if len(set(operations)) != len(operations):
        raise NavigatorMalformedResultError(f"Navigator {name} contains duplicates")
    return tuple(operations)


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise NavigatorMalformedResultError(f"Navigator {name} must be a boolean")
    return value


def _strict_transport_message(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NavigatorMalformedResultError(
            "Navigator failure message must be a nonblank string"
        )
    return value.strip()[:512]


def _require_module_origin(module: Any, expected: Path) -> None:
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str) or Path(origin).resolve(strict=True) != expected.resolve(
        strict=True
    ):
        raise NavigatorAdapterValidationError(
            f"loaded unexpected Battlestar module origin for {expected.name}"
        )


def _intake_receipt_id(handoff_id: str, envelope_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{handoff_id}:{envelope_sha256}:intake-receipt".encode("utf-8")
    ).hexdigest()[:16]
    return f"navigator-intake-receipt-{digest}"


def _idempotency_key(handoff_id: str, envelope_sha256: str) -> str:
    digest = hashlib.sha256(
        f"{handoff_id}:{envelope_sha256}:shadow-intake".encode("utf-8")
    ).hexdigest()[:24]
    return f"navigator-shadow-{digest}"


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "NavigatorError"


def _sanitize_message(message: str, *roots: Path) -> str:
    sanitized = str(message)
    for root in roots:
        sanitized = sanitized.replace(str(root), "<redacted-path>")
    sanitized = _ABSOLUTE_POSIX_PATH.sub("<redacted-path>", sanitized)
    sanitized = _ABSOLUTE_WINDOWS_PATH.sub("<redacted-path>", sanitized)
    sanitized = " ".join(sanitized.split())[:512]
    return sanitized or "Navigator technical failure"
