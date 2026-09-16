#!/usr/bin/env python3
"""Explicitly capture alternate canonical Navigator datasets for one LIVE Cabin."""

from __future__ import annotations

import argparse
from pathlib import Path

from blackpod_build_week.cabin_context import CabinContextError
from blackpod_build_week.cabin_reader import CabinReaderError
from blackpod_build_week.contracts import ContractValidationError
from blackpod_build_week.mission_store import MissionStoreError
from blackpod_build_week.navigator_catalog import capture_navigator_catalog_from_http


def _pair(value: str) -> tuple[str, int]:
    try:
        timeframe, period = value.split(":")
        return timeframe, int(period)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("pair must be TIMEFRAME:MA, for example 1h:20") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--navigator-base-url", required=True)
    parser.add_argument("--navigator-repository", type=Path, required=True)
    parser.add_argument("--source-identity", default="navigator-local-api")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--pair", type=_pair, action="append",
                        help="Optional repeatable pair; default captures all 14 non-default pairs.")
    args = parser.parse_args(argv)
    try:
        result = capture_navigator_catalog_from_http(
            artifacts_root=args.artifacts_root, mission_id=args.mission_id,
            navigator_base_url=args.navigator_base_url, navigator_repository=args.navigator_repository,
            pairs=args.pair, source_identity=args.source_identity, timeout_seconds=args.timeout_seconds,
        )
    except (CabinContextError, CabinReaderError, ContractValidationError, MissionStoreError, OSError) as exc:
        print(f"Navigator catalog capture failed: {exc}")
        return 2
    print(f"Mission: {result.catalog.mission_id}")
    print(f"Variants: {len(result.catalog.entries)}")
    print(f"Catalog: {result.catalog_path}")
    print(f"Result: {'CAPTURED' if result.written else 'NO_OP_ALREADY_SATISFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
