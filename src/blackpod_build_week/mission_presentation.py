"""Deterministic JSON, Markdown, and non-canonical HTML presentation views."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import quote

from .contracts import (
    CAPTAINS_LOG_MARKDOWN_PATH,
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_ARTIFACT_LINKS,
    MISSION_SUMMARY_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ArtifactReference,
    CaptainsLog,
    MissionSnapshot,
    MissionSummary,
    ModelDockCallStatus,
    OperatorActionStatus,
    StageStatus,
)
from .contracts.mission_request import load_strict_json_object
from .hashing import canonical_json_bytes, sha256_bytes
from .mission_store import LoadedMission, MissionStore


class MissionPresentationError(RuntimeError):
    """Raised when canonical state cannot be projected safely."""


@dataclass(frozen=True, slots=True)
class MissionPresentationResult:
    captain_log: CaptainsLog
    mission_summary: MissionSummary
    captains_log_json_path: Path
    captains_log_markdown_path: Path
    mission_summary_path: Path
    mission_brief_path: Path
    captains_log_json_written: bool
    captains_log_markdown_written: bool
    mission_summary_written: bool
    mission_brief_written: bool


_TERMINAL_STAGE_STATUSES = {StageStatus.SUCCEEDED, StageStatus.FAILED}
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?:api[_-]?key|authorization|password|secret|token)\s*[:=]",
    re.IGNORECASE,
)
_KNOWN_WARNING_FIELDS = {
    "oracle_report": ("warnings",),
    "oracle_modeldock_narrative": ("warnings",),
    "council_executive_summary": ("notable_warnings", "warnings"),
    "governor_warning_classification": ("warnings",),
}
_CAPTAINS_LOG_STAGE_SOURCES = {
    "harbormaster": ("mission_request",),
    "oracle": (
        "oracle_report",
        "oracle_readiness_report",
        "oracle_measurement_diagnostics",
    ),
    "council": ("council_synthesis", "council_executive_summary"),
    "governor": (
        "governor_rendered_decision",
        "governor_warning_classification",
    ),
    "navigator": (
        "navigator_staging_receipt",
        "navigator_intake_receipt",
        "navigator_shadow_plan",
    ),
}
_CAPTAINS_LOG_MODELDOCK_SOURCES = (
    "oracle_modeldock_narrative",
    "oracle_modeldock_provenance",
)
_CAPTAINS_LOG_OPERATOR_SOURCES = ("operator_action", "operator_receipt")
MISSION_BRIEF_PATH = "presentation/mission_brief.html"


def _snapshot_reference(
    loaded: LoadedMission, snapshot: MissionSnapshot
) -> ArtifactReference:
    path = loaded.paths.snapshots_dir / f"mission_snapshot-r{snapshot.revision:04d}.json"
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise MissionPresentationError(
            f"could not read immutable presentation source r{snapshot.revision:04d}: {exc}"
        ) from exc
    if payload != canonical_json_bytes(snapshot.to_dict()):
        raise MissionPresentationError(
            f"immutable presentation source r{snapshot.revision:04d} changed after validation"
        )
    return ArtifactReference.from_mapping(
        {
            "name": f"mission_snapshot_r{snapshot.revision:04d}",
            "path": f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json",
            "sha256": sha256_bytes(payload),
            "producer": "harbormaster",
            "byte_size": len(payload),
            "schema_version": snapshot.schema_version,
            "observed_at": snapshot.observed_at,
        }
    )


def _find_stage_event(
    history: tuple[MissionSnapshot, ...], stage_name: str
) -> MissionSnapshot:
    if stage_name == "oracle":
        for snapshot in history:
            stage = snapshot.stages[stage_name]
            if stage.status in _TERMINAL_STAGE_STATUSES and not stage.modeldock_calls:
                return snapshot
    for snapshot in history:
        if snapshot.stages[stage_name].status in _TERMINAL_STAGE_STATUSES:
            return snapshot
    for snapshot in reversed(history):
        if snapshot.stages[stage_name].status is StageStatus.RUNNING:
            return snapshot
    return history[-1]


def _find_modeldock_event(history: tuple[MissionSnapshot, ...]) -> MissionSnapshot:
    with_call = [
        snapshot for snapshot in history if snapshot.stages["oracle"].modeldock_calls
    ]
    for snapshot in with_call:
        if snapshot.stages["oracle"].modeldock_calls[-1].status in {
            ModelDockCallStatus.SUCCEEDED,
            ModelDockCallStatus.FAILED,
        }:
            return snapshot
    return with_call[-1] if with_call else history[-1]


def _find_operator_event(history: tuple[MissionSnapshot, ...]) -> MissionSnapshot:
    for desired in (
        OperatorActionStatus.SUCCEEDED,
        OperatorActionStatus.FAILED,
        OperatorActionStatus.RUNNING,
    ):
        for snapshot in history:
            if snapshot.operator.action_status is desired:
                return snapshot
    for snapshot in history:
        if snapshot.operator.route is not None:
            return snapshot
    return history[-1]


def _unique_sources(
    values: Iterable[ArtifactReference],
) -> tuple[ArtifactReference, ...]:
    by_path: dict[str, ArtifactReference] = {}
    for value in values:
        by_path.setdefault(value.path, value)
    return tuple(by_path.values())


def _stage_sources(
    loaded: LoadedMission,
    snapshot: MissionSnapshot,
    stage_name: str,
) -> tuple[ArtifactReference, ...]:
    artifact_by_name = {artifact.name: artifact for artifact in snapshot.artifacts}
    names = _CAPTAINS_LOG_STAGE_SOURCES[stage_name]
    return _unique_sources(
        (
            _snapshot_reference(loaded, snapshot),
            *(artifact_by_name[name] for name in names if name in artifact_by_name),
        )
    )


def _stage_summary(stage_name: str, snapshot: MissionSnapshot) -> str:
    display = stage_name.capitalize()
    stage = snapshot.stages[stage_name]
    if stage.status is StageStatus.NOT_STARTED:
        return f"No {display} result is recorded in the canonical mission."
    if stage.status is StageStatus.RUNNING:
        return f"{display} is recorded as technically RUNNING."
    if stage.status is StageStatus.FAILED:
        code = stage.error.code if stage.error is not None else "UNKNOWN_FAILURE"
        return f"{display} recorded a technical failure with code {code}."
    native = stage.native_state or "UNSPECIFIED"
    if stage_name == "governor":
        return (
            f"Governor returned rendered disposition {native}; this alone is not "
            "operator approval."
        )
    if stage_name == "navigator" and native == "CREATED":
        return (
            "Navigator created a SHADOW plan; no broker or order operation was "
            "authorized."
        )
    return f"{display} technically succeeded with native state {native}."


def _captains_log_mapping(loaded: LoadedMission) -> dict[str, object]:
    history = loaded.snapshot_history
    current = loaded.snapshot
    final_reference = _snapshot_reference(loaded, current)
    artifact_by_name = {artifact.name: artifact for artifact in current.artifacts}

    harbormaster_event = _find_stage_event(history, "harbormaster")
    oracle_event = _find_stage_event(history, "oracle")
    modeldock_event = _find_modeldock_event(history)
    council_event = _find_stage_event(history, "council")
    governor_event = _find_stage_event(history, "governor")
    operator_event = _find_operator_event(history)
    navigator_event = _find_stage_event(history, "navigator")

    modeldock_calls = modeldock_event.stages["oracle"].modeldock_calls
    if modeldock_calls:
        modeldock_call = modeldock_calls[-1]
        modeldock_status = modeldock_call.status.value
        modeldock_summary = (
            "ModelDock narrative enrichment technically succeeded."
            if modeldock_call.status is ModelDockCallStatus.SUCCEEDED
            else (
                "ModelDock narrative enrichment recorded a technical failure."
                if modeldock_call.status is ModelDockCallStatus.FAILED
                else "ModelDock narrative enrichment is recorded as RUNNING."
            )
        )
        modeldock_sources = _unique_sources(
            (
                _snapshot_reference(loaded, modeldock_event),
                *(
                    artifact_by_name[name]
                    for name in _CAPTAINS_LOG_MODELDOCK_SOURCES
                    if name in artifact_by_name
                ),
            )
        )
    else:
        modeldock_status = "NOT_RECORDED"
        modeldock_summary = "No ModelDock narrative call is recorded in the mission."
        modeldock_sources = (_snapshot_reference(loaded, modeldock_event),)

    operator = operator_event.operator
    if operator.action_status is OperatorActionStatus.SUCCEEDED:
        operator_status = (
            operator.result.value if operator.result is not None else "SUCCEEDED"
        )
        operator_summary = (
            f"Operator explicitly recorded result {operator_status}."
        )
    elif operator.action_status is OperatorActionStatus.FAILED:
        operator_status = "FAILED"
        code = operator.error.code if operator.error is not None else "UNKNOWN_FAILURE"
        operator_summary = f"Operator action recording failed with code {code}."
    elif operator.action_status is OperatorActionStatus.RUNNING:
        operator_status = "RUNNING"
        operator_summary = "An explicit operator action is recorded as RUNNING."
    elif operator.route is not None:
        operator_status = operator.route.value
        operator_summary = f"Operator routing is {operator.route.value}; no action is implied."
    else:
        operator_status = "NOT_STARTED"
        operator_summary = "No operator route or action is recorded in the mission."
    operator_sources = _unique_sources(
        (
            _snapshot_reference(loaded, operator_event),
            *(
                artifact_by_name[name]
                for name in _CAPTAINS_LOG_OPERATOR_SOURCES
                if name in artifact_by_name
            ),
        )
    )

    final_scope = (
        ""
        if current.approval_scope is None
        else f" Approval scope is {current.approval_scope.value}."
    )
    entries = [
        {
            "stage": "HARBORMASTER",
            "timestamp": harbormaster_event.observed_at,
            "status": harbormaster_event.stages["harbormaster"].status.value,
            "summary": "Harbormaster accepted and initialized the mission request.",
            "source_artifacts": [
                source.to_dict()
                for source in _stage_sources(
                    loaded, harbormaster_event, "harbormaster"
                )
            ],
        },
        {
            "stage": "ORACLE",
            "timestamp": oracle_event.observed_at,
            "status": oracle_event.stages["oracle"].status.value,
            "summary": _stage_summary("oracle", oracle_event),
            "source_artifacts": [
                source.to_dict()
                for source in _stage_sources(loaded, oracle_event, "oracle")
            ],
        },
        {
            "stage": "MODELDOCK",
            "timestamp": modeldock_event.observed_at,
            "status": modeldock_status,
            "summary": modeldock_summary,
            "source_artifacts": [source.to_dict() for source in modeldock_sources],
        },
        {
            "stage": "COUNCIL",
            "timestamp": council_event.observed_at,
            "status": council_event.stages["council"].status.value,
            "summary": _stage_summary("council", council_event),
            "source_artifacts": [
                source.to_dict()
                for source in _stage_sources(loaded, council_event, "council")
            ],
        },
        {
            "stage": "GOVERNOR",
            "timestamp": governor_event.observed_at,
            "status": governor_event.stages["governor"].status.value,
            "summary": _stage_summary("governor", governor_event),
            "source_artifacts": [
                source.to_dict()
                for source in _stage_sources(loaded, governor_event, "governor")
            ],
        },
        {
            "stage": "OPERATOR",
            "timestamp": operator_event.observed_at,
            "status": operator_status,
            "summary": operator_summary,
            "source_artifacts": [source.to_dict() for source in operator_sources],
        },
        {
            "stage": "NAVIGATOR",
            "timestamp": navigator_event.observed_at,
            "status": navigator_event.stages["navigator"].status.value,
            "summary": _stage_summary("navigator", navigator_event),
            "source_artifacts": [
                source.to_dict()
                for source in _stage_sources(loaded, navigator_event, "navigator")
            ],
        },
        {
            "stage": "MISSION",
            "timestamp": current.observed_at,
            "status": current.mission_outcome.value,
            "summary": f"Canonical mission outcome is {current.mission_outcome.value}.{final_scope}",
            "source_artifacts": [final_reference.to_dict()],
        },
    ]
    return {
        "schema_version": CAPTAINS_LOG_SCHEMA_VERSION,
        "mission_id": current.mission_id,
        "request_id": current.request_id,
        "symbol": loaded.request.symbol,
        "run_mode": current.run_mode.value,
        "generated_at": current.observed_at,
        "generated_from_snapshot": final_reference.to_dict(),
        "entries": entries,
    }


def _safe_warning(value: object, artifact_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise MissionPresentationError(
            f"{artifact_name} contains an invalid warning value"
        )
    if len(value) > 512 or any(ord(character) < 32 for character in value):
        raise MissionPresentationError(
            f"{artifact_name} warning exceeds the presentation safety envelope"
        )
    if (
        _ABSOLUTE_POSIX_PATH.search(value)
        or _ABSOLUTE_WINDOWS_PATH.search(value)
        or _SECRET_ASSIGNMENT.search(value)
    ):
        raise MissionPresentationError(
            f"{artifact_name} warning contains unsafe local or secret-like text"
        )
    return value


def _important_warnings(loaded: LoadedMission) -> tuple[str, ...]:
    values: list[str] = []
    current = loaded.snapshot
    for stage_name, stage in current.stages.items():
        if stage.error is not None:
            values.append(f"{stage_name.upper()}: {stage.error.code}")
    if current.operator.error is not None:
        values.append(f"OPERATOR: {current.operator.error.code}")

    artifact_by_name = {artifact.name: artifact for artifact in current.artifacts}
    for artifact_name, warning_fields in _KNOWN_WARNING_FIELDS.items():
        artifact = artifact_by_name.get(artifact_name)
        if artifact is None:
            continue
        relative = PurePosixPath(artifact.path)
        path = loaded.paths.mission_root.joinpath(*relative.parts)
        try:
            payload = load_strict_json_object(path)
        except (OSError, ValueError) as exc:
            raise MissionPresentationError(
                f"could not parse canonical warning artifact {artifact_name}: {exc}"
            ) from exc
        for field_name in warning_fields:
            if field_name not in payload:
                continue
            field_value = payload[field_name]
            if not isinstance(field_value, list):
                raise MissionPresentationError(
                    f"{artifact_name}.{field_name} must be an array"
                )
            values.extend(
                _safe_warning(item, artifact_name) for item in field_value
            )
            break
    return tuple(dict.fromkeys(values))


def _presentation_display_state(
    snapshot: MissionSnapshot, stage_name: str, modeldock_status: str
) -> str:
    if stage_name == "MODELDOCK":
        return modeldock_status
    if stage_name == "OPERATOR":
        if snapshot.operator.result is not None:
            return snapshot.operator.result.value
        if snapshot.operator.route is not None:
            return snapshot.operator.route.value
        return snapshot.operator.action_status.value
    canonical_name = stage_name.lower()
    stage = snapshot.stages[canonical_name]
    if stage_name == "GOVERNOR" and stage.native_state is not None:
        return stage.native_state
    if stage_name == "NAVIGATOR" and (
        snapshot.navigator.mode is not None
        and snapshot.navigator.plan_status is not None
    ):
        return (
            f"{snapshot.navigator.mode.value} PLAN "
            f"{snapshot.navigator.plan_status.value}"
        )
    return stage.status.value


def _mission_summary_mapping(
    loaded: LoadedMission, captain_log: CaptainsLog
) -> dict[str, object]:
    current = loaded.snapshot
    call = (
        current.stages["oracle"].modeldock_calls[-1]
        if current.stages["oracle"].modeldock_calls
        else None
    )
    modeldock = {
        "status": "NOT_RECORDED" if call is None else call.status.value,
        "provider": None if call is None else call.provider,
        "model": None if call is None else call.model,
        "trace_id": None if call is None else call.trace_id,
    }
    navigator = current.navigator
    return {
        "schema_version": MISSION_SUMMARY_SCHEMA_VERSION,
        "mission_id": current.mission_id,
        "request_id": current.request_id,
        "symbol": loaded.request.symbol,
        "run_mode": current.run_mode.value,
        "generated_at": current.observed_at,
        "generated_from_snapshot": _snapshot_reference(loaded, current).to_dict(),
        "current_phase": current.current_phase.value,
        "terminal": current.terminal,
        "stages": {
            name: {
                "technical_status": current.stages[name].status.value,
                "native_state": current.stages[name].native_state,
            }
            for name in current.stages
        },
        "modeldock": modeldock,
        "governor_disposition": current.stages["governor"].native_state,
        "operator": {
            "route": (
                None if current.operator.route is None else current.operator.route.value
            ),
            "action_status": current.operator.action_status.value,
            "action": (
                None if current.operator.action is None else current.operator.action.value
            ),
            "result": (
                None if current.operator.result is None else current.operator.result.value
            ),
        },
        "navigator": {
            "technical_status": current.stages["navigator"].status.value,
            "native_state": current.stages["navigator"].native_state,
            "mode": None if navigator.mode is None else navigator.mode.value,
            "handoff_status": (
                None
                if navigator.handoff_status is None
                else navigator.handoff_status.value
            ),
            "intake_status": (
                None if navigator.intake_status is None else navigator.intake_status.value
            ),
            "plan_status": (
                None if navigator.plan_status is None else navigator.plan_status.value
            ),
        },
        "approval_scope": (
            None if current.approval_scope is None else current.approval_scope.value
        ),
        "final_outcome": current.mission_outcome.value,
        "important_warnings": list(_important_warnings(loaded)),
        "snapshot_count": len(loaded.snapshot_history),
        "canonical_snapshot_path": "mission_snapshot.json",
        "display_title": f"BlackPod Mission: {loaded.request.symbol}",
        "subtitle": (
            f"{current.run_mode.value} | {current.mission_outcome.value} | "
            f"{current.current_phase.value}"
        ),
        "ordered_stages": [
            {
                "stage": entry.stage,
                "display_state": _presentation_display_state(
                    current, entry.stage, modeldock["status"]
                ),
                "summary": entry.summary,
                "artifact_paths": [
                    artifact.path for artifact in entry.source_artifacts
                ],
            }
            for entry in captain_log.entries[:-1]
        ],
        "resumable": not current.terminal,
        "event_count": len(captain_log.entries),
        "artifact_links": dict(MISSION_SUMMARY_ARTIFACT_LINKS),
    }


def _escape_markdown(value: str) -> str:
    for character in ("\\", "`", "*", "_", "{", "}", "[", "]", "<", ">"):
        value = value.replace(character, f"\\{character}")
    return value


def render_captains_log_markdown(log: CaptainsLog) -> bytes:
    """Render one byte-stable Markdown view from the validated JSON contract."""

    lines = [
        f"# Captain's Log: {_escape_markdown(log.mission_id)}",
        "",
        f"- Symbol: `{_escape_markdown(log.symbol)}`",
        f"- Mode: `{log.run_mode.value}`",
        f"- Source snapshot: `{log.generated_from_snapshot.path}`",
        "",
        "## Mission timeline",
        "",
    ]
    for entry in log.entries:
        lines.extend(
            [
                f"### {entry.stage}",
                "",
                f"- Timestamp: `{entry.timestamp}`",
                f"- Status: `{entry.status}`",
                "",
                _escape_markdown(entry.summary),
                "",
                "Sources:",
                "",
                *(
                    f"- `{source.path}` — `{source.sha256}`"
                    for source in entry.source_artifacts
                ),
                "",
            ]
        )
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


_MISSION_BRIEF_CSS = """
:root {
  color-scheme: dark;
  --bg: #071019;
  --panel: #0d1a26;
  --panel-2: #122334;
  --line: #274056;
  --text: #edf5fb;
  --muted: #9db0c0;
  --accent: #70d6ff;
  --good: #68e0a5;
  --warn: #ffd166;
  --bad: #ff7b86;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: linear-gradient(160deg, #071019 0%, #0a1621 55%, #08121b 100%);
  color: var(--text);
  font: 16px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--accent); }
code { overflow-wrap: anywhere; }
.shell { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 56px; }
.eyebrow { color: var(--accent); font-size: .76rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }
.hero { display: flex; gap: 24px; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
h1 { font-size: clamp(2rem, 5vw, 3.6rem); line-height: 1.03; margin: 8px 0 10px; }
h2 { margin: 0 0 16px; font-size: 1.3rem; }
h3 { margin: 0; font-size: 1rem; }
p { margin: 8px 0; }
.subtitle, .muted { color: var(--muted); }
.outcome { border: 1px solid var(--line); border-radius: 999px; padding: 9px 15px; font-weight: 800; white-space: nowrap; }
.outcome-approved { border-color: var(--good); color: var(--good); }
.outcome-held, .outcome-incomplete { border-color: var(--warn); color: var(--warn); }
.outcome-vetoed, .outcome-failed { border-color: var(--bad); color: var(--bad); }
.safety { border: 1px solid #315d6f; border-radius: 14px; background: #0c2630; padding: 16px 18px; margin: 20px 0 28px; }
.safety strong { color: #9ee8ff; }
.section { margin-top: 28px; }
.stages { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 10px; }
.stage { min-width: 0; border: 1px solid var(--line); border-top-width: 4px; border-radius: 12px; background: var(--panel); padding: 13px; }
.stage-complete { border-top-color: var(--good); }
.stage-running { border-top-color: var(--accent); }
.stage-failed { border-top-color: var(--bad); }
.stage-pending { border-top-color: #64798a; }
.stage-state { color: var(--muted); font: 700 .73rem/1.3 ui-monospace, SFMono-Regular, Consolas, monospace; margin: 5px 0 12px; overflow-wrap: anywhere; }
.stage p { font-size: .87rem; }
.grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 18px; }
.card { border: 1px solid var(--line); border-radius: 14px; background: var(--panel); padding: 18px; }
.gates { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 14px; }
.gate { background: var(--panel-2); border-radius: 10px; padding: 12px; }
.gate span { display: block; color: var(--muted); font-size: .75rem; letter-spacing: .08em; text-transform: uppercase; }
.gate strong { display: block; margin-top: 5px; overflow-wrap: anywhere; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 7px 14px; margin: 12px 0 0; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.timeline { list-style: none; padding: 0; margin: 0; border-left: 1px solid var(--line); }
.timeline li { margin-left: 17px; padding: 0 0 20px 18px; position: relative; }
.timeline li::before { content: ""; position: absolute; width: 9px; height: 9px; left: -23px; top: 7px; border-radius: 50%; background: var(--accent); }
.timeline-head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.status { color: var(--accent); font: 700 .78rem ui-monospace, SFMono-Regular, Consolas, monospace; }
.timestamp { color: var(--muted); font-size: .78rem; }
details { margin-top: 10px; }
summary { color: var(--accent); cursor: pointer; font-size: .84rem; }
.evidence { padding-left: 20px; font-size: .78rem; color: var(--muted); }
.evidence li { margin: 6px 0; }
.warnings { padding-left: 20px; }
.warnings li { margin: 6px 0; color: var(--warn); }
.operations { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.operations ul { margin-bottom: 0; }
.canonical { border-style: dashed; }
.source-links { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; }
.authority { margin-top: 30px; color: var(--muted); font-size: .84rem; text-align: center; }
@media (max-width: 900px) {
  .stages { grid-template-columns: repeat(2, 1fr); }
  .grid, .operations { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .shell { width: min(100% - 20px, 1120px); padding-top: 24px; }
  .hero { display: block; }
  .outcome { display: inline-block; margin-top: 8px; }
  .stages, .gates { grid-template-columns: 1fr; }
}
""".strip()


_BRIEF_STAGE_LABELS = {
    "HARBORMASTER": "Harbormaster",
    "ORACLE": "Oracle",
    "MODELDOCK": "ModelDock",
    "COUNCIL": "Council",
    "GOVERNOR": "Governor",
    "OPERATOR": "Operator",
    "NAVIGATOR": "Navigator",
}


def _brief_text(value: object) -> str:
    return escape(str(value), quote=True)


def _brief_href(path: str) -> str:
    relative = PurePosixPath(path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(part in {"", "."} for part in relative.parts)
        or relative.as_posix() != path
    ):
        raise MissionPresentationError(
            f"mission brief source path is not mission-relative: {path!r}"
        )
    if relative.parts[0] == "presentation":
        target = PurePosixPath(*relative.parts[1:])
    else:
        target = PurePosixPath("..", *relative.parts)
    return escape(quote(target.as_posix(), safe="/-._~"), quote=True)


def _brief_artifact_link(path: str) -> str:
    return f'<a href="{_brief_href(path)}"><code>{_brief_text(path)}</code></a>'


def _brief_stage_technical_status(summary: MissionSummary, stage_name: str) -> str:
    if stage_name == "MODELDOCK":
        return summary.modeldock.status
    if stage_name == "OPERATOR":
        return summary.operator.action_status.value
    return summary.stages[stage_name.lower()].technical_status.value


def _brief_stage_class(technical_status: str) -> str:
    if technical_status == "FAILED":
        return "failed"
    if technical_status == "RUNNING":
        return "running"
    if technical_status in {"NOT_STARTED", "NOT_RECORDED", "SKIPPED"}:
        return "pending"
    return "complete"


def _render_brief_stages(summary: MissionSummary) -> str:
    cards: list[str] = []
    for stage in summary.ordered_stages:
        technical_status = _brief_stage_technical_status(summary, stage.stage)
        evidence = "\n".join(
            f"<li>{_brief_artifact_link(path)}</li>" for path in stage.artifact_paths
        )
        cards.append(
            "\n".join(
                (
                    f'<article class="stage stage-{_brief_stage_class(technical_status)}">',
                    f"<h3>{_brief_text(_BRIEF_STAGE_LABELS[stage.stage])}</h3>",
                    f'<div class="stage-state">{_brief_text(stage.display_state)}</div>',
                    f"<p>{_brief_text(stage.summary)}</p>",
                    "<details>",
                    f"<summary>Evidence ({len(stage.artifact_paths)})</summary>",
                    f'<ul class="evidence">{evidence}</ul>',
                    "</details>",
                    "</article>",
                )
            )
        )
    return "\n".join(cards)


def _render_brief_timeline(log: CaptainsLog) -> str:
    entries: list[str] = []
    for entry in log.entries:
        sources = "\n".join(
            "<li>"
            + _brief_artifact_link(source.path)
            + f' <span class="muted">sha256 {_brief_text(source.sha256)}</span></li>'
            for source in entry.source_artifacts
        )
        entries.append(
            "\n".join(
                (
                    "<li>",
                    '<div class="timeline-head">',
                    f"<strong>{_brief_text(entry.stage)}</strong>",
                    f'<span class="status">{_brief_text(entry.status)}</span>',
                    f'<span class="timestamp">{_brief_text(entry.timestamp)}</span>',
                    "</div>",
                    f"<p>{_brief_text(entry.summary)}</p>",
                    "<details>",
                    f"<summary>Source evidence ({len(entry.source_artifacts)})</summary>",
                    f'<ul class="evidence">{sources}</ul>',
                    "</details>",
                    "</li>",
                )
            )
        )
    return "\n".join(entries)


def render_mission_brief_html(
    summary: MissionSummary,
    log: CaptainsLog,
) -> bytes:
    """Render a deterministic, read-only HTML view from canonical JSON contracts."""

    if (
        summary.mission_id != log.mission_id
        or summary.request_id != log.request_id
        or summary.symbol != log.symbol
        or summary.run_mode is not log.run_mode
        or summary.generated_at != log.generated_at
        or summary.generated_from_snapshot != log.generated_from_snapshot
    ):
        raise MissionPresentationError(
            "mission brief sources contain inconsistent mission correlation"
        )

    governor = summary.governor_disposition or "NOT REACHED"
    operator = (
        summary.operator.result.value
        if summary.operator.result is not None
        else (
            summary.operator.route.value
            if summary.operator.route is not None
            else summary.operator.action_status.value
        )
    )
    navigator = (
        f"{summary.navigator.mode.value} PLAN {summary.navigator.plan_status.value}"
        if summary.navigator.mode is not None
        and summary.navigator.plan_status is not None
        else (
            summary.navigator.native_state
            or summary.navigator.technical_status.value
        )
    )
    if summary.run_mode.value == "REPLAY":
        modeldock_note = (
            "Validated replay fixture; no network call."
            if summary.modeldock.status == "SUCCEEDED"
            else "No live ModelDock call is made in REPLAY mode."
        )
    else:
        modeldock_note = (
            "Validated local ModelDock narrative response."
            if summary.modeldock.status == "SUCCEEDED"
            else "No validated ModelDock narrative response is recorded."
        )
    warnings = (
        "\n".join(
            f"<li><code>{_brief_text(warning)}</code></li>"
            for warning in summary.important_warnings
        )
        if summary.important_warnings
        else '<li class="muted">No important warnings recorded.</li>'
    )
    allowed = "\n".join(
        f"<li><code>{_brief_text(operation)}</code></li>"
        for operation in NAVIGATOR_ALLOWED_OPERATIONS
    )
    prohibited = "\n".join(
        f"<li><code>{_brief_text(operation)}</code></li>"
        for operation in NAVIGATOR_PROHIBITED_OPERATIONS
    )
    approval_scope = (
        "NONE" if summary.approval_scope is None else summary.approval_scope.value
    )
    modeldock_values = {
        "Provider": summary.modeldock.provider or "NOT RECORDED",
        "Model": summary.modeldock.model or "NOT RECORDED",
        "Trace": summary.modeldock.trace_id or "NOT RECORDED",
    }
    modeldock_facts = "\n".join(
        f"<dt>{_brief_text(label)}</dt><dd><code>{_brief_text(value)}</code></dd>"
        for label, value in modeldock_values.items()
    )
    source_links = "\n".join(
        (
            f'<a href="{_brief_href(MISSION_SUMMARY_PATH)}">Mission summary JSON</a>',
            f'<a href="{_brief_href(CAPTAINS_LOG_PATH)}">Captain\'s Log JSON</a>',
            f'<a href="{_brief_href(CAPTAINS_LOG_MARKDOWN_PATH)}">Captain\'s Log Markdown</a>',
            f'<a href="{_brief_href(summary.canonical_snapshot_path)}">Canonical snapshot JSON</a>',
        )
    )
    outcome_class = summary.final_outcome.value.lower().replace("_", "-")
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'">
<meta name="referrer" content="no-referrer">
<title>{_brief_text(summary.display_title)}</title>
<style>{_MISSION_BRIEF_CSS}</style>
</head>
<body>
<main class="shell">
<header class="hero">
<div>
<div class="eyebrow">BlackPod Battlestar · Mission brief</div>
<h1>{_brief_text(summary.display_title)}</h1>
<p class="subtitle">{_brief_text(summary.subtitle)} · Mission {_brief_text(summary.mission_id)}</p>
</div>
<div class="outcome outcome-{_brief_text(outcome_class)}">{_brief_text(summary.final_outcome.value)}</div>
</header>

<section class="safety" aria-label="Safety boundary">
<strong>Navigator SHADOW handoff only — no trade or order execution.</strong>
<p>Governor <code>PROCEED</code> is not approval. Approval scope: <code>{_brief_text(approval_scope)}</code>.</p>
</section>

<section class="section" aria-labelledby="progress-title">
<h2 id="progress-title">Mission progression</h2>
<div class="stages">{_render_brief_stages(summary)}</div>
</section>

<section class="section grid" aria-label="Decision and ModelDock evidence">
<article class="card">
<h2>Explicit decision gate</h2>
<p class="muted">Canonical progression keeps Governor disposition, operator approval, and Navigator planning separate.</p>
<div class="gates">
<div class="gate"><span>Governor</span><strong>{_brief_text(governor)}</strong></div>
<div class="gate"><span>Operator</span><strong>{_brief_text(operator)}</strong></div>
<div class="gate"><span>Navigator</span><strong>{_brief_text(navigator)}</strong></div>
</div>
</article>
<article class="card">
<h2>ModelDock narrative</h2>
<p><strong>{_brief_text(summary.modeldock.status)}</strong> — {_brief_text(modeldock_note)}</p>
<p class="muted">Narrative only. Oracle remains authoritative for facts, measurements, diagnostics, and readiness.</p>
<dl class="facts">{modeldock_facts}</dl>
</article>
</section>

<section class="section grid" aria-label="Warnings and safety operations">
<article class="card">
<h2>Important warnings</h2>
<ul class="warnings">{warnings}</ul>
</article>
<article class="card operations">
<div><h3>Allowed operations</h3><ul>{allowed}</ul></div>
<div><h3>Prohibited operations</h3><ul>{prohibited}</ul></div>
</article>
</section>

<section class="section card" aria-labelledby="log-title">
<h2 id="log-title">Captain's Log</h2>
<p class="muted">{summary.event_count} canonical log entries · {summary.snapshot_count} immutable snapshots</p>
<ol class="timeline">{_render_brief_timeline(log)}</ol>
</section>

<section class="section card canonical" aria-labelledby="evidence-title">
<h2 id="evidence-title">Canonical evidence</h2>
<p>This HTML is a deterministic, read-only projection. The JSON contracts and immutable snapshot chain remain authoritative.</p>
<dl class="facts">
<dt>Source revision</dt><dd>{_brief_artifact_link(summary.generated_from_snapshot.path)}</dd>
<dt>Source SHA-256</dt><dd><code>{_brief_text(summary.generated_from_snapshot.sha256)}</code></dd>
<dt>Generated at</dt><dd><code>{_brief_text(summary.generated_at)}</code></dd>
<dt>Resumable</dt><dd><code>{_brief_text(str(summary.resumable).lower())}</code></dd>
</dl>
<nav class="source-links" aria-label="Canonical presentation sources">{source_links}</nav>
</section>

<footer class="authority">No controls, approvals, broker calls, or execution operations exist in this presentation.</footer>
</main>
</body>
</html>
"""
    return document.encode("utf-8")


def render_mission_presentation(
    store: MissionStore, loaded: LoadedMission
) -> MissionPresentationResult:
    """Validate, deterministically derive, and atomically publish presentation views."""

    history = loaded.snapshot_history
    if (
        not history
        or len(history) != loaded.snapshot.revision
        or history[-1] != loaded.snapshot
        or loaded.request.mission_id != loaded.snapshot.mission_id
    ):
        raise MissionPresentationError(
            "loaded mission does not contain a complete canonical snapshot history"
        )

    captain_log = CaptainsLog.from_mapping(_captains_log_mapping(loaded))
    mission_summary = MissionSummary.from_mapping(
        _mission_summary_mapping(loaded, captain_log)
    )
    captain_log_bytes = canonical_json_bytes(captain_log.to_dict())
    captain_markdown_bytes = render_captains_log_markdown(captain_log)
    mission_summary_bytes = canonical_json_bytes(mission_summary.to_dict())
    mission_brief_bytes = render_mission_brief_html(mission_summary, captain_log)

    log_json_write = store.write_presentation_artifact(
        loaded.snapshot.mission_id,
        relative_path=CAPTAINS_LOG_PATH,
        payload=captain_log_bytes,
    )
    log_markdown_write = store.write_presentation_artifact(
        loaded.snapshot.mission_id,
        relative_path=CAPTAINS_LOG_MARKDOWN_PATH,
        payload=captain_markdown_bytes,
    )
    summary_write = store.write_presentation_artifact(
        loaded.snapshot.mission_id,
        relative_path=MISSION_SUMMARY_PATH,
        payload=mission_summary_bytes,
    )
    brief_write = store.write_presentation_artifact(
        loaded.snapshot.mission_id,
        relative_path=MISSION_BRIEF_PATH,
        payload=mission_brief_bytes,
    )
    return MissionPresentationResult(
        captain_log=captain_log,
        mission_summary=mission_summary,
        captains_log_json_path=log_json_write.path,
        captains_log_markdown_path=log_markdown_write.path,
        mission_summary_path=summary_write.path,
        mission_brief_path=brief_write.path,
        captains_log_json_written=log_json_write.written,
        captains_log_markdown_written=log_markdown_write.written,
        mission_summary_written=summary_write.written,
        mission_brief_written=brief_write.written,
    )
