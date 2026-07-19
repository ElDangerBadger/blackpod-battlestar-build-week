"""Read-only configuration and preflight checks for the Battlestar Oracle.

Only paths needed by the narrow Oracle adapter are exposed.  Local absolute
paths are intentionally kept in this in-memory configuration object; callers
must not serialize them into canonical mission artifacts.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


BATTLESTAR_PATH_ENV = "BATTLESTAR_PATH"
ORACLE_ENTRY_POINT = "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
ORACLE_MODULE_RELATIVE_PATH = Path("blackpod/runtime/oracle_pipeline.py")
ORACLE_FLEET_RELATIVE_PATH = Path(
    "configs/universes/oracles_vapors.example.yaml"
)

_GIT_TIMEOUT_SECONDS = 10.0
_GIT_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{40,64}\Z")


class BattlestarConfigurationError(ValueError):
    """Raised when the configured Battlestar repository fails preflight."""


@dataclass(frozen=True, slots=True)
class BattlestarConfig:
    """Validated, process-local Battlestar configuration and provenance."""

    root: Path
    oracle_module_path: Path
    fleet_path: Path
    git_revision: str
    git_branch: str | None
    dirty_worktree: bool


def load_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
) -> BattlestarConfig:
    """Validate ``BATTLESTAR_PATH`` and collect read-only Git provenance.

    ``artifacts_root`` may be absent when this function is called.  It is
    resolved non-strictly so a Battlestar path equal to or below the eventual
    Build Week artifact root is still rejected.
    """

    environment = os.environ if environ is None else environ
    configured_value = environment.get(BATTLESTAR_PATH_ENV, "").strip()
    if not configured_value:
        raise BattlestarConfigurationError(
            f"{BATTLESTAR_PATH_ENV} is not configured"
        )

    configured_path = Path(configured_value)
    if not configured_path.exists():
        raise BattlestarConfigurationError(
            f"{BATTLESTAR_PATH_ENV} does not exist"
        )
    if not configured_path.is_dir():
        raise BattlestarConfigurationError(
            f"{BATTLESTAR_PATH_ENV} is not a directory"
        )

    try:
        root = configured_path.resolve(strict=True)
        resolved_artifacts_root = Path(artifacts_root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise BattlestarConfigurationError(
            "configured paths could not be resolved safely"
        ) from exc

    if (
        root == resolved_artifacts_root
        or root.is_relative_to(resolved_artifacts_root)
        or resolved_artifacts_root.is_relative_to(root)
    ):
        raise BattlestarConfigurationError(
            f"{BATTLESTAR_PATH_ENV} and the mission artifact root must not overlap"
        )

    oracle_module_path = _required_repository_file(
        root,
        ORACLE_MODULE_RELATIVE_PATH,
        description="Oracle module",
    )
    fleet_path = _required_repository_file(
        root,
        ORACLE_FLEET_RELATIVE_PATH,
        description="Oracle fleet configuration",
    )

    revision = _git_revision(root)
    branch = _git_branch(root)
    dirty_worktree = _git_dirty_worktree(root)
    if strict_clean and dirty_worktree:
        raise BattlestarConfigurationError(
            "Battlestar worktree is dirty; strict clean mode rejects it"
        )

    return BattlestarConfig(
        root=root,
        oracle_module_path=oracle_module_path,
        fleet_path=fleet_path,
        git_revision=revision,
        git_branch=branch,
        dirty_worktree=dirty_worktree,
    )


def _required_repository_file(
    root: Path,
    relative_path: Path,
    *,
    description: str,
) -> Path:
    candidate = root / relative_path
    if not candidate.is_file():
        raise BattlestarConfigurationError(f"{description} is missing")

    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BattlestarConfigurationError(
            f"{description} could not be resolved safely"
        ) from exc

    if not resolved.is_relative_to(root):
        raise BattlestarConfigurationError(
            f"{description} must resolve inside the Battlestar repository"
        )
    return resolved


def _git_revision(root: Path) -> str:
    completed = _run_git(root, ("rev-parse", "--verify", "HEAD"))
    if completed.returncode != 0:
        raise BattlestarConfigurationError("Battlestar Git revision is unavailable")

    revision = completed.stdout.strip()
    if _GIT_REVISION_PATTERN.fullmatch(revision) is None:
        raise BattlestarConfigurationError("Battlestar Git revision is malformed")
    return revision.lower()


def _git_branch(root: Path) -> str | None:
    completed = _run_git(root, ("symbolic-ref", "--quiet", "--short", "HEAD"))
    if completed.returncode == 0:
        branch = completed.stdout.strip()
        if not branch or "\n" in branch or "\r" in branch:
            raise BattlestarConfigurationError("Battlestar Git branch is malformed")
        return branch
    if completed.returncode == 1 and not completed.stdout.strip():
        return None
    raise BattlestarConfigurationError("Battlestar Git branch could not be inspected")


def _git_dirty_worktree(root: Path) -> bool:
    completed = _run_git(
        root,
        ("status", "--porcelain=v1", "--untracked-files=normal"),
    )
    if completed.returncode != 0:
        raise BattlestarConfigurationError(
            "Battlestar Git worktree state could not be inspected"
        )
    return bool(completed.stdout)


def _run_git(root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    git_environment = os.environ.copy()
    git_environment["GIT_OPTIONAL_LOCKS"] = "0"
    git_environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ("git", "-C", str(root), *arguments),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=git_environment,
        )
    except FileNotFoundError as exc:
        raise BattlestarConfigurationError(
            "Git is required for Battlestar preflight"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BattlestarConfigurationError(
            "Battlestar Git inspection timed out"
        ) from exc
    except OSError as exc:
        raise BattlestarConfigurationError(
            "Battlestar Git inspection could not be started"
        ) from exc
