"""Harbormaster CLI for mission initialization and the Phase 2 Oracle stage."""

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
from .identifiers import IdentifierError, allocate_mission_id
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


EXIT_SUCCESS = 0
EXIT_INVALID_REQUEST = 2
EXIT_DUPLICATE_MISSION = 3
EXIT_PERSISTENCE_FAILURE = 4
EXIT_ORACLE_FAILURE = 5


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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "run-oracle":
        return _run_oracle_command(arguments[1:])

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
