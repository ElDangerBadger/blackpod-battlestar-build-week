"""Deterministic plain-text renderer for Build Week demonstrations."""

from __future__ import annotations

from .contracts import OperatorActionStatus, StageStatus
from .demo_workflow import DemoWorkflowResult
from .mission_presentation import MissionPresentationResult


_LABELS = {
    "HARBORMASTER": "Harbormaster",
    "ORACLE": "Oracle",
    "MODELDOCK": "ModelDock",
    "COUNCIL": "Council",
    "GOVERNOR": "Governor",
    "OPERATOR": "Operator",
    "NAVIGATOR": "Navigator",
}


def render_demo_terminal(
    result: DemoWorkflowResult,
    *,
    no_color: bool = False,
) -> str:
    """Return stable terminal output with no timing, animation, or raw tracebacks.

    ``no_color`` is intentionally accepted as part of the public CLI contract.
    The current renderer is plain text in every environment, so redirected
    output and recordings are byte-stable without terminal capability probes.
    """

    del no_color
    unified = result.unified
    snapshot = unified.snapshot
    presentation = unified.presentation
    if not isinstance(presentation, MissionPresentationResult):
        raise ValueError("demo result does not contain presentation output")
    summary = presentation.mission_summary
    stage_by_name = {item.stage: item for item in summary.ordered_stages}

    lines = [
        "BLACKPOD BATTLESTAR",
        f"Mission: {snapshot.mission_id}",
        f"Symbol: {unified.request.symbol}",
        f"Mode: {snapshot.run_mode.value}",
        "",
    ]
    for stage_name in _LABELS:
        display_state = _display_state(result, stage_name, stage_by_name)
        lines.append(
            f"{_marker(display_state)} {_LABELS[stage_name]:<16}{display_state}"
        )

    lines.extend(
        [
            "",
            f"Outcome: {snapshot.mission_outcome.value}",
            "Approval scope: "
            + (
                snapshot.approval_scope.value
                if snapshot.approval_scope is not None
                else "NONE"
            ),
            f"Snapshots: {snapshot.revision}",
            f"ModelDock mode: {result.modeldock_mode.value}",
            f"Unified action: {unified.action.value}",
            f"Captain's Log: {presentation.captains_log_markdown_path.resolve()}",
            f"Mission summary: {presentation.mission_summary_path.resolve()}",
            f"Demo manifest: {result.manifest_path.resolve()}",
        ]
    )
    if result.rehearsal is not None:
        lines.extend(
            [
                "Rehearsal cold: " + result.rehearsal.cold_action.value,
                "Rehearsal warm: " + result.rehearsal.warm_action.value,
                "Rehearsal artifacts unchanged: true",
            ]
        )
    if not unified.technical_success:
        stage, reason = _failure(snapshot)
        lines.extend(
            [
                "",
                f"Failed stage: {stage}",
                f"Reason: {reason}",
                f"Resumable: {str(not snapshot.terminal).lower()}",
                f"Last valid snapshot: {unified.paths.current_snapshot.resolve()}",
                f"Mission artifacts: {unified.paths.mission_root.resolve()}",
            ]
        )
    return "\n".join(lines) + "\n"


def _display_state(
    result: DemoWorkflowResult,
    stage_name: str,
    ordered: dict[str, object],
) -> str:
    snapshot = result.unified.snapshot
    if stage_name == "MODELDOCK":
        return {
            "REPLAYED": "Narrative validated (REPLAY)",
            "LIVE": "Narrative validated (LIVE)",
            "DISABLED": "DISABLED",
            "FAILED": "FAILED",
        }[result.modeldock_mode.value]
    if stage_name == "ORACLE":
        stage = snapshot.stages["oracle"]
        return stage.native_state or stage.status.value
    if stage_name == "COUNCIL":
        stage = snapshot.stages["council"]
        return stage.native_state or stage.status.value
    item = ordered[stage_name]
    return str(getattr(item, "display_state"))


def _marker(display_state: str) -> str:
    if "FAILED" in display_state or "REJECTED" in display_state:
        return "[!]"
    if display_state in {
        "NOT_STARTED",
        "NOT_RECORDED",
        "PENDING_APPROVAL",
        "DISABLED",
    }:
        return "[-]"
    return "[✓]"


def _failure(snapshot: object) -> tuple[str, str]:
    stages = getattr(snapshot, "stages")
    for name, stage in stages.items():
        if stage.status is StageStatus.FAILED:
            if stage.error is None:
                return name.upper(), "UNKNOWN_FAILURE"
            return name.upper(), f"{stage.error.code}: {stage.error.message}"
    operator = getattr(snapshot, "operator")
    if operator.action_status is OperatorActionStatus.FAILED:
        if operator.error is None:
            return "OPERATOR", "UNKNOWN_FAILURE"
        return "OPERATOR", f"{operator.error.code}: {operator.error.message}"
    return "MISSION", "CANONICAL_TECHNICAL_FAILURE"
