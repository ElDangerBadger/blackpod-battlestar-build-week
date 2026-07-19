"""Read-only configuration and preflight checks for Battlestar stages.

Only paths needed by the narrow Oracle, Council, Governor, operator, and
Navigator adapters are exposed. Local absolute paths are intentionally kept in this in-memory
configuration object; callers must not serialize them into canonical mission
artifacts.
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
CANDIDATE_ENTRY_POINT = (
    "blackpod.advisors.trading_candidate_generator.build_trading_candidate_report"
)
CANDIDATE_MODULE_RELATIVE_PATH = Path(
    "blackpod/advisors/trading_candidate_generator.py"
)
SENATE_REVIEW_ENTRY_POINT = (
    "blackpod.advisors.senate_candidate_intake.build_senate_review_packet"
)
SENATE_REVIEW_MODULE_RELATIVE_PATH = Path(
    "blackpod/advisors/senate_candidate_intake.py"
)
SENATE_DELIBERATION_ENTRY_POINT = (
    "blackpod.advisors.senate_deliberation.build_senate_deliberation"
)
SENATE_DELIBERATION_MODULE_RELATIVE_PATH = Path(
    "blackpod/advisors/senate_deliberation.py"
)
MANDATE_ENTRY_POINT = "blackpod.advisors.mandate.MandateAdvisor.run"
MANDATE_MODULE_RELATIVE_PATH = Path("blackpod/advisors/mandate.py")
COUNCIL_SYNTHESIS_ENTRY_POINT = (
    "blackpod.governor.council_synthesis.build_council_synthesis"
)
COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/council_synthesis.py"
)
COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT = (
    "blackpod.governor.council_executive_summary.build_council_executive_summary"
)
COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/council_executive_summary.py"
)
ADVISOR_HEALTH_ENTRY_POINT = (
    "blackpod.runtime.advisor_health.build_advisor_health_summary"
)
ADVISOR_HEALTH_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/advisor_health.py"
)
RUNTIME_VALIDATION_ENTRY_POINT = (
    "blackpod.runtime.validation_report.build_runtime_validation_report"
)
RUNTIME_VALIDATION_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/validation_report.py"
)
GOVERNOR_SENATE_INTAKE_ENTRY_POINT = (
    "blackpod.governor.governor_senate_intake.build_governor_senate_intake"
)
GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/governor_senate_intake.py"
)
GOVERNOR_PREPARATION_ENTRY_POINT = (
    "blackpod.governor.governor_deliberation_prep."
    "build_governor_deliberation_prep"
)
GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/governor_deliberation_prep.py"
)
GOVERNOR_DELIBERATION_ENTRY_POINT = (
    "blackpod.governor.governor_deliberation.build_governor_deliberation"
)
GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/governor_deliberation.py"
)
GOVERNOR_READINESS_ENTRY_POINT = (
    "blackpod.governor.governor_decision_readiness."
    "build_governor_decision_readiness"
)
GOVERNOR_READINESS_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/governor_decision_readiness.py"
)
GOVERNOR_RENDERING_ENTRY_POINT = (
    "blackpod.governor.governor_decision.build_governor_decision"
)
GOVERNOR_RENDERING_MODULE_RELATIVE_PATH = Path(
    "blackpod/governor/governor_decision.py"
)
GOVERNOR_DECISION_CONSUMER_ENTRY_POINT = (
    "blackpod.runtime.governor_decision_consumer.consume_run_dir"
)
GOVERNOR_DECISION_CONSUMER_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/governor_decision_consumer.py"
)
OPERATOR_ACTION_ENTRY_POINT = (
    "blackpod.runtime.operator_inbox_action.record_operator_action"
)
OPERATOR_ACTION_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/operator_inbox_action.py"
)
NAVIGATOR_HANDOFF_ENTRY_POINT = (
    "blackpod.runtime.navigator_handoff.stage_navigator_handoff"
)
NAVIGATOR_HANDOFF_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/navigator_handoff.py"
)
NAVIGATOR_INTAKE_ENTRY_POINT = (
    "blackpod.runtime.navigator_intake.accept_handoff_envelope"
)
# The current intake entry point creates the non-executable SHADOW plan after
# accepting the envelope; Battlestar exposes no separate public plan builder.
NAVIGATOR_SHADOW_PLAN_ENTRY_POINT = NAVIGATOR_INTAKE_ENTRY_POINT
NAVIGATOR_INTAKE_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/navigator_intake.py"
)
NAVIGATOR_SHADOW_WORKFLOW_ENTRY_POINT = (
    "blackpod.runtime.navigator_shadow_workflow.run_workflow"
)
NAVIGATOR_SHADOW_WORKFLOW_MODULE_RELATIVE_PATH = Path(
    "blackpod/runtime/navigator_shadow_workflow.py"
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
    candidate_module_path: Path | None = None
    senate_review_module_path: Path | None = None
    senate_deliberation_module_path: Path | None = None
    mandate_module_path: Path | None = None
    council_synthesis_module_path: Path | None = None
    council_executive_summary_module_path: Path | None = None
    advisor_health_module_path: Path | None = None
    runtime_validation_module_path: Path | None = None
    governor_senate_intake_module_path: Path | None = None
    governor_preparation_module_path: Path | None = None
    governor_deliberation_module_path: Path | None = None
    governor_readiness_module_path: Path | None = None
    governor_rendering_module_path: Path | None = None
    governor_decision_consumer_module_path: Path | None = None
    operator_action_module_path: Path | None = None
    navigator_handoff_module_path: Path | None = None
    navigator_intake_module_path: Path | None = None
    navigator_shadow_workflow_module_path: Path | None = None


def load_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
    require_council: bool = False,
    require_governor: bool = False,
    require_operator: bool = False,
    require_navigator: bool = False,
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
    council_paths: dict[str, Path | None] = {
        "candidate_module_path": None,
        "senate_review_module_path": None,
        "senate_deliberation_module_path": None,
        "mandate_module_path": None,
        "council_synthesis_module_path": None,
        "council_executive_summary_module_path": None,
        "advisor_health_module_path": None,
        "runtime_validation_module_path": None,
    }
    if require_council:
        council_paths = {
            "candidate_module_path": _required_repository_file(
                root,
                CANDIDATE_MODULE_RELATIVE_PATH,
                description="candidate-generation module",
            ),
            "senate_review_module_path": _required_repository_file(
                root,
                SENATE_REVIEW_MODULE_RELATIVE_PATH,
                description="Senate review module",
            ),
            "senate_deliberation_module_path": _required_repository_file(
                root,
                SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
                description="Senate deliberation module",
            ),
            "mandate_module_path": _required_repository_file(
                root,
                MANDATE_MODULE_RELATIVE_PATH,
                description="Mandate module",
            ),
            "council_synthesis_module_path": _required_repository_file(
                root,
                COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
                description="Council synthesis module",
            ),
            "council_executive_summary_module_path": _required_repository_file(
                root,
                COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
                description="Council executive-summary module",
            ),
            "advisor_health_module_path": _required_repository_file(
                root,
                ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
                description="advisor-health module",
            ),
            "runtime_validation_module_path": _required_repository_file(
                root,
                RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
                description="runtime-validation module",
            ),
        }
    governor_paths: dict[str, Path | None] = {
        "governor_senate_intake_module_path": None,
        "governor_preparation_module_path": None,
        "governor_deliberation_module_path": None,
        "governor_readiness_module_path": None,
        "governor_rendering_module_path": None,
    }
    if require_governor:
        governor_paths = {
            "governor_senate_intake_module_path": _required_repository_file(
                root,
                GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH,
                description="Governor Senate-intake module",
            ),
            "governor_preparation_module_path": _required_repository_file(
                root,
                GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH,
                description="Governor preparation module",
            ),
            "governor_deliberation_module_path": _required_repository_file(
                root,
                GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH,
                description="Governor deliberation module",
            ),
            "governor_readiness_module_path": _required_repository_file(
                root,
                GOVERNOR_READINESS_MODULE_RELATIVE_PATH,
                description="Governor readiness module",
            ),
            "governor_rendering_module_path": _required_repository_file(
                root,
                GOVERNOR_RENDERING_MODULE_RELATIVE_PATH,
                description="Governor rendering module",
            ),
        }
    operator_paths: dict[str, Path | None] = {
        "governor_decision_consumer_module_path": None,
        "operator_action_module_path": None,
    }
    if require_operator or require_navigator:
        operator_paths = {
            "governor_decision_consumer_module_path": _required_repository_file(
                root,
                GOVERNOR_DECISION_CONSUMER_MODULE_RELATIVE_PATH,
                description="Governor decision-consumer module",
            ),
            "operator_action_module_path": _required_repository_file(
                root,
                OPERATOR_ACTION_MODULE_RELATIVE_PATH,
                description="operator-action module",
            ),
        }
    navigator_paths: dict[str, Path | None] = {
        "navigator_handoff_module_path": None,
        "navigator_intake_module_path": None,
        "navigator_shadow_workflow_module_path": None,
    }
    if require_navigator:
        navigator_paths = {
            "navigator_handoff_module_path": _required_repository_file(
                root,
                NAVIGATOR_HANDOFF_MODULE_RELATIVE_PATH,
                description="Navigator handoff module",
            ),
            "navigator_intake_module_path": _required_repository_file(
                root,
                NAVIGATOR_INTAKE_MODULE_RELATIVE_PATH,
                description="Navigator intake module",
            ),
            "navigator_shadow_workflow_module_path": _required_repository_file(
                root,
                NAVIGATOR_SHADOW_WORKFLOW_MODULE_RELATIVE_PATH,
                description="Navigator SHADOW workflow module",
            ),
        }

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
        **council_paths,
        **governor_paths,
        **operator_paths,
        **navigator_paths,
    )


def load_council_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
) -> BattlestarConfig:
    """Run Oracle-compatible preflight plus all Phase 3 Council module checks."""

    return load_battlestar_config(
        artifacts_root=artifacts_root,
        environ=environ,
        strict_clean=strict_clean,
        require_council=True,
    )


def load_governor_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
) -> BattlestarConfig:
    """Run Phase 3-compatible preflight plus Phase 4 Governor module checks."""

    return load_battlestar_config(
        artifacts_root=artifacts_root,
        environ=environ,
        strict_clean=strict_clean,
        require_council=True,
        require_governor=True,
    )


def load_operator_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
) -> BattlestarConfig:
    """Run Phase 4 preflight plus the explicit operator-gate checks."""

    return load_battlestar_config(
        artifacts_root=artifacts_root,
        environ=environ,
        strict_clean=strict_clean,
        require_council=True,
        require_governor=True,
        require_operator=True,
    )


def load_navigator_battlestar_config(
    *,
    artifacts_root: Path,
    environ: Mapping[str, str] | None = None,
    strict_clean: bool = False,
) -> BattlestarConfig:
    """Run operator-compatible preflight plus current SHADOW workflow checks."""

    return load_battlestar_config(
        artifacts_root=artifacts_root,
        environ=environ,
        strict_clean=strict_clean,
        require_council=True,
        require_governor=True,
        require_operator=True,
        require_navigator=True,
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
