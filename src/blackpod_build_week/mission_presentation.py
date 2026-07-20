"""Deterministic Captain's Log and mission-summary projection generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .contracts import (
    CAPTAINS_LOG_MARKDOWN_PATH,
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_ARTIFACT_LINKS,
    MISSION_SUMMARY_SCHEMA_VERSION,
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
    captains_log_json_written: bool
    captains_log_markdown_written: bool
    mission_summary_written: bool


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
    return MissionPresentationResult(
        captain_log=captain_log,
        mission_summary=mission_summary,
        captains_log_json_path=log_json_write.path,
        captains_log_markdown_path=log_markdown_write.path,
        mission_summary_path=summary_write.path,
        captains_log_json_written=log_json_write.written,
        captains_log_markdown_written=log_markdown_write.written,
        mission_summary_written=summary_write.written,
    )
