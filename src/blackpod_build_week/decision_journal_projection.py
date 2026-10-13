"""Read-only mission verification and pure, passive journal projection.

No stage workflow, provider, model or execution adapter is imported here.  The
loader captures only canonical mission evidence; projection operates entirely
on those captured bytes and never consults the source filesystem.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .contracts import MissionRequest, MissionSnapshot
from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import (
    ContractValidationError,
    parse_strict_json_object_bytes,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError, _directory, read_regular


MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024


class HistoryVerificationError(ValueError):
    """Mission evidence is incomplete, changed during capture or unsafe."""


@dataclass(frozen=True, slots=True)
class VerifiedHistory:
    """Immutable capture with defensive copies of native mission contracts.

    ``mission_snapshot.json`` is verified as the current pointer but is not
    retained as evidence: its replacement during mission growth must not alter
    evidence identity.  Each event references its immutable revision instead.
    """

    source_root: Path
    _request_bytes: bytes
    _snapshot_bytes: tuple[bytes, ...]
    source_files: Mapping[str, bytes]

    def __post_init__(self) -> None:
        snapshots = tuple(self._snapshot_bytes)
        files = dict(self.source_files)
        if not isinstance(self._request_bytes, bytes) or not snapshots or any(not isinstance(raw, bytes) for raw in snapshots):
            raise HistoryVerificationError("captured request and snapshots must be immutable bytes")
        for path, raw in files.items():
            if not isinstance(path, str) or not isinstance(raw, bytes):
                raise HistoryVerificationError("captured source files must map relative paths to immutable bytes")
            _relative_path(path)
        object.__setattr__(self, "_snapshot_bytes", snapshots)
        object.__setattr__(self, "source_files", MappingProxyType(files))

    @property
    def request(self) -> MissionRequest:
        return MissionRequest.from_mapping(_json(self._request_bytes))

    @property
    def snapshot_history(self) -> tuple[MissionSnapshot, ...]:
        return tuple(MissionSnapshot.from_mapping(_json(raw)) for raw in self._snapshot_bytes)


def _json(payload: bytes) -> dict[str, Any]:
    try:
        return parse_strict_json_object_bytes(payload)
    except RecursionError as exc:
        raise HistoryVerificationError("source JSON nesting exceeds safe parsing depth") from exc


def _safe_existing(path: Path, *, directory: bool = False) -> os.stat_result:
    """Reject linked files and linked ancestors before any source reads."""

    if not path.is_absolute():
        raise HistoryVerificationError("source paths must be absolute")
    for ancestor in reversed(path.parents):
        try:
            details = ancestor.lstat()
        except OSError as exc:
            raise HistoryVerificationError(f"source ancestor is missing: {ancestor}") from exc
        if not stat.S_ISDIR(details.st_mode):
            raise HistoryVerificationError(f"source ancestor is not an unlinked directory: {ancestor}")
    try:
        details = path.lstat()
    except OSError as exc:
        raise HistoryVerificationError(f"source evidence is missing: {path}") from exc
    if directory:
        if not stat.S_ISDIR(details.st_mode):
            raise HistoryVerificationError(f"source directory is unsafe: {path}")
    elif not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise HistoryVerificationError(f"source evidence must be an unlinked regular file: {path}")
    return details


def _fingerprint(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev,
        details.st_ino,
        details.st_mode,
        details.st_nlink,
        details.st_size,
        details.st_mtime_ns,
        details.st_ctime_ns,
    )


def _capture_file(path: Path) -> tuple[bytes, tuple[int, ...]]:
    before = _safe_existing(path)
    try:
        # Anchored O_NOFOLLOW directory descriptors reject ancestor swaps as
        # well as final-file links.  This existing helper performs bounded,
        # stable reads and rejects devices and multiply linked files.
        payload = read_regular(path, max_bytes=MAX_SOURCE_FILE_BYTES)
    except RecoveryError as exc:
        raise HistoryVerificationError(f"could not capture source evidence: {path}: {exc}") from exc
    after = _safe_existing(path)
    if _fingerprint(before) != _fingerprint(after) or len(payload) != after.st_size:
        raise HistoryVerificationError(f"source changed during capture: {path}")
    return payload, _fingerprint(after)


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise HistoryVerificationError(f"unsafe source evidence path: {value!r}")
    return value


def _snapshot_names(root: Path) -> tuple[str, ...]:
    directory = root / "snapshots"
    _safe_existing(directory, directory=True)
    descriptor = None
    try:
        descriptor = _directory(directory)
        return tuple(sorted(os.listdir(descriptor)))
    except (RecoveryError, OSError) as exc:
        raise HistoryVerificationError("snapshot directory cannot be inspected safely") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_verified_history(source_root: Path) -> VerifiedHistory:
    """Capture a complete existing mission, without creating or changing files.

    Verification uses the existing mission contracts and MissionStore lineage rules,
    checks every revision's artifacts, and compares stable before/after captures
    to reject concurrent changes.  Only declared evidence is retained.
    """

    root = Path(os.path.abspath(Path(source_root).expanduser()))
    _safe_existing(root, directory=True)
    if root.parent.name != "missions":
        raise HistoryVerificationError("source_root must be an exact mission directory beneath missions/")
    initial_names = _snapshot_names(root)
    captured: dict[str, tuple[bytes, tuple[int, ...]]] = {}

    def capture(relative: str) -> bytes:
        relative = _relative_path(relative)
        if relative not in captured:
            captured[relative] = _capture_file(root / relative)
        return captured[relative][0]

    try:
        current_bytes = capture("mission_snapshot.json")
        current = MissionSnapshot.from_mapping(_json(current_bytes))
        request_bytes = capture("request/mission_request.json")
        request = MissionRequest.from_mapping(_json(request_bytes))
        if current.revision != len(initial_names):
            raise HistoryVerificationError("missing, future or stray immutable snapshot revision")
        expected_names = tuple(sorted(
            f"mission_snapshot-r{revision:04d}.json"
            for revision in range(1, current.revision + 1)
        ))
        if initial_names != expected_names:
            raise HistoryVerificationError("missing, future or stray immutable snapshot revision")
        snapshots: list[MissionSnapshot] = []
        revision_bytes: list[bytes] = []
        for revision in range(1, current.revision + 1):
            relative = f"snapshots/mission_snapshot-r{revision:04d}.json"
            raw = capture(relative)
            snapshot = MissionSnapshot.from_mapping(_json(raw))
            if (
                snapshot.mission_id != root.name
                or snapshot.mission_id != request.mission_id
                or snapshot.request_id != request.request_id
                or snapshot.run_mode is not request.run_mode
            ):
                raise HistoryVerificationError("revision correlation does not match stored request")
            for artifact in snapshot.artifacts:
                raw_artifact = capture(artifact.path)
                if sha256_bytes(raw_artifact) != artifact.sha256:
                    raise HistoryVerificationError(f"source artifact hash mismatch: {artifact.path}")
                if artifact.byte_size is not None and len(raw_artifact) != artifact.byte_size:
                    raise HistoryVerificationError(f"source artifact size mismatch: {artifact.path}")
            request_refs = [a for a in snapshot.artifacts if a.name == "mission_request"]
            if len(request_refs) != 1 or (
                request_refs[0].path != "request/mission_request.json"
                or request_refs[0].sha256 != sha256_bytes(request_bytes)
            ):
                raise HistoryVerificationError("revision must retain the verified mission request")
            snapshots.append(snapshot)
            revision_bytes.append(raw)
        if revision_bytes[-1] != current_bytes:
            raise HistoryVerificationError("current snapshot does not match immutable latest revision")

        # Apply MissionStore's revision continuity checks over captured bytes.
        # Calling its usual load method would create directories and perform
        # ordinary path reads, neither of which belongs in this offline import.
        previous_snapshot = None
        previous_digest = None
        for revision, (snapshot, raw) in enumerate(zip(snapshots, revision_bytes), 1):
            if snapshot.revision != revision or snapshot.previous_snapshot_sha256 != previous_digest:
                raise HistoryVerificationError("immutable snapshot revision hash chain is invalid")
            if snapshot.started_at != snapshots[0].started_at:
                raise HistoryVerificationError("snapshot identity changed across revisions")
            if previous_snapshot is not None:
                artifacts = {artifact.name: artifact for artifact in snapshot.artifacts}
                for artifact in previous_snapshot.artifacts:
                    if artifacts.get(artifact.name) != artifact:
                        raise HistoryVerificationError("snapshot history removed or changed artifact")
                for name, component in previous_snapshot.components.items():
                    if snapshot.components.get(name) != component:
                        raise HistoryVerificationError("snapshot history changed component provenance")
            previous_snapshot = snapshot
            previous_digest = sha256_bytes(raw)
        for relative, original in captured.items():
            if _capture_file(root / relative) != original:
                raise HistoryVerificationError(f"source changed during verification: {relative}")
        if _snapshot_names(root) != initial_names:
            raise HistoryVerificationError("snapshot history changed during verification")
    except (ContractValidationError, OSError) as exc:
        raise HistoryVerificationError(f"mission history verification failed: {exc}") from exc

    retained = {relative: raw for relative, (raw, _) in captured.items() if relative != "mission_snapshot.json"}
    return VerifiedHistory(root, request_bytes, tuple(revision_bytes), retained)


def _artifact_json(history: VerifiedHistory, snapshot: MissionSnapshot, name: str) -> dict[str, Any] | None:
    references = [artifact for artifact in snapshot.artifacts if artifact.name == name]
    if not references:
        return None
    return _json(history.source_files[references[0].path])


def _validate_captured_evidence(history: VerifiedHistory, snapshot: MissionSnapshot, raw_snapshot: bytes) -> None:
    revision_path = f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json"
    if history.source_files.get(revision_path) != raw_snapshot:
        raise HistoryVerificationError("captured revision bytes disagree with the projected snapshot")
    if history.source_files.get("request/mission_request.json") != history._request_bytes:
        raise HistoryVerificationError("captured request bytes disagree with the projected request")
    for artifact in snapshot.artifacts:
        raw = history.source_files.get(artifact.path)
        if raw is None or sha256_bytes(raw) != artifact.sha256:
            raise HistoryVerificationError(f"captured artifact hash mismatch: {artifact.path}")
        if artifact.byte_size is not None and len(raw) != artifact.byte_size:
            raise HistoryVerificationError(f"captured artifact size mismatch: {artifact.path}")


def _decision(history: VerifiedHistory, snapshot: MissionSnapshot) -> dict[str, Any]:
    disposition = snapshot.stages["governor"].native_state
    native = _artifact_json(history, snapshot, "governor_decision")
    decision_id = None
    if native is not None:
        decision_id = native.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id.strip():
            raise HistoryVerificationError("native Governor decision lacks recorded identity")
        if native.get("decision_state") != disposition:
            raise HistoryVerificationError("native Governor disposition disagrees with snapshot")
    return {"disposition": disposition, "authority": None if disposition is None else "GOVERNOR", "decision_id": decision_id}


def _authorization(history: VerifiedHistory, snapshot: MissionSnapshot) -> dict[str, Any]:
    result = snapshot.operator.result
    if result is None:
        return {"status": "NOT_RECORDED", "scope": None, "operator_id": None, "action_id": None}
    native = _artifact_json(history, snapshot, "operator_action")
    if native is not None and (
        native.get("action_id") != snapshot.operator.action_id
        or native.get("operator_id") != snapshot.operator.operator_id
        or native.get("source_run_id") != snapshot.mission_id
        or native.get("resulting_status") != result.value
        or native.get("action") != snapshot.operator.action.value
    ):
        raise HistoryVerificationError("native operator action disagrees with snapshot")
    return {
        "status": "SHADOW_APPROVED" if result.value == "APPROVED_FOR_HANDOFF" else "REJECTED",
        "scope": None if snapshot.approval_scope is None else snapshot.approval_scope.value,
        "operator_id": snapshot.operator.operator_id,
        "action_id": snapshot.operator.action_id,
    }


def _execution_status(history: VerifiedHistory, snapshot: MissionSnapshot) -> str:
    if snapshot.navigator.plan_status is None:
        return "NOT_EXECUTED"
    native = _artifact_json(history, snapshot, "navigator_shadow_plan")
    expected_constraints = {
        "mode": "SHADOW",
        "allowed_operations": ["VALIDATE", "PLAN_ONLY"],
        "prohibited_operations": ["SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL"],
    }
    if native is None or (
        native.get("schema_version") != "navigator_shadow_plan.v1"
        or native.get("planning_status") != "CREATED"
        or native.get("plan_id") != snapshot.navigator.plan_id
        or native.get("handoff_id") != snapshot.navigator.handoff_id
        or native.get("source_run_id") != snapshot.mission_id
        or native.get("validated_constraints") != expected_constraints
        or native.get("prohibited_operations") != expected_constraints["prohibited_operations"]
    ):
        raise HistoryVerificationError("recorded Navigator plan lacks verified SHADOW constraints")
    refs, hashes = native.get("source_artifact_refs"), native.get("source_artifact_hashes")
    if not isinstance(refs, dict) or not isinstance(hashes, dict) or set(refs) != set(hashes):
        raise HistoryVerificationError("Navigator plan lacks matching source references and hashes")
    artifacts_by_path = {artifact.path: artifact for artifact in snapshot.artifacts}
    for key, path in refs.items():
        if (
            not isinstance(path, str)
            or not isinstance(hashes[key], str)
            or path not in artifacts_by_path
            or artifacts_by_path[path].sha256 != hashes[key]
        ):
            raise HistoryVerificationError("Navigator plan source lineage is not declared verified evidence")
    return "SHADOW_ONLY"


def project_history(
    history: VerifiedHistory,
    domain: str = "UNCLASSIFIED",
    classification_reason: str | None = None,
) -> tuple[JournalEvent, ...]:
    """Pure projection preserving dispositions without conferring authority."""

    if domain not in {"TRADING", "INVESTMENT", "CAPITAL_ALLOCATION", "UNCLASSIFIED"}:
        raise ContractValidationError(f"unsupported journal domain: {domain!r}")
    if classification_reason is not None and (
        not isinstance(classification_reason, str)
        or not classification_reason.strip()
        or classification_reason != classification_reason.strip()
    ):
        raise ContractValidationError("classification_reason must be nonblank trimmed text")
    if domain != "UNCLASSIFIED" and classification_reason is None:
        raise ContractValidationError("classified historical imports require an explicit classification reason")
    request = history.request
    decision_id = "journal-decision-" + sha256_bytes(canonical_json_bytes({
        "kind": "MISSION", "mission_id": request.mission_id,
        "request_id": request.request_id, "run_mode": request.run_mode.value,
    }))
    events: list[JournalEvent] = []
    for snapshot, raw_snapshot in zip(history.snapshot_history, history._snapshot_bytes):
        _validate_captured_evidence(history, snapshot, raw_snapshot)
        event_type = "MISSION_SNAPSHOT_RECORDED"
        revision_path = f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json"
        evidence_paths = {"request/mission_request.json", revision_path}
        evidence_paths.update(artifact.path for artifact in snapshot.artifacts)
        event_id = "journal-event-" + sha256_bytes(canonical_json_bytes({
            "decision_id": decision_id, "event_type": event_type, "revision": snapshot.revision,
        }))
        events.append(JournalEvent.from_mapping({
            "schema_version": "blackpod.decision_journal_event.v1",
            "event_id": event_id,
            "decision_id": decision_id,
            "domain": domain,
            "event_type": event_type,
            "recorded_at": snapshot.observed_at,
            "source": {
                "kind": "MISSION", "mission_id": snapshot.mission_id,
                "request_id": snapshot.request_id, "run_mode": snapshot.run_mode.value,
                "revision": snapshot.revision,
                "source_sha256": sha256_bytes(history.source_files[revision_path]),
            },
            "evidence": [{
                "path": path, "sha256": sha256_bytes(history.source_files[path]),
                "size_bytes": len(history.source_files[path]),
            } for path in sorted(evidence_paths)],
            "payload": {
                "classification": {
                    "basis": "HISTORICAL_UNCLASSIFIED" if domain == "UNCLASSIFIED" else "EXPLICIT_IMPORT_CLASSIFICATION",
                    "reason": classification_reason or "Historical mission has no recorded desk classification.",
                },
                "symbol": request.symbol,
                "mission_outcome": snapshot.mission_outcome.value,
                "current_phase": snapshot.current_phase.value,
                "terminal": snapshot.terminal,
                "stages": [{"name": name, "status": stage.status.value, "native_state": stage.native_state}
                           for name, stage in sorted(snapshot.stages.items())],
                "decision": _decision(history, snapshot),
                "authorization": _authorization(history, snapshot),
                "execution_status": _execution_status(history, snapshot),
                "historical_semantics": {field: "NOT_RECORDED" for field in (
                    "hypothesis", "expectations", "investment_horizon", "confidence_probability", "evaluation",
                )},
            },
        }))
    return tuple(events)
