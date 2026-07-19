"""Narrow, deadline-controlled adapter for Battlestar's operator action seam."""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import re
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .contracts import ContractValidationError, MissionRequest, RunMode
from .contracts.mission_request import (
    normalize_rfc3339,
    parse_strict_json_object_bytes,
)
from .contracts.mission_snapshot import (
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
)
from .identifiers import IdentifierError, validate_identifier, validate_mission_id


OPERATOR_REPLAY_ACTION_SCHEMA_VERSION = "blackpod.operator_action_replay.v1"
OPERATOR_REVIEW_PACKET_SCHEMA_VERSION = "operator_review_packet.v1"
OPERATOR_ACTION_SCHEMA_VERSION = "operator_inbox_action.v1"
OPERATOR_RECEIPT_SCHEMA_VERSION = "decision_consumption_receipt.v1"
# Battlestar's current decision-consumer ledger event is intentionally
# unversioned. Preserve that fact in ArtifactReference/lineage metadata.
OPERATOR_LEDGER_SCHEMA_VERSION = None
OPERATOR_PROVENANCE_SCHEMA_VERSION = "blackpod.operator_provenance.v1"
OPERATOR_LINEAGE_SCHEMA_VERSION = "blackpod.operator_lineage.v1"

_NATIVE_PACKET_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "manifest_schema_version",
        "packet_id",
        "run_id",
        "run_completed_at",
        "governor_posture",
        "decision_state",
        "allowed_next_step",
        "decision_summary",
        "readiness_state",
        "readiness_summary",
        "blockers",
        "warnings",
        "deliberation_summary",
        "operator_route",
        "source_artifact_paths",
        "source_artifact_hashes",
        "decision_input_hash",
        "created_at",
    }
)
_NATIVE_PACKET_OPTIONAL_FIELDS = frozenset({"unresolved_questions"})
_NATIVE_ACTION_FIELDS = frozenset(
    {
        "schema_version",
        "packet_sha256",
        "decision_input_hash",
        "source_run_id",
        "action",
        "operator_id",
        "reason",
        "created_at",
        "expires_at",
        "action_id",
        "packet_path",
        "packet_id",
        "resulting_status",
    }
)
_NATIVE_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "event_timestamp",
        "run_id",
        "decision_input_hash",
        "operator_route",
        "packet_path",
        "result_status",
    }
)
_NATIVE_LEDGER_FIELDS = frozenset(_NATIVE_RECEIPT_FIELDS - {"schema_version"})

# Public compatibility descriptors used by the Navigator boundary.  They are
# field sets, not Build Week alternatives to Battlestar's native contracts.
NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS = _NATIVE_PACKET_REQUIRED_FIELDS
NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS = _NATIVE_PACKET_OPTIONAL_FIELDS
NATIVE_OPERATOR_ACTION_FIELDS = _NATIVE_ACTION_FIELDS
NATIVE_OPERATOR_RECEIPT_FIELDS = _NATIVE_RECEIPT_FIELDS
NATIVE_OPERATOR_LEDGER_FIELDS = _NATIVE_LEDGER_FIELDS

OPERATOR_REPLAY_INPUT_PATH = "operator/inputs/operator_replay_action.json"
OPERATOR_ATTEMPT_DIRECTORY = "operator/attempt-0001"
OPERATOR_REVIEW_PACKET_PATH = f"{OPERATOR_ATTEMPT_DIRECTORY}/review_packet.json"
OPERATOR_ACTION_PATH = f"{OPERATOR_ATTEMPT_DIRECTORY}/operator_action.json"
OPERATOR_RECEIPT_PATH = f"{OPERATOR_ATTEMPT_DIRECTORY}/operator_receipt.json"
OPERATOR_LEDGER_ENTRY_PATH = (
    f"{OPERATOR_ATTEMPT_DIRECTORY}/operator_ledger_entry.json"
)
OPERATOR_PROVENANCE_PATH = f"{OPERATOR_ATTEMPT_DIRECTORY}/operator_provenance.json"
OPERATOR_LINEAGE_PATH = f"{OPERATOR_ATTEMPT_DIRECTORY}/lineage_manifest.json"

EXPECTED_OPERATOR_OUTPUT_PATHS = (
    OPERATOR_REVIEW_PACKET_PATH,
    OPERATOR_ACTION_PATH,
    OPERATOR_RECEIPT_PATH,
    OPERATOR_LEDGER_ENTRY_PATH,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_LINEAGE_PATH,
)

GOVERNOR_DECISION_PATH = "governor/attempt-0001/governor_decision.json"
GOVERNOR_READINESS_PATH = (
    "governor/attempt-0001/governor_decision_readiness.json"
)
GOVERNOR_DELIBERATION_PATH = "governor/attempt-0001/governor_deliberation.json"
GOVERNOR_RENDERED_PATH = (
    "governor/attempt-0001/governor_rendered_decision.json"
)
GOVERNOR_PROVENANCE_PATH = "governor/attempt-0001/governor_provenance.json"
GOVERNOR_LINEAGE_PATH = "governor/attempt-0001/lineage_manifest.json"

OPERATOR_ACTION_ENTRY_POINT = (
    "blackpod.runtime.operator_inbox_action.record_operator_action"
)
GOVERNOR_DECISION_LOADER_ENTRY_POINT = (
    "blackpod.governor.governor_decision.load_governor_decision"
)
GOVERNOR_READINESS_LOADER_ENTRY_POINT = (
    "blackpod.governor.governor_decision_readiness."
    "load_governor_decision_readiness"
)
GOVERNOR_DELIBERATION_LOADER_ENTRY_POINT = (
    "blackpod.governor.governor_deliberation.load_governor_deliberation"
)
OPERATOR_PACKET_ADAPTER_ENTRY_POINT = (
    "blackpod_build_week.operator_adapter._build_operator_review_packet"
)

_REQUIRED_BATTLESTAR_MODULES = (
    Path("blackpod/governor/governor_decision.py"),
    Path("blackpod/governor/governor_decision_readiness.py"),
    Path("blackpod/governor/governor_deliberation.py"),
    Path("blackpod/runtime/governor_decision_consumer.py"),
    Path("blackpod/runtime/operator_inbox_action.py"),
)
_TRANSPORT_RESULT_FIELDS = frozenset(
    {
        "route",
        "action",
        "result",
        "native_status",
        "action_id",
        "operator_id",
        "acted_at",
        "warnings",
        "review_packet_path",
        "produced_paths",
    }
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)
_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


class OperatorAdapterValidationError(ValueError):
    """Raised when adapter-owned inputs are invalid before native execution."""


class OperatorMalformedResultError(RuntimeError):
    """Raised when native output is malformed, inconsistent, or unsafe."""


class OperatorTransportTimeout(TimeoutError):
    """Raised when the isolated operator worker exceeds its deadline."""


class OperatorRemoteExecutionError(RuntimeError):
    """A sanitized native exception returned by the isolated worker."""

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


def _strict_text(value: object, field_name: str, *, max_length: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank trimmed string")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    if _ABSOLUTE_POSIX_PATH.search(value) or _ABSOLUTE_WINDOWS_PATH.search(value):
        raise ContractValidationError(f"{field_name} may not contain an absolute path")
    return value


def _positive_minutes(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractValidationError(
            "expires_in_minutes must be null or a positive integer"
        )
    return value


@dataclass(frozen=True, slots=True)
class OperatorActionInput:
    """Validated effective action input for LIVE or deterministic REPLAY."""

    run_mode: RunMode
    action: OperatorAction
    operator_id: str
    reason: str
    acted_at: str
    expires_in_minutes: int | None
    fixture_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_mode, RunMode) or not isinstance(
            self.action, OperatorAction
        ):
            raise ContractValidationError(
                "operator action input requires typed run mode and action"
            )
        try:
            validate_identifier(self.operator_id, "operator_id")
            if self.fixture_id is not None:
                validate_identifier(self.fixture_id, "fixture_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        _strict_text(self.reason, "reason")
        normalize_rfc3339(self.acted_at, "acted_at")
        _positive_minutes(self.expires_in_minutes)
        if (
            self.action is OperatorAction.APPROVE_HANDOFF
            and self.expires_in_minutes is None
        ):
            raise ContractValidationError(
                "APPROVE_HANDOFF requires a positive expires_in_minutes"
            )
        if self.run_mode is RunMode.REPLAY and self.fixture_id is None:
            raise ContractValidationError("REPLAY operator input requires fixture_id")
        if self.run_mode is RunMode.LIVE and self.fixture_id is not None:
            raise ContractValidationError("LIVE operator input forbids fixture_id")

    @classmethod
    def from_replay_bytes(cls, payload: bytes) -> "OperatorActionInput":
        return cls.from_replay_mapping(
            parse_strict_json_object_bytes(
                payload, document_name="operator replay action"
            )
        )

    @classmethod
    def from_replay_mapping(cls, value: object) -> "OperatorActionInput":
        if not isinstance(value, Mapping):
            raise ContractValidationError("operator replay action must be an object")
        _require_exact_fields(
            value,
            {
                "schema_version",
                "fixture_id",
                "run_mode",
                "action",
                "operator_id",
                "reason",
                "acted_at",
                "expires_in_minutes",
            },
            "operator replay action",
        )
        if value["schema_version"] != OPERATOR_REPLAY_ACTION_SCHEMA_VERSION:
            raise ContractValidationError(
                "unsupported operator replay action schema_version"
            )
        if value["run_mode"] != RunMode.REPLAY.value:
            raise ContractValidationError("operator replay action run_mode must be REPLAY")
        try:
            fixture_id = validate_identifier(value["fixture_id"], "fixture_id")
            action = OperatorAction(value["action"])
            operator_id = validate_identifier(value["operator_id"], "operator_id")
        except (IdentifierError, TypeError, ValueError) as exc:
            raise ContractValidationError(str(exc)) from exc
        return cls(
            run_mode=RunMode.REPLAY,
            action=action,
            operator_id=operator_id,
            reason=_strict_text(value["reason"], "reason"),
            acted_at=normalize_rfc3339(value["acted_at"], "acted_at"),
            expires_in_minutes=_positive_minutes(value["expires_in_minutes"]),
            fixture_id=fixture_id,
        )

    @classmethod
    def live(
        cls,
        *,
        action: OperatorAction | str,
        operator_id: str,
        reason: str,
        acted_at: str,
        expires_in_minutes: int | None,
    ) -> "OperatorActionInput":
        try:
            parsed_action = (
                action if isinstance(action, OperatorAction) else OperatorAction(action)
            )
            parsed_operator = validate_identifier(operator_id, "operator_id")
        except (IdentifierError, TypeError, ValueError) as exc:
            raise ContractValidationError(str(exc)) from exc
        return cls(
            run_mode=RunMode.LIVE,
            action=parsed_action,
            operator_id=parsed_operator,
            reason=_strict_text(reason, "reason"),
            acted_at=normalize_rfc3339(acted_at, "acted_at"),
            expires_in_minutes=_positive_minutes(expires_in_minutes),
            fixture_id=None,
        )

    def to_transport_dict(self) -> dict[str, object]:
        return {
            "run_mode": self.run_mode.value,
            "action": self.action.value,
            "operator_id": self.operator_id,
            "reason": self.reason,
            "acted_at": self.acted_at,
            "expires_in_minutes": self.expires_in_minutes,
            "fixture_id": self.fixture_id,
        }


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OperatorAdapterValidationError(
            f"{field_name} must be a relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise OperatorAdapterValidationError(
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
class OperatorMissionContext:
    mission_id: str
    mission_root: Path
    governor_decision_path: str = GOVERNOR_DECISION_PATH
    governor_readiness_path: str = GOVERNOR_READINESS_PATH
    governor_deliberation_path: str = GOVERNOR_DELIBERATION_PATH
    governor_rendered_path: str = GOVERNOR_RENDERED_PATH
    governor_provenance_path: str = GOVERNOR_PROVENANCE_PATH
    governor_lineage_path: str = GOVERNOR_LINEAGE_PATH
    output_dir: str = OPERATOR_ATTEMPT_DIRECTORY
    battlestar_git_revision: str = "0000000"
    battlestar_git_branch: str | None = None
    battlestar_dirty_worktree: bool = False

    def __post_init__(self) -> None:
        try:
            mission_id = validate_mission_id(self.mission_id)
        except IdentifierError as exc:
            raise OperatorAdapterValidationError(str(exc)) from exc
        root_input = Path(self.mission_root)
        if not root_input.is_absolute() or root_input.is_symlink() or not root_input.is_dir():
            raise OperatorAdapterValidationError(
                "mission_root must be an existing absolute non-symlink directory"
            )
        root = root_input.resolve(strict=True)
        path_fields = (
            "governor_decision_path",
            "governor_readiness_path",
            "governor_deliberation_path",
            "governor_rendered_path",
            "governor_provenance_path",
            "governor_lineage_path",
            "output_dir",
        )
        values = {
            name: _validate_relative_path(getattr(self, name), name)
            for name in path_fields
        }
        output = (root / values["output_dir"]).resolve(strict=False)
        if not _is_relative_to(output, root):
            raise OperatorAdapterValidationError(
                "operator output_dir must remain beneath the mission root"
            )
        for name in path_fields[:-1]:
            candidate = (root / values[name]).resolve(strict=False)
            if not _is_relative_to(candidate, root) or _is_relative_to(candidate, output):
                raise OperatorAdapterValidationError(
                    "operator inputs must remain beneath the mission root and outside output_dir"
                )
        revision = str(self.battlestar_git_revision).lower()
        if _GIT_REVISION_PATTERN.fullmatch(revision) is None:
            raise OperatorAdapterValidationError(
                "battlestar_git_revision must be a Git revision"
            )
        if self.battlestar_git_branch is not None:
            _strict_text(
                self.battlestar_git_branch,
                "battlestar_git_branch",
                max_length=256,
            )
        if type(self.battlestar_dirty_worktree) is not bool:
            raise OperatorAdapterValidationError(
                "battlestar_dirty_worktree must be a boolean"
            )
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "mission_root", root)
        object.__setattr__(self, "battlestar_git_revision", revision)
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def absolute(self, relative_path: str) -> Path:
        return self.mission_root.joinpath(*PurePosixPath(relative_path).parts)

    @property
    def input_paths(self) -> tuple[str, ...]:
        return (
            self.governor_decision_path,
            self.governor_readiness_path,
            self.governor_deliberation_path,
            self.governor_rendered_path,
            self.governor_provenance_path,
            self.governor_lineage_path,
        )

    @property
    def output_absolute(self) -> Path:
        return self.absolute(self.output_dir)


@dataclass(frozen=True, slots=True)
class OperatorTransportRequest:
    battlestar_path: Path
    mission_root: Path
    mission_id: str
    request_id: str
    run_mode: str
    governor_decision_path: str
    governor_readiness_path: str
    governor_deliberation_path: str
    governor_rendered_path: str
    governor_provenance_path: str
    governor_lineage_path: str
    output_dir: str
    action_input: dict[str, object]
    battlestar_git_revision: str
    battlestar_git_branch: str | None
    battlestar_dirty_worktree: bool


class OperatorTransport(Protocol):
    def run(
        self, request: OperatorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]: ...


OperatorTransportCallable = Callable[
    [OperatorTransportRequest, float], Mapping[str, object]
]


@dataclass(frozen=True, slots=True)
class OperatorFailure:
    code: str
    error_type: str
    message: str
    resumable: bool


@dataclass(frozen=True, slots=True)
class OperatorExecutionResult:
    mission_id: str
    request_id: str
    run_mode: RunMode
    technical_status: OperatorActionStatus
    route: OperatorRoute
    action: OperatorAction
    result: OperatorResult | None
    native_status: str | None
    action_id: str | None
    operator_id: str
    acted_at: str
    warnings: tuple[str, ...]
    review_packet_path: str | None
    produced_paths: tuple[str, ...]
    source_lineage: tuple[str, ...]
    fixture_id: str | None
    failure: OperatorFailure | None

    def __post_init__(self) -> None:
        if self.technical_status is OperatorActionStatus.SUCCEEDED:
            if (
                self.failure is not None
                or self.result is None
                or not self.action_id
                or self.native_status not in {"RECORDED", "ALREADY_RECORDED"}
                or self.review_packet_path != OPERATOR_REVIEW_PACKET_PATH
                or self.produced_paths != EXPECTED_OPERATOR_OUTPUT_PATHS
            ):
                raise ValueError("successful operator result is incomplete")
        elif self.technical_status is OperatorActionStatus.FAILED:
            if self.failure is None or self.result is not None:
                raise ValueError("failed operator result requires a structured failure")
        else:
            raise ValueError("operator result must be technically SUCCEEDED or FAILED")


class ProcessOperatorTransport:
    """Run the native operator action in a terminable spawned process."""

    def run(
        self, request: OperatorTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_operator_worker, args=(sender, request))
        process.start()
        sender.close()
        try:
            if not receiver.poll(deadline_seconds):
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                raise OperatorTransportTimeout(
                    f"operator action exceeded its {deadline_seconds:g}-second deadline"
                )
            try:
                envelope = receiver.recv()
            except EOFError as exc:
                raise OperatorMalformedResultError(
                    f"operator worker exited without a result (exit code {process.exitcode})"
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
            raise OperatorMalformedResultError(
                "operator worker returned a malformed envelope"
            )
        if envelope["ok"] is True and isinstance(envelope.get("result"), Mapping):
            return envelope["result"]
        if envelope["ok"] is False:
            raise OperatorRemoteExecutionError(
                str(envelope["error_type"]), str(envelope["message"])
            )
        raise OperatorMalformedResultError("operator worker envelope is malformed")


class OperatorAdapter:
    """Validate Governor evidence and invoke only the native action recorder."""

    def __init__(
        self,
        battlestar_path: Path,
        *,
        transport: OperatorTransport | OperatorTransportCallable | None = None,
        deadline_seconds: float = 60.0,
    ) -> None:
        path_input = Path(battlestar_path)
        if not path_input.is_absolute() or not path_input.is_dir():
            raise OperatorAdapterValidationError(
                "Battlestar path must be an existing absolute directory"
            )
        path = path_input.resolve(strict=True)
        for relative in _REQUIRED_BATTLESTAR_MODULES:
            module = path / relative
            if module.is_symlink() or not module.is_file():
                raise OperatorAdapterValidationError(
                    f"Battlestar operator module is missing: {relative.as_posix()}"
                )
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise OperatorAdapterValidationError(
                "deadline_seconds must be finite and positive"
            )
        self.battlestar_path = path
        self.transport = transport or ProcessOperatorTransport()
        self.deadline_seconds = float(deadline_seconds)

    def execute(
        self,
        request: MissionRequest,
        context: OperatorMissionContext,
        *,
        action_input: OperatorActionInput,
    ) -> OperatorExecutionResult:
        if not isinstance(request, MissionRequest):
            raise OperatorAdapterValidationError("request must be a MissionRequest")
        if not isinstance(context, OperatorMissionContext):
            raise OperatorAdapterValidationError(
                "context must be an OperatorMissionContext"
            )
        if not isinstance(action_input, OperatorActionInput):
            raise OperatorAdapterValidationError("action_input must be validated")
        correlation_error = self._correlation_error(request, context)
        if correlation_error is not None:
            return self._failure(
                request,
                context,
                action_input,
                code="OPERATOR_CORRELATION_MISMATCH",
                error_type="CorrelationError",
                message=correlation_error,
                resumable=False,
            )
        if action_input.run_mode is not request.run_mode:
            return self._failure(
                request,
                context,
                action_input,
                code="OPERATOR_MODE_MISMATCH",
                error_type="RunModeError",
                message="operator action run mode conflicts with mission",
                resumable=False,
            )
        path_error = self._validate_execution_paths(context)
        if path_error is not None:
            return self._failure(
                request,
                context,
                action_input,
                code=path_error[0],
                error_type=path_error[1],
                message=path_error[2],
                resumable=False,
            )
        if action_input.run_mode is RunMode.REPLAY:
            fixture_path = context.absolute(OPERATOR_REPLAY_INPUT_PATH)
            if (
                fixture_path.is_symlink()
                or not fixture_path.is_file()
                or not _is_relative_to(
                    fixture_path.resolve(strict=True), context.mission_root
                )
            ):
                return self._failure(
                    request,
                    context,
                    action_input,
                    code="OPERATOR_INPUT_INVALID",
                    error_type="PathValidationError",
                    message="operator replay fixture is missing or unsafe",
                    resumable=False,
                )
        invocation = OperatorTransportRequest(
            battlestar_path=self.battlestar_path,
            mission_root=context.mission_root,
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode.value,
            governor_decision_path=context.governor_decision_path,
            governor_readiness_path=context.governor_readiness_path,
            governor_deliberation_path=context.governor_deliberation_path,
            governor_rendered_path=context.governor_rendered_path,
            governor_provenance_path=context.governor_provenance_path,
            governor_lineage_path=context.governor_lineage_path,
            output_dir=context.output_dir,
            action_input=action_input.to_transport_dict(),
            battlestar_git_revision=context.battlestar_git_revision,
            battlestar_git_branch=context.battlestar_git_branch,
            battlestar_dirty_worktree=context.battlestar_dirty_worktree,
        )
        try:
            raw = self._run_transport(invocation)
            parsed = self._validate_transport_result(raw)
            self._validate_committed_outputs(context, request, action_input, parsed)
            produced_paths = self._validate_complete_output_set(context)
        except OperatorTransportTimeout as exc:
            return self._failure_from_exception(
                request,
                context,
                action_input,
                "OPERATOR_TIMEOUT",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        except OperatorRemoteExecutionError as exc:
            return self._failure(
                request,
                context,
                action_input,
                code="OPERATOR_EXECUTION_FAILED",
                error_type=_safe_error_type(exc.error_type),
                message=_sanitize_message(
                    str(exc), self.battlestar_path, context.mission_root
                ),
                resumable=request.run_mode is RunMode.LIVE,
                produced_paths=self._discover_outputs(context),
            )
        except OperatorMalformedResultError as exc:
            return self._failure_from_exception(
                request,
                context,
                action_input,
                "OPERATOR_MALFORMED_RESULT",
                exc,
                resumable=False,
            )
        except Exception as exc:
            return self._failure_from_exception(
                request,
                context,
                action_input,
                "OPERATOR_EXECUTION_FAILED",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        return OperatorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode,
            technical_status=OperatorActionStatus.SUCCEEDED,
            route=OperatorRoute.PENDING_APPROVAL,
            action=parsed["action"],
            result=parsed["result"],
            native_status=parsed["native_status"],
            action_id=parsed["action_id"],
            operator_id=parsed["operator_id"],
            acted_at=parsed["acted_at"],
            warnings=parsed["warnings"],
            review_packet_path=parsed["review_packet_path"],
            produced_paths=produced_paths,
            source_lineage=(
                *context.input_paths,
                *((OPERATOR_REPLAY_INPUT_PATH,) if request.run_mode is RunMode.REPLAY else ()),
            ),
            fixture_id=action_input.fixture_id,
            failure=None,
        )

    @staticmethod
    def _correlation_error(
        request: MissionRequest, context: OperatorMissionContext
    ) -> str | None:
        if request.mission_id != context.mission_id:
            return "request mission_id does not match operator context"
        return None

    def _run_transport(
        self, request: OperatorTransportRequest
    ) -> Mapping[str, object]:
        runner = getattr(self.transport, "run", None)
        if callable(runner):
            return runner(request, deadline_seconds=self.deadline_seconds)
        if callable(self.transport):
            return self.transport(request, self.deadline_seconds)
        raise OperatorAdapterValidationError("operator transport is not callable")

    def _validate_execution_paths(
        self, context: OperatorMissionContext
    ) -> tuple[str, str, str] | None:
        for relative in context.input_paths:
            path = context.absolute(relative)
            if (
                path.is_symlink()
                or not path.is_file()
                or not _is_relative_to(path.resolve(strict=True), context.mission_root)
            ):
                return (
                    "OPERATOR_INPUT_INVALID",
                    "PathValidationError",
                    "operator requires contained regular Governor artifacts",
                )
        output = context.output_absolute
        if output.exists():
            if output.is_symlink() or not output.is_dir():
                return (
                    "OPERATOR_OUTPUT_INVALID",
                    "PathValidationError",
                    "operator output path must be a contained directory",
                )
            if any(output.iterdir()):
                return (
                    "OPERATOR_IMMUTABLE_COLLISION",
                    "ArtifactCollisionError",
                    "operator output directory contains immutable artifacts",
                )
        return None

    def _validate_transport_result(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, Mapping) or set(raw) != _TRANSPORT_RESULT_FIELDS:
            raise OperatorMalformedResultError(
                "operator return fields do not match the supported contract"
            )
        try:
            route = OperatorRoute(raw["route"])
            action = OperatorAction(raw["action"])
            result = OperatorResult(raw["result"])
        except (TypeError, ValueError) as exc:
            raise OperatorMalformedResultError(
                "operator returned unsupported route, action, or result"
            ) from exc
        if route is not OperatorRoute.PENDING_APPROVAL:
            raise OperatorMalformedResultError("operator route must be PENDING_APPROVAL")
        expected_result = {
            OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
            OperatorAction.REJECT: OperatorResult.REJECTED,
        }[action]
        if result is not expected_result:
            raise OperatorMalformedResultError("operator action and result conflict")
        native_status = _native_text(raw["native_status"], "native_status")
        if native_status not in {"RECORDED", "ALREADY_RECORDED"}:
            raise OperatorMalformedResultError("unsupported native operator status")
        action_id = _native_identifier(raw["action_id"], "action_id")
        operator_id = _native_identifier(raw["operator_id"], "operator_id")
        acted_at = normalize_rfc3339(raw["acted_at"], "acted_at")
        review_packet_path = _native_relative_path(raw["review_packet_path"])
        if review_packet_path != OPERATOR_REVIEW_PACKET_PATH:
            raise OperatorMalformedResultError(
                "operator returned a noncanonical review packet path"
            )
        paths = raw["produced_paths"]
        if not isinstance(paths, (list, tuple)):
            raise OperatorMalformedResultError("produced_paths must be an array")
        produced = tuple(_native_relative_path(item) for item in paths)
        if produced != EXPECTED_OPERATOR_OUTPUT_PATHS:
            raise OperatorMalformedResultError(
                "operator return does not declare the canonical artifact set"
            )
        warnings = _text_tuple(raw["warnings"], "warnings")
        return {
            "route": route,
            "action": action,
            "result": result,
            "native_status": native_status,
            "action_id": action_id,
            "operator_id": operator_id,
            "acted_at": acted_at,
            "warnings": warnings,
            "review_packet_path": review_packet_path,
            "produced_paths": produced,
        }

    def _validate_committed_outputs(
        self,
        context: OperatorMissionContext,
        request: MissionRequest,
        action_input: OperatorActionInput,
        parsed: Mapping[str, Any],
    ) -> None:
        validate_operator_artifact_bundle(
            context,
            request,
            action_input=action_input,
            parsed=parsed,
            battlestar_path=self.battlestar_path,
        )

    def _validate_complete_output_set(
        self, context: OperatorMissionContext
    ) -> tuple[str, ...]:
        found = self._discover_outputs(context, reject_unsafe=True)
        if found != EXPECTED_OPERATOR_OUTPUT_PATHS:
            raise OperatorMalformedResultError(
                "operator output set is incomplete or unsupported"
            )
        return found

    def _discover_outputs(
        self, context: OperatorMissionContext, *, reject_unsafe: bool = False
    ) -> tuple[str, ...]:
        output = context.output_absolute
        if not output.is_dir() or output.is_symlink():
            return ()
        found: list[str] = []
        try:
            for candidate in sorted(output.rglob("*"), key=lambda item: item.as_posix()):
                if candidate.is_symlink():
                    if reject_unsafe:
                        raise OperatorMalformedResultError(
                            "operator output contains an unsafe artifact"
                        )
                    continue
                if candidate.is_dir():
                    continue
                if not candidate.is_file():
                    if reject_unsafe:
                        raise OperatorMalformedResultError(
                            "operator output contains an unsafe artifact"
                        )
                    continue
                resolved = candidate.resolve(strict=True)
                if not _is_relative_to(resolved, context.mission_root):
                    if reject_unsafe:
                        raise OperatorMalformedResultError(
                            "operator artifact escaped the mission root"
                        )
                    continue
                found.append(candidate.relative_to(context.mission_root).as_posix())
        except OSError as exc:
            if reject_unsafe:
                raise OperatorMalformedResultError(
                    "operator outputs cannot be inspected"
                ) from exc
        order = {path: index for index, path in enumerate(EXPECTED_OPERATOR_OUTPUT_PATHS)}
        return tuple(sorted(found, key=lambda value: order.get(value, 999)))

    def _failure_from_exception(
        self,
        request: MissionRequest,
        context: OperatorMissionContext,
        action_input: OperatorActionInput,
        code: str,
        exc: Exception,
        *,
        resumable: bool,
    ) -> OperatorExecutionResult:
        return self._failure(
            request,
            context,
            action_input,
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
        context: OperatorMissionContext,
        action_input: OperatorActionInput,
        *,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        produced_paths: tuple[str, ...] = (),
    ) -> OperatorExecutionResult:
        return OperatorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode,
            technical_status=OperatorActionStatus.FAILED,
            route=OperatorRoute.PENDING_APPROVAL,
            action=action_input.action,
            result=None,
            native_status=None,
            action_id=None,
            operator_id=action_input.operator_id,
            acted_at=action_input.acted_at,
            warnings=(),
            review_packet_path=(
                OPERATOR_REVIEW_PACKET_PATH
                if OPERATOR_REVIEW_PACKET_PATH in produced_paths
                else None
            ),
            produced_paths=produced_paths,
            source_lineage=(
                *context.input_paths,
                *((OPERATOR_REPLAY_INPUT_PATH,) if request.run_mode is RunMode.REPLAY else ()),
            ),
            fixture_id=action_input.fixture_id,
            failure=OperatorFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=message or "operator action failed",
                resumable=resumable,
            ),
        )


def validate_operator_artifact_bundle(
    context: OperatorMissionContext,
    request: MissionRequest,
    *,
    action_input: OperatorActionInput,
    parsed: Mapping[str, Any],
    battlestar_path: Path,
) -> None:
    """Validate the complete immutable operator artifact graph."""

    try:
        packet = _read_strict_json(context.absolute(OPERATOR_REVIEW_PACKET_PATH))
        action = _read_strict_json(context.absolute(OPERATOR_ACTION_PATH))
        receipt = _read_strict_json(context.absolute(OPERATOR_RECEIPT_PATH))
        ledger = _read_strict_json(context.absolute(OPERATOR_LEDGER_ENTRY_PATH))
        provenance = _read_strict_json(context.absolute(OPERATOR_PROVENANCE_PATH))
        lineage = _read_strict_json(context.absolute(OPERATOR_LINEAGE_PATH))
        governor_provenance = _read_strict_json(
            context.absolute(context.governor_provenance_path)
        )
        governor_decision = _read_strict_json(
            context.absolute(context.governor_decision_path)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OperatorMalformedResultError(
            "operator artifacts are not strict JSON objects"
        ) from exc

    component = governor_provenance.get("component")
    governor_revision = (
        component.get("git_revision") if isinstance(component, Mapping) else None
    )
    if (
        governor_provenance.get("schema_version")
        != "blackpod.governor_provenance.v1"
        or governor_provenance.get("mission_id") != context.mission_id
        or governor_provenance.get("request_id") != request.request_id
        or governor_provenance.get("run_mode") != request.run_mode.value
        or not isinstance(governor_revision, str)
        or _GIT_REVISION_PATTERN.fullmatch(governor_revision) is None
    ):
        raise OperatorMalformedResultError(
            "recorded Governor provenance is malformed or inconsistent"
        )

    source_paths = {
        "governor_decision": context.governor_decision_path,
        "governor_decision_readiness": context.governor_readiness_path,
        "governor_deliberation": context.governor_deliberation_path,
        "governor_rendered_decision": context.governor_rendered_path,
        "governor_provenance": context.governor_provenance_path,
        "governor_lineage_manifest": context.governor_lineage_path,
    }
    source_hashes = {
        name: _sha256_file(context.absolute(path))
        for name, path in source_paths.items()
    }
    decision_input_hash = _decision_input_hash(context.mission_id, source_hashes)
    packet_path = context.absolute(OPERATOR_REVIEW_PACKET_PATH)
    packet_sha256 = _sha256_file(packet_path)
    decision_id = governor_decision.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise OperatorMalformedResultError("Governor decision lacks decision_id")
    packet_expected = {
        "schema_version": OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
        "manifest_schema_version": "blackpod.mission_snapshot.v1",
        "run_id": context.mission_id,
        "decision_state": "PROCEED",
        "allowed_next_step": "OPERATOR_REVIEW",
        "readiness_state": "READY",
        "operator_route": OperatorRoute.PENDING_APPROVAL.value,
        "source_artifact_paths": source_paths,
        "source_artifact_hashes": source_hashes,
        "decision_input_hash": decision_input_hash,
        "created_at": action_input.acted_at,
    }
    _expect_values(packet, packet_expected, "operator review packet")
    packet_fields = frozenset(packet)
    if packet_fields not in {
        _NATIVE_PACKET_REQUIRED_FIELDS,
        _NATIVE_PACKET_REQUIRED_FIELDS | _NATIVE_PACKET_OPTIONAL_FIELDS,
    }:
        raise OperatorMalformedResultError(
            "operator review packet does not preserve the native packet shape"
        )
    if "unresolved_questions" in packet and not packet["unresolved_questions"]:
        raise OperatorMalformedResultError(
            "native operator packet omits empty unresolved_questions"
        )

    action_expected = {
        "schema_version": OPERATOR_ACTION_SCHEMA_VERSION,
        "packet_sha256": packet_sha256,
        "decision_input_hash": decision_input_hash,
        "source_run_id": context.mission_id,
        "action": parsed["action"].value,
        "operator_id": parsed["operator_id"],
        "reason": action_input.reason,
        "created_at": parsed["acted_at"],
        "expires_at": _expected_expires_at(action_input),
        "action_id": parsed["action_id"],
        "packet_path": OPERATOR_REVIEW_PACKET_PATH,
        "packet_id": packet.get("packet_id"),
        "resulting_status": parsed["result"].value,
    }
    _expect_exact_values(action, action_expected, "operator action")
    if frozenset(action) != _NATIVE_ACTION_FIELDS:
        raise OperatorMalformedResultError(
            "operator action does not preserve the native action shape"
        )

    audit_expected = {
        "event_timestamp": parsed["acted_at"],
        "run_id": context.mission_id,
        "decision_input_hash": decision_input_hash,
        "operator_route": OperatorRoute.PENDING_APPROVAL.value,
        "packet_path": OPERATOR_REVIEW_PACKET_PATH,
        "result_status": "CONSUMED",
    }
    _expect_exact_values(
        receipt,
        {"schema_version": OPERATOR_RECEIPT_SCHEMA_VERSION, **audit_expected},
        "operator receipt",
    )
    _expect_exact_values(ledger, audit_expected, "operator ledger entry")
    if frozenset(receipt) != _NATIVE_RECEIPT_FIELDS:
        raise OperatorMalformedResultError(
            "operator receipt does not preserve the native receipt shape"
        )
    if frozenset(ledger) != _NATIVE_LEDGER_FIELDS:
        raise OperatorMalformedResultError(
            "operator ledger entry does not preserve the native ledger shape"
        )

    fixture_path = context.absolute(OPERATOR_REPLAY_INPUT_PATH)
    fixture_sha = (
        _sha256_file(fixture_path) if request.run_mode is RunMode.REPLAY else None
    )
    provenance_expected = {
        "schema_version": OPERATOR_PROVENANCE_SCHEMA_VERSION,
        "mission_id": context.mission_id,
        "request_id": request.request_id,
        "run_mode": request.run_mode.value,
        "observed_at": parsed["acted_at"],
        "decision_id": decision_id,
        "action_id": parsed["action_id"],
        "action": parsed["action"].value,
        "result": parsed["result"].value,
        "operator_id": parsed["operator_id"],
        "battlestar_git_revision": context.battlestar_git_revision,
        "battlestar_git_branch": context.battlestar_git_branch,
        "battlestar_dirty_worktree": context.battlestar_dirty_worktree,
        "governor_decision_loader_entry_point": GOVERNOR_DECISION_LOADER_ENTRY_POINT,
        "governor_readiness_loader_entry_point": GOVERNOR_READINESS_LOADER_ENTRY_POINT,
        "governor_deliberation_loader_entry_point": GOVERNOR_DELIBERATION_LOADER_ENTRY_POINT,
        "packet_adapter_entry_point": OPERATOR_PACKET_ADAPTER_ENTRY_POINT,
        "operator_action_entry_point": OPERATOR_ACTION_ENTRY_POINT,
        "native_status": parsed["native_status"],
        "fixture_id": action_input.fixture_id,
        "fixture_sha256": fixture_sha,
    }
    _expect_exact_values(provenance, provenance_expected, "operator provenance")

    expected_input_entries = [
        _expected_lineage_entry(
            context,
            name=name,
            path=path,
            producer="governor",
            schema_version=_governor_input_schema(name),
            component_revision=governor_revision,
            request_id=request.request_id,
            observed_at=parsed["acted_at"],
        )
        for name, path in source_paths.items()
    ]
    if request.run_mode is RunMode.REPLAY:
        expected_input_entries.append(
            _expected_lineage_entry(
                context,
                name="operator_replay_action",
                path=OPERATOR_REPLAY_INPUT_PATH,
                producer="harbormaster",
                schema_version=OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
                component_revision=f"sha256:{fixture_sha}",
                request_id=request.request_id,
                observed_at=parsed["acted_at"],
            )
        )
    output_sources = {
        "operator_review_packet": list(source_paths),
        "operator_action": [
            "operator_review_packet",
            *(("operator_replay_action",) if request.run_mode is RunMode.REPLAY else ()),
        ],
        "operator_receipt": ["operator_action", "operator_review_packet"],
        "operator_ledger_entry": ["operator_action", "operator_review_packet"],
        "operator_provenance": [
            "operator_action",
            *(("operator_replay_action",) if request.run_mode is RunMode.REPLAY else ()),
        ],
    }
    output_paths = (
        OPERATOR_REVIEW_PACKET_PATH,
        OPERATOR_ACTION_PATH,
        OPERATOR_RECEIPT_PATH,
        OPERATOR_LEDGER_ENTRY_PATH,
        OPERATOR_PROVENANCE_PATH,
    )
    expected_output_entries = []
    for path in output_paths:
        name = _operator_output_name(path)
        entry = _expected_lineage_entry(
            context,
            name=name,
            path=path,
            producer="operator",
            schema_version=_operator_output_schema(path),
            component_revision=context.battlestar_git_revision,
            request_id=request.request_id,
            observed_at=parsed["acted_at"],
        )
        entry["source_input_names"] = output_sources[name]
        expected_output_entries.append(entry)
    _expect_exact_values(
        lineage,
        {
            "schema_version": OPERATOR_LINEAGE_SCHEMA_VERSION,
            "mission_id": context.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode.value,
            "observed_at": parsed["acted_at"],
            "decision_id": decision_id,
            "action_id": parsed["action_id"],
            "inputs": expected_input_entries,
            "outputs": expected_output_entries,
        },
        "operator lineage manifest",
    )
    if action_input.action is not parsed["action"] or action_input.operator_id != parsed["operator_id"]:
        raise OperatorMalformedResultError("operator action input was not preserved")
    _reject_absolute_values(
        (packet, action, receipt, ledger, provenance, lineage),
        context.mission_root,
        battlestar_path,
    )


def _expect_values(
    actual: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    if any(actual.get(field) != value for field, value in expected.items()):
        raise OperatorMalformedResultError(f"{label} correlation is inconsistent")


def _expect_exact_values(
    actual: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    if set(actual) != set(expected) or actual != expected:
        raise OperatorMalformedResultError(f"{label} contract is inconsistent")


def _expected_lineage_entry(
    context: OperatorMissionContext,
    *,
    name: str,
    path: str,
    producer: str,
    schema_version: str | None,
    component_revision: str,
    request_id: str,
    observed_at: str,
) -> dict[str, object]:
    artifact = context.absolute(path)
    return {
        "name": name,
        "path": path,
        "producer": producer,
        "sha256": _sha256_file(artifact),
        "byte_size": artifact.stat().st_size,
        "schema_version": schema_version,
        "originating_component_revision": component_revision,
        "mission_id": context.mission_id,
        "request_id": request_id,
        "observed_at": observed_at,
    }


def _operator_worker(sender: Any, request: OperatorTransportRequest) -> None:
    try:
        sender.send({"ok": True, "result": _run_native_operator(request)})
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


def _run_native_operator(request: OperatorTransportRequest) -> dict[str, object]:
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    battlestar_root = request.battlestar_path.resolve(strict=True)
    mission_root = request.mission_root.resolve(strict=True)
    sys.path.insert(0, str(battlestar_root))
    prior_cwd = Path.cwd()
    os.chdir(mission_root)
    try:
        import blackpod.governor.governor_decision as decision_module
        import blackpod.governor.governor_decision_readiness as readiness_module
        import blackpod.governor.governor_deliberation as deliberation_module
        import blackpod.runtime.operator_inbox_action as action_module

        for module in (
            decision_module,
            readiness_module,
            deliberation_module,
            action_module,
        ):
            _require_module_origin(module, battlestar_root)

        action_input = _parse_transport_action_input(request.action_input)
        output = Path(request.output_dir)
        if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
            raise OperatorMalformedResultError(
                "reserved operator output directory is missing or nonempty"
            )

        decision = decision_module.load_governor_decision(
            request.governor_decision_path
        )
        readiness = readiness_module.load_governor_decision_readiness(
            request.governor_readiness_path
        )
        deliberation = deliberation_module.load_governor_deliberation(
            request.governor_deliberation_path
        )
        rendered = _read_strict_json(Path(request.governor_rendered_path))
        governor_provenance = _read_strict_json(
            Path(request.governor_provenance_path)
        )
        governor_lineage = _read_strict_json(Path(request.governor_lineage_path))
        governor_revision = _validate_governor_inputs(
            request,
            decision,
            readiness,
            deliberation,
            rendered,
            governor_provenance,
            governor_lineage,
        )

        source_paths = {
            "governor_decision": request.governor_decision_path,
            "governor_decision_readiness": request.governor_readiness_path,
            "governor_deliberation": request.governor_deliberation_path,
            "governor_rendered_decision": request.governor_rendered_path,
            "governor_provenance": request.governor_provenance_path,
            "governor_lineage_manifest": request.governor_lineage_path,
        }
        source_hashes = {
            name: _sha256_file(Path(path)) for name, path in source_paths.items()
        }
        decision_input_hash = _decision_input_hash(request.mission_id, source_hashes)
        packet = _build_operator_review_packet(
            request,
            decision,
            readiness,
            deliberation,
            source_paths=source_paths,
            source_hashes=source_hashes,
            decision_input_hash=decision_input_hash,
            acted_at=action_input.acted_at,
        )
        review_path = Path(OPERATOR_REVIEW_PACKET_PATH)
        packet_bytes = _json_bytes(packet)
        _write_bytes_exclusive(review_path, packet_bytes)

        with tempfile.TemporaryDirectory(prefix="blackpod-operator-native-") as raw_tmp:
            temporary_root = Path(raw_tmp).resolve(strict=True)
            # Mirror the mission-relative packet path in the isolated native
            # recorder workspace.  This lets the native payload retain its
            # exact packet_path field without later mutation while still
            # pointing at the immutable packet materialized in the mission.
            temporary_packet = temporary_root / OPERATOR_REVIEW_PACKET_PATH
            _write_bytes_exclusive(temporary_packet, packet_bytes)
            native_cwd = Path.cwd()
            os.chdir(temporary_root)
            try:
                native_result = action_module.record_operator_action(
                    Path(OPERATOR_REVIEW_PACKET_PATH),
                    action=action_input.action.value,
                    operator_id=action_input.operator_id,
                    reason=action_input.reason,
                    expires_in_minutes=action_input.expires_in_minutes,
                    created_at=action_input.acted_at,
                )
                native_action = _read_contained_native_action(
                    native_result.action_path,
                    temporary_root,
                )
            finally:
                os.chdir(native_cwd)
            _validate_native_action(
                native_result,
                native_action,
                action_input=action_input,
                packet=packet,
                packet_sha256=_sha256_bytes(packet_bytes),
                mission_id=request.mission_id,
            )

        result = OperatorResult(str(native_action["resulting_status"]))
        # The persisted operator action is the native
        # operator_inbox_action.v1 payload, unchanged in shape and values.
        _write_json_exclusive(Path(OPERATOR_ACTION_PATH), native_action)

        receipt = {
            "schema_version": OPERATOR_RECEIPT_SCHEMA_VERSION,
            "event_timestamp": action_input.acted_at,
            "run_id": request.mission_id,
            "decision_input_hash": decision_input_hash,
            "operator_route": OperatorRoute.PENDING_APPROVAL.value,
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "result_status": "CONSUMED",
        }
        _write_json_exclusive(Path(OPERATOR_RECEIPT_PATH), receipt)

        ledger = {
            "event_timestamp": action_input.acted_at,
            "run_id": request.mission_id,
            "decision_input_hash": decision_input_hash,
            "operator_route": OperatorRoute.PENDING_APPROVAL.value,
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "result_status": "CONSUMED",
        }
        _write_json_exclusive(Path(OPERATOR_LEDGER_ENTRY_PATH), ledger)

        provenance = {
            "schema_version": OPERATOR_PROVENANCE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode,
            "observed_at": action_input.acted_at,
            "decision_id": decision.decision_id,
            "action_id": native_result.action_id,
            "action": action_input.action.value,
            "result": result.value,
            "operator_id": action_input.operator_id,
            "battlestar_git_revision": request.battlestar_git_revision,
            "battlestar_git_branch": request.battlestar_git_branch,
            "battlestar_dirty_worktree": request.battlestar_dirty_worktree,
            "governor_decision_loader_entry_point": GOVERNOR_DECISION_LOADER_ENTRY_POINT,
            "governor_readiness_loader_entry_point": GOVERNOR_READINESS_LOADER_ENTRY_POINT,
            "governor_deliberation_loader_entry_point": GOVERNOR_DELIBERATION_LOADER_ENTRY_POINT,
            "packet_adapter_entry_point": OPERATOR_PACKET_ADAPTER_ENTRY_POINT,
            "operator_action_entry_point": OPERATOR_ACTION_ENTRY_POINT,
            "native_status": native_result.status,
            "fixture_id": action_input.fixture_id,
            "fixture_sha256": (
                _sha256_file(Path(OPERATOR_REPLAY_INPUT_PATH))
                if action_input.run_mode is RunMode.REPLAY
                else None
            ),
        }
        _write_json_exclusive(Path(OPERATOR_PROVENANCE_PATH), provenance)

        output_before_lineage = (
            OPERATOR_REVIEW_PACKET_PATH,
            OPERATOR_ACTION_PATH,
            OPERATOR_RECEIPT_PATH,
            OPERATOR_LEDGER_ENTRY_PATH,
            OPERATOR_PROVENANCE_PATH,
        )
        lineage_inputs = [
            _lineage_file_entry(
                name,
                path,
                producer="governor",
                schema_version=_governor_input_schema(name),
                component_revision=governor_revision,
                mission_id=request.mission_id,
                request_id=request.request_id,
                observed_at=action_input.acted_at,
            )
            for name, path in source_paths.items()
        ]
        if action_input.run_mode is RunMode.REPLAY:
            fixture_sha = _sha256_file(Path(OPERATOR_REPLAY_INPUT_PATH))
            lineage_inputs.append(
                _lineage_file_entry(
                    "operator_replay_action",
                    OPERATOR_REPLAY_INPUT_PATH,
                    producer="harbormaster",
                    schema_version=OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
                    component_revision=f"sha256:{fixture_sha}",
                    mission_id=request.mission_id,
                    request_id=request.request_id,
                    observed_at=action_input.acted_at,
                )
            )
        lineage = {
            "schema_version": OPERATOR_LINEAGE_SCHEMA_VERSION,
            "mission_id": request.mission_id,
            "request_id": request.request_id,
            "run_mode": request.run_mode,
            "observed_at": action_input.acted_at,
            "decision_id": decision.decision_id,
            "action_id": native_result.action_id,
            "inputs": lineage_inputs,
            "outputs": [
                _lineage_file_entry(
                    _operator_output_name(path),
                    path,
                    producer="operator",
                    schema_version=_operator_output_schema(path),
                    component_revision=request.battlestar_git_revision,
                    mission_id=request.mission_id,
                    request_id=request.request_id,
                    observed_at=action_input.acted_at,
                )
                for path in output_before_lineage
            ],
        }
        output_sources = {
            "operator_review_packet": list(source_paths),
            "operator_action": [
                "operator_review_packet",
                *(("operator_replay_action",) if action_input.run_mode is RunMode.REPLAY else ()),
            ],
            "operator_receipt": ["operator_action", "operator_review_packet"],
            "operator_ledger_entry": ["operator_action", "operator_review_packet"],
            "operator_provenance": [
                "operator_action",
                *(("operator_replay_action",) if action_input.run_mode is RunMode.REPLAY else ()),
            ],
        }
        for entry in lineage["outputs"]:
            entry["source_input_names"] = output_sources[entry["name"]]
        _write_json_exclusive(Path(OPERATOR_LINEAGE_PATH), lineage)

        _reject_absolute_output_leaks(output, battlestar_root, mission_root)
        return {
            "route": OperatorRoute.PENDING_APPROVAL.value,
            "action": action_input.action.value,
            "result": result.value,
            "native_status": native_result.status,
            "action_id": native_result.action_id,
            "operator_id": action_input.operator_id,
            "acted_at": action_input.acted_at,
            "warnings": list(packet["warnings"]),
            "review_packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "produced_paths": list(EXPECTED_OPERATOR_OUTPUT_PATHS),
        }
    finally:
        os.chdir(prior_cwd)


def _parse_transport_action_input(value: object) -> OperatorActionInput:
    if not isinstance(value, Mapping):
        raise OperatorMalformedResultError("transport action input must be an object")
    _require_exact_fields(
        value,
        {
            "run_mode",
            "action",
            "operator_id",
            "reason",
            "acted_at",
            "expires_in_minutes",
            "fixture_id",
        },
        "transport action input",
    )
    try:
        run_mode = RunMode(value["run_mode"])
        action = OperatorAction(value["action"])
        operator_id = validate_identifier(value["operator_id"], "operator_id")
        fixture_id = (
            None
            if value["fixture_id"] is None
            else validate_identifier(value["fixture_id"], "fixture_id")
        )
    except (IdentifierError, TypeError, ValueError) as exc:
        raise OperatorMalformedResultError(str(exc)) from exc
    if (run_mode is RunMode.REPLAY) is (fixture_id is None):
        raise OperatorMalformedResultError(
            "REPLAY requires fixture_id and LIVE forbids fixture_id"
        )
    try:
        return OperatorActionInput(
            run_mode=run_mode,
            action=action,
            operator_id=operator_id,
            reason=_strict_text(value["reason"], "reason"),
            acted_at=normalize_rfc3339(value["acted_at"], "acted_at"),
            expires_in_minutes=_positive_minutes(value["expires_in_minutes"]),
            fixture_id=fixture_id,
        )
    except ContractValidationError as exc:
        raise OperatorMalformedResultError(str(exc)) from exc


def _validate_governor_inputs(
    request: OperatorTransportRequest,
    decision: Any,
    readiness: Any,
    deliberation: Any,
    rendered: Mapping[str, Any],
    provenance: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> str:
    component = provenance.get("component")
    if not isinstance(component, Mapping):
        raise OperatorMalformedResultError("Governor provenance component is malformed")
    governor_revision = component.get("git_revision")
    checks = (
        (decision.decision_state, "PROCEED"),
        (decision.decision_status, "RENDERED"),
        (decision.allowed_next_step, "OPERATOR_REVIEW"),
        (readiness.readiness_state, "READY"),
        (decision.deliberation_id, deliberation.deliberation_id),
        (readiness.deliberation_id, deliberation.deliberation_id),
        (decision.readiness_id, readiness.readiness_id),
        (rendered.get("schema_version"), "blackpod.governor_rendered_decision.v1"),
        (rendered.get("mission_id"), request.mission_id),
        (rendered.get("request_id"), request.request_id),
        (rendered.get("run_mode"), request.run_mode),
        (rendered.get("decision_id"), decision.decision_id),
        (rendered.get("readiness_id"), readiness.readiness_id),
        (rendered.get("readiness_state"), readiness.readiness_state),
        (rendered.get("disposition"), "PROCEED"),
        (rendered.get("allowed_next_step"), "OPERATOR_REVIEW"),
        (provenance.get("schema_version"), "blackpod.governor_provenance.v1"),
        (provenance.get("mission_id"), request.mission_id),
        (provenance.get("request_id"), request.request_id),
        (provenance.get("run_mode"), request.run_mode),
        (component.get("run_mode"), request.run_mode),
        (lineage.get("schema_version"), "blackpod.governor_lineage.v1"),
        (lineage.get("mission_id"), request.mission_id),
        (lineage.get("request_id"), request.request_id),
        (lineage.get("run_mode"), request.run_mode),
    )
    if any(actual != expected for actual, expected in checks):
        raise OperatorMalformedResultError(
            "Governor artifacts do not represent the correlated PROCEED gate"
        )
    if (
        not isinstance(governor_revision, str)
        or _GIT_REVISION_PATTERN.fullmatch(governor_revision) is None
    ):
        raise OperatorMalformedResultError(
            "Governor provenance Git revision is malformed"
        )
    output_entries = lineage.get("outputs")
    if not isinstance(output_entries, list):
        raise OperatorMalformedResultError("Governor lineage outputs are malformed")
    by_path = {
        item.get("path"): item
        for item in output_entries
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    for path in (
        request.governor_decision_path,
        request.governor_readiness_path,
        request.governor_deliberation_path,
        request.governor_rendered_path,
        request.governor_provenance_path,
    ):
        entry = by_path.get(path)
        if not isinstance(entry, Mapping):
            raise OperatorMalformedResultError(
                "Governor lineage is missing a required operator input"
            )
        file = Path(path)
        if (
            entry.get("sha256") != _sha256_file(file)
            or entry.get("byte_size") != file.stat().st_size
            or entry.get("mission_id") != request.mission_id
            or entry.get("request_id") != request.request_id
        ):
            raise OperatorMalformedResultError(
                "Governor lineage input metadata does not match current artifacts"
            )
        if entry.get("originating_component_revision") != governor_revision:
            raise OperatorMalformedResultError(
                "Governor lineage revision conflicts with recorded provenance"
            )
    return governor_revision


def _build_operator_review_packet(
    request: OperatorTransportRequest,
    decision: Any,
    readiness: Any,
    deliberation: Any,
    *,
    source_paths: Mapping[str, str],
    source_hashes: Mapping[str, str],
    decision_input_hash: str,
    acted_at: str,
) -> dict[str, object]:
    seed = {
        "schema_version": OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
        "run_id": request.mission_id,
        "decision_input_hash": decision_input_hash,
        "operator_route": OperatorRoute.PENDING_APPROVAL.value,
    }
    packet_id = f"operator-review-packet-{_sha256_canonical(seed)[:16]}"
    warnings = list(
        dict.fromkeys(
            (*deliberation.warnings, *readiness.warnings, *decision.warnings)
        )
    )
    blockers = list(
        dict.fromkeys(
            (*deliberation.blockers, *readiness.blockers, *decision.blockers)
        )
    )
    packet: dict[str, object] = {
        "schema_version": OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
        # The current consumer contract exposes this field even though Phase 5
        # adapts from the mission spine rather than a legacy live-run manifest.
        # The canonical mission snapshot is the truthful source manifest here.
        "manifest_schema_version": "blackpod.mission_snapshot.v1",
        "packet_id": packet_id,
        "run_id": request.mission_id,
        "run_completed_at": decision.generated_at,
        "governor_posture": decision.posture,
        "decision_state": decision.decision_state,
        "allowed_next_step": decision.allowed_next_step,
        "decision_summary": decision.governor_rationale,
        "readiness_state": readiness.readiness_state,
        "readiness_summary": readiness.summary,
        "blockers": blockers,
        "warnings": warnings,
        "deliberation_summary": list(deliberation.governor_reasoning),
        "operator_route": OperatorRoute.PENDING_APPROVAL.value,
        "source_artifact_paths": dict(source_paths),
        "source_artifact_hashes": dict(source_hashes),
        "decision_input_hash": decision_input_hash,
        "created_at": acted_at,
    }
    if deliberation.unresolved_questions:
        packet["unresolved_questions"] = list(deliberation.unresolved_questions)
    return packet


def _validate_native_action(
    native_result: Any,
    payload: Mapping[str, Any],
    *,
    action_input: OperatorActionInput,
    packet: Mapping[str, Any],
    packet_sha256: str,
    mission_id: str,
) -> None:
    expected_result = {
        OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
        OperatorAction.REJECT: OperatorResult.REJECTED,
    }[action_input.action]
    checks = (
        (native_result.status, "RECORDED"),
        (native_result.source_run_id, mission_id),
        (native_result.action, action_input.action.value),
        (payload.get("schema_version"), OPERATOR_ACTION_SCHEMA_VERSION),
        (payload.get("action_id"), native_result.action_id),
        (payload.get("packet_id"), packet.get("packet_id")),
        (payload.get("packet_sha256"), packet_sha256),
        (payload.get("decision_input_hash"), packet.get("decision_input_hash")),
        (payload.get("source_run_id"), mission_id),
        (payload.get("action"), action_input.action.value),
        (payload.get("operator_id"), action_input.operator_id),
        (payload.get("reason"), action_input.reason),
        (payload.get("created_at"), action_input.acted_at),
        (payload.get("resulting_status"), expected_result.value),
    )
    if any(actual != expected for actual, expected in checks):
        raise OperatorMalformedResultError(
            "native operator action did not preserve validated inputs"
        )
    if payload.get("expires_at") != _expected_expires_at(action_input):
        raise OperatorMalformedResultError("native operator expiry is inconsistent")


def _read_contained_native_action(
    action_path: str | Path,
    temporary_root: Path,
) -> dict[str, Any]:
    """Read the native recorder's relative result beneath its resolved temp root."""

    root = Path(temporary_root).resolve(strict=True)
    candidate = Path(action_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise OperatorMalformedResultError(
            "native operator action artifact is missing"
        ) from exc
    if not _is_relative_to(resolved, root) or resolved.is_symlink():
        raise OperatorMalformedResultError(
            "native operator action escaped its temporary directory"
        )
    return _read_strict_json(resolved)


def _expected_expires_at(value: OperatorActionInput) -> str | None:
    if value.expires_in_minutes is None:
        return None
    from datetime import timedelta

    from .contracts.mission_request import format_rfc3339, parse_rfc3339

    return format_rfc3339(
        parse_rfc3339(value.acted_at, "acted_at")
        + timedelta(minutes=value.expires_in_minutes)
    )


def _lineage_file_entry(
    name: str,
    path: str,
    *,
    producer: str,
    schema_version: str | None,
    component_revision: str,
    mission_id: str,
    request_id: str,
    observed_at: str,
) -> dict[str, object]:
    file = Path(path)
    return {
        "name": name,
        "path": path,
        "producer": producer,
        "sha256": _sha256_file(file),
        "byte_size": file.stat().st_size,
        "schema_version": schema_version,
        "originating_component_revision": component_revision,
        "mission_id": mission_id,
        "request_id": request_id,
        "observed_at": observed_at,
    }


def _governor_input_schema(name: str) -> str:
    return {
        "governor_decision": "blackpod.contracts.governor_decision.GovernorDecision",
        "governor_decision_readiness": "blackpod.contracts.GovernorDecisionReadiness",
        "governor_deliberation": "blackpod.contracts.GovernorDeliberation",
        "governor_rendered_decision": "blackpod.governor_rendered_decision.v1",
        "governor_provenance": "blackpod.governor_provenance.v1",
        "governor_lineage_manifest": "blackpod.governor_lineage.v1",
    }[name]


def _operator_output_schema(path: str) -> str | None:
    return {
        OPERATOR_REVIEW_PACKET_PATH: OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
        OPERATOR_ACTION_PATH: OPERATOR_ACTION_SCHEMA_VERSION,
        OPERATOR_RECEIPT_PATH: OPERATOR_RECEIPT_SCHEMA_VERSION,
        OPERATOR_LEDGER_ENTRY_PATH: OPERATOR_LEDGER_SCHEMA_VERSION,
        OPERATOR_PROVENANCE_PATH: OPERATOR_PROVENANCE_SCHEMA_VERSION,
    }[path]


def _operator_output_name(path: str) -> str:
    return {
        OPERATOR_REVIEW_PACKET_PATH: "operator_review_packet",
        OPERATOR_ACTION_PATH: "operator_action",
        OPERATOR_RECEIPT_PATH: "operator_receipt",
        OPERATOR_LEDGER_ENTRY_PATH: "operator_ledger_entry",
        OPERATOR_PROVENANCE_PATH: "operator_provenance",
    }[path]


def _decision_input_hash(run_id: str, source_hashes: Mapping[str, str]) -> str:
    return _sha256_canonical({"run_id": run_id, "source_hashes": dict(source_hashes)})


def _sha256_canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_bytes_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _write_json_exclusive(path: Path, value: Mapping[str, object]) -> None:
    _write_bytes_exclusive(path, _json_bytes(value))


def _read_strict_json(path: Path) -> dict[str, Any]:
    return parse_strict_json_object_bytes(
        path.read_bytes(), document_name=f"artifact {path.name}"
    )


def _require_module_origin(module: Any, battlestar_root: Path) -> None:
    source = getattr(module, "__file__", None)
    if not isinstance(source, str):
        raise OperatorMalformedResultError("Battlestar module origin is unavailable")
    resolved = Path(source).resolve(strict=True)
    if not _is_relative_to(resolved, battlestar_root):
        raise OperatorMalformedResultError(
            "operator imported a module outside BATTLESTAR_PATH"
        )


def _reject_absolute_output_leaks(
    output: Path, battlestar_root: Path, mission_root: Path
) -> None:
    values = tuple(
        _read_strict_json(path)
        for path in output.iterdir()
        if path.is_file() and path.suffix == ".json"
    )
    _reject_absolute_values(values, mission_root, battlestar_root)


def _reject_absolute_values(
    values: tuple[Mapping[str, Any], ...], *forbidden_roots: Path
) -> None:
    serialized = "\n".join(json.dumps(value, sort_keys=True) for value in values)
    if (
        any(str(path) in serialized for path in forbidden_roots)
        or _ABSOLUTE_POSIX_PATH.search(serialized)
        or _ABSOLUTE_WINDOWS_PATH.search(serialized)
    ):
        raise OperatorMalformedResultError(
            "operator artifact contains an absolute local path"
        )


def _native_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OperatorMalformedResultError("operator artifact path must be relative")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise OperatorMalformedResultError("operator artifact path is unsafe")
    return value


def _native_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise OperatorMalformedResultError(f"{field_name} must be a nonblank string")
    return value


def _native_identifier(value: object, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name)
    except IdentifierError as exc:
        raise OperatorMalformedResultError(str(exc)) from exc


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise OperatorMalformedResultError(f"{field_name} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise OperatorMalformedResultError(
                f"{field_name} must contain nonblank strings"
            )
        result.append(item)
    return tuple(result)


def _safe_error_type(value: str) -> str:
    filtered = "".join(
        character if character.isalnum() or character in "._:@-" else "_"
        for character in str(value)
    )[:128]
    return filtered if filtered and filtered[0].isalnum() else "OperatorError"


def _sanitize_message(message: str, *paths: Path) -> str:
    result = str(message)
    for path in sorted((str(path) for path in paths), key=len, reverse=True):
        result = result.replace(path, "<redacted-path>")
    result = _ABSOLUTE_POSIX_PATH.sub("<redacted-path>", result)
    result = _ABSOLUTE_WINDOWS_PATH.sub("<redacted-path>", result)
    return result[:512] or "operator action failed"
