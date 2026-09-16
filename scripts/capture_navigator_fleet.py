#!/usr/bin/env python3
"""Capture observed fleet symbols as immutable Navigator reference datasets."""
from __future__ import annotations

import argparse
from pathlib import Path

from blackpod_build_week.cabin_context import CabinContextError
from blackpod_build_week.cabin_reader import CabinReaderError
from blackpod_build_week.contracts import ContractValidationError
from blackpod_build_week.mission_store import MissionStoreError
from blackpod_build_week.navigator_catalog import ALL_NAVIGATOR_PAIRS
from blackpod_build_week.navigator_fleet_catalog import capture_navigator_fleet_from_http


def _pair(value: str) -> tuple[str, int]:
    try:
        timeframe, period = value.split(":")
        return timeframe, int(period)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("pair must be TIMEFRAME:MA, for example 1d:250") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--navigator-base-url", required=True)
    parser.add_argument("--navigator-repository", type=Path, required=True)
    parser.add_argument("--all-observed", action="store_true", required=True,
                        help="Explicitly capture all symbols in the canonical normalized fleet, excluding an existing default chart symbol.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pair", type=_pair, action="append", help="Repeatable pair; default 1d:250.")
    group.add_argument("--all-pairs", action="store_true", help="Capture every supported interval/MA pair per observed symbol.")
    parser.add_argument("--source-identity", default="navigator-local-api")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--pace-seconds", type=float, default=1.1)
    args = parser.parse_args(argv)
    try:
        result = capture_navigator_fleet_from_http(
            artifacts_root=args.artifacts_root, mission_id=args.mission_id,
            navigator_base_url=args.navigator_base_url, navigator_repository=args.navigator_repository,
            pairs=ALL_NAVIGATOR_PAIRS if args.all_pairs else args.pair or (("1d", 250),),
            source_identity=args.source_identity, timeout_seconds=args.timeout_seconds,
            pace_seconds=args.pace_seconds, progress=lambda message: print(message, flush=True),
        )
    except (CabinContextError, CabinReaderError, ContractValidationError, MissionStoreError, OSError) as exc:
        print(f"Navigator fleet capture failed: {exc}", flush=True)
        return 2
    print(f"Mission: {result.catalog.mission_id}")
    print(f"Captured symbols: {len({entry.symbol for entry in result.catalog.entries})}")
    print(f"Captured datasets: {len(result.catalog.entries)}")
    print(f"Catalog: {result.catalog_path}")
    print(f"Result: {'CAPTURED' if result.written else 'NO_OP_ALREADY_SATISFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
