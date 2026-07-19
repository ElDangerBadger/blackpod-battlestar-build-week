"""Harbormaster CLI for the complete Stage 1 mission lifecycle."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .battlestar_config import BattlestarConfigurationError
from .contracts import ContractValidationError, MissionRequest, RunMode
from .contracts.mission_request import format_rfc3339
from .council_workflow import (
    CouncilInvocationError,
    CouncilRunSettings,
    CouncilStateConflictError,
    CouncilWorkflowError,
    CouncilWorkflowResult,
    run_council,
)
from .identifiers import IdentifierError, allocate_mission_id
from .governor_workflow import (
    GovernorInvocationError,
    GovernorRunSettings,
    GovernorStateConflictError,
    GovernorWorkflowError,
    GovernorWorkflowResult,
    run_governor,
)
from .mission_store import (
    DuplicateMissionError,
    MissionInitialization,
    MissionStore,
    MissionStoreError,
    PersistenceError,
    UnsafePathError,
)
from .oracle_workflow import (
    OracleInvocationError,
    OracleRunSettings,
    OracleStateConflictError,
    OracleWorkflowError,
    OracleWorkflowResult,
    run_oracle,
)
from .operator_workflow import (
    OperatorInvocationError,
    OperatorPreconditionError,
    OperatorRunSettings,
    OperatorStateConflictError,
    OperatorWorkflowError,
    OperatorWorkflowResult,
    run_operator_action,
)
from .navigator_workflow import (
    NavigatorInvocationError,
    NavigatorPreconditionError,
    NavigatorRunSettings,
    NavigatorStateConflictError,
    NavigatorWorkflowError,
    NavigatorWorkflowResult,
    run_navigator,
)


EXIT_SUCCESS = 0
EXIT_INVALID_REQUEST = 2
EXIT_DUPLICATE_MISSION = 3
EXIT_PERSISTENCE_FAILURE = 4
EXIT_ORACLE_FAILURE = 5
EXIT_COUNCIL_FAILURE = 6
EXIT_GOVERNOR_FAILURE = 7
EXIT_OPERATOR_FAILURE = 8
EXIT_NAVIGATOR_FAILURE = 9


@dataclass(frozen=True, slots=True)
class HarbormasterSettings:
    request_path: Path
    artifacts_root: Path


def initialize_mission(
    settings: HarbormasterSettings,
    *,
    now: datetime | None = None,
) -> MissionInitialization:
    """Validate one request and persist its Phase 1 mission spine."""

    request = MissionRequest.from_file(settings.request_path)
    mission_id = allocate_mission_id(
        request.identity_payload(),
        request_id=request.request_id,
        run_mode=request.run_mode.value,
        supplied_mission_id=request.mission_id,
    )

    if request.run_mode is RunMode.REPLAY:
        initialization_time = request.requested_at
    else:
        clock_value = now if now is not None else datetime.now(UTC)
        initialization_time = format_rfc3339(clock_value)

    store = MissionStore(settings.artifacts_root)
    return store.initialize(
        request,
        mission_id=mission_id,
        started_at=initialization_time,
        observed_at=initialization_time,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster",
        description="Initialize one BlackPod Build Week mission spine.",
    )
    parser.add_argument("--request", required=True, type=Path, help="mission request JSON")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root beneath which missions/ is created (default: artifacts)",
    )
    return parser


def build_oracle_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster run-oracle",
        description="Run the existing Battlestar Oracle for an initialized mission.",
    )
    parser.add_argument("--mission-id", required=True, help="initialized mission ID")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    parser.add_argument(
        "--replay-fixture",
        type=Path,
        help="strict deterministic Oracle input; required only for REPLAY missions",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="hard Oracle worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def build_council_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster run-council",
        description="Run Battlestar Council for a mission with a completed Oracle stage.",
    )
    parser.add_argument("--mission-id", required=True, help="initialized mission ID")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--replay-fixture",
        type=Path,
        help="deterministic Council policy input; required for REPLAY missions",
    )
    transport.add_argument(
        "--policy-input",
        type=Path,
        help="explicit Council policy input; required for LIVE missions",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="hard Council worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def build_governor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster run-governor",
        description=(
            "Run Battlestar Governor for a mission with a completed Council stage."
        ),
    )
    parser.add_argument("--mission-id", required=True, help="initialized mission ID")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument(
        "--replay-fixture",
        type=Path,
        help="deterministic Governor context; required for REPLAY missions",
    )
    transport.add_argument(
        "--context-input",
        type=Path,
        help="explicit Governor context; required for LIVE missions",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="hard Governor worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def build_operator_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster operator-action",
        description="Record one explicit operator action after Governor PROCEED.",
    )
    parser.add_argument("--mission-id", required=True, help="initialized mission ID")
    parser.add_argument(
        "--action",
        required=True,
        choices=("APPROVE_HANDOFF", "REJECT"),
        help="explicit operator action",
    )
    parser.add_argument("--operator-id", required=True, help="operator audit identity")
    parser.add_argument(
        "--reason",
        required=True,
        help="nonblank approval or rejection rationale",
    )
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    parser.add_argument(
        "--replay-fixture",
        type=Path,
        help="deterministic operator action context; required for REPLAY missions",
    )
    parser.add_argument(
        "--expires-in-minutes",
        type=int,
        default=None,
        help=(
            "required for LIVE APPROVE_HANDOFF; REPLAY uses the fixture value"
        ),
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="hard operator worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def build_navigator_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster run-navigator",
        description="Stage, intake, and plan an operator-approved SHADOW handoff.",
    )
    parser.add_argument("--mission-id", required=True, help="approved mission ID")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    parser.add_argument(
        "--replay-fixture",
        type=Path,
        help="deterministic Navigator context; required for REPLAY missions",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="hard Navigator worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def _print_summary(result: MissionInitialization) -> None:
    print(f"mission_id={result.snapshot.mission_id}")
    print(f"run_mode={result.snapshot.run_mode.value}")
    print(f"current_phase={result.snapshot.current_phase.value}")
    print(f"mission_outcome={result.snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")


def _print_oracle_summary(result: OracleWorkflowResult) -> None:
    snapshot = result.snapshot
    oracle = snapshot.stages["oracle"]
    provenance = snapshot.components["battlestar"]
    print(f"mission_id={snapshot.mission_id}")
    print(f"run_mode={snapshot.run_mode.value}")
    print(f"oracle_status={oracle.status.value}")
    print(
        "oracle_native_state="
        + (oracle.native_state if oracle.native_state is not None else "null")
    )
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(f"oracle_artifact_directory={result.oracle_artifact_directory.resolve()}")
    print(f"oracle_action={result.action.value}")
    print(f"battlestar_revision={provenance.git_revision}")
    print(
        "battlestar_branch="
        + (provenance.git_branch if provenance.git_branch is not None else "DETACHED")
    )
    print(f"battlestar_dirty={str(provenance.dirty_worktree).lower()}")


def _print_council_summary(result: CouncilWorkflowResult) -> None:
    snapshot = result.snapshot
    council = snapshot.stages["council"]
    provenance = snapshot.components["battlestar_council"]
    print(f"mission_id={snapshot.mission_id}")
    print(f"run_mode={snapshot.run_mode.value}")
    print(f"council_status={council.status.value}")
    print(
        "council_native_state="
        + (council.native_state if council.native_state is not None else "null")
    )
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(f"council_artifact_directory={result.council_artifact_directory.resolve()}")
    print(f"council_action={result.action.value}")
    print(f"battlestar_revision={provenance.git_revision}")
    print(
        "battlestar_branch="
        + (provenance.git_branch if provenance.git_branch is not None else "DETACHED")
    )
    print(f"battlestar_dirty={str(provenance.dirty_worktree).lower()}")


def _print_governor_summary(result: GovernorWorkflowResult) -> None:
    snapshot = result.snapshot
    governor = snapshot.stages["governor"]
    provenance = snapshot.components["battlestar_governor"]
    print(f"mission_id={snapshot.mission_id}")
    print(f"run_mode={snapshot.run_mode.value}")
    print(f"governor_status={governor.status.value}")
    print(
        "governor_disposition="
        + (governor.native_state if governor.native_state is not None else "null")
    )
    print(
        "governor_readiness_state="
        + (result.readiness_state if result.readiness_state is not None else "null")
    )
    print(
        "allowed_next_step="
        + (
            result.allowed_next_step
            if result.allowed_next_step is not None
            else "null"
        )
    )
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(f"governor_artifact_directory={result.governor_artifact_directory.resolve()}")
    print(f"governor_action={result.action.value}")
    print(f"battlestar_revision={provenance.git_revision}")
    print(
        "battlestar_branch="
        + (provenance.git_branch if provenance.git_branch is not None else "DETACHED")
    )
    print(f"battlestar_dirty={str(provenance.dirty_worktree).lower()}")


def _print_operator_summary(result: OperatorWorkflowResult) -> None:
    snapshot = result.snapshot
    print(f"mission_id={snapshot.mission_id}")
    print(f"action={_display_value(result.action)}")
    print(f"result={_display_value(result.result)}")
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(f"operator_action_status={_display_value(result.technical_status)}")
    print(f"operator_action_id={result.action_id or 'null'}")
    print(f"operator_action_disposition={_display_value(result.disposition)}")


def _display_value(value: object) -> str:
    if value is None:
        return "null"
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _print_navigator_summary(result: NavigatorWorkflowResult) -> None:
    snapshot = result.snapshot
    navigator_stage = snapshot.stages["navigator"]
    print(f"mission_id={snapshot.mission_id}")
    print(f"navigator_status={navigator_stage.status.value}")
    print(f"handoff_status={_display_value(result.handoff_status)}")
    print(f"intake_status={_display_value(result.intake_status)}")
    print(f"plan_status={_display_value(result.plan_status)}")
    print(f"mode={_display_value(result.mode)}")
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(f"navigator_artifact_directory={result.navigator_artifact_directory.resolve()}")
    print(f"navigator_action={_display_value(result.action)}")


def _run_oracle_command(argv: Sequence[str]) -> int:
    args = build_oracle_parser().parse_args(argv)
    settings = OracleRunSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        replay_fixture=args.replay_fixture,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )
    try:
        result = run_oracle(settings)
    except (
        BattlestarConfigurationError,
        ContractValidationError,
        IdentifierError,
        OracleInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid Oracle invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except OracleStateConflictError as exc:
        print(f"harbormaster: Oracle state conflict: {exc}", file=sys.stderr)
        return EXIT_ORACLE_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except OracleWorkflowError as exc:
        print(f"harbormaster: Oracle workflow failure: {exc}", file=sys.stderr)
        return EXIT_ORACLE_FAILURE

    _print_oracle_summary(result)
    oracle = result.snapshot.stages["oracle"]
    if oracle.status.value != "SUCCEEDED":
        if oracle.error is not None:
            print(
                f"harbormaster: Oracle technical failure: "
                f"{oracle.error.code}: {oracle.error.message}",
                file=sys.stderr,
            )
        return EXIT_ORACLE_FAILURE
    return EXIT_SUCCESS


def _run_council_command(argv: Sequence[str]) -> int:
    args = build_council_parser().parse_args(argv)
    settings = CouncilRunSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        replay_fixture=args.replay_fixture,
        policy_input=args.policy_input,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )
    try:
        result = run_council(settings)
    except (
        BattlestarConfigurationError,
        ContractValidationError,
        IdentifierError,
        CouncilInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid Council invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except CouncilStateConflictError as exc:
        print(f"harbormaster: Council state conflict: {exc}", file=sys.stderr)
        return EXIT_COUNCIL_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except CouncilWorkflowError as exc:
        print(f"harbormaster: Council workflow failure: {exc}", file=sys.stderr)
        return EXIT_COUNCIL_FAILURE

    _print_council_summary(result)
    council = result.snapshot.stages["council"]
    if council.status.value != "SUCCEEDED":
        if council.error is not None:
            print(
                f"harbormaster: Council technical failure: "
                f"{council.error.code}: {council.error.message}",
                file=sys.stderr,
            )
        return EXIT_COUNCIL_FAILURE
    return EXIT_SUCCESS


def _run_governor_command(argv: Sequence[str]) -> int:
    args = build_governor_parser().parse_args(argv)
    settings = GovernorRunSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        replay_fixture=args.replay_fixture,
        context_input=args.context_input,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )
    try:
        result = run_governor(settings)
    except (
        BattlestarConfigurationError,
        ContractValidationError,
        IdentifierError,
        GovernorInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid Governor invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except GovernorStateConflictError as exc:
        print(f"harbormaster: Governor state conflict: {exc}", file=sys.stderr)
        return EXIT_GOVERNOR_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except GovernorWorkflowError as exc:
        print(f"harbormaster: Governor workflow failure: {exc}", file=sys.stderr)
        return EXIT_GOVERNOR_FAILURE

    _print_governor_summary(result)
    governor = result.snapshot.stages["governor"]
    if governor.status.value != "SUCCEEDED":
        if governor.error is not None:
            print(
                f"harbormaster: Governor technical failure: "
                f"{governor.error.code}: {governor.error.message}",
                file=sys.stderr,
            )
        return EXIT_GOVERNOR_FAILURE
    return EXIT_SUCCESS


def _run_operator_command(argv: Sequence[str]) -> int:
    args = build_operator_parser().parse_args(argv)
    settings = OperatorRunSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        action=args.action,
        operator_id=args.operator_id,
        reason=args.reason,
        replay_fixture=args.replay_fixture,
        expires_in_minutes=args.expires_in_minutes,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )
    try:
        result = run_operator_action(settings)
    except (
        BattlestarConfigurationError,
        ContractValidationError,
        IdentifierError,
        OperatorInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid operator invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except (OperatorPreconditionError, OperatorStateConflictError) as exc:
        print(f"harbormaster: operator state conflict: {exc}", file=sys.stderr)
        return EXIT_OPERATOR_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except OperatorWorkflowError as exc:
        print(f"harbormaster: operator workflow failure: {exc}", file=sys.stderr)
        return EXIT_OPERATOR_FAILURE

    _print_operator_summary(result)
    if result.technical_status.value != "SUCCEEDED":
        return EXIT_OPERATOR_FAILURE
    return EXIT_SUCCESS


def _run_navigator_command(argv: Sequence[str]) -> int:
    args = build_navigator_parser().parse_args(argv)
    settings = NavigatorRunSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        replay_fixture=args.replay_fixture,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )
    try:
        result = run_navigator(settings)
    except (
        BattlestarConfigurationError,
        ContractValidationError,
        IdentifierError,
        NavigatorInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid Navigator invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except (NavigatorPreconditionError, NavigatorStateConflictError) as exc:
        print(f"harbormaster: Navigator state conflict: {exc}", file=sys.stderr)
        return EXIT_NAVIGATOR_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except NavigatorWorkflowError as exc:
        print(f"harbormaster: Navigator workflow failure: {exc}", file=sys.stderr)
        return EXIT_NAVIGATOR_FAILURE

    _print_navigator_summary(result)
    navigator = result.snapshot.stages["navigator"]
    if navigator.status.value != "SUCCEEDED":
        if navigator.error is not None:
            print(
                f"harbormaster: Navigator technical failure: "
                f"{navigator.error.code}: {navigator.error.message}",
                file=sys.stderr,
            )
        return EXIT_NAVIGATOR_FAILURE
    return EXIT_SUCCESS


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "run-oracle":
        return _run_oracle_command(arguments[1:])
    if arguments and arguments[0] == "run-council":
        return _run_council_command(arguments[1:])
    if arguments and arguments[0] == "run-governor":
        return _run_governor_command(arguments[1:])
    if arguments and arguments[0] == "operator-action":
        return _run_operator_command(arguments[1:])
    if arguments and arguments[0] == "run-navigator":
        return _run_navigator_command(arguments[1:])

    args = build_parser().parse_args(arguments)
    settings = HarbormasterSettings(
        request_path=args.request,
        artifacts_root=args.artifacts_root,
    )
    try:
        result = initialize_mission(settings)
    except (ContractValidationError, IdentifierError, UnsafePathError) as exc:
        print(f"harbormaster: invalid request: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except DuplicateMissionError as exc:
        print(f"harbormaster: duplicate mission: {exc}", file=sys.stderr)
        return EXIT_DUPLICATE_MISSION
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE

    _print_summary(result)
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
