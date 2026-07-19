"""Harbormaster stage commands and canonical unified mission CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .battlestar_config import BattlestarConfigurationError
from .contracts import ContractValidationError, StageStatus
from .council_workflow import (
    CouncilInvocationError,
    CouncilRunSettings,
    CouncilStateConflictError,
    CouncilWorkflowError,
    CouncilWorkflowResult,
    run_council,
)
from .identifiers import IdentifierError
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
    MissionStoreError,
    PersistenceError,
    UnsafePathError,
)
from .mission_initialization import HarbormasterSettings, initialize_mission
from .mission_presentation import MissionPresentationError, MissionPresentationResult
from .modeldock_config import (
    ModelDockConfigurationError,
    load_modeldock_config,
)
from .modeldock_preflight import run_modeldock_preflight
from .oracle_workflow import (
    OracleInvocationError,
    OracleRunSettings,
    OracleStateConflictError,
    OracleWorkflowError,
    OracleWorkflowResult,
    run_oracle,
)
from .oracle_enrichment_workflow import (
    OracleEnrichmentInvocationError,
    OracleEnrichmentPreconditionError,
    OracleEnrichmentSettings,
    OracleEnrichmentStateConflictError,
    OracleEnrichmentWorkflowError,
    OracleEnrichmentWorkflowResult,
    run_oracle_enrichment,
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
from .unified_mission_workflow import (
    MissionThrough,
    UnifiedMissionInvocationError,
    UnifiedMissionResult,
    UnifiedMissionSettings,
    UnifiedMissionStateConflictError,
    UnifiedMissionWorkflowError,
    resume_unified_mission,
    run_unified_mission,
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
EXIT_MODELDOCK_FAILURE = 10
EXIT_UNIFIED_MISSION_FAILURE = 11


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


def build_oracle_enrichment_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster enrich-oracle",
        description=(
            "Enrich a completed Oracle stage with one strict local ModelDock narrative."
        ),
    )
    parser.add_argument("--mission-id", required=True, help="completed Oracle mission ID")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    parser.add_argument(
        "--replay-fixture",
        type=Path,
        help="deterministic ModelDock replay pack; required for REPLAY missions",
    )
    return parser


def build_modeldock_preflight_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m blackpod_build_week.harbormaster modeldock-preflight",
        description="Check ModelDock health and one real, non-mocked MLX inference.",
    )


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


def _build_unified_parser(*, resume: bool) -> argparse.ArgumentParser:
    command = "mission-resume" if resume else "mission-run"
    parser = argparse.ArgumentParser(
        prog=f"python -m blackpod_build_week.harbormaster {command}",
        description=(
            "Resume one validated mission from its canonical state."
            if resume
            else "Initialize and orchestrate one canonical BlackPod mission."
        ),
    )
    if resume:
        parser.add_argument("--mission-id", required=True, help="existing mission ID")
    else:
        parser.add_argument("--request", required=True, type=Path, help="mission request JSON")
    parser.add_argument(
        "--artifacts-root",
        type=Path,
        default=Path("artifacts"),
        help="artifact root containing missions/ (default: artifacts)",
    )
    modeldock = parser.add_mutually_exclusive_group(required=True)
    modeldock.add_argument(
        "--with-modeldock",
        dest="with_modeldock",
        action="store_true",
        help="require strict Oracle narrative enrichment",
    )
    modeldock.add_argument(
        "--without-modeldock",
        dest="with_modeldock",
        action="store_false",
        help="explicitly omit Oracle narrative enrichment",
    )
    parser.add_argument(
        "--through",
        choices=tuple(item.value for item in MissionThrough),
        default=MissionThrough.NAVIGATOR.value,
        help="inclusive final eligible stage (default: NAVIGATOR)",
    )
    parser.add_argument(
        "--operator-action",
        choices=("APPROVE_HANDOFF", "REJECT"),
        help="explicit action required when continuing through Operator or Navigator",
    )
    parser.add_argument("--operator-id", help="operator audit identity")
    parser.add_argument("--operator-reason", help="operator approval or rejection rationale")
    parser.add_argument(
        "--expires-in-minutes",
        type=int,
        default=None,
        help="required for LIVE APPROVE_HANDOFF",
    )
    parser.add_argument(
        "--oracle-replay-fixture",
        type=Path,
        help="deterministic Oracle input for REPLAY",
    )
    parser.add_argument(
        "--modeldock-replay-fixture",
        type=Path,
        help="deterministic ModelDock replay pack for REPLAY",
    )
    council = parser.add_mutually_exclusive_group()
    council.add_argument(
        "--council-replay-fixture",
        type=Path,
        help="deterministic Council supporting input for REPLAY",
    )
    council.add_argument(
        "--council-policy-input",
        type=Path,
        help="explicit Council supporting input for LIVE",
    )
    governor = parser.add_mutually_exclusive_group()
    governor.add_argument(
        "--governor-replay-fixture",
        type=Path,
        help="deterministic Governor context for REPLAY",
    )
    governor.add_argument(
        "--governor-context-input",
        type=Path,
        help="explicit Governor context for LIVE",
    )
    parser.add_argument(
        "--operator-replay-fixture",
        type=Path,
        help="deterministic operator action input for REPLAY",
    )
    parser.add_argument(
        "--navigator-replay-fixture",
        type=Path,
        help="deterministic Navigator SHADOW input for REPLAY",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60.0,
        help="existing per-stage worker deadline in seconds (default: 60)",
    )
    parser.add_argument(
        "--strict-battlestar-clean",
        action="store_true",
        help="reject a dirty Battlestar worktree during preflight",
    )
    return parser


def build_mission_run_parser() -> argparse.ArgumentParser:
    return _build_unified_parser(resume=False)


def build_mission_resume_parser() -> argparse.ArgumentParser:
    return _build_unified_parser(resume=True)


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


def _print_oracle_enrichment_summary(
    result: OracleEnrichmentWorkflowResult,
) -> None:
    snapshot = result.snapshot
    oracle = snapshot.stages["oracle"]
    call = result.call
    print(f"mission_id={snapshot.mission_id}")
    print(f"oracle_status={oracle.status.value}")
    print(
        "modeldock_call_status="
        + (call.status.value if call is not None else "null")
    )
    print(f"provider={call.provider if call and call.provider else 'null'}")
    print(f"model={call.model if call and call.model else 'null'}")
    print(f"trace_id={call.trace_id if call and call.trace_id else 'null'}")
    print(f"latency_ms={call.latency_ms if call and call.latency_ms is not None else 'null'}")
    print(
        "narrative_artifact_path="
        + (result.narrative_artifact_path or "null")
    )
    print(f"current_phase={snapshot.current_phase.value}")
    print(f"mission_outcome={snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")
    print(
        "modeldock_artifact_directory="
        f"{result.modeldock_artifact_directory.resolve()}"
    )
    print(f"modeldock_action={result.action.value}")


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


def _run_oracle_enrichment_command(argv: Sequence[str]) -> int:
    args = build_oracle_enrichment_parser().parse_args(argv)
    settings = OracleEnrichmentSettings(
        mission_id=args.mission_id,
        artifacts_root=args.artifacts_root,
        replay_fixture=args.replay_fixture,
    )
    try:
        result = run_oracle_enrichment(settings)
    except (
        ModelDockConfigurationError,
        ContractValidationError,
        IdentifierError,
        OracleEnrichmentInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid ModelDock invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except (
        OracleEnrichmentPreconditionError,
        OracleEnrichmentStateConflictError,
    ) as exc:
        print(f"harbormaster: ModelDock state conflict: {exc}", file=sys.stderr)
        return EXIT_MODELDOCK_FAILURE
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: persistence failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except OracleEnrichmentWorkflowError as exc:
        print(f"harbormaster: ModelDock workflow failure: {exc}", file=sys.stderr)
        return EXIT_MODELDOCK_FAILURE

    _print_oracle_enrichment_summary(result)
    call = result.call
    if (
        result.snapshot.stages["oracle"].status is not StageStatus.SUCCEEDED
        or call is None
        or call.status.value != "SUCCEEDED"
    ):
        if call is not None and call.error is not None:
            print(
                "harbormaster: ModelDock technical failure: "
                f"{call.error.code}: {call.error.message}",
                file=sys.stderr,
            )
        return EXIT_MODELDOCK_FAILURE
    return EXIT_SUCCESS


def _run_modeldock_preflight_command(argv: Sequence[str]) -> int:
    build_modeldock_preflight_parser().parse_args(argv)
    try:
        config = load_modeldock_config()
        report = run_modeldock_preflight(config)
    except ModelDockConfigurationError as exc:
        print(f"harbormaster: invalid ModelDock configuration: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    print(f"base_url={report.base_url}")
    print(f"service_reachable={str(report.service_reachable).lower()}")
    print(f"health_ready={str(report.health_ready).lower()}")
    print(
        "health_response="
        + (
            json.dumps(report.health_response, sort_keys=True, separators=(",", ":"))
            if report.health_response is not None
            else "null"
        )
    )
    print(
        f"models_endpoint_ready={str(report.models_endpoint_ready).lower()}"
    )
    print(
        "selected_model_available="
        + (
            str(report.selected_model_available).lower()
            if report.selected_model_available is not None
            else "null"
        )
    )
    print(f"text_generate_available={str(report.text_generate_endpoint_available).lower()}")
    print(f"provider={report.provider or 'null'}")
    print(f"model={report.model or 'null'}")
    print(f"model_revision={report.model_revision or 'null'}")
    print(f"trace_id={report.trace_id or 'null'}")
    print(f"mocked={str(report.mocked).lower() if report.mocked is not None else 'null'}")
    print(f"latency_ms={report.latency_ms if report.latency_ms is not None else 'null'}")
    print(f"timeout_seconds={report.timeout_seconds}")
    print(f"inference_ready={str(report.inference_ready).lower()}")
    print(f"ready={str(report.ready).lower()}")
    for issue in report.issues:
        print(
            f"modeldock_preflight_issue={issue['code']}:{issue['message']}",
            file=sys.stderr,
        )
    return EXIT_SUCCESS if report.ready else EXIT_MODELDOCK_FAILURE


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


def _unified_settings_from_args(
    args: argparse.Namespace,
    *,
    resume: bool,
) -> UnifiedMissionSettings:
    return UnifiedMissionSettings(
        request_path=None if resume else args.request,
        mission_id=args.mission_id if resume else None,
        artifacts_root=args.artifacts_root,
        with_modeldock=args.with_modeldock,
        through=args.through,
        operator_action=args.operator_action,
        operator_id=args.operator_id,
        operator_reason=args.operator_reason,
        expires_in_minutes=args.expires_in_minutes,
        oracle_replay_fixture=args.oracle_replay_fixture,
        modeldock_replay_fixture=args.modeldock_replay_fixture,
        council_replay_fixture=args.council_replay_fixture,
        council_policy_input=args.council_policy_input,
        governor_replay_fixture=args.governor_replay_fixture,
        governor_context_input=args.governor_context_input,
        operator_replay_fixture=args.operator_replay_fixture,
        navigator_replay_fixture=args.navigator_replay_fixture,
        deadline_seconds=args.deadline_seconds,
        strict_battlestar_clean=args.strict_battlestar_clean,
    )


def _unified_stage_value(result: UnifiedMissionResult, stage_name: str) -> str:
    stage = result.snapshot.stages[stage_name]
    if stage_name == "governor" and stage.status is StageStatus.SUCCEEDED:
        return stage.native_state or stage.status.value
    if stage_name == "navigator" and stage.status is StageStatus.SUCCEEDED:
        navigator = result.snapshot.navigator
        if (
            _display_value(navigator.mode) == "SHADOW"
            and _display_value(navigator.plan_status) == "CREATED"
        ):
            return "SHADOW PLAN CREATED"
    return stage.status.value


def _print_unified_summary(result: UnifiedMissionResult) -> None:
    snapshot = result.snapshot
    modeldock_calls = snapshot.stages["oracle"].modeldock_calls
    modeldock = (
        modeldock_calls[-1].status.value if modeldock_calls else "NOT_RECORDED"
    )
    operator = snapshot.operator
    operator_value = _display_value(operator.result)
    if operator_value == "null":
        operator_value = _display_value(operator.route)
    if operator_value == "null":
        operator_value = operator.action_status.value
    presentation = result.presentation
    captain_path = "null"
    summary_path = "null"
    if isinstance(presentation, MissionPresentationResult):
        captain_path = str(presentation.captains_log_markdown_path.resolve())
        summary_path = str(presentation.mission_summary_path.resolve())

    print(f"Mission: {snapshot.mission_id}")
    print(f"Symbol: {result.request.symbol}")
    print(f"Mode: {snapshot.run_mode.value}")
    print()
    print(f"{'Harbormaster':<15}{snapshot.stages['harbormaster'].status.value}")
    print(f"{'Oracle':<15}{snapshot.stages['oracle'].status.value}")
    print(f"{'ModelDock':<15}{modeldock}")
    print(f"{'Council':<15}{snapshot.stages['council'].status.value}")
    print(f"{'Governor':<15}{_unified_stage_value(result, 'governor')}")
    print(f"{'Operator':<15}{operator_value}")
    print(f"{'Navigator':<15}{_unified_stage_value(result, 'navigator')}")
    print()
    print(f"Outcome: {snapshot.mission_outcome.value}")
    print(f"Current phase: {snapshot.current_phase.value}")
    print(f"Snapshots: {snapshot.revision}")
    print(f"Unified action: {result.action.value}")
    print(
        "Executed stages: "
        + (", ".join(result.executed_stages) if result.executed_stages else "none")
    )
    print(f"Current snapshot: {result.paths.current_snapshot.resolve()}")
    print(f"Captain's log: {captain_path}")
    print(f"Mission summary: {summary_path}")


def _run_unified_command(argv: Sequence[str], *, resume: bool) -> int:
    parser = build_mission_resume_parser() if resume else build_mission_run_parser()
    args = parser.parse_args(argv)
    settings = _unified_settings_from_args(args, resume=resume)
    try:
        result = (
            resume_unified_mission(settings)
            if resume
            else run_unified_mission(settings)
        )
    except (
        BattlestarConfigurationError,
        ModelDockConfigurationError,
        ContractValidationError,
        IdentifierError,
        DuplicateMissionError,
        OracleInvocationError,
        OracleEnrichmentInvocationError,
        CouncilInvocationError,
        GovernorInvocationError,
        OperatorInvocationError,
        NavigatorInvocationError,
        UnifiedMissionInvocationError,
        UnsafePathError,
    ) as exc:
        print(f"harbormaster: invalid unified mission invocation: {exc}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    except (PersistenceError, MissionStoreError, OSError) as exc:
        print(f"harbormaster: unified mission integrity failure: {exc}", file=sys.stderr)
        return EXIT_PERSISTENCE_FAILURE
    except (
        OracleWorkflowError,
        OracleEnrichmentWorkflowError,
        CouncilWorkflowError,
        GovernorWorkflowError,
        OperatorWorkflowError,
        NavigatorWorkflowError,
        UnifiedMissionStateConflictError,
        UnifiedMissionWorkflowError,
        MissionPresentationError,
    ) as exc:
        print(f"harbormaster: unified mission failure: {exc}", file=sys.stderr)
        return EXIT_UNIFIED_MISSION_FAILURE

    _print_unified_summary(result)
    if not result.technical_success:
        print(
            "harbormaster: unified mission ended in a technical failure",
            file=sys.stderr,
        )
        return EXIT_UNIFIED_MISSION_FAILURE
    return EXIT_SUCCESS


def _run_mission_command(argv: Sequence[str]) -> int:
    return _run_unified_command(argv, resume=False)


def _run_mission_resume_command(argv: Sequence[str]) -> int:
    return _run_unified_command(argv, resume=True)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "mission-run":
        return _run_mission_command(arguments[1:])
    if arguments and arguments[0] == "mission-resume":
        return _run_mission_resume_command(arguments[1:])
    if arguments and arguments[0] == "run-oracle":
        return _run_oracle_command(arguments[1:])
    if arguments and arguments[0] == "enrich-oracle":
        return _run_oracle_enrichment_command(arguments[1:])
    if arguments and arguments[0] == "modeldock-preflight":
        return _run_modeldock_preflight_command(arguments[1:])
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
