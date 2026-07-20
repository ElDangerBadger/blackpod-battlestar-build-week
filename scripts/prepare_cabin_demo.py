#!/usr/bin/env python3
"""Validate and materialize one canonical mission for the Captain's Cabin."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from blackpod_build_week.contracts.demo import DemoManifest
from blackpod_build_week.contracts.mission_snapshot import MissionSnapshot
from blackpod_build_week.contracts.presentation import CaptainsLog, MissionSummary


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    REPOSITORY_ROOT
    / "artifacts"
    / "demo-readiness"
    / "judge"
    / "approved"
    / "missions"
    / "mission-buildweek-replay-001"
)
DEFAULT_DESTINATION = REPOSITORY_ROOT / "ui" / "public" / "demo" / "approved"
PUBLIC_DEMO_ROOT = REPOSITORY_ROOT / "ui" / "public" / "demo"


class PreparationError(RuntimeError):
    """Raised when the selected mission cannot be safely materialized."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreparationError(f"cannot read canonical JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise PreparationError(f"canonical JSON artifact must contain an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_reference(source: Path, path: str, digest: str, size: int) -> None:
    target = (source / path).resolve()
    try:
        target.relative_to(source)
    except ValueError as exc:
        raise PreparationError(f"artifact reference escapes mission root: {path}") from exc
    if not target.is_file() or target.is_symlink():
        raise PreparationError(f"referenced mission artifact is not a regular file: {path}")
    if target.stat().st_size != size or _sha256(target) != digest:
        raise PreparationError(f"referenced mission artifact failed integrity validation: {path}")


def _validate_source(source: Path) -> tuple[str, str]:
    presentation = source / "presentation"
    summary = MissionSummary.from_mapping(
        _load_json(presentation / "mission_summary.json")
    )
    log = CaptainsLog.from_mapping(_load_json(presentation / "captains_log.json"))
    manifest = DemoManifest.from_mapping(
        _load_json(presentation / "demo_manifest.json")
    )
    snapshot = MissionSnapshot.from_mapping(_load_json(source / "mission_snapshot.json"))

    identities = {
        (summary.mission_id, summary.symbol, summary.run_mode.value),
        (log.mission_id, log.symbol, log.run_mode.value),
        (manifest.mission_id, manifest.symbol, manifest.run_mode.value),
        (snapshot.mission_id, summary.symbol, snapshot.run_mode.value),
    }
    if len(identities) != 1:
        raise PreparationError("canonical presentation artifacts disagree on mission identity")
    if (
        summary.request_id != log.request_id
        or summary.request_id != snapshot.request_id
        or summary.final_outcome is not manifest.final_outcome
        or summary.final_outcome is not snapshot.mission_outcome
        or summary.snapshot_count != manifest.snapshot_count
        or summary.snapshot_count != snapshot.revision
    ):
        raise PreparationError("canonical presentation artifacts contain inconsistent state")

    for reference in (
        manifest.captains_log,
        manifest.mission_summary,
        manifest.final_snapshot,
    ):
        if reference.byte_size is None:
            raise PreparationError(f"manifest reference has no byte size: {reference.path}")
        _validate_reference(
            source,
            reference.path,
            reference.sha256,
            reference.byte_size,
        )

    return summary.mission_id, summary.final_outcome.value


def _copy_if_changed(source: Path, destination: Path) -> bool:
    content = source.read_bytes()
    if destination.is_file() and not destination.is_symlink():
        if destination.read_bytes() == content:
            return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, destination)
    return True


def prepare(source_value: Path, destination_value: Path) -> tuple[str, str, int, int]:
    source = source_value.expanduser().resolve()
    destination = destination_value.expanduser().resolve()
    public_demo_root = PUBLIC_DEMO_ROOT.resolve()

    if not source.is_dir() or source.is_symlink():
        raise PreparationError(f"mission source is not a directory: {source}")
    try:
        destination.relative_to(public_demo_root)
    except ValueError as exc:
        raise PreparationError(
            f"destination must remain beneath {public_demo_root}"
        ) from exc
    if destination == public_demo_root:
        raise PreparationError("destination must select one named demo beneath public/demo")

    mission_id, outcome = _validate_source(source)
    copied = 0
    unchanged = 0
    for source_path in sorted(source.rglob("*")):
        if source_path.is_symlink():
            raise PreparationError(f"mission source contains a symbolic link: {source_path}")
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source)
        destination_path = destination / relative
        if _copy_if_changed(source_path, destination_path):
            copied += 1
        else:
            unchanged += 1
    return mission_id, outcome, copied, unchanged


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and prepare a read-only Captain's Cabin demo mission."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        mission_id, outcome, copied, unchanged = prepare(args.source, args.destination)
    except Exception as exc:  # normal command mode emits a concise, sanitized failure
        print(f"Captain's Cabin preparation failed: {exc}")
        return 2
    print(f"Mission: {mission_id}")
    print(f"Outcome: {outcome}")
    print(f"Prepared files: {copied}")
    print(f"Unchanged files: {unchanged}")
    print(f"Cabin data: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
