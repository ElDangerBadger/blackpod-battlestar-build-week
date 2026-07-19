"""State-driven orchestration for one complete, existing BlackPod mission path.

This module contains no stage policy.  It dispatches only to the already
implemented Harbormaster workflows and uses the canonical snapshot as its
resume cursor.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .contracts import (
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    ModelDockCallStatus,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    RunMode,
    StageStatus,
)
from .council_workflow import CouncilRunSettings, run_council
from .governor_workflow import GovernorRunSettings, run_governor
from .hashing import sha256_file
from .identifiers import IdentifierError, validate_identifier
from .mission_initialization import (
    HarbormasterSettings,
    MissionInitializationAction,
    MissionInitializationResolution,
    initialize_or_validate_existing,
)
from .mission_store import LoadedMission, MissionPaths, MissionStore
from .modeldock_config import load_modeldock_config
from .modeldock_preflight import run_modeldock_preflight
from .navigator_workflow import NavigatorRunSettings, run_navigator
from .operator_workflow import OperatorRunSettings, run_operator_action
from .oracle_enrichment_workflow import (
    OracleEnrichmentSettings,
    run_oracle_enrichment,
)
from .oracle_workflow import OracleRunSettings, run_oracle


class UnifiedMissionWorkflowError(RuntimeError):
    """Base class for unified mission orchestration failures."""


class UnifiedMissionInvocationError(UnifiedMissionWorkflowError):
    """Raised before execution when unified command inputs are inconsistent."""


class UnifiedMissionStateConflictError(UnifiedMissionWorkflowError):
    """Raised when the canonical snapshot cannot be safely dispatched."""


class MissionThrough(str, Enum):
    ORACLE = "ORACLE"
    COUNCIL = "COUNCIL"
    GOVERNOR = "GOVERNOR"
    OPERATOR = "OPERATOR"
    NAVIGATOR = "NAVIGATOR"


_THROUGH_ORDER = {
    MissionThrough.ORACLE: 1,
    MissionThrough.COUNCIL: 2,
    MissionThrough.GOVERNOR: 3,
    MissionThrough.OPERATOR: 4,
    MissionThrough.NAVIGATOR: 5,
}


class UnifiedMissionAction(str, Enum):
    EXECUTED = "EXECUTED"
    STOPPED = "STOPPED"
    NO_OP_ALREADY_SATISFIED = "NO_OP_ALREADY_SATISFIED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class UnifiedMissionSettings:
    artifacts_root: Path
    with_modeldock: bool
    request_path: Path | None = None
    mission_id: str | None = None
    through: MissionThrough | str = MissionThrough.NAVIGATOR
    operator_action: OperatorAction | str | None = None
    operator_id: str | None = None
    operator_reason: str | None = None
    expires_in_minutes: int | None = None
    oracle_replay_fixture: Path | None = None
    modeldock_replay_fixture: Path | None = None
    council_replay_fixture: Path | None = None
    council_policy_input: Path | None = None
    governor_replay_fixture: Path | None = None
    governor_context_input: Path | None = None
    operator_replay_fixture: Path | None = None
    navigator_replay_fixture: Path | None = None
    deadline_seconds: float = 60.0
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class UnifiedMissionResult:
    request: MissionRequest
    snapshot: MissionSnapshot
    paths: MissionPaths
    action: UnifiedMissionAction
    technical_success: bool
    no_op: bool
    stopped: bool
    through: MissionThrough
    executed_stages: tuple[str, ...]
    initialization_action: MissionInitializationAction | None
    presentation: object | None


Environment = Mapping[str, str] | None
StageRunner = Callable[[Any, Environment], Any]
MissionLoader = Callable[[MissionStore, str], LoadedMission]
Initializer = Callable[
    [HarbormasterSettings, datetime | None], MissionInitializationResolution
]
PresentationRenderer = Callable[[MissionStore, LoadedMission], object]


def _default_initializer(
    settings: HarbormasterSettings,
    now: datetime | None,
) -> MissionInitializationResolution:
    return initialize_or_validate_existing(settings, now=now)


def _default_loader(store: MissionStore, mission_id: str) -> LoadedMission:
    return store.load_mission(mission_id)


def _default_oracle(settings: OracleRunSettings, environ: Environment) -> Any:
    return run_oracle(settings, environ=environ)


def _default_enrichment(
    settings: OracleEnrichmentSettings, environ: Environment
) -> Any:
    return run_oracle_enrichment(settings, environ=environ)


def _default_council(settings: CouncilRunSettings, environ: Environment) -> Any:
    return run_council(settings, environ=environ)


def _default_governor(settings: GovernorRunSettings, environ: Environment) -> Any:
    return run_governor(settings, environ=environ)


def _default_operator(settings: OperatorRunSettings, environ: Environment) -> Any:
    return run_operator_action(settings, environ=environ)


def _default_navigator(settings: NavigatorRunSettings, environ: Environment) -> Any:
    return run_navigator(settings, environ=environ)


def _default_modeldock_config(environ: Environment) -> Any:
    return load_modeldock_config(environ=environ)


def _default_modeldock_preflight(config: object) -> Any:
    return run_modeldock_preflight(config)  # type: ignore[arg-type]


def _default_presentation_renderer(
    store: MissionStore, loaded: LoadedMission
) -> object:
    # Imported lazily so stage-level commands remain independent of the
    # presentation projection and to avoid a module cycle during startup.
    from .mission_presentation import render_mission_presentation

    return render_mission_presentation(store, loaded)


@dataclass(frozen=True, slots=True)
class UnifiedMissionRunners:
    initializer: Initializer = _default_initializer
    loader: MissionLoader = _default_loader
    oracle: StageRunner = _default_oracle
    enrichment: StageRunner = _default_enrichment
    council: StageRunner = _default_council
    governor: StageRunner = _default_governor
    operator: StageRunner = _default_operator
    navigator: StageRunner = _default_navigator
    modeldock_config_loader: Callable[[Environment], object] = (
        _default_modeldock_config
    )
    modeldock_preflight: Callable[[object], object] = _default_modeldock_preflight
    presentation_renderer: PresentationRenderer = _default_presentation_renderer


@dataclass(slots=True)
class _Execution:
    store: MissionStore
    loaded: LoadedMission
    target: MissionThrough
    initialization_action: MissionInitializationAction | None
    executed_stages: list[str] = field(default_factory=list)


def run_unified_mission(
    settings: UnifiedMissionSettings,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    runners: UnifiedMissionRunners | None = None,
) -> UnifiedMissionResult:
    """Initialize or validate one request, then orchestrate to ``through``."""

    active = runners or UnifiedMissionRunners()
    target, action = _validate_settings(settings, require_request=True)
    resolution = active.initializer(
        HarbormasterSettings(
            request_path=Path(settings.request_path),  # type: ignore[arg-type]
            artifacts_root=settings.artifacts_root,
        ),
        now,
    )
    store = MissionStore(settings.artifacts_root)
    loaded = active.loader(store, resolution.request.mission_id or "")
    execution = _Execution(
        store=store,
        loaded=loaded,
        target=target,
        initialization_action=resolution.action,
    )
    return _orchestrate(
        settings,
        execution,
        parsed_operator_action=action,
        environ=environ,
        runners=active,
    )


def resume_unified_mission(
    settings: UnifiedMissionSettings,
    *,
    environ: Mapping[str, str] | None = None,
    runners: UnifiedMissionRunners | None = None,
) -> UnifiedMissionResult:
    """Validate and resume an existing mission from its canonical snapshot."""

    active = runners or UnifiedMissionRunners()
    target, action = _validate_settings(settings, require_request=False)
    store = MissionStore(settings.artifacts_root)
    loaded = active.loader(store, settings.mission_id or "")
    execution = _Execution(
        store=store,
        loaded=loaded,
        target=target,
        initialization_action=None,
    )
    return _orchestrate(
        settings,
        execution,
        parsed_operator_action=action,
        environ=environ,
        runners=active,
    )


def _validate_settings(
    settings: UnifiedMissionSettings,
    *,
    require_request: bool,
) -> tuple[MissionThrough, OperatorAction | None]:
    if type(settings.with_modeldock) is not bool:
        raise UnifiedMissionInvocationError("with_modeldock must be explicitly boolean")
    if not settings.with_modeldock and settings.modeldock_replay_fixture is not None:
        raise UnifiedMissionInvocationError(
            "--without-modeldock forbids a ModelDock replay fixture"
        )
    if require_request:
        if settings.request_path is None or settings.mission_id is not None:
            raise UnifiedMissionInvocationError(
                "mission-run requires request_path and forbids mission_id"
            )
    elif settings.mission_id is None or settings.request_path is not None:
        raise UnifiedMissionInvocationError(
            "mission-resume requires mission_id and forbids request_path"
        )
    try:
        target = (
            settings.through
            if isinstance(settings.through, MissionThrough)
            else MissionThrough(settings.through)
        )
    except (TypeError, ValueError) as exc:
        raise UnifiedMissionInvocationError(
            "through must be ORACLE, COUNCIL, GOVERNOR, OPERATOR, or NAVIGATOR"
        ) from exc
    if (
        isinstance(settings.deadline_seconds, bool)
        or not isinstance(settings.deadline_seconds, (int, float))
        or not math.isfinite(float(settings.deadline_seconds))
        or settings.deadline_seconds <= 0
    ):
        raise UnifiedMissionInvocationError(
            "deadline_seconds must be finite and positive"
        )

    parsed_action: OperatorAction | None = None
    if _THROUGH_ORDER[target] >= _THROUGH_ORDER[MissionThrough.OPERATOR]:
        try:
            parsed_action = (
                settings.operator_action
                if isinstance(settings.operator_action, OperatorAction)
                else OperatorAction(settings.operator_action)
            )
            validate_identifier(settings.operator_id, "operator_id")
        except (IdentifierError, TypeError, ValueError) as exc:
            raise UnifiedMissionInvocationError(
                "through OPERATOR or NAVIGATOR requires an explicit supported "
                "operator action and operator_id"
            ) from exc
        if (
            not isinstance(settings.operator_reason, str)
            or not settings.operator_reason.strip()
            or settings.operator_reason != settings.operator_reason.strip()
            or len(settings.operator_reason) > 1024
        ):
            raise UnifiedMissionInvocationError(
                "through OPERATOR or NAVIGATOR requires a trimmed nonblank "
                "operator_reason of at most 1024 characters"
            )
    elif any(
        value is not None
        for value in (
            settings.operator_action,
            settings.operator_id,
            settings.operator_reason,
            settings.expires_in_minutes,
            settings.operator_replay_fixture,
        )
    ):
        # Supplying future operator controls while deliberately stopping before
        # Governor/Operator is ambiguous and makes repeat identity unclear.
        raise UnifiedMissionInvocationError(
            "operator controls are allowed only when through is OPERATOR or NAVIGATOR"
        )
    return target, parsed_action


def _orchestrate(
    settings: UnifiedMissionSettings,
    execution: _Execution,
    *,
    parsed_operator_action: OperatorAction | None,
    environ: Environment,
    runners: UnifiedMissionRunners,
) -> UnifiedMissionResult:
    _validate_modeldock_history(execution.loaded.snapshot, settings.with_modeldock)
    _validate_completed_input_identity(settings, execution.loaded)
    blocked = _existing_attempt_result(settings, execution, runners=runners)
    if blocked is not None:
        return blocked
    _validate_completed_operator_identity(
        execution.loaded.snapshot,
        action=parsed_operator_action,
        operator_id=settings.operator_id,
    )

    if _target_reached(
        execution.loaded.snapshot,
        execution.target,
        with_modeldock=settings.with_modeldock,
    ):
        return _finish(
            settings,
            execution,
            runners=runners,
            stopped=(
                execution.target is not MissionThrough.NAVIGATOR
                and not execution.loaded.snapshot.terminal
            ),
        )

    snapshot = execution.loaded.snapshot
    if snapshot.stages["oracle"].status is StageStatus.NOT_STARTED:
        _run_stage(
            execution,
            "oracle",
            runners.oracle,
            OracleRunSettings(
                mission_id=snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                replay_fixture=settings.oracle_replay_fixture,
                deadline_seconds=settings.deadline_seconds,
                strict_battlestar_clean=settings.strict_battlestar_clean,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked
    elif snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED:
        raise UnifiedMissionStateConflictError(
            "Oracle is neither NOT_STARTED nor technically successful"
        )

    if settings.with_modeldock and not execution.loaded.snapshot.stages[
        "oracle"
    ].modeldock_calls:
        if execution.loaded.request.run_mode is RunMode.LIVE:
            config = runners.modeldock_config_loader(environ)
            report = runners.modeldock_preflight(config)
            if not bool(getattr(report, "ready", False)):
                raise UnifiedMissionStateConflictError(
                    "LIVE ModelDock deep inference preflight is not ready"
                )
        _run_stage(
            execution,
            "modeldock",
            runners.enrichment,
            OracleEnrichmentSettings(
                mission_id=execution.loaded.snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                replay_fixture=settings.modeldock_replay_fixture,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked

    if execution.target is MissionThrough.ORACLE:
        return _finish(
            settings,
            execution,
            runners=runners,
            stopped=not execution.loaded.snapshot.terminal,
        )

    snapshot = execution.loaded.snapshot
    if snapshot.stages["council"].status is StageStatus.NOT_STARTED:
        _run_stage(
            execution,
            "council",
            runners.council,
            CouncilRunSettings(
                mission_id=snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                replay_fixture=settings.council_replay_fixture,
                policy_input=settings.council_policy_input,
                deadline_seconds=settings.deadline_seconds,
                strict_battlestar_clean=settings.strict_battlestar_clean,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked
    elif snapshot.stages["council"].status is not StageStatus.SUCCEEDED:
        raise UnifiedMissionStateConflictError(
            "Council is neither NOT_STARTED nor technically successful"
        )

    if execution.target is MissionThrough.COUNCIL:
        return _finish(
            settings,
            execution,
            runners=runners,
            stopped=not execution.loaded.snapshot.terminal,
        )

    snapshot = execution.loaded.snapshot
    if snapshot.stages["governor"].status is StageStatus.NOT_STARTED:
        _run_stage(
            execution,
            "governor",
            runners.governor,
            GovernorRunSettings(
                mission_id=snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                replay_fixture=settings.governor_replay_fixture,
                context_input=settings.governor_context_input,
                deadline_seconds=settings.deadline_seconds,
                strict_battlestar_clean=settings.strict_battlestar_clean,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked
    elif snapshot.stages["governor"].status is not StageStatus.SUCCEEDED:
        raise UnifiedMissionStateConflictError(
            "Governor is neither NOT_STARTED nor technically successful"
        )

    if execution.target is MissionThrough.GOVERNOR:
        return _finish(
            settings,
            execution,
            runners=runners,
            stopped=not execution.loaded.snapshot.terminal,
        )

    snapshot = execution.loaded.snapshot
    if snapshot.stages["governor"].native_state != "PROCEED":
        # HOLD, REVIEW_REQUIRED, BLOCKED, and STAND_DOWN are valid native
        # decisions.  The configured operator action is deliberately ignored.
        return _finish(settings, execution, runners=runners, stopped=False)

    operator_status = snapshot.operator.action_status
    if operator_status is OperatorActionStatus.NOT_STARTED:
        if parsed_operator_action is None:
            raise AssertionError("validated operator target lacks an explicit action")
        _run_stage(
            execution,
            "operator",
            runners.operator,
            OperatorRunSettings(
                mission_id=snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                action=parsed_operator_action,
                operator_id=settings.operator_id or "",
                reason=settings.operator_reason or "",
                replay_fixture=settings.operator_replay_fixture,
                expires_in_minutes=settings.expires_in_minutes,
                deadline_seconds=settings.deadline_seconds,
                strict_battlestar_clean=settings.strict_battlestar_clean,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked
    elif operator_status is not OperatorActionStatus.SUCCEEDED:
        raise UnifiedMissionStateConflictError(
            "operator action is neither NOT_STARTED nor technically successful"
        )

    snapshot = execution.loaded.snapshot
    _validate_completed_operator_identity(
        snapshot,
        action=parsed_operator_action,
        operator_id=settings.operator_id,
    )
    if execution.target is MissionThrough.OPERATOR:
        # Approval is a deliberate resumable stop at Navigator. Rejection is
        # already a canonical terminal VETOED mission, so do not present it as
        # merely stopped.
        return _finish(
            settings,
            execution,
            runners=runners,
            stopped=not snapshot.terminal,
        )
    if snapshot.operator.result is OperatorResult.REJECTED:
        return _finish(settings, execution, runners=runners, stopped=False)
    if snapshot.operator.result is not OperatorResult.APPROVED_FOR_HANDOFF:
        raise UnifiedMissionStateConflictError(
            "operator completion lacks a canonical handoff result"
        )

    navigator_status = snapshot.stages["navigator"].status
    if navigator_status is StageStatus.NOT_STARTED:
        _run_stage(
            execution,
            "navigator",
            runners.navigator,
            NavigatorRunSettings(
                mission_id=snapshot.mission_id,
                artifacts_root=settings.artifacts_root,
                replay_fixture=settings.navigator_replay_fixture,
                deadline_seconds=settings.deadline_seconds,
                strict_battlestar_clean=settings.strict_battlestar_clean,
            ),
            environ=environ,
            runners=runners,
        )
        blocked = _existing_attempt_result(settings, execution, runners=runners)
        if blocked is not None:
            return blocked
    elif navigator_status is not StageStatus.SUCCEEDED:
        raise UnifiedMissionStateConflictError(
            "Navigator is neither NOT_STARTED nor technically successful"
        )
    return _finish(settings, execution, runners=runners, stopped=False)


def _run_stage(
    execution: _Execution,
    name: str,
    runner: StageRunner,
    settings: object,
    *,
    environ: Environment,
    runners: UnifiedMissionRunners,
) -> None:
    result = runner(settings, environ)
    action = getattr(getattr(result, "action", None), "value", None)
    if action is None:
        action = getattr(getattr(result, "disposition", None), "value", None)
    if not isinstance(action, str) or not action.startswith("NO_OP"):
        execution.executed_stages.append(name)
    execution.loaded = runners.loader(
        execution.store, execution.loaded.snapshot.mission_id
    )


def _existing_attempt_result(
    settings: UnifiedMissionSettings,
    execution: _Execution,
    *,
    runners: UnifiedMissionRunners,
) -> UnifiedMissionResult | None:
    snapshot = execution.loaded.snapshot
    if snapshot.mission_outcome is MissionOutcome.FAILED:
        return _finish(settings, execution, runners=runners, stopped=False)
    running = [
        name
        for name, stage in snapshot.stages.items()
        if stage.status is StageStatus.RUNNING
    ]
    if snapshot.operator.action_status is OperatorActionStatus.RUNNING:
        running.append("operator")
    if running:
        raise UnifiedMissionStateConflictError(
            "mission contains an interrupted RUNNING attempt: "
            + ", ".join(running)
        )
    failed = [
        name
        for name, stage in snapshot.stages.items()
        if stage.status is StageStatus.FAILED
    ]
    if snapshot.operator.action_status is OperatorActionStatus.FAILED:
        failed.append("operator")
    if failed:
        raise UnifiedMissionStateConflictError(
            "failed mission state lacks the canonical FAILED outcome"
        )
    return None


def _validate_modeldock_history(
    snapshot: MissionSnapshot,
    with_modeldock: bool,
) -> None:
    calls = snapshot.stages["oracle"].modeldock_calls
    if calls and not with_modeldock:
        raise UnifiedMissionStateConflictError(
            "mission already contains ModelDock enrichment but this invocation "
            "requested --without-modeldock"
        )
    downstream_started = any(
        snapshot.stages[name].status is not StageStatus.NOT_STARTED
        for name in ("council", "governor", "navigator")
    )
    if with_modeldock and not calls and downstream_started:
        raise UnifiedMissionStateConflictError(
            "ModelDock enrichment cannot be added after Council has started"
        )
    if calls and calls[0].status not in {
        ModelDockCallStatus.RUNNING,
        ModelDockCallStatus.SUCCEEDED,
        ModelDockCallStatus.FAILED,
    }:
        raise UnifiedMissionStateConflictError(
            "mission contains an unsupported ModelDock call state"
        )


def _validate_completed_input_identity(
    settings: UnifiedMissionSettings,
    loaded: LoadedMission,
) -> None:
    """Bind explicitly repeated inputs to their recorded immutable identity.

    Resume intentionally permits callers to omit inputs for stages that are
    already complete.  When callers do provide them, however, accepting bytes
    different from the canonical attempt would make a completed unified run
    appear idempotent under a conflicting invocation.
    """

    snapshot = loaded.snapshot
    request = loaded.request
    artifacts = {
        artifact.name: artifact for artifact in getattr(snapshot, "artifacts", ())
    }

    if request.run_mode is RunMode.LIVE:
        replay_inputs = (
            settings.oracle_replay_fixture,
            settings.modeldock_replay_fixture,
            settings.council_replay_fixture,
            settings.governor_replay_fixture,
            settings.operator_replay_fixture,
            settings.navigator_replay_fixture,
        )
        if any(path is not None for path in replay_inputs):
            raise UnifiedMissionInvocationError(
                "LIVE unified missions forbid replay fixtures"
            )
    else:
        if settings.council_policy_input is not None:
            raise UnifiedMissionInvocationError(
                "REPLAY unified missions forbid Council LIVE policy input"
            )
        if settings.governor_context_input is not None:
            raise UnifiedMissionInvocationError(
                "REPLAY unified missions forbid Governor LIVE context input"
            )

    completed_stage_inputs = (
        (
            "Oracle",
            snapshot.stages["oracle"].status
            in {StageStatus.SUCCEEDED, StageStatus.FAILED},
            settings.oracle_replay_fixture,
            "oracle_replay_input",
        ),
        (
            "Council",
            snapshot.stages["council"].status
            in {StageStatus.SUCCEEDED, StageStatus.FAILED},
            (
                settings.council_replay_fixture
                if request.run_mode is RunMode.REPLAY
                else settings.council_policy_input
            ),
            "council_supporting_input",
        ),
        (
            "Governor",
            snapshot.stages["governor"].status
            in {StageStatus.SUCCEEDED, StageStatus.FAILED},
            (
                settings.governor_replay_fixture
                if request.run_mode is RunMode.REPLAY
                else settings.governor_context_input
            ),
            "governor_supporting_context",
        ),
        (
            "operator",
            snapshot.operator.action_status
            in {OperatorActionStatus.SUCCEEDED, OperatorActionStatus.FAILED},
            settings.operator_replay_fixture,
            "operator_replay_action",
        ),
        (
            "Navigator",
            snapshot.stages["navigator"].status
            in {StageStatus.SUCCEEDED, StageStatus.FAILED},
            settings.navigator_replay_fixture,
            "navigator_replay_input",
        ),
    )
    for label, completed, supplied_path, artifact_name in completed_stage_inputs:
        if not completed or supplied_path is None:
            continue
        artifact = artifacts.get(artifact_name)
        if artifact is None:
            raise UnifiedMissionStateConflictError(
                f"completed {label} input identity is missing from canonical artifacts"
            )
        actual_sha = _explicit_input_sha256(supplied_path, label)
        if actual_sha != artifact.sha256:
            raise UnifiedMissionStateConflictError(
                f"supplied {label} input conflicts with the completed mission"
            )

    calls = snapshot.stages["oracle"].modeldock_calls
    modeldock_complete = bool(calls) and calls[0].status in {
        ModelDockCallStatus.SUCCEEDED,
        ModelDockCallStatus.FAILED,
    }
    if modeldock_complete and settings.modeldock_replay_fixture is not None:
        component = getattr(snapshot, "components", {}).get("modeldock")
        expected_sha = getattr(component, "replay_fixture_sha256", None)
        if expected_sha is None:
            raise UnifiedMissionStateConflictError(
                "completed ModelDock replay identity is missing from provenance"
            )
        actual_sha = _explicit_input_sha256(
            settings.modeldock_replay_fixture, "ModelDock"
        )
        if actual_sha != expected_sha:
            raise UnifiedMissionStateConflictError(
                "supplied ModelDock replay fixture conflicts with the completed mission"
            )


def _explicit_input_sha256(path: Path, label: str) -> str:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise UnifiedMissionInvocationError(
            f"supplied {label} input must be a regular non-symlink file"
        )
    try:
        return sha256_file(candidate)
    except OSError as exc:
        raise UnifiedMissionInvocationError(
            f"supplied {label} input could not be read"
        ) from exc


def _validate_completed_operator_identity(
    snapshot: MissionSnapshot,
    *,
    action: OperatorAction | None,
    operator_id: str | None,
) -> None:
    operator = snapshot.operator
    if operator.action_status is not OperatorActionStatus.SUCCEEDED:
        return
    if action is not None and operator.action is not action:
        raise UnifiedMissionStateConflictError(
            "configured operator action conflicts with the completed mission"
        )
    if operator_id is not None and operator.operator_id != operator_id:
        raise UnifiedMissionStateConflictError(
            "configured operator_id conflicts with the completed mission"
        )


def _target_reached(
    snapshot: MissionSnapshot,
    target: MissionThrough,
    *,
    with_modeldock: bool,
) -> bool:
    if target is MissionThrough.ORACLE:
        if snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED:
            return False
        if not with_modeldock:
            return True
        calls = snapshot.stages["oracle"].modeldock_calls
        return len(calls) == 1 and calls[0].status is ModelDockCallStatus.SUCCEEDED
    if target is MissionThrough.COUNCIL:
        return snapshot.stages["council"].status is StageStatus.SUCCEEDED
    if target is MissionThrough.GOVERNOR:
        return snapshot.stages["governor"].status is StageStatus.SUCCEEDED
    if target is MissionThrough.OPERATOR:
        return snapshot.operator.action_status is OperatorActionStatus.SUCCEEDED
    return snapshot.stages["navigator"].status is StageStatus.SUCCEEDED


def _finish(
    settings: UnifiedMissionSettings,
    execution: _Execution,
    *,
    runners: UnifiedMissionRunners,
    stopped: bool,
) -> UnifiedMissionResult:
    loaded = runners.loader(execution.store, execution.loaded.snapshot.mission_id)
    execution.loaded = loaded
    technical_success = loaded.snapshot.mission_outcome is not MissionOutcome.FAILED
    no_op = (
        execution.initialization_action
        is not MissionInitializationAction.INITIALIZED
        and not execution.executed_stages
    )
    if not technical_success:
        action = UnifiedMissionAction.FAILED
    elif no_op:
        action = UnifiedMissionAction.NO_OP_ALREADY_SATISFIED
    elif stopped:
        action = UnifiedMissionAction.STOPPED
    else:
        action = UnifiedMissionAction.EXECUTED
    presentation = runners.presentation_renderer(execution.store, loaded)
    return UnifiedMissionResult(
        request=loaded.request,
        snapshot=loaded.snapshot,
        paths=loaded.paths,
        action=action,
        technical_success=technical_success,
        no_op=no_op,
        stopped=stopped,
        through=execution.target,
        executed_stages=tuple(execution.executed_stages),
        initialization_action=execution.initialization_action,
        presentation=presentation,
    )
