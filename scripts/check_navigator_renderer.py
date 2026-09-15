#!/usr/bin/env python3
"""Check the reviewed Navigator renderer snapshot without modifying either repo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("ui/navigator-renderer-source.json")
TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$")


class RendererSourceError(ValueError):
    """The manifest or one of its inputs cannot be checked."""


def _relative_path(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise RendererSourceError(f"{field} must be a normalized relative path")
    return value


def _inside(root: Path, relative: str) -> Path:
    target = root
    for part in PurePosixPath(relative).parts:
        target = target / part
        if target.is_symlink():
            raise RendererSourceError(f"symbolic link is not allowed: {target}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise RendererSourceError(f"path escapes its root: {relative}")
    return target


def _read_file(path: Path) -> bytes:
    if not path.is_file():
        raise RendererSourceError(f"missing regular file: {path}")
    return path.read_bytes()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(_read_file(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RendererSourceError(f"invalid manifest JSON: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise RendererSourceError("manifest must use schema_version 1")
    revision = manifest.get("canonical_revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise RendererSourceError("canonical_revision must be a full Git commit ID")
    for field in ("source_root", "renderer_root"):
        _relative_path(manifest.get(field), field)
    files = manifest.get("files")
    consumers = manifest.get("consumer_files")
    if not isinstance(files, list) or not files:
        raise RendererSourceError("files must be a nonempty source mapping")
    if not isinstance(consumers, list):
        raise RendererSourceError("consumer_files must be an explicit list")
    sources: set[str] = set()
    destinations: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise RendererSourceError("each source mapping must be an object")
        for field, seen in (("source", sources), ("destination", destinations)):
            value = _relative_path(entry.get(field), field)
            if value in seen:
                raise RendererSourceError(f"duplicate {field}: {value}")
            seen.add(value)
        for field in ("source_sha256", "destination_sha256"):
            value = entry.get(field)
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise RendererSourceError(f"{field} must be a SHA-256 digest")
        if not isinstance(entry.get("adaptation"), str) or not entry["adaptation"].strip():
            raise RendererSourceError("each mapping must explain its adaptation")
    for consumer in consumers:
        _relative_path(consumer, "consumer_files entry")
        if consumer in destinations:
            raise RendererSourceError(f"duplicate destination or consumer: {consumer}")
        destinations.add(consumer)
    return manifest


def _pinned_source(repository: Path, revision: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "blob", f"{revision}:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RendererSourceError(f"cannot read pinned canonical source {revision}:{relative}")
    return result.stdout


def check_renderer(
    repository_root: Path,
    manifest_path: Path | None = None,
    battlestar_path: Path | None = None,
) -> list[str]:
    """Return drift findings; malformed manifests raise RendererSourceError."""
    repository_root = repository_root.resolve()
    manifest = _load_manifest(manifest_path or repository_root / DEFAULT_MANIFEST)
    renderer_root = _inside(repository_root, manifest["renderer_root"])
    errors: list[str] = []
    expected = {entry["destination"] for entry in manifest["files"]}
    expected.update(manifest["consumer_files"])

    for entry in manifest["files"]:
        try:
            content = _read_file(_inside(renderer_root, entry["destination"]))
            if _sha256(content) != entry["destination_sha256"]:
                errors.append(f"local renderer drift: {entry['destination']}")
        except (OSError, RendererSourceError) as exc:
            errors.append(str(exc))
    for consumer in manifest["consumer_files"]:
        try:
            _read_file(_inside(renderer_root, consumer))
        except (OSError, RendererSourceError) as exc:
            errors.append(str(exc))

    for path in sorted(renderer_root.rglob("*")):
        relative = path.relative_to(renderer_root).as_posix()
        if path.is_symlink():
            errors.append(f"symbolic link is not allowed in renderer: {relative}")
        elif path.is_file() and relative not in expected:
            if path.name != ".DS_Store" and not TEST_FILE.search(path.name):
                errors.append(f"unclassified renderer file: {relative}")

    if battlestar_path is not None:
        battlestar_path = battlestar_path.resolve()
        if not battlestar_path.is_dir():
            raise RendererSourceError(f"Battlestar checkout does not exist: {battlestar_path}")
        for entry in manifest["files"]:
            relative = f"{manifest['source_root']}/{entry['source']}"
            try:
                pinned = _pinned_source(battlestar_path, manifest["canonical_revision"], relative)
                if _sha256(pinned) != entry["source_sha256"]:
                    errors.append(f"manifest disagrees with pinned canonical source: {entry['source']}")
                current = _read_file(_inside(battlestar_path, relative))
                if _sha256(current) != entry["source_sha256"]:
                    errors.append(f"upstream source drift: {entry['source']}")
            except (OSError, RendererSourceError) as exc:
                errors.append(str(exc))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--battlestar-path", type=Path, help="also check pinned and current canonical sources")
    parser.add_argument("--upstream", action="store_true", help="check upstream using BATTLESTAR_PATH")
    args = parser.parse_args(argv)
    battlestar = args.battlestar_path
    if args.upstream and battlestar is None:
        configured = os.environ.get("BATTLESTAR_PATH", "").strip()
        if not configured:
            parser.error("--upstream requires BATTLESTAR_PATH or --battlestar-path")
        battlestar = Path(configured)
    try:
        errors = check_renderer(args.repository_root, args.manifest, battlestar)
    except (OSError, RendererSourceError) as exc:
        errors = [str(exc)]
    if errors:
        for error in errors:
            print(f"Navigator source check: {error}", file=sys.stderr)
        print("Review docs/NAVIGATOR_V3_INTEGRATION.md before updating the snapshot or manifest.", file=sys.stderr)
        return 1
    scope = "local snapshot, pinned canonical sources, and current upstream files" if battlestar else "local snapshot (upstream not checked)"
    print(f"Navigator source check passed: {scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
