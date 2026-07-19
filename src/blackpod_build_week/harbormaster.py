"""Harbormaster CLI for Stage 1, Phase 1 mission initialization."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

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


EXIT_SUCCESS = 0
EXIT_INVALID_REQUEST = 2
EXIT_DUPLICATE_MISSION = 3
EXIT_PERSISTENCE_FAILURE = 4


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


def _print_summary(result: MissionInitialization) -> None:
    print(f"mission_id={result.snapshot.mission_id}")
    print(f"run_mode={result.snapshot.run_mode.value}")
    print(f"current_phase={result.snapshot.current_phase.value}")
    print(f"mission_outcome={result.snapshot.mission_outcome.value}")
    print(f"snapshot_path={result.paths.current_snapshot.resolve()}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

