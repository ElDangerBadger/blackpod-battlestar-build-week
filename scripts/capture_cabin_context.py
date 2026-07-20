#!/usr/bin/env python3
"""Capture optional read-only market and portfolio context for one cabin mission."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from blackpod_build_week.cabin_context import (
    CabinContextError,
    CaptureTransport,
    capture_cabin_context,
    fetch_navigator_market,
    inspect_git_revision,
    validate_git_revision,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.mission_store import MissionStore, MissionStoreError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture strict read-only Navigator/portfolio inputs beside an existing "
            "mission without changing canonical mission contracts."
        )
    )
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    market = parser.add_mutually_exclusive_group()
    market.add_argument("--market-url")
    market.add_argument("--market-json", type=Path)
    revision = parser.add_mutually_exclusive_group()
    revision.add_argument("--navigator-revision")
    revision.add_argument("--navigator-repository", type=Path)
    parser.add_argument(
        "--market-source-identity",
        default="navigator-local-json",
        help="Opaque identity used for a local JSON capture; never a filesystem path.",
    )
    parser.add_argument("--portfolio-json", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--captured-at",
        help="RFC 3339 timestamp; defaults to the current UTC time.",
    )
    return parser


def _read_exact(path: Path, label: str) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise CabinContextError(f"{label} is not a regular file")
        return path.read_bytes()
    except OSError as exc:
        raise CabinContextError(f"could not read {label}") from exc


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    captured_at = args.captured_at or datetime.now(UTC).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    try:
        store = MissionStore(args.artifacts_root)
        loaded = store.load_mission(args.mission_id)
        market_bytes = None
        transport = None
        source_identity = None
        revision = None
        if args.market_url or args.market_json:
            if not args.navigator_revision and not args.navigator_repository:
                raise CabinContextError(
                    "market capture requires --navigator-revision or --navigator-repository"
                )
            revision = (
                validate_git_revision(args.navigator_revision)
                if args.navigator_revision
                else inspect_git_revision(args.navigator_repository)
            )
            if args.market_url:
                market_bytes = fetch_navigator_market(
                    args.market_url,
                    expected_symbol=loaded.request.symbol,
                    timeout_seconds=args.timeout_seconds,
                )
                transport = CaptureTransport.HTTP
                source_identity = "navigator-local-api"
            else:
                market_bytes = _read_exact(args.market_json, "market JSON")
                transport = CaptureTransport.LOCAL_JSON
                source_identity = args.market_source_identity
        portfolio_bytes = (
            None
            if args.portfolio_json is None
            else _read_exact(args.portfolio_json, "portfolio JSON")
        )
        result = capture_cabin_context(
            store,
            mission_id=args.mission_id,
            captured_at=captured_at,
            market_bytes=market_bytes,
            market_transport=transport,
            market_source_identity=source_identity,
            navigator_git_revision=revision,
            portfolio_bytes=portfolio_bytes,
        )
    except (CabinContextError, ContractValidationError, MissionStoreError) as exc:
        print(f"Captain's Cabin context capture failed: {exc}")
        return 2

    print(f"Mission: {result.context.mission_id}")
    print(f"Market: {result.context.capture_provenance.market_status.value}")
    print(f"Portfolio: {result.context.capture_provenance.portfolio_status.value}")
    print(f"Context: {result.context_path}")
    print(f"Result: {'CAPTURED' if result.written else 'NO_OP_ALREADY_SATISFIED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
