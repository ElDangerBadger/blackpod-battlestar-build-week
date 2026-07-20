"""Freeze one verified LIVE mission behind the existing demo-manifest contract.

This module is deliberately a packaging seam, not an execution workflow.  It
loads a mission through :class:`MissionStore`, verifies the completed canonical
state and its presentation projections, and publishes the existing
``blackpod.demo_manifest.v1`` artifact without changing any mission evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence

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
    ApprovalScope,
    ArtifactReference,
    CaptainsLog,
    CurrentPhase,
    DemoManifest,
    DemoModelDockMode,
    MissionOutcome,
    MissionSummary,
    ModelDockCallStatus,
    ModelDockTransportKind,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    RunMode,
    StageStatus,
)
from .contracts.mission_request import load_strict_json_object
from .hashing import canonical_json_bytes
from .mission_store import ImmutableArtifactError, MissionStore, MissionStoreError
from .repository_state import GitWorktreeState, RepositoryStateError, inspect_git_worktree


class LiveDemoPackagingError(RuntimeError):
    """Raised when a mission is not eligible to become the canonical LIVE demo."""


class LiveDemoPackageAction(str, Enum):
    CREATED = "CREATED"
    NO_OP_ALREADY_SATISFIED = "NO_OP_ALREADY_SATISFIED"


@dataclass(frozen=True, slots=True)
class LiveDemoPackageResult:
    manifest: DemoManifest
    path: Path
    action: LiveDemoPackageAction


WorktreeInspector = Callable[[Path], GitWorktreeState]


def package_live_demo(
    *,
    mission_id: str,
    artifacts_root: Path,
    repository_root: Path,
    store: MissionStore | None = None,
    worktree_inspector: WorktreeInspector = inspect_git_worktree,
) -> LiveDemoPackageResult:
    """Validate and immutably package an existing LIVE mission.

    Repeating the operation with byte-identical output is an explicit no-op.
    An existing different manifest is an immutable conflict and is never
    overwritten. Only an explicitly approved, completed SHADOW mission can be
    published; partial or held missions remain canonical mission evidence but
    are not presentation packs.
    """

    mission_store = store or MissionStore(Path(artifacts_root))
    try:
        loaded = mission_store.load_mission(mission_id)
        build_week = worktree_inspector(Path(repository_root))
    except (MissionStoreError, RepositoryStateError, OSError) as exc:
        raise LiveDemoPackagingError(str(exc)) from exc

    snapshot = loaded.snapshot
    request = loaded.request
    _validate_completed_live_state(loaded)

    log = _load_captains_log(loaded.paths.mission_root)
    summary = _load_mission_summary(loaded.paths.mission_root)
    _validate_presentations(
        mission_store,
        loaded,
        log=log,
        summary=summary,
        expected_outcome=snapshot.mission_outcome,
    )

    call = snapshot.stages["oracle"].modeldock_calls[0]
    battlestar = snapshot.components.get("battlestar")
    modeldock = snapshot.components.get("modeldock")
    battlestar_revision = getattr(battlestar, "git_revision", None)
    battlestar_dirty = getattr(battlestar, "dirty_worktree", None)
    endpoint = getattr(modeldock, "endpoint", None)
    if build_week.dirty:
        raise LiveDemoPackagingError(
            "Build Week worktree must be clean before freezing a verified LIVE demo"
        )
    if not isinstance(battlestar_revision, str) or not battlestar_revision:
        raise LiveDemoPackagingError(
            "Battlestar revision is absent from canonical Oracle provenance"
        )
    if battlestar_dirty is not False:
        raise LiveDemoPackagingError(
            "Battlestar worktree must have been clean for the verified LIVE mission"
        )
    if not isinstance(endpoint, str) or endpoint != call.endpoint:
        raise LiveDemoPackagingError(
            "ModelDock service identity is absent or differs from the canonical call"
        )

    generated_at = snapshot.observed_at
    captains_log_reference = _presentation_reference(
        mission_store,
        mission_id,
        path=CAPTAINS_LOG_PATH,
        name="captains_log",
        schema_version=CAPTAINS_LOG_SCHEMA_VERSION,
        observed_at=generated_at,
    )
    mission_summary_reference = _presentation_reference(
        mission_store,
        mission_id,
        path=MISSION_SUMMARY_PATH,
        name="mission_summary",
        schema_version=MISSION_SUMMARY_SCHEMA_VERSION,
        observed_at=generated_at,
    )
    final_snapshot_reference = _presentation_reference(
        mission_store,
        mission_id,
        path=CANONICAL_SNAPSHOT_PATH,
        name="mission_snapshot",
        schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
        observed_at=generated_at,
    )

    manifest = DemoManifest.from_mapping(
        {
            "schema_version": DEMO_MANIFEST_SCHEMA_VERSION,
            "demo_scenario": snapshot.mission_outcome.value.lower(),
            "mission_id": snapshot.mission_id,
            "symbol": request.symbol,
            "run_mode": RunMode.LIVE.value,
            "build_week_revision": build_week.revision,
            "battlestar_revision": battlestar_revision,
            "modeldock_mode": DemoModelDockMode.LIVE.value,
            "modeldock_revision_or_service_identity": endpoint,
            "modeldock_provider": call.provider,
            "modeldock_model": call.model,
            "modeldock_trace_id": call.trace_id,
            "final_outcome": snapshot.mission_outcome.value,
            "snapshot_count": len(loaded.snapshot_history),
            "captains_log": captains_log_reference.to_dict(),
            "mission_summary": mission_summary_reference.to_dict(),
            "final_snapshot": final_snapshot_reference.to_dict(),
            "generated_at": generated_at,
            "shadow_only_declaration": SHADOW_ONLY_DECLARATION,
            "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
            "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
        }
    )
    payload = canonical_json_bytes(manifest.to_dict())
    path = loaded.paths.mission_root / DEMO_MANIFEST_PATH
    try:
        mission_store.write_immutable_artifact(
            mission_id,
            relative_path=DEMO_MANIFEST_PATH,
            payload=payload,
            name="demo_manifest",
            producer="harbormaster",
            schema_version=DEMO_MANIFEST_SCHEMA_VERSION,
            observed_at=generated_at,
        )
    except ImmutableArtifactError as exc:
        try:
            _presentation_reference(
                mission_store,
                mission_id,
                path=DEMO_MANIFEST_PATH,
                name="demo_manifest",
                schema_version=DEMO_MANIFEST_SCHEMA_VERSION,
                observed_at=generated_at,
            )
            existing_payload = path.read_bytes()
        except (MissionStoreError, OSError) as read_exc:
            raise LiveDemoPackagingError(
                "existing demo manifest is unsafe or unreadable"
            ) from read_exc
        if existing_payload != payload:
            raise LiveDemoPackagingError(
                "immutable demo manifest already exists with different content"
            ) from exc
        return LiveDemoPackageResult(
            manifest=manifest,
            path=path,
            action=LiveDemoPackageAction.NO_OP_ALREADY_SATISFIED,
        )
    except MissionStoreError as exc:
        raise LiveDemoPackagingError(str(exc)) from exc

    return LiveDemoPackageResult(
        manifest=manifest,
        path=path,
        action=LiveDemoPackageAction.CREATED,
    )


def _validate_completed_live_state(loaded: object) -> None:
    snapshot = loaded.snapshot
    request = loaded.request
    if request.run_mode is not RunMode.LIVE or snapshot.run_mode is not RunMode.LIVE:
        raise LiveDemoPackagingError("canonical demo packaging requires a LIVE mission")
    if (
        request.mission_id != snapshot.mission_id
        or request.request_id != snapshot.request_id
    ):
        raise LiveDemoPackagingError("mission request and snapshot correlation differ")
    if len(loaded.snapshot_history) != snapshot.revision:
        raise LiveDemoPackagingError("snapshot history count differs from final revision")
    if set(snapshot.stages) != {
        "harbormaster",
        "oracle",
        "council",
        "governor",
        "navigator",
    }:
        raise LiveDemoPackagingError("all five canonical stage objects must be present")
    if (
        snapshot.mission_outcome is not MissionOutcome.APPROVED
        or snapshot.current_phase is not CurrentPhase.COMPLETE
        or not snapshot.terminal
    ):
        raise LiveDemoPackagingError(
            "canonical LIVE demo must be terminal APPROVED in COMPLETE phase"
        )
    if any(
        stage.status is not StageStatus.SUCCEEDED for stage in snapshot.stages.values()
    ):
        raise LiveDemoPackagingError("all five canonical stages must be SUCCEEDED")
    if snapshot.stages["governor"].native_state != "PROCEED":
        raise LiveDemoPackagingError("approved LIVE demo requires Governor PROCEED")

    operator = snapshot.operator
    if (
        operator.route is not OperatorRoute.PENDING_APPROVAL
        or operator.action_status is not OperatorActionStatus.SUCCEEDED
        or operator.action is not OperatorAction.APPROVE_HANDOFF
        or operator.result is not OperatorResult.APPROVED_FOR_HANDOFF
    ):
        raise LiveDemoPackagingError(
            "approved LIVE demo requires explicit APPROVED_FOR_HANDOFF operator state"
        )

    navigator = snapshot.navigator
    if (
        snapshot.approval_scope is not ApprovalScope.NAVIGATOR_SHADOW_HANDOFF
        or navigator.mode is not NavigatorMode.SHADOW
        or navigator.handoff_status is not NavigatorHandoffStatus.STAGED
        or navigator.intake_status is not NavigatorIntakeStatus.ACCEPTED
        or navigator.plan_status is not NavigatorPlanStatus.CREATED
        or navigator.allowed_operations != NAVIGATOR_ALLOWED_OPERATIONS
        or navigator.prohibited_operations != NAVIGATOR_PROHIBITED_OPERATIONS
    ):
        raise LiveDemoPackagingError(
            "approved LIVE demo must end with the exact Navigator SHADOW safety state"
        )

    calls = snapshot.stages["oracle"].modeldock_calls
    if len(calls) != 1:
        raise LiveDemoPackagingError(
            "canonical LIVE demo requires exactly one ModelDock call"
        )
    call = calls[0]
    if (
        call.status is not ModelDockCallStatus.SUCCEEDED
        or call.run_mode is not RunMode.LIVE
        or call.mocked is not False
        or call.provider != "mlx"
        or not call.model
        or not call.trace_id
        or call.mission_id != snapshot.mission_id
        or call.request_id != snapshot.request_id
    ):
        raise LiveDemoPackagingError(
            "canonical LIVE demo requires one correlated, non-mocked MLX inference"
        )
    component = snapshot.components.get("modeldock")
    if (
        component is None
        or component.run_mode is not RunMode.LIVE
        or component.transport is not ModelDockTransportKind.LIVE_HTTP
        or component.expected_provider != "mlx"
        or component.replay_fixture_id is not None
        or component.endpoint != call.endpoint
    ):
        raise LiveDemoPackagingError("ModelDock LIVE provenance is inconsistent")


def _load_captains_log(mission_root: Path) -> CaptainsLog:
    try:
        return CaptainsLog.from_mapping(
            load_strict_json_object(mission_root / CAPTAINS_LOG_PATH)
        )
    except (OSError, ValueError) as exc:
        raise LiveDemoPackagingError("Captain's Log is missing or invalid") from exc


def _load_mission_summary(mission_root: Path) -> MissionSummary:
    try:
        return MissionSummary.from_mapping(
            load_strict_json_object(mission_root / MISSION_SUMMARY_PATH)
        )
    except (OSError, ValueError) as exc:
        raise LiveDemoPackagingError("mission summary is missing or invalid") from exc


def _validate_presentations(
    store: MissionStore,
    loaded: object,
    *,
    log: CaptainsLog,
    summary: MissionSummary,
    expected_outcome: MissionOutcome = MissionOutcome.APPROVED,
) -> None:
    snapshot = loaded.snapshot
    request = loaded.request
    identity = (snapshot.mission_id, snapshot.request_id, request.symbol, RunMode.LIVE)
    if (
        (log.mission_id, log.request_id, log.symbol, log.run_mode) != identity
        or (summary.mission_id, summary.request_id, summary.symbol, summary.run_mode)
        != identity
    ):
        raise LiveDemoPackagingError("presentation artifacts disagree on mission identity")
    if (
        log.generated_at != snapshot.observed_at
        or summary.generated_at != snapshot.observed_at
    ):
        raise LiveDemoPackagingError(
            "presentation timestamps differ from the final canonical snapshot"
        )

    final_revision_path = f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json"
    final_revision_reference = _presentation_reference(
        store,
        snapshot.mission_id,
        path=final_revision_path,
        name=f"mission_snapshot_r{snapshot.revision:04d}",
        schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
        observed_at=snapshot.observed_at,
    )
    if (
        log.generated_from_snapshot != final_revision_reference
        or summary.generated_from_snapshot != final_revision_reference
    ):
        raise LiveDemoPackagingError(
            "presentation artifacts do not hash-match the final immutable snapshot"
        )

    if (
        summary.current_phase is not snapshot.current_phase
        or summary.terminal is not snapshot.terminal
        or summary.final_outcome is not snapshot.mission_outcome
        or summary.snapshot_count != snapshot.revision
        or summary.approval_scope is not snapshot.approval_scope
        or summary.governor_disposition
        != snapshot.stages["governor"].native_state
    ):
        raise LiveDemoPackagingError("mission summary differs from canonical mission state")
    for stage_name, stage in snapshot.stages.items():
        presented = summary.stages[stage_name]
        if (
            presented.technical_status is not stage.status
            or presented.native_state != stage.native_state
        ):
            raise LiveDemoPackagingError(
                f"mission summary differs from canonical {stage_name} state"
            )

    call = snapshot.stages["oracle"].modeldock_calls[0]
    if (
        summary.modeldock.status != call.status.value
        or summary.modeldock.provider != call.provider
        or summary.modeldock.model != call.model
        or summary.modeldock.trace_id != call.trace_id
    ):
        raise LiveDemoPackagingError("mission summary ModelDock identity is inconsistent")
    if (
        summary.operator.route is not snapshot.operator.route
        or summary.operator.action_status is not snapshot.operator.action_status
        or summary.operator.action is not snapshot.operator.action
        or summary.operator.result is not snapshot.operator.result
    ):
        raise LiveDemoPackagingError("mission summary operator state is inconsistent")
    navigator = snapshot.navigator
    if (
        summary.navigator.technical_status
        is not snapshot.stages["navigator"].status
        or summary.navigator.native_state
        != snapshot.stages["navigator"].native_state
        or summary.navigator.mode is not navigator.mode
        or summary.navigator.handoff_status is not navigator.handoff_status
        or summary.navigator.intake_status is not navigator.intake_status
        or summary.navigator.plan_status is not navigator.plan_status
    ):
        raise LiveDemoPackagingError("mission summary Navigator state is inconsistent")

    log_by_stage = {entry.stage: entry for entry in log.entries}
    for ordered in summary.ordered_stages:
        entry = log_by_stage[ordered.stage]
        if (
            ordered.summary != entry.summary
            or ordered.artifact_paths
            != tuple(reference.path for reference in entry.source_artifacts)
        ):
            raise LiveDemoPackagingError(
                f"mission summary and Captain's Log differ for {ordered.stage}"
            )
    if log.entries[-1].status != expected_outcome.value:
        raise LiveDemoPackagingError(
            "Captain's Log does not record the canonical final outcome"
        )
    for entry in log.entries:
        for reference in entry.source_artifacts:
            _verify_reference(store, snapshot.mission_id, reference)


def _presentation_reference(
    store: MissionStore,
    mission_id: str,
    *,
    path: str,
    name: str,
    schema_version: str | None,
    observed_at: str,
) -> ArtifactReference:
    try:
        return store.reference_existing_artifact(
            mission_id,
            relative_path=path,
            name=name,
            producer="harbormaster",
            schema_version=schema_version,
            observed_at=observed_at,
        )
    except MissionStoreError as exc:
        raise LiveDemoPackagingError(
            f"required mission artifact is missing or unsafe: {path}"
        ) from exc


def _verify_reference(
    store: MissionStore,
    mission_id: str,
    reference: ArtifactReference,
) -> None:
    if (
        reference.producer is None
        or reference.byte_size is None
        or reference.observed_at is None
    ):
        raise LiveDemoPackagingError(
            f"presentation evidence reference is incomplete: {reference.path}"
        )
    try:
        actual = store.reference_existing_artifact(
            mission_id,
            relative_path=reference.path,
            name=reference.name,
            producer=reference.producer,
            schema_version=reference.schema_version,
            observed_at=reference.observed_at,
        )
    except MissionStoreError as exc:
        raise LiveDemoPackagingError(
            f"presentation evidence is missing or unsafe: {reference.path}"
        ) from exc
    if actual != reference:
        raise LiveDemoPackagingError(
            f"presentation evidence hash or size mismatch: {reference.path}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Immutably package one verified completed LIVE mission for demo use."
    )
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = package_live_demo(
            mission_id=args.mission_id,
            artifacts_root=args.artifacts_root,
            repository_root=args.repository_root,
        )
    except LiveDemoPackagingError as exc:
        print(f"LIVE demo packaging failed: {exc}")
        return 2
    print(f"mission_id: {result.manifest.mission_id}")
    print(f"modeldock_mode: {result.manifest.modeldock_mode.value}")
    print(f"provider: {result.manifest.modeldock_provider}")
    print(f"model: {result.manifest.modeldock_model}")
    print(f"trace_id: {result.manifest.modeldock_trace_id}")
    print("presentation_scope: APPROVED_CANONICAL_DEMO")
    print(f"action: {result.action.value}")
    print(f"manifest_path: {result.path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the script shim
    raise SystemExit(main())
