"""Deterministic, presentation-ready wrappers around unified mission orchestration.

This module deliberately contains no stage policy.  A demo scenario resolves to
the same :class:`UnifiedMissionSettings` accepted by ``mission-run`` and then
dispatches the existing unified workflow exactly once (or twice for an explicit
cold/warm rehearsal).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .contracts import (
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    CANONICAL_SNAPSHOT_PATH,
    DEMO_MANIFEST_PATH,
    DEMO_MANIFEST_SCHEMA_VERSION,
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    SHADOW_ONLY_DECLARATION,
    DemoManifest,
    DemoModelDockMode,
    ModelDockCallStatus,
)
from .demo_catalog import (
    DemoCatalog,
    DemoScenarioSpec,
    ResolvedDemoScenario,
    load_demo_catalog,
)
from .hashing import canonical_json_bytes, sha256_file
from .mission_presentation import MissionPresentationResult
from .mission_store import MissionStore
from .modeldock_config import (
    MODELDOCK_BASE_URL_ENV,
    MODELDOCK_MODEL_ENV,
    MODELDOCK_PROFILE_ENV,
    MODELDOCK_PROVIDER_ENV,
    MODELDOCK_TIMEOUT_SECONDS_ENV,
)
from .repository_state import inspect_git_worktree
from .unified_mission_workflow import (
    UnifiedMissionAction,
    UnifiedMissionResult,
    UnifiedMissionSettings,
    run_unified_mission,
)


_REPLAY_MODELDOCK_ENVIRONMENT = {
    MODELDOCK_BASE_URL_ENV: "http://127.0.0.1:8000",
    MODELDOCK_TIMEOUT_SECONDS_ENV: "30",
    MODELDOCK_PROFILE_ENV: "default",
    MODELDOCK_PROVIDER_ENV: "mlx",
}


class DemoWorkflowError(RuntimeError):
    """Raised when a committed demo cannot be reproduced canonically."""


@dataclass(frozen=True, slots=True)
class DemoSettings:
    scenario: str
    artifacts_root: Path | None = None
    without_modeldock: bool = False
    rehearse: bool = False
    strict_battlestar_clean: bool = False


@dataclass(frozen=True, slots=True)
class RehearsalResult:
    cold_action: UnifiedMissionAction
    warm_action: UnifiedMissionAction
    snapshot_count: int
    checked_file_count: int
    immutable_files_unchanged: bool


@dataclass(frozen=True, slots=True)
class DemoWorkflowResult:
    scenario: DemoScenarioSpec
    resolved_scenario: ResolvedDemoScenario
    unified: UnifiedMissionResult
    manifest: DemoManifest
    manifest_path: Path
    artifacts_root: Path
    created_isolated_root: bool
    modeldock_mode: DemoModelDockMode
    rehearsal: RehearsalResult | None


UnifiedRunner = Callable[..., UnifiedMissionResult]
TemporaryRootFactory = Callable[[], Path]


def run_demo(
    settings: DemoSettings,
    *,
    environ: Mapping[str, str] | None = None,
    catalog: DemoCatalog | None = None,
    unified_runner: UnifiedRunner = run_unified_mission,
    temporary_root_factory: TemporaryRootFactory | None = None,
) -> DemoWorkflowResult:
    """Run one committed scenario through the existing unified mission path."""

    active_catalog = catalog or load_demo_catalog()
    scenario_name = _scenario_name(settings)
    scenario = active_catalog.scenario(scenario_name)
    resolved = scenario.resolve(active_catalog.repository_root)
    artifacts_root, isolated = _artifacts_root(
        settings.artifacts_root,
        factory=temporary_root_factory,
    )
    environment = _replay_environment(environ)
    unified_settings = _unified_settings(
        resolved,
        artifacts_root=artifacts_root,
        strict_clean=settings.strict_battlestar_clean,
    )

    cold = unified_runner(unified_settings, environ=environment)
    _validate_result(cold, scenario)
    manifest, manifest_path = _write_manifest(
        active_catalog,
        scenario,
        cold,
    )

    rehearsal: RehearsalResult | None = None
    final = cold
    if settings.rehearse:
        if scenario.name not in {"approved", "without-modeldock"}:
            raise DemoWorkflowError(
                "cold/warm rehearsal is supported only for the approved scenario"
            )
        before = _file_fingerprints(cold.paths.mission_root)
        warm = unified_runner(unified_settings, environ=environment)
        _validate_result(warm, scenario)
        warm_manifest, warm_manifest_path = _write_manifest(
            active_catalog,
            scenario,
            warm,
        )
        after = _file_fingerprints(warm.paths.mission_root)
        if warm.action is not UnifiedMissionAction.NO_OP_ALREADY_SATISFIED:
            raise DemoWorkflowError(
                "warm rehearsal did not report NO_OP_ALREADY_SATISFIED"
            )
        if warm.snapshot.revision != cold.snapshot.revision:
            raise DemoWorkflowError("warm rehearsal created snapshot revisions")
        if before != after:
            raise DemoWorkflowError("warm rehearsal changed mission artifact bytes")
        if warm_manifest != manifest or warm_manifest_path != manifest_path:
            raise DemoWorkflowError("warm rehearsal changed the demo manifest")
        rehearsal = RehearsalResult(
            cold_action=cold.action,
            warm_action=warm.action,
            snapshot_count=warm.snapshot.revision,
            checked_file_count=len(after),
            immutable_files_unchanged=True,
        )
        final = warm

    return DemoWorkflowResult(
        scenario=scenario,
        resolved_scenario=resolved,
        unified=final,
        manifest=manifest,
        manifest_path=manifest_path,
        artifacts_root=artifacts_root,
        created_isolated_root=isolated,
        modeldock_mode=manifest.modeldock_mode,
        rehearsal=rehearsal,
    )


def _scenario_name(settings: DemoSettings) -> str:
    if settings.scenario not in {"approved", "held", "vetoed", "failed", "incomplete"}:
        raise DemoWorkflowError(f"unsupported demo scenario: {settings.scenario!r}")
    if settings.without_modeldock:
        if settings.scenario != "approved":
            raise DemoWorkflowError(
                "--without-modeldock is supported only for the approved demo"
            )
        return "without-modeldock"
    return settings.scenario


def _artifacts_root(
    configured: Path | None,
    *,
    factory: TemporaryRootFactory | None,
) -> tuple[Path, bool]:
    if configured is not None:
        return Path(configured).expanduser(), False
    if factory is None:
        path = Path(tempfile.mkdtemp(prefix="blackpod-build-week-demo-"))
    else:
        path = Path(factory())
        path.mkdir(parents=True, exist_ok=False)
    return path.resolve(strict=True), True


def _replay_environment(environ: Mapping[str, str] | None) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    # Demo is always deterministic REPLAY.  These values configure replay
    # provenance only; no ModelDock network call is made by replay enrichment.
    environment.update(_REPLAY_MODELDOCK_ENVIRONMENT)
    environment.pop(MODELDOCK_MODEL_ENV, None)
    return environment


def _unified_settings(
    scenario: ResolvedDemoScenario,
    *,
    artifacts_root: Path,
    strict_clean: bool,
) -> UnifiedMissionSettings:
    spec = scenario.spec
    return UnifiedMissionSettings(
        request_path=scenario.request,
        artifacts_root=artifacts_root,
        with_modeldock=spec.with_modeldock,
        through=spec.through,
        operator_action=spec.operator_action,
        operator_id=spec.operator_id,
        operator_reason=spec.operator_reason,
        oracle_replay_fixture=scenario.oracle_fixture,
        modeldock_replay_fixture=scenario.modeldock_fixture,
        council_replay_fixture=scenario.council_fixture,
        governor_replay_fixture=scenario.governor_fixture,
        operator_replay_fixture=scenario.operator_fixture,
        navigator_replay_fixture=scenario.navigator_fixture,
        strict_battlestar_clean=strict_clean,
    )


def _validate_result(result: UnifiedMissionResult, scenario: DemoScenarioSpec) -> None:
    snapshot = result.snapshot
    mismatches: list[str] = []
    if snapshot.mission_outcome is not scenario.expected_outcome:
        mismatches.append(
            f"outcome {snapshot.mission_outcome.value} != {scenario.expected_outcome.value}"
        )
    if snapshot.current_phase is not scenario.expected_phase:
        mismatches.append(
            f"phase {snapshot.current_phase.value} != {scenario.expected_phase.value}"
        )
    if snapshot.terminal is not scenario.expected_terminal:
        mismatches.append(
            f"terminal {snapshot.terminal} != {scenario.expected_terminal}"
        )
    if snapshot.revision != scenario.expected_snapshot_count:
        mismatches.append(
            f"snapshots {snapshot.revision} != {scenario.expected_snapshot_count}"
        )
    expected_success = scenario.expected_exit_code == 0
    if result.technical_success is not expected_success:
        mismatches.append(
            f"technical_success {result.technical_success} != {expected_success}"
        )
    if mismatches:
        raise DemoWorkflowError(
            f"demo scenario {scenario.name} produced unexpected canonical state: "
            + "; ".join(mismatches)
        )
    if not isinstance(result.presentation, MissionPresentationResult):
        raise DemoWorkflowError("unified mission did not create presentation artifacts")


def _write_manifest(
    catalog: DemoCatalog,
    scenario: DemoScenarioSpec,
    result: UnifiedMissionResult,
) -> tuple[DemoManifest, Path]:
    snapshot = result.snapshot
    presentation = result.presentation
    if not isinstance(presentation, MissionPresentationResult):
        raise DemoWorkflowError("presentation artifacts are unavailable")
    store = MissionStore(result.paths.mission_root.parent.parent)
    generated_at = snapshot.observed_at
    captain_reference = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=CAPTAINS_LOG_PATH,
        name="captains_log",
        producer="harbormaster",
        schema_version=CAPTAINS_LOG_SCHEMA_VERSION,
        observed_at=generated_at,
    )
    summary_reference = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=MISSION_SUMMARY_PATH,
        name="mission_summary",
        producer="harbormaster",
        schema_version=MISSION_SUMMARY_SCHEMA_VERSION,
        observed_at=generated_at,
    )
    snapshot_reference = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=CANONICAL_SNAPSHOT_PATH,
        name="mission_snapshot",
        producer="harbormaster",
        schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
        observed_at=generated_at,
    )
    modeldock_mode, service_identity, provider, model, trace_id = _modeldock_identity(
        result,
        enabled=scenario.with_modeldock,
    )
    battlestar = snapshot.components.get("battlestar")
    battlestar_revision = getattr(battlestar, "git_revision", None)
    if not isinstance(battlestar_revision, str):
        raise DemoWorkflowError("Battlestar revision is absent from Oracle provenance")
    build_week = inspect_git_worktree(catalog.repository_root)
    manifest = DemoManifest.from_mapping(
        {
            "schema_version": DEMO_MANIFEST_SCHEMA_VERSION,
            "demo_scenario": scenario.expected_outcome.value.lower(),
            "mission_id": snapshot.mission_id,
            "symbol": result.request.symbol,
            "run_mode": snapshot.run_mode.value,
            "build_week_revision": build_week.revision,
            "battlestar_revision": battlestar_revision,
            "modeldock_mode": modeldock_mode.value,
            "modeldock_revision_or_service_identity": service_identity,
            "modeldock_provider": provider,
            "modeldock_model": model,
            "modeldock_trace_id": trace_id,
            "final_outcome": snapshot.mission_outcome.value,
            "snapshot_count": snapshot.revision,
            "captains_log": captain_reference.to_dict(),
            "mission_summary": summary_reference.to_dict(),
            "final_snapshot": snapshot_reference.to_dict(),
            "generated_at": generated_at,
            "shadow_only_declaration": SHADOW_ONLY_DECLARATION,
            "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
            "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
        }
    )
    write = store.write_presentation_artifact(
        snapshot.mission_id,
        relative_path=DEMO_MANIFEST_PATH,
        payload=canonical_json_bytes(manifest.to_dict()),
    )
    return manifest, write.path


def _modeldock_identity(
    result: UnifiedMissionResult,
    *,
    enabled: bool,
) -> tuple[DemoModelDockMode, str | None, str | None, str | None, str | None]:
    if not enabled:
        return DemoModelDockMode.DISABLED, None, None, None, None
    calls = result.snapshot.stages["oracle"].modeldock_calls
    if len(calls) != 1:
        raise DemoWorkflowError("enabled demo requires one canonical ModelDock call")
    call = calls[0]
    if call.status is ModelDockCallStatus.FAILED:
        mode = DemoModelDockMode.FAILED
    elif call.status is ModelDockCallStatus.SUCCEEDED:
        mode = DemoModelDockMode.REPLAYED
    else:
        raise DemoWorkflowError("demo ended with an incomplete ModelDock call")
    component = result.snapshot.components.get("modeldock")
    identity = getattr(component, "replay_fixture_id", None)
    if not isinstance(identity, str) or not identity:
        identity = None
    return mode, identity, call.provider, call.model, call.trace_id


def _file_fingerprints(mission_root: Path) -> dict[str, tuple[str, int, int]]:
    fingerprints: dict[str, tuple[str, int, int]] = {}
    for path in sorted(mission_root.rglob("*")):
        if path.is_symlink():
            raise DemoWorkflowError("mission rehearsal encountered an unsafe symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(mission_root).as_posix()
        stat = path.stat()
        fingerprints[relative] = (sha256_file(path), stat.st_size, stat.st_mtime_ns)
    return fingerprints
