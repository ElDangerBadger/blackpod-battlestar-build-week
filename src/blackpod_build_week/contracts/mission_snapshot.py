"""Canonical mission snapshot contract for the Build Week submission."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_request import (
    ContractValidationError,
    RunMode,
    normalize_rfc3339,
    parse_rfc3339,
)


MISSION_SNAPSHOT_SCHEMA_VERSION = "blackpod.mission_snapshot.v1"
STAGE_NAMES = ("harbormaster", "oracle", "council", "governor", "navigator")
_SNAPSHOT_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "snapshot_id",
        "mission_id",
        "request_id",
        "revision",
        "previous_snapshot_sha256",
        "run_mode",
        "started_at",
        "observed_at",
        "mission_outcome",
        "current_phase",
        "terminal",
        "stages",
        "artifacts",
    }
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class MissionOutcome(str, Enum):
    APPROVED = "APPROVED"
    HELD = "HELD"
    VETOED = "VETOED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class CurrentPhase(str, Enum):
    HARBORMASTER = "HARBORMASTER"
    ORACLE = "ORACLE"
    COUNCIL = "COUNCIL"
    GOVERNOR = "GOVERNOR"
    OPERATOR = "OPERATOR"
    NAVIGATOR = "NAVIGATOR"
    COMPLETE = "COMPLETE"


class OracleTransportKind(str, Enum):
    LIVE_YFINANCE = "LIVE_YFINANCE"
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


class CouncilTransportKind(str, Enum):
    LIVE_MISSION_INPUTS = "LIVE_MISSION_INPUTS"
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


class GovernorTransportKind(str, Enum):
    LIVE_MISSION_INPUTS = "LIVE_MISSION_INPUTS"
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


class OperatorRoute(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PENDING_REVIEW = "PENDING_REVIEW"
    CLOSED_BLOCKED = "CLOSED_BLOCKED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class OperatorActionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class OperatorAction(str, Enum):
    APPROVE_HANDOFF = "APPROVE_HANDOFF"
    REJECT = "REJECT"


class OperatorResult(str, Enum):
    APPROVED_FOR_HANDOFF = "APPROVED_FOR_HANDOFF"
    REJECTED = "REJECTED"


class NavigatorMode(str, Enum):
    SHADOW = "SHADOW"


class NavigatorHandoffStatus(str, Enum):
    STAGED = "STAGED"


class NavigatorIntakeStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NavigatorPlanStatus(str, Enum):
    CREATED = "CREATED"


class ApprovalScope(str, Enum):
    NAVIGATOR_SHADOW_HANDOFF = "NAVIGATOR_SHADOW_HANDOFF"


NAVIGATOR_ALLOWED_OPERATIONS = ("VALIDATE", "PLAN_ONLY")
NAVIGATOR_PROHIBITED_OPERATIONS = (
    "SUBMIT_ORDER",
    "CANCEL_ORDER",
    "MODIFY_PORTFOLIO",
    "BROKER_CALL",
)


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], name: str
) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _parse_enum(enum_type: type[Enum], value: object, field_name: str) -> Any:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(str(member.value) for member in enum_type)
        raise ContractValidationError(
            f"unsupported {field_name}: {value!r}; expected one of {choices}"
        ) from exc


def _validate_text(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
    max_length: int = 512,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank string")
    if value != value.strip():
        raise ContractValidationError(f"{field_name} may not have surrounding whitespace")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{field_name} must contain valid Unicode text") from exc
    return value


def _artifact_names(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be an array")
    names: list[str] = []
    for item in value:
        try:
            name = validate_identifier(item, field_name)
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        names.append(name)
    if len(set(names)) != len(names):
        raise ContractValidationError(f"{field_name} values must be unique")
    return tuple(names)


@dataclass(frozen=True, slots=True)
class StageError:
    code: str
    error_type: str
    message: str
    resumable: bool
    observed_at: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StageError":
        if not isinstance(value, Mapping):
            raise ContractValidationError("stage error must be an object")
        _require_exact_fields(
            value,
            {"code", "error_type", "message", "resumable", "observed_at"},
            "stage error",
        )
        try:
            code = validate_identifier(value["code"], "stage error code")
            error_type = validate_identifier(value["error_type"], "stage error type")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if type(value["resumable"]) is not bool:
            raise ContractValidationError("stage error resumable must be a boolean")
        return cls(
            code=code,
            error_type=error_type,
            message=str(_validate_text(value["message"], "stage error message")),
            resumable=value["resumable"],
            observed_at=normalize_rfc3339(value["observed_at"], "stage error observed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "error_type": self.error_type,
            "message": self.message,
            "resumable": self.resumable,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    status: StageStatus
    native_state: str | None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    error: StageError | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], stage_name: str) -> "StageSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError(f"stage {stage_name} must be an object")
        fields = set(value)
        legacy_fields = {"status", "native_state"}
        current_fields = legacy_fields | {"inputs", "outputs", "error"}
        if fields == legacy_fields:
            inputs: tuple[str, ...] = ()
            outputs: tuple[str, ...] = ()
            error = None
        elif fields == current_fields:
            inputs = _artifact_names(value["inputs"], f"{stage_name}.inputs")
            outputs = _artifact_names(value["outputs"], f"{stage_name}.outputs")
            error_value = value["error"]
            error = None if error_value is None else StageError.from_mapping(error_value)
        else:
            _require_exact_fields(value, current_fields, f"stage {stage_name}")
            raise AssertionError("unreachable")

        status = _parse_enum(StageStatus, value["status"], f"{stage_name}.status")
        native_state = _validate_text(
            value["native_state"],
            f"{stage_name}.native_state",
            allow_none=True,
            max_length=128,
        )
        if status is StageStatus.NOT_STARTED and (
            native_state is not None or inputs or outputs or error is not None
        ):
            raise ContractValidationError(
                f"{stage_name} NOT_STARTED may not contain native state, I/O, or an error"
            )
        if status is StageStatus.FAILED and error is None:
            raise ContractValidationError(f"{stage_name} FAILED requires a structured error")
        if status is not StageStatus.FAILED and error is not None:
            raise ContractValidationError(
                f"{stage_name} may contain an error only when status is FAILED"
            )
        return cls(
            status=status,
            native_state=native_state,
            inputs=inputs,
            outputs=outputs,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "native_state": self.native_state,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OperatorState:
    """Auditable operator-routing and explicit handoff-action state."""

    route: OperatorRoute | None
    action_status: OperatorActionStatus = OperatorActionStatus.NOT_STARTED
    action: OperatorAction | None = None
    result: OperatorResult | None = None
    action_id: str | None = None
    operator_id: str | None = None
    acted_at: str | None = None
    error: StageError | None = None

    @classmethod
    def empty(cls) -> "OperatorState":
        return cls(route=None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OperatorState":
        if not isinstance(value, Mapping):
            raise ContractValidationError("operator state must be an object")
        fields = set(value)
        legacy_fields = {"route", "action", "result", "operator_id", "acted_at"}
        current_fields = legacy_fields | {"action_status", "action_id", "error"}
        if fields == legacy_fields:
            if any(value[field_name] is not None for field_name in legacy_fields - {"route"}):
                raise ContractValidationError(
                    "legacy operator action fields must remain null"
                )
            action_status = OperatorActionStatus.NOT_STARTED
            action = None
            result = None
            action_id = None
            operator_id = None
            acted_at = None
            error = None
        elif fields == current_fields:
            action_status = _parse_enum(
                OperatorActionStatus,
                value["action_status"],
                "operator action_status",
            )
            action = (
                None
                if value["action"] is None
                else _parse_enum(OperatorAction, value["action"], "operator action")
            )
            result = (
                None
                if value["result"] is None
                else _parse_enum(OperatorResult, value["result"], "operator result")
            )
            try:
                action_id = (
                    None
                    if value["action_id"] is None
                    else validate_identifier(value["action_id"], "operator action_id")
                )
                operator_id = (
                    None
                    if value["operator_id"] is None
                    else validate_identifier(value["operator_id"], "operator operator_id")
                )
            except IdentifierError as exc:
                raise ContractValidationError(str(exc)) from exc
            acted_at = (
                None
                if value["acted_at"] is None
                else normalize_rfc3339(value["acted_at"], "operator acted_at")
            )
            error_value = value["error"]
            error = None if error_value is None else StageError.from_mapping(error_value)
        else:
            _require_exact_fields(value, current_fields, "operator state")
            raise AssertionError("unreachable")

        route_value = value["route"]
        route = (
            None
            if route_value is None
            else _parse_enum(OperatorRoute, route_value, "operator route")
        )

        has_attempt_identity = action is not None and operator_id is not None
        has_completed_identity = has_attempt_identity and action_id is not None
        if action_status is OperatorActionStatus.NOT_STARTED:
            if any(
                item is not None
                for item in (action, result, action_id, operator_id, acted_at, error)
            ):
                raise ContractValidationError(
                    "operator NOT_STARTED may not contain action state"
                )
        elif action_status is OperatorActionStatus.RUNNING:
            if not has_attempt_identity or any(
                item is not None for item in (result, action_id, acted_at, error)
            ):
                raise ContractValidationError(
                    "operator RUNNING requires actor identity and no native result or action ID"
                )
        elif action_status is OperatorActionStatus.SUCCEEDED:
            if (
                not has_completed_identity
                or result is None
                or acted_at is None
                or error is not None
            ):
                raise ContractValidationError(
                    "operator SUCCEEDED requires action identity, result, and acted_at"
                )
            expected_result = {
                OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
                OperatorAction.REJECT: OperatorResult.REJECTED,
            }[action]
            if result is not expected_result:
                raise ContractValidationError(
                    "operator action and result are inconsistent"
                )
        else:
            if (
                not has_attempt_identity
                or result is not None
                or acted_at is None
                or error is None
            ):
                raise ContractValidationError(
                    "operator FAILED requires action identity, acted_at, and an error"
                )
            if error.observed_at != acted_at:
                raise ContractValidationError(
                    "operator failure timestamp must match acted_at"
                )

        if action_status is not OperatorActionStatus.NOT_STARTED and route is not OperatorRoute.PENDING_APPROVAL:
            raise ContractValidationError(
                "operator actions require the PENDING_APPROVAL route"
            )
        return cls(
            route=route,
            action_status=action_status,
            action=action,
            result=result,
            action_id=action_id,
            operator_id=operator_id,
            acted_at=acted_at,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": None if self.route is None else self.route.value,
            "action_status": self.action_status.value,
            "action": None if self.action is None else self.action.value,
            "result": None if self.result is None else self.result.value,
            "action_id": self.action_id,
            "operator_id": self.operator_id,
            "acted_at": self.acted_at,
            "error": None if self.error is None else self.error.to_dict(),
        }


def _operation_names(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be an array")
    operations: list[str] = []
    for item in value:
        try:
            operations.append(validate_identifier(item, field_name))
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
    if len(set(operations)) != len(operations):
        raise ContractValidationError(f"{field_name} values must be unique")
    return tuple(operations)


@dataclass(frozen=True, slots=True)
class NavigatorState:
    """Structured state for the non-executing Navigator SHADOW handoff."""

    mode: NavigatorMode | None
    handoff_status: NavigatorHandoffStatus | None
    intake_status: NavigatorIntakeStatus | None
    plan_status: NavigatorPlanStatus | None
    handoff_id: str | None
    intake_receipt_id: str | None
    plan_id: str | None
    expires_at: str | None
    idempotency_key: str | None
    allowed_operations: tuple[str, ...]
    prohibited_operations: tuple[str, ...]

    @classmethod
    def empty(cls) -> "NavigatorState":
        return cls(
            mode=None,
            handoff_status=None,
            intake_status=None,
            plan_status=None,
            handoff_id=None,
            intake_receipt_id=None,
            plan_id=None,
            expires_at=None,
            idempotency_key=None,
            allowed_operations=(),
            prohibited_operations=(),
        )

    @classmethod
    def shadow_running(cls) -> "NavigatorState":
        return cls.from_mapping(
            {
                "mode": NavigatorMode.SHADOW.value,
                "handoff_status": None,
                "intake_status": None,
                "plan_status": None,
                "handoff_id": None,
                "intake_receipt_id": None,
                "plan_id": None,
                "expires_at": None,
                "idempotency_key": None,
                "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
                "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
            }
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NavigatorState":
        if not isinstance(value, Mapping):
            raise ContractValidationError("navigator state must be an object")
        fields = {
            "mode",
            "handoff_status",
            "intake_status",
            "plan_status",
            "handoff_id",
            "intake_receipt_id",
            "plan_id",
            "expires_at",
            "idempotency_key",
            "allowed_operations",
            "prohibited_operations",
        }
        _require_exact_fields(value, fields, "navigator state")
        mode = (
            None
            if value["mode"] is None
            else _parse_enum(NavigatorMode, value["mode"], "navigator mode")
        )
        handoff_status = (
            None
            if value["handoff_status"] is None
            else _parse_enum(
                NavigatorHandoffStatus,
                value["handoff_status"],
                "navigator handoff_status",
            )
        )
        intake_status = (
            None
            if value["intake_status"] is None
            else _parse_enum(
                NavigatorIntakeStatus,
                value["intake_status"],
                "navigator intake_status",
            )
        )
        plan_status = (
            None
            if value["plan_status"] is None
            else _parse_enum(
                NavigatorPlanStatus,
                value["plan_status"],
                "navigator plan_status",
            )
        )
        identifiers: dict[str, str | None] = {}
        try:
            for field_name in (
                "handoff_id",
                "intake_receipt_id",
                "plan_id",
                "idempotency_key",
            ):
                identifiers[field_name] = (
                    None
                    if value[field_name] is None
                    else validate_identifier(value[field_name], f"navigator {field_name}")
                )
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        expires_at = (
            None
            if value["expires_at"] is None
            else normalize_rfc3339(value["expires_at"], "navigator expires_at")
        )
        allowed = _operation_names(
            value["allowed_operations"], "navigator allowed_operations"
        )
        prohibited = _operation_names(
            value["prohibited_operations"], "navigator prohibited_operations"
        )

        if mode is None:
            if any(
                item is not None
                for item in (
                    handoff_status,
                    intake_status,
                    plan_status,
                    *identifiers.values(),
                    expires_at,
                )
            ) or allowed or prohibited:
                raise ContractValidationError(
                    "empty navigator state may not contain SHADOW progress"
                )
        else:
            if allowed != NAVIGATOR_ALLOWED_OPERATIONS:
                raise ContractValidationError(
                    "Navigator SHADOW allowed_operations must be exactly VALIDATE and PLAN_ONLY"
                )
            if prohibited != NAVIGATOR_PROHIBITED_OPERATIONS:
                raise ContractValidationError(
                    "Navigator SHADOW prohibited_operations must be exactly the non-execution envelope"
                )
            if (handoff_status is None) != (identifiers["handoff_id"] is None):
                raise ContractValidationError(
                    "navigator handoff status and handoff_id must appear together"
                )
            if (intake_status is None) != (identifiers["intake_receipt_id"] is None):
                raise ContractValidationError(
                    "navigator intake status and receipt ID must appear together"
                )
            if (plan_status is None) != (identifiers["plan_id"] is None):
                raise ContractValidationError(
                    "navigator plan status and plan_id must appear together"
                )
            if intake_status is not None and handoff_status is None:
                raise ContractValidationError(
                    "navigator intake requires a staged handoff"
                )
            if plan_status is not None and intake_status is not NavigatorIntakeStatus.ACCEPTED:
                raise ContractValidationError(
                    "navigator plan creation requires accepted intake"
                )
            if expires_at is not None and handoff_status is None:
                raise ContractValidationError(
                    "navigator expires_at requires a staged handoff"
                )
            if identifiers["idempotency_key"] is not None and handoff_status is None:
                raise ContractValidationError(
                    "navigator idempotency_key requires a staged handoff"
                )

        return cls(
            mode=mode,
            handoff_status=handoff_status,
            intake_status=intake_status,
            plan_status=plan_status,
            handoff_id=identifiers["handoff_id"],
            intake_receipt_id=identifiers["intake_receipt_id"],
            plan_id=identifiers["plan_id"],
            expires_at=expires_at,
            idempotency_key=identifiers["idempotency_key"],
            allowed_operations=allowed,
            prohibited_operations=prohibited,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": None if self.mode is None else self.mode.value,
            "handoff_status": (
                None if self.handoff_status is None else self.handoff_status.value
            ),
            "intake_status": (
                None if self.intake_status is None else self.intake_status.value
            ),
            "plan_status": None if self.plan_status is None else self.plan_status.value,
            "handoff_id": self.handoff_id,
            "intake_receipt_id": self.intake_receipt_id,
            "plan_id": self.plan_id,
            "expires_at": self.expires_at,
            "idempotency_key": self.idempotency_key,
            "allowed_operations": list(self.allowed_operations),
            "prohibited_operations": list(self.prohibited_operations),
        }


def _validate_relative_artifact_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractValidationError("artifact path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ContractValidationError("artifact path must remain beneath the mission root")
    if any(part in {"", "."} for part in path.parts):
        raise ContractValidationError("artifact path contains an unsafe segment")
    _validate_text(value, "artifact path", max_length=512)
    return value


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    name: str
    path: str
    sha256: str
    producer: str | None = None
    byte_size: int | None = None
    schema_version: str | None = None
    observed_at: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactReference":
        if not isinstance(value, Mapping):
            raise ContractValidationError("artifact reference must be an object")
        fields = set(value)
        legacy_fields = {"name", "path", "sha256"}
        current_fields = legacy_fields | {
            "producer",
            "byte_size",
            "schema_version",
            "observed_at",
        }
        if fields == legacy_fields:
            producer = None
            byte_size = None
            schema_version = None
            observed_at = None
        elif fields == current_fields:
            producer_value = value["producer"]
            try:
                producer = validate_identifier(producer_value, "artifact producer")
            except IdentifierError as exc:
                raise ContractValidationError(str(exc)) from exc
            byte_size_value = value["byte_size"]
            if (
                isinstance(byte_size_value, bool)
                or not isinstance(byte_size_value, int)
                or byte_size_value < 0
            ):
                raise ContractValidationError(
                    "artifact byte_size must be a nonnegative integer"
                )
            byte_size = byte_size_value
            schema_version = _validate_text(
                value["schema_version"],
                "artifact schema_version",
                allow_none=True,
                max_length=128,
            )
            observed_value = value["observed_at"]
            observed_at = normalize_rfc3339(observed_value, "artifact observed_at")
        else:
            _require_exact_fields(value, current_fields, "artifact reference")
            raise AssertionError("unreachable")

        try:
            name = validate_identifier(value["name"], "artifact name")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        digest = value["sha256"]
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ContractValidationError(
                "artifact sha256 must be 64 lowercase hex characters"
            )
        return cls(
            name=name,
            path=_validate_relative_artifact_path(value["path"]),
            sha256=digest,
            producer=producer,
            byte_size=byte_size,
            schema_version=schema_version,
            observed_at=observed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        if (
            self.producer is None
            and self.byte_size is None
            and self.schema_version is None
            and self.observed_at is None
        ):
            return {"name": self.name, "path": self.path, "sha256": self.sha256}
        return {
            "name": self.name,
            "path": self.path,
            "sha256": self.sha256,
            "producer": self.producer,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class ComponentProvenance:
    git_revision: str
    git_branch: str | None
    dirty_worktree: bool
    oracle_entry_point: str
    run_mode: RunMode
    transport: OracleTransportKind
    replay_fixture_id: str | None
    replay_fixture_sha256: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ComponentProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError("component provenance must be an object")
        _require_exact_fields(
            value,
            {
                "git_revision",
                "git_branch",
                "dirty_worktree",
                "oracle_entry_point",
                "run_mode",
                "transport",
                "replay_fixture_id",
                "replay_fixture_sha256",
            },
            "component provenance",
        )
        revision = value["git_revision"]
        if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(revision):
            raise ContractValidationError("git_revision must be a hexadecimal Git object ID")
        branch = _validate_text(
            value["git_branch"], "git_branch", allow_none=True, max_length=256
        )
        if type(value["dirty_worktree"]) is not bool:
            raise ContractValidationError("dirty_worktree must be a boolean")
        run_mode = _parse_enum(RunMode, value["run_mode"], "component run_mode")
        transport = _parse_enum(
            OracleTransportKind, value["transport"], "Oracle transport"
        )
        fixture_id = _validate_text(
            value["replay_fixture_id"],
            "replay_fixture_id",
            allow_none=True,
            max_length=128,
        )
        fixture_sha = value["replay_fixture_sha256"]
        if fixture_sha is not None and (
            not isinstance(fixture_sha, str) or not _SHA256_PATTERN.fullmatch(fixture_sha)
        ):
            raise ContractValidationError(
                "replay_fixture_sha256 must be null or 64 lowercase hex characters"
            )
        if transport is OracleTransportKind.REPLAY_FIXTURE:
            if run_mode is not RunMode.REPLAY or fixture_id is None or fixture_sha is None:
                raise ContractValidationError(
                    "REPLAY_FIXTURE provenance requires REPLAY mode and fixture identity"
                )
        elif run_mode is not RunMode.LIVE or fixture_id is not None or fixture_sha is not None:
            raise ContractValidationError(
                "LIVE_YFINANCE provenance requires LIVE mode and no replay fixture"
            )
        return cls(
            git_revision=revision,
            git_branch=branch,
            dirty_worktree=value["dirty_worktree"],
            oracle_entry_point=str(
                _validate_text(
                    value["oracle_entry_point"],
                    "oracle_entry_point",
                    max_length=256,
                )
            ),
            run_mode=run_mode,
            transport=transport,
            replay_fixture_id=fixture_id,
            replay_fixture_sha256=fixture_sha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "git_branch": self.git_branch,
            "dirty_worktree": self.dirty_worktree,
            "oracle_entry_point": self.oracle_entry_point,
            "run_mode": self.run_mode.value,
            "transport": self.transport.value,
            "replay_fixture_id": self.replay_fixture_id,
            "replay_fixture_sha256": self.replay_fixture_sha256,
        }


@dataclass(frozen=True, slots=True)
class CouncilComponentProvenance:
    """Immutable provenance for the Battlestar Council evidence chain."""

    git_revision: str
    git_branch: str | None
    dirty_worktree: bool
    candidate_entry_point: str
    senate_review_entry_point: str
    senate_deliberation_entry_point: str
    mandate_entry_point: str
    runtime_validation_entry_point: str
    advisor_health_entry_point: str
    council_synthesis_entry_point: str
    council_executive_summary_entry_point: str
    run_mode: RunMode
    transport: CouncilTransportKind
    replay_fixture_id: str | None
    replay_fixture_sha256: str | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "CouncilComponentProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Council component provenance must be an object")
        entry_point_fields = (
            "candidate_entry_point",
            "senate_review_entry_point",
            "senate_deliberation_entry_point",
            "mandate_entry_point",
            "runtime_validation_entry_point",
            "advisor_health_entry_point",
            "council_synthesis_entry_point",
            "council_executive_summary_entry_point",
        )
        _require_exact_fields(
            value,
            {
                "git_revision",
                "git_branch",
                "dirty_worktree",
                *entry_point_fields,
                "run_mode",
                "transport",
                "replay_fixture_id",
                "replay_fixture_sha256",
            },
            "Council component provenance",
        )
        revision = value["git_revision"]
        if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(revision):
            raise ContractValidationError(
                "git_revision must be a hexadecimal Git object ID"
            )
        branch = _validate_text(
            value["git_branch"], "git_branch", allow_none=True, max_length=256
        )
        if type(value["dirty_worktree"]) is not bool:
            raise ContractValidationError("dirty_worktree must be a boolean")
        entry_points = {
            field_name: str(
                _validate_text(value[field_name], field_name, max_length=256)
            )
            for field_name in entry_point_fields
        }
        run_mode = _parse_enum(RunMode, value["run_mode"], "component run_mode")
        transport = _parse_enum(
            CouncilTransportKind, value["transport"], "Council transport"
        )
        fixture_id = _validate_text(
            value["replay_fixture_id"],
            "replay_fixture_id",
            allow_none=True,
            max_length=128,
        )
        fixture_sha = value["replay_fixture_sha256"]
        if fixture_sha is not None and (
            not isinstance(fixture_sha, str) or not _SHA256_PATTERN.fullmatch(fixture_sha)
        ):
            raise ContractValidationError(
                "replay_fixture_sha256 must be null or 64 lowercase hex characters"
            )
        if transport is CouncilTransportKind.REPLAY_FIXTURE:
            if run_mode is not RunMode.REPLAY or fixture_id is None or fixture_sha is None:
                raise ContractValidationError(
                    "Council REPLAY_FIXTURE provenance requires REPLAY mode and fixture identity"
                )
        elif run_mode is not RunMode.LIVE or fixture_id is not None or fixture_sha is not None:
            raise ContractValidationError(
                "LIVE_MISSION_INPUTS provenance requires LIVE mode and no replay fixture"
            )
        return cls(
            git_revision=revision,
            git_branch=branch,
            dirty_worktree=value["dirty_worktree"],
            candidate_entry_point=entry_points["candidate_entry_point"],
            senate_review_entry_point=entry_points["senate_review_entry_point"],
            senate_deliberation_entry_point=entry_points[
                "senate_deliberation_entry_point"
            ],
            mandate_entry_point=entry_points["mandate_entry_point"],
            runtime_validation_entry_point=entry_points[
                "runtime_validation_entry_point"
            ],
            advisor_health_entry_point=entry_points["advisor_health_entry_point"],
            council_synthesis_entry_point=entry_points[
                "council_synthesis_entry_point"
            ],
            council_executive_summary_entry_point=entry_points[
                "council_executive_summary_entry_point"
            ],
            run_mode=run_mode,
            transport=transport,
            replay_fixture_id=fixture_id,
            replay_fixture_sha256=fixture_sha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "git_branch": self.git_branch,
            "dirty_worktree": self.dirty_worktree,
            "candidate_entry_point": self.candidate_entry_point,
            "senate_review_entry_point": self.senate_review_entry_point,
            "senate_deliberation_entry_point": self.senate_deliberation_entry_point,
            "mandate_entry_point": self.mandate_entry_point,
            "runtime_validation_entry_point": self.runtime_validation_entry_point,
            "advisor_health_entry_point": self.advisor_health_entry_point,
            "council_synthesis_entry_point": self.council_synthesis_entry_point,
            "council_executive_summary_entry_point": (
                self.council_executive_summary_entry_point
            ),
            "run_mode": self.run_mode.value,
            "transport": self.transport.value,
            "replay_fixture_id": self.replay_fixture_id,
            "replay_fixture_sha256": self.replay_fixture_sha256,
        }


@dataclass(frozen=True, slots=True)
class GovernorComponentProvenance:
    """Immutable provenance for the current rendered Governor chain."""

    git_revision: str
    git_branch: str | None
    dirty_worktree: bool
    senate_intake_entry_point: str
    preparation_entry_point: str
    deliberation_entry_point: str
    readiness_entry_point: str
    rendering_entry_point: str
    run_mode: RunMode
    transport: GovernorTransportKind
    replay_fixture_id: str | None
    replay_fixture_sha256: str | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "GovernorComponentProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError(
                "Governor component provenance must be an object"
            )
        entry_point_fields = (
            "senate_intake_entry_point",
            "preparation_entry_point",
            "deliberation_entry_point",
            "readiness_entry_point",
            "rendering_entry_point",
        )
        _require_exact_fields(
            value,
            {
                "git_revision",
                "git_branch",
                "dirty_worktree",
                *entry_point_fields,
                "run_mode",
                "transport",
                "replay_fixture_id",
                "replay_fixture_sha256",
            },
            "Governor component provenance",
        )
        revision = value["git_revision"]
        if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(
            revision
        ):
            raise ContractValidationError(
                "git_revision must be a hexadecimal Git object ID"
            )
        branch = _validate_text(
            value["git_branch"], "git_branch", allow_none=True, max_length=256
        )
        if type(value["dirty_worktree"]) is not bool:
            raise ContractValidationError("dirty_worktree must be a boolean")
        entry_points = {
            field_name: str(
                _validate_text(value[field_name], field_name, max_length=256)
            )
            for field_name in entry_point_fields
        }
        run_mode = _parse_enum(RunMode, value["run_mode"], "component run_mode")
        transport = _parse_enum(
            GovernorTransportKind, value["transport"], "Governor transport"
        )
        fixture_id = _validate_text(
            value["replay_fixture_id"],
            "replay_fixture_id",
            allow_none=True,
            max_length=128,
        )
        fixture_sha = value["replay_fixture_sha256"]
        if fixture_sha is not None and (
            not isinstance(fixture_sha, str)
            or not _SHA256_PATTERN.fullmatch(fixture_sha)
        ):
            raise ContractValidationError(
                "replay_fixture_sha256 must be null or 64 lowercase hex characters"
            )
        if transport is GovernorTransportKind.REPLAY_FIXTURE:
            if (
                run_mode is not RunMode.REPLAY
                or fixture_id is None
                or fixture_sha is None
            ):
                raise ContractValidationError(
                    "Governor REPLAY_FIXTURE provenance requires REPLAY mode and fixture identity"
                )
        elif (
            run_mode is not RunMode.LIVE
            or fixture_id is not None
            or fixture_sha is not None
        ):
            raise ContractValidationError(
                "Governor LIVE_MISSION_INPUTS provenance requires LIVE mode and no replay fixture"
            )
        return cls(
            git_revision=revision,
            git_branch=branch,
            dirty_worktree=value["dirty_worktree"],
            senate_intake_entry_point=entry_points["senate_intake_entry_point"],
            preparation_entry_point=entry_points["preparation_entry_point"],
            deliberation_entry_point=entry_points["deliberation_entry_point"],
            readiness_entry_point=entry_points["readiness_entry_point"],
            rendering_entry_point=entry_points["rendering_entry_point"],
            run_mode=run_mode,
            transport=transport,
            replay_fixture_id=fixture_id,
            replay_fixture_sha256=fixture_sha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "git_branch": self.git_branch,
            "dirty_worktree": self.dirty_worktree,
            "senate_intake_entry_point": self.senate_intake_entry_point,
            "preparation_entry_point": self.preparation_entry_point,
            "deliberation_entry_point": self.deliberation_entry_point,
            "readiness_entry_point": self.readiness_entry_point,
            "rendering_entry_point": self.rendering_entry_point,
            "run_mode": self.run_mode.value,
            "transport": self.transport.value,
            "replay_fixture_id": self.replay_fixture_id,
            "replay_fixture_sha256": self.replay_fixture_sha256,
        }


def _validate_operator_route(
    operator: OperatorState,
    *,
    navigator: NavigatorState,
    approval_scope: ApprovalScope | None,
    stages: Mapping[str, StageSnapshot],
    current_phase: CurrentPhase,
    mission_outcome: MissionOutcome,
    terminal: bool,
) -> None:
    route = operator.route
    governor = stages["governor"]
    navigator_stage = stages["navigator"]
    empty_navigator = NavigatorState.empty()

    if route is None:
        if governor.status is StageStatus.SUCCEEDED:
            raise ContractValidationError(
                "a technically successful Governor stage requires an operator route"
            )
        if operator.action_status is not OperatorActionStatus.NOT_STARTED:
            raise ContractValidationError("operator action may not precede Governor routing")
        if navigator_stage.status is not StageStatus.NOT_STARTED:
            raise ContractValidationError("Navigator may not precede operator approval")
        if navigator != empty_navigator or approval_scope is not None:
            raise ContractValidationError(
                "Navigator state and approval scope may not precede operator approval"
            )
        return

    if governor.status is not StageStatus.SUCCEEDED:
        raise ContractValidationError(
            "an operator route requires a technically successful Governor stage"
        )

    if route is OperatorRoute.PENDING_APPROVAL:
        if governor.native_state != "PROCEED":
            raise ContractValidationError(
                "PENDING_APPROVAL requires the PROCEED Governor disposition"
            )
        action_status = operator.action_status
        if action_status in {
            OperatorActionStatus.NOT_STARTED,
            OperatorActionStatus.RUNNING,
        }:
            if (
                current_phase is not CurrentPhase.OPERATOR
                or mission_outcome is not MissionOutcome.HELD
                or terminal
                or navigator_stage.status is not StageStatus.NOT_STARTED
                or navigator != empty_navigator
                or approval_scope is not None
            ):
                raise ContractValidationError(
                    "pending operator approval conflicts with mission state"
                )
            return
        if action_status is OperatorActionStatus.FAILED:
            if operator.error is None:
                raise AssertionError("validated failed operator action lacks an error")
            if (
                current_phase is not CurrentPhase.OPERATOR
                or mission_outcome is not MissionOutcome.FAILED
                or terminal is operator.error.resumable
                or navigator_stage.status is not StageStatus.NOT_STARTED
                or navigator != empty_navigator
                or approval_scope is not None
            ):
                raise ContractValidationError(
                    "failed operator action conflicts with mission state"
                )
            return

        if operator.action is OperatorAction.REJECT:
            if (
                operator.result is not OperatorResult.REJECTED
                or current_phase is not CurrentPhase.COMPLETE
                or mission_outcome is not MissionOutcome.VETOED
                or not terminal
                or navigator_stage.status is not StageStatus.NOT_STARTED
                or navigator != empty_navigator
                or approval_scope is not None
            ):
                raise ContractValidationError(
                    "rejected operator handoff conflicts with mission state"
                )
            return

        if (
            operator.action is not OperatorAction.APPROVE_HANDOFF
            or operator.result is not OperatorResult.APPROVED_FOR_HANDOFF
            or approval_scope is not ApprovalScope.NAVIGATOR_SHADOW_HANDOFF
        ):
            raise ContractValidationError(
                "successful operator approval lacks the Navigator SHADOW scope"
            )

        if navigator_stage.status is StageStatus.NOT_STARTED:
            if (
                current_phase is not CurrentPhase.NAVIGATOR
                or mission_outcome is not MissionOutcome.HELD
                or terminal
                or navigator != empty_navigator
            ):
                raise ContractValidationError(
                    "approved Navigator handoff conflicts with mission state"
                )
            return
        if navigator_stage.status is StageStatus.RUNNING:
            if (
                current_phase is not CurrentPhase.NAVIGATOR
                or mission_outcome is not MissionOutcome.HELD
                or terminal
                or navigator_stage.native_state != NavigatorMode.SHADOW.value
                or navigator != NavigatorState.shadow_running()
            ):
                raise ContractValidationError(
                    "running Navigator SHADOW attempt conflicts with mission state"
                )
            return
        if navigator_stage.status is StageStatus.SUCCEEDED:
            if (
                current_phase is not CurrentPhase.COMPLETE
                or mission_outcome is not MissionOutcome.APPROVED
                or not terminal
                or navigator_stage.native_state != NavigatorPlanStatus.CREATED.value
                or navigator.mode is not NavigatorMode.SHADOW
                or navigator.handoff_status is not NavigatorHandoffStatus.STAGED
                or navigator.intake_status is not NavigatorIntakeStatus.ACCEPTED
                or navigator.plan_status is not NavigatorPlanStatus.CREATED
                or any(
                    item is None
                    for item in (
                        navigator.handoff_id,
                        navigator.intake_receipt_id,
                        navigator.plan_id,
                        navigator.expires_at,
                        navigator.idempotency_key,
                    )
                )
            ):
                raise ContractValidationError(
                    "completed Navigator SHADOW plan conflicts with mission state"
                )
            return
        if navigator_stage.status is StageStatus.FAILED:
            if navigator_stage.error is None:
                raise AssertionError("validated failed Navigator stage lacks an error")
            if (
                current_phase is not CurrentPhase.NAVIGATOR
                or mission_outcome is not MissionOutcome.FAILED
                or terminal is navigator_stage.error.resumable
                or navigator.mode is not NavigatorMode.SHADOW
            ):
                raise ContractValidationError(
                    "failed Navigator SHADOW attempt conflicts with mission state"
                )
            return
        raise ContractValidationError("approved Navigator handoff has unsupported status")

    if operator.action_status is not OperatorActionStatus.NOT_STARTED:
        raise ContractValidationError(
            "operator action is supported only for PENDING_APPROVAL"
        )
    if navigator_stage.status is not StageStatus.NOT_STARTED:
        raise ContractValidationError(
            "Phase 4 non-approval routing requires Navigator to remain NOT_STARTED"
        )
    if navigator != empty_navigator or approval_scope is not None:
        raise ContractValidationError(
            "non-approval routing may not contain Navigator state or approval scope"
        )
    expected = {
        OperatorRoute.PENDING_REVIEW: (
            {"HOLD", "REVIEW_REQUIRED"},
            CurrentPhase.OPERATOR,
            MissionOutcome.HELD,
            False,
        ),
        OperatorRoute.CLOSED_BLOCKED: (
            "BLOCKED",
            CurrentPhase.GOVERNOR,
            MissionOutcome.HELD,
            True,
        ),
        OperatorRoute.CLOSED_NO_ACTION: (
            "STAND_DOWN",
            CurrentPhase.COMPLETE,
            MissionOutcome.VETOED,
            True,
        ),
    }[route]
    native_state, expected_phase, expected_outcome, expected_terminal = expected
    native_matches = (
        governor.native_state in native_state
        if isinstance(native_state, set)
        else governor.native_state == native_state
    )
    if (
        not native_matches
        or current_phase is not expected_phase
        or mission_outcome is not expected_outcome
        or terminal is not expected_terminal
    ):
        raise ContractValidationError(
            "operator route conflicts with the rendered Governor disposition"
        )


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    schema_version: str
    snapshot_id: str
    mission_id: str
    request_id: str
    revision: int
    previous_snapshot_sha256: str | None
    run_mode: RunMode
    started_at: str
    observed_at: str
    mission_outcome: MissionOutcome
    current_phase: CurrentPhase
    terminal: bool
    stages: dict[str, StageSnapshot]
    artifacts: tuple[ArtifactReference, ...]
    components: dict[
        str,
        ComponentProvenance
        | CouncilComponentProvenance
        | GovernorComponentProvenance,
    ]
    operator: OperatorState
    navigator: NavigatorState
    approval_scope: ApprovalScope | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission snapshot must be an object")
        fields = set(value)
        missing = set(_SNAPSHOT_BASE_FIELDS) - fields
        unknown = fields - set(_SNAPSHOT_BASE_FIELDS) - {
            "components",
            "operator",
            "navigator",
            "approval_scope",
        }
        if missing:
            raise ContractValidationError(
                f"mission snapshot is missing fields: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ContractValidationError(
                f"mission snapshot contains unknown fields: {', '.join(sorted(unknown))}"
            )
        if value["schema_version"] != MISSION_SNAPSHOT_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported schema_version: {value['schema_version']!r}; expected "
                f"{MISSION_SNAPSHOT_SCHEMA_VERSION!r}"
            )

        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if mission_id == request_id:
            raise ContractValidationError("mission_id must be distinct from request_id")

        revision = value["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractValidationError("revision must be an integer greater than zero")
        expected_snapshot_id = f"{mission_id}-r{revision:04d}"
        if value["snapshot_id"] != expected_snapshot_id:
            raise ContractValidationError(
                f"snapshot_id must be {expected_snapshot_id!r} for revision {revision}"
            )

        previous_digest = value["previous_snapshot_sha256"]
        if revision == 1:
            if previous_digest is not None:
                raise ContractValidationError(
                    "revision 1 previous_snapshot_sha256 must be null"
                )
        elif not isinstance(previous_digest, str) or not _SHA256_PATTERN.fullmatch(
            previous_digest
        ):
            raise ContractValidationError(
                "later revisions require a 64-character previous snapshot SHA-256"
            )

        started_at = normalize_rfc3339(value["started_at"], "started_at")
        observed_at = normalize_rfc3339(value["observed_at"], "observed_at")
        if parse_rfc3339(observed_at, "observed_at") < parse_rfc3339(
            started_at, "started_at"
        ):
            raise ContractValidationError("observed_at may not precede started_at")

        stages_value = value["stages"]
        if not isinstance(stages_value, Mapping):
            raise ContractValidationError("stages must be an object")
        if set(stages_value) != set(STAGE_NAMES):
            raise ContractValidationError(
                "stages must contain exactly: " + ", ".join(STAGE_NAMES)
            )
        stages = {
            stage_name: StageSnapshot.from_mapping(stages_value[stage_name], stage_name)
            for stage_name in STAGE_NAMES
        }

        artifacts_value = value["artifacts"]
        if not isinstance(artifacts_value, list):
            raise ContractValidationError("artifacts must be an array")
        artifacts = tuple(ArtifactReference.from_mapping(item) for item in artifacts_value)
        if len({item.name for item in artifacts}) != len(artifacts):
            raise ContractValidationError("artifact names must be unique")
        if len({item.path for item in artifacts}) != len(artifacts):
            raise ContractValidationError("artifact paths must be unique")
        artifact_names = {item.name for item in artifacts}
        for stage_name, stage in stages.items():
            unknown_names = (set(stage.inputs) | set(stage.outputs)) - artifact_names
            if unknown_names:
                raise ContractValidationError(
                    f"{stage_name} references unknown artifacts: "
                    + ", ".join(sorted(unknown_names))
                )

        components_value = value.get("components", {})
        if not isinstance(components_value, Mapping):
            raise ContractValidationError("components must be an object")
        supported_components = {
            "battlestar",
            "battlestar_council",
            "battlestar_governor",
        }
        if set(components_value) - supported_components:
            raise ContractValidationError(
                "components supports battlestar, battlestar_council, and "
                "battlestar_governor only"
            )
        components: dict[
            str,
            ComponentProvenance
            | CouncilComponentProvenance
            | GovernorComponentProvenance,
        ] = {}
        if "battlestar" in components_value:
            components["battlestar"] = ComponentProvenance.from_mapping(
                components_value["battlestar"]
            )
        if "battlestar_council" in components_value:
            if "battlestar" not in components_value:
                raise ContractValidationError(
                    "battlestar_council provenance requires Battlestar Oracle provenance"
                )
            components["battlestar_council"] = (
                CouncilComponentProvenance.from_mapping(
                    components_value["battlestar_council"]
                )
            )
        if "battlestar_governor" in components_value:
            if not {"battlestar", "battlestar_council"}.issubset(
                components_value
            ):
                raise ContractValidationError(
                    "battlestar_governor provenance requires Battlestar Oracle "
                    "and Council provenance"
                )
            components["battlestar_governor"] = (
                GovernorComponentProvenance.from_mapping(
                    components_value["battlestar_governor"]
                )
            )

        run_mode = _parse_enum(RunMode, value["run_mode"], "run_mode")
        if any(component.run_mode is not run_mode for component in components.values()):
            raise ContractValidationError("component run_mode must match mission run_mode")
        terminal = value["terminal"]
        if type(terminal) is not bool:
            raise ContractValidationError("terminal must be a boolean")
        mission_outcome = _parse_enum(
            MissionOutcome, value["mission_outcome"], "mission_outcome"
        )
        current_phase = _parse_enum(
            CurrentPhase, value["current_phase"], "current_phase"
        )
        operator = (
            OperatorState.empty()
            if "operator" not in value
            else OperatorState.from_mapping(value["operator"])
        )
        navigator = (
            NavigatorState.empty()
            if "navigator" not in value
            else NavigatorState.from_mapping(value["navigator"])
        )
        approval_scope_value = value.get("approval_scope")
        approval_scope = (
            None
            if approval_scope_value is None
            else _parse_enum(
                ApprovalScope,
                approval_scope_value,
                "approval_scope",
            )
        )
        _validate_operator_route(
            operator,
            navigator=navigator,
            approval_scope=approval_scope,
            stages=stages,
            current_phase=current_phase,
            mission_outcome=mission_outcome,
            terminal=terminal,
        )

        return cls(
            schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=expected_snapshot_id,
            mission_id=mission_id,
            request_id=request_id,
            revision=revision,
            previous_snapshot_sha256=previous_digest,
            run_mode=run_mode,
            started_at=started_at,
            observed_at=observed_at,
            mission_outcome=mission_outcome,
            current_phase=current_phase,
            terminal=terminal,
            stages=stages,
            artifacts=artifacts,
            components=components,
            operator=operator,
            navigator=navigator,
            approval_scope=approval_scope,
        )

    @classmethod
    def create_phase1(
        cls,
        *,
        mission_id: str,
        request_id: str,
        run_mode: RunMode,
        started_at: str,
        observed_at: str,
        request_artifact: ArtifactReference,
    ) -> "MissionSnapshot":
        stages = {
            "harbormaster": StageSnapshot(
                status=StageStatus.SUCCEEDED,
                native_state="INITIALIZED",
                inputs=(request_artifact.name,),
            ),
            "oracle": StageSnapshot(StageStatus.NOT_STARTED, None),
            "council": StageSnapshot(StageStatus.NOT_STARTED, None),
            "governor": StageSnapshot(StageStatus.NOT_STARTED, None),
            "navigator": StageSnapshot(StageStatus.NOT_STARTED, None),
        }
        outcome = derive_phase1_outcome(stages)
        return cls.from_mapping(
            {
                "schema_version": MISSION_SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": f"{mission_id}-r0001",
                "mission_id": mission_id,
                "request_id": request_id,
                "revision": 1,
                "previous_snapshot_sha256": None,
                "run_mode": run_mode.value,
                "started_at": started_at,
                "observed_at": observed_at,
                "mission_outcome": outcome.value,
                "current_phase": CurrentPhase.ORACLE.value,
                "terminal": False,
                "stages": {name: stage.to_dict() for name, stage in stages.items()},
                "artifacts": [request_artifact.to_dict()],
                "components": {},
                "operator": OperatorState.empty().to_dict(),
                "navigator": NavigatorState.empty().to_dict(),
                "approval_scope": None,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "revision": self.revision,
            "previous_snapshot_sha256": self.previous_snapshot_sha256,
            "run_mode": self.run_mode.value,
            "started_at": self.started_at,
            "observed_at": self.observed_at,
            "mission_outcome": self.mission_outcome.value,
            "current_phase": self.current_phase.value,
            "terminal": self.terminal,
            "stages": {name: self.stages[name].to_dict() for name in STAGE_NAMES},
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "components": {
                name: self.components[name].to_dict() for name in sorted(self.components)
            },
            "operator": self.operator.to_dict(),
            "navigator": self.navigator.to_dict(),
            "approval_scope": (
                None if self.approval_scope is None else self.approval_scope.value
            ),
        }


def derive_phase1_outcome(stages: Mapping[str, StageSnapshot]) -> MissionOutcome:
    """Derive the only successful Phase 1 outcome without future policy."""

    if set(stages) != set(STAGE_NAMES):
        raise ContractValidationError("Phase 1 requires all canonical stages")
    if stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise ContractValidationError("Phase 1 requires Harbormaster to succeed")
    if any(
        stages[name].status is not StageStatus.NOT_STARTED
        for name in STAGE_NAMES
        if name != "harbormaster"
    ):
        raise ContractValidationError(
            "Phase 1 requires all downstream stages to remain NOT_STARTED"
        )
    return MissionOutcome.INCOMPLETE
