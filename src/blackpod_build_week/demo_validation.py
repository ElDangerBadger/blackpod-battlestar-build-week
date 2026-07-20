"""Strict validation for committed replay packs and generated demo missions.

The module deliberately does not import the demo workflow.  The operator-facing
``validate-demo-packs`` command can inject its runner, while this boundary owns
only validation of committed inputs and canonical mission output.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import (
    CAPTAINS_LOG_MARKDOWN_PATH,
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    CANONICAL_SNAPSHOT_PATH,
    DEMO_MANIFEST_PATH,
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ArtifactReference,
    CaptainsLog,
    DemoManifest,
    DemoModelDockMode,
    DemoScenario,
    MissionOutcome,
    MissionSummary,
    ModelDockCallStatus,
    NavigatorMode,
)
from .contracts.mission_request import (
    ContractValidationError,
    load_strict_json_object,
)
from .demo_catalog import (
    DemoCatalog,
    DemoScenarioSpec,
    ResolvedDemoScenario,
    load_demo_catalog,
)
from .hashing import canonical_json_bytes, sha256_file
from .mission_presentation import render_captains_log_markdown
from .mission_store import LoadedMission, MissionStore, MissionStoreError


class DemoValidationError(RuntimeError):
    """Raised when a committed pack or generated demonstration is invalid."""


@dataclass(frozen=True, slots=True)
class DemoMissionTarget:
    """Minimal workflow-independent locator returned by an injected runner."""

    artifacts_root: Path
    mission_id: str
    exit_code: int


@dataclass(frozen=True, slots=True)
class DemoValidationResult:
    scenario: str
    mission_id: str
    outcome: MissionOutcome
    snapshot_count: int
    captains_log_path: Path
    mission_summary_path: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class DemoPackFailure:
    scenario: str
    reason: str


@dataclass(frozen=True, slots=True)
class DemoPackValidationReport:
    catalog_schema_version: str
    results: tuple[DemoValidationResult, ...]
    failures: tuple[DemoPackFailure, ...]

    @property
    def ready(self) -> bool:
        return not self.failures

    def require_ready(self) -> "DemoPackValidationReport":
        if self.failures:
            details = "; ".join(
                f"{failure.scenario}: {failure.reason}"
                for failure in self.failures
            )
            raise DemoValidationError(f"demo pack validation failed: {details}")
        return self


DemoPackRunner = Callable[[ResolvedDemoScenario], DemoMissionTarget]


_LOCAL_PATH = re.compile(
    r"(?:file://|/Users/|/home/|/private/|/tmp/|/var/folders/|[A-Za-z]:\\)",
    re.IGNORECASE,
)
_HIGH_CONFIDENCE_SECRET = re.compile(
    r"(?:sk-proj-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_-]{8,}"
    r"|github_pat_[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9_-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{8,})",
    re.IGNORECASE,
)
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "secret",
    "access_token",
    "refresh_token",
}
_STACK_KEYS = {"stack", "stack_trace", "stacktrace", "traceback"}
_OPERATION_KEYS = {"action", "operation", "operations", "allowed_operations"}
_PROHIBITED_OPERATION_FIELD = re.compile(
    r'''["']?(?:action|operation|operations|allowed_operations)["']?\s*[:=]\s*'''
    r'''(?:["']|\[[^\]]*)?(?:SUBMIT_ORDER|CANCEL_ORDER|MODIFY_PORTFOLIO|BROKER_CALL)''',
    re.IGNORECASE,
)
_SECRET_FIELD_TEXT = re.compile(
    r'''["']?(?:api[_-]?key|authorization|password|passwd|secret|access_token|refresh_token)["']?\s*[:=]\s*\S+''',
    re.IGNORECASE,
)
_STACK_FIELD_TEXT = re.compile(
    r'''["']?(?:stack|stack_trace|stacktrace|traceback)["']?\s*[:=]''',
    re.IGNORECASE,
)


def validate_demo_catalog(
    *,
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> DemoCatalog:
    """Validate all committed pack schemas, hashes, correlation, and safety."""

    return load_demo_catalog(root=root, catalog_path=catalog_path)


def validate_demo_packs(
    catalog: DemoCatalog,
    runner: DemoPackRunner,
) -> DemoPackValidationReport:
    """Run and validate every committed pack without depending on a workflow.

    A failure in one scenario is recorded and validation continues so an
    operator receives one complete readiness report.
    """

    results: list[DemoValidationResult] = []
    failures: list[DemoPackFailure] = []
    for spec in catalog.scenarios:
        try:
            resolved = spec.resolve(catalog.repository_root)
            target = runner(resolved)
            if not isinstance(target, DemoMissionTarget):
                raise DemoValidationError(
                    "demo runner must return DemoMissionTarget"
                )
            result = validate_demo_mission(
                MissionStore(target.artifacts_root),
                spec,
                target.mission_id,
                exit_code=target.exit_code,
            )
        except Exception as exc:  # every pack should still be checked
            failures.append(
                DemoPackFailure(
                    scenario=spec.name,
                    reason=_sanitized_reason(exc),
                )
            )
        else:
            results.append(result)
    return DemoPackValidationReport(
        catalog_schema_version=catalog.schema_version,
        results=tuple(results),
        failures=tuple(failures),
    )


def validate_demo_mission(
    store: MissionStore,
    scenario: DemoScenarioSpec | ResolvedDemoScenario,
    mission_id: str,
    *,
    exit_code: int | None = None,
) -> DemoValidationResult:
    """Validate one generated mission against its committed scenario contract."""

    spec = scenario.spec if isinstance(scenario, ResolvedDemoScenario) else scenario
    if exit_code is not None and (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        raise DemoValidationError("demo exit code must be an integer")
    if exit_code is not None and exit_code != spec.expected_exit_code:
        raise DemoValidationError(
            f"{spec.name} exit code {exit_code} does not match expected "
            f"{spec.expected_exit_code}"
        )

    try:
        loaded = store.load_mission(mission_id)
    except (MissionStoreError, ContractValidationError, OSError, ValueError) as exc:
        raise DemoValidationError(
            f"canonical mission validation failed: {_sanitized_reason(exc)}"
        ) from exc
    snapshot = loaded.snapshot
    if snapshot.mission_outcome is not spec.expected_outcome:
        raise DemoValidationError(
            f"{spec.name} outcome {snapshot.mission_outcome.value} does not match "
            f"expected {spec.expected_outcome.value}"
        )
    if snapshot.current_phase is not spec.expected_phase:
        raise DemoValidationError(
            f"{spec.name} phase {snapshot.current_phase.value} does not match "
            f"expected {spec.expected_phase.value}"
        )
    if snapshot.terminal is not spec.expected_terminal:
        raise DemoValidationError(f"{spec.name} terminal state is inconsistent")
    if len(loaded.snapshot_history) != spec.expected_snapshot_count:
        raise DemoValidationError(
            f"{spec.name} snapshot count {len(loaded.snapshot_history)} does not "
            f"match expected {spec.expected_snapshot_count}"
        )

    mission_root = loaded.paths.mission_root
    log_path = _mission_file(mission_root, CAPTAINS_LOG_PATH)
    summary_path = _mission_file(mission_root, MISSION_SUMMARY_PATH)
    manifest_path = _mission_file(mission_root, DEMO_MANIFEST_PATH)
    markdown_path = _mission_file(mission_root, CAPTAINS_LOG_MARKDOWN_PATH)

    log = _load_canonical_contract(log_path, CaptainsLog.from_mapping, "Captain's Log")
    summary = _load_canonical_contract(
        summary_path, MissionSummary.from_mapping, "mission summary"
    )
    manifest = _load_canonical_contract(
        manifest_path, DemoManifest.from_mapping, "demo manifest"
    )

    _validate_captains_log(loaded, log)
    _validate_mission_summary(loaded, log, summary)
    _validate_manifest(loaded, spec, log, summary, manifest, store)
    if markdown_path.read_bytes() != render_captains_log_markdown(log):
        raise DemoValidationError(
            "Captain's Log Markdown is not the deterministic rendering of its JSON"
        )
    _validate_portable_tree(mission_root)

    return DemoValidationResult(
        scenario=spec.name,
        mission_id=mission_id,
        outcome=snapshot.mission_outcome,
        snapshot_count=len(loaded.snapshot_history),
        captains_log_path=log_path,
        mission_summary_path=summary_path,
        manifest_path=manifest_path,
    )


def _load_canonical_contract(
    path: Path,
    parser: Callable[[Mapping[str, Any]], Any],
    label: str,
) -> Any:
    try:
        value = load_strict_json_object(path)
        contract = parser(value)
    except (ContractValidationError, OSError, ValueError) as exc:
        raise DemoValidationError(
            f"{label} is invalid: {_sanitized_reason(exc)}"
        ) from exc
    if path.read_bytes() != canonical_json_bytes(contract.to_dict()):
        raise DemoValidationError(f"{label} is not canonical deterministic JSON")
    return contract


def _validate_captains_log(loaded: LoadedMission, log: CaptainsLog) -> None:
    snapshot = loaded.snapshot
    if (
        log.mission_id != snapshot.mission_id
        or log.request_id != snapshot.request_id
        or log.symbol != loaded.request.symbol
        or log.run_mode is not snapshot.run_mode
        or log.generated_at != snapshot.observed_at
    ):
        raise DemoValidationError("Captain's Log correlation is inconsistent")

    final_revision = _revision_reference(loaded, snapshot.revision)
    if log.generated_from_snapshot != final_revision:
        raise DemoValidationError(
            "Captain's Log does not reference the final immutable snapshot"
        )
    known = _known_evidence(loaded)
    for entry in log.entries:
        if not entry.source_artifacts:
            raise DemoValidationError(
                f"Captain's Log {entry.stage} entry has no source evidence"
            )
        first = entry.source_artifacts[0]
        if not first.path.startswith("snapshots/mission_snapshot-r"):
            raise DemoValidationError(
                f"Captain's Log {entry.stage} entry must begin with snapshot evidence"
            )
        if first.observed_at != entry.timestamp:
            raise DemoValidationError(
                f"Captain's Log {entry.stage} timestamp is not source-derived"
            )
        for reference in entry.source_artifacts:
            _verify_reference(loaded.paths.mission_root, reference)
            if known.get(reference.path) != reference:
                raise DemoValidationError(
                    f"Captain's Log has unrecorded source evidence: {reference.path}"
                )
    mission_entry = log.entries[-1]
    if (
        mission_entry.status != snapshot.mission_outcome.value
        or mission_entry.source_artifacts != (final_revision,)
    ):
        raise DemoValidationError("Captain's Log final outcome is not canonical")


def _validate_mission_summary(
    loaded: LoadedMission,
    log: CaptainsLog,
    summary: MissionSummary,
) -> None:
    snapshot = loaded.snapshot
    if (
        summary.mission_id != snapshot.mission_id
        or summary.request_id != snapshot.request_id
        or summary.symbol != loaded.request.symbol
        or summary.run_mode is not snapshot.run_mode
        or summary.generated_at != snapshot.observed_at
        or summary.generated_from_snapshot
        != _revision_reference(loaded, snapshot.revision)
        or summary.current_phase is not snapshot.current_phase
        or summary.terminal is not snapshot.terminal
        or summary.final_outcome is not snapshot.mission_outcome
        or summary.snapshot_count != len(loaded.snapshot_history)
    ):
        raise DemoValidationError("mission summary does not match canonical state")

    for name, stage in snapshot.stages.items():
        projected = summary.stages[name]
        if (
            projected.technical_status is not stage.status
            or projected.native_state != stage.native_state
        ):
            raise DemoValidationError(
                f"mission summary stage {name} differs from canonical state"
            )

    call = (
        snapshot.stages["oracle"].modeldock_calls[-1]
        if snapshot.stages["oracle"].modeldock_calls
        else None
    )
    expected_modeldock = (
        ("NOT_RECORDED", None, None, None)
        if call is None
        else (call.status.value, call.provider, call.model, call.trace_id)
    )
    actual_modeldock = (
        summary.modeldock.status,
        summary.modeldock.provider,
        summary.modeldock.model,
        summary.modeldock.trace_id,
    )
    if actual_modeldock != expected_modeldock:
        raise DemoValidationError("mission summary ModelDock state is inconsistent")

    operator = snapshot.operator
    if (
        summary.governor_disposition != snapshot.stages["governor"].native_state
        or summary.operator.route is not operator.route
        or summary.operator.action_status is not operator.action_status
        or summary.operator.action is not operator.action
        or summary.operator.result is not operator.result
    ):
        raise DemoValidationError("mission summary decision state is inconsistent")
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
        or summary.approval_scope is not snapshot.approval_scope
    ):
        raise DemoValidationError("mission summary Navigator state is inconsistent")
    if summary.display_title != f"BlackPod Mission: {loaded.request.symbol}":
        raise DemoValidationError("mission summary display title is not deterministic")
    expected_subtitle = (
        f"{snapshot.run_mode.value} | {snapshot.mission_outcome.value} | "
        f"{snapshot.current_phase.value}"
    )
    if summary.subtitle != expected_subtitle:
        raise DemoValidationError("mission summary subtitle is not deterministic")
    if summary.event_count != len(log.entries):
        raise DemoValidationError("mission summary event count differs from the log")
    for ordered, entry in zip(summary.ordered_stages, log.entries[:-1], strict=True):
        if (
            ordered.stage != entry.stage
            or ordered.summary != entry.summary
            or ordered.artifact_paths
            != tuple(reference.path for reference in entry.source_artifacts)
        ):
            raise DemoValidationError(
                f"mission summary ordered stage {ordered.stage} differs from the log"
            )
    for relative_path in summary.artifact_links.values():
        _mission_file(loaded.paths.mission_root, relative_path)


def _validate_manifest(
    loaded: LoadedMission,
    spec: DemoScenarioSpec,
    log: CaptainsLog,
    summary: MissionSummary,
    manifest: DemoManifest,
    store: MissionStore,
) -> None:
    snapshot = loaded.snapshot
    expected_scenario = DemoScenario(spec.expected_outcome.value.lower())
    if (
        manifest.demo_scenario is not expected_scenario
        or manifest.mission_id != snapshot.mission_id
        or manifest.symbol != loaded.request.symbol
        or manifest.run_mode is not snapshot.run_mode
        or manifest.final_outcome is not snapshot.mission_outcome
        or manifest.snapshot_count != len(loaded.snapshot_history)
        or manifest.generated_at != snapshot.observed_at
    ):
        raise DemoValidationError("demo manifest identity or expected outcome is invalid")

    battlestar = snapshot.components.get("battlestar")
    if battlestar is None or manifest.battlestar_revision != battlestar.git_revision:
        raise DemoValidationError(
            "demo manifest Battlestar revision is missing or inconsistent"
        )

    calls = snapshot.stages["oracle"].modeldock_calls
    if spec.with_modeldock:
        if not calls or calls[-1].status is not ModelDockCallStatus.SUCCEEDED:
            raise DemoValidationError(
                "ModelDock-enabled demo lacks successful canonical enrichment"
            )
        call = calls[-1]
        if (
            manifest.modeldock_mode is not DemoModelDockMode.REPLAYED
            or manifest.modeldock_revision_or_service_identity
            != getattr(snapshot.components.get("modeldock"), "replay_fixture_id", None)
            or manifest.modeldock_provider != call.provider
            or manifest.modeldock_model != call.model
            or manifest.modeldock_trace_id != call.trace_id
        ):
            raise DemoValidationError("demo manifest ModelDock identity is inconsistent")
    elif (
        calls
        or "modeldock" in snapshot.components
        or manifest.modeldock_mode is not DemoModelDockMode.DISABLED
    ):
        raise DemoValidationError(
            "ModelDock-disabled demo contains ModelDock execution state"
        )

    expected_log = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=CAPTAINS_LOG_PATH,
        name="captains_log",
        producer="harbormaster",
        schema_version=CAPTAINS_LOG_SCHEMA_VERSION,
        observed_at=snapshot.observed_at,
    )
    expected_summary = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=MISSION_SUMMARY_PATH,
        name="mission_summary",
        producer="harbormaster",
        schema_version=MISSION_SUMMARY_SCHEMA_VERSION,
        observed_at=snapshot.observed_at,
    )
    expected_snapshot = store.reference_existing_artifact(
        snapshot.mission_id,
        relative_path=CANONICAL_SNAPSHOT_PATH,
        name="mission_snapshot",
        producer="harbormaster",
        schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
        observed_at=snapshot.observed_at,
    )
    if (
        manifest.captains_log != expected_log
        or manifest.mission_summary != expected_summary
        or manifest.final_snapshot != expected_snapshot
        or log.generated_at != manifest.generated_at
        or summary.generated_at != manifest.generated_at
    ):
        raise DemoValidationError("demo manifest artifact hashes are inconsistent")
    for reference in (
        manifest.captains_log,
        manifest.mission_summary,
        manifest.final_snapshot,
    ):
        _verify_reference(loaded.paths.mission_root, reference)

    if snapshot.navigator.mode is not None:
        if (
            snapshot.navigator.mode is not NavigatorMode.SHADOW
            or snapshot.navigator.allowed_operations
            != NAVIGATOR_ALLOWED_OPERATIONS
            or snapshot.navigator.prohibited_operations
            != NAVIGATOR_PROHIBITED_OPERATIONS
        ):
            raise DemoValidationError("generated mission exceeds the SHADOW boundary")


def _known_evidence(loaded: LoadedMission) -> dict[str, ArtifactReference]:
    evidence = {artifact.path: artifact for artifact in loaded.snapshot.artifacts}
    for revision in range(1, loaded.snapshot.revision + 1):
        reference = _revision_reference(loaded, revision)
        evidence[reference.path] = reference
    return evidence


def _revision_reference(loaded: LoadedMission, revision: int) -> ArtifactReference:
    snapshot = loaded.snapshot_history[revision - 1]
    path = loaded.paths.snapshots_dir / f"mission_snapshot-r{revision:04d}.json"
    return ArtifactReference.from_mapping(
        {
            "name": f"mission_snapshot_r{revision:04d}",
            "path": f"snapshots/mission_snapshot-r{revision:04d}.json",
            "sha256": sha256_file(path),
            "producer": "harbormaster",
            "byte_size": path.stat().st_size,
            "schema_version": snapshot.schema_version,
            "observed_at": snapshot.observed_at,
        }
    )


def _verify_reference(mission_root: Path, reference: ArtifactReference) -> None:
    path = _mission_file(mission_root, reference.path)
    if sha256_file(path) != reference.sha256:
        raise DemoValidationError(f"artifact reference hash mismatch: {reference.path}")
    if reference.byte_size is None or path.stat().st_size != reference.byte_size:
        raise DemoValidationError(
            f"artifact reference byte size mismatch: {reference.path}"
        )


def _mission_file(mission_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise DemoValidationError("demo artifact path must be relative POSIX text")
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(part in {"", "."} for part in relative.parts)
        or relative.as_posix() != relative_path
    ):
        raise DemoValidationError(
            f"demo artifact path is not mission-relative: {relative_path}"
        )
    root = mission_root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise DemoValidationError(f"demo artifact path contains a symlink: {relative_path}")
    if not candidate.is_file():
        raise DemoValidationError(f"demo artifact is missing: {relative_path}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise DemoValidationError(f"demo artifact escapes mission root: {relative_path}")
    return resolved


def _validate_portable_tree(mission_root: Path) -> None:
    root = mission_root.resolve(strict=True)
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise DemoValidationError(
                f"generated demo contains a symlink: {path.relative_to(root).as_posix()}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if path.suffix == ".json":
            try:
                value = _load_json_value(path)
            except (OSError, UnicodeError, ValueError) as exc:
                raise DemoValidationError(
                    f"generated JSON is invalid ({relative}): {_sanitized_reason(exc)}"
                ) from exc
            _scan_portable_value(value, location=relative)
        elif path.suffix == ".jsonl":
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise DemoValidationError(
                    f"generated JSON Lines is unreadable: {relative}"
                ) from exc
            _scan_portable_text(text, location=relative)
            _scan_text_fields(text, location=relative)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    value = _loads_json_value(line)
                except ValueError:
                    # Legacy Oracle ledgers are captured as opaque evidence.
                    # Their bytes remain hash-verified by MissionStore; safety
                    # inspection above still rejects paths, secrets, and
                    # prohibited operations without inventing a new schema.
                    continue
                _scan_portable_value(value, location=f"{relative}:{line_number}")
        elif path.suffix in {".md", ".txt", ".yaml", ".yml", ".log"}:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise DemoValidationError(
                    f"generated text artifact is invalid: {relative}"
                ) from exc
            _scan_portable_text(text, location=relative)
            _scan_text_fields(text, location=relative)


def _load_json_value(path: Path) -> object:
    return _loads_json_value(path.read_text(encoding="utf-8"))


def _loads_json_value(payload: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(payload, object_pairs_hook=pairs)


def _scan_portable_value(value: object, *, location: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS:
                raise DemoValidationError(
                    f"secret-like field found in generated demo: {location}"
                )
            if normalized in _STACK_KEYS:
                raise DemoValidationError(
                    f"raw diagnostic stack found in generated demo: {location}"
                )
            if normalized in _OPERATION_KEYS and normalized != "prohibited_operations":
                candidates = child if isinstance(child, list) else [child]
                prohibited = {
                    str(item).upper().replace("-", "_").replace(" ", "_")
                    for item in candidates
                    if isinstance(item, str)
                }
                if prohibited.intersection(NAVIGATOR_PROHIBITED_OPERATIONS):
                    raise DemoValidationError(
                        f"prohibited execution operation found in {location}"
                    )
            _scan_portable_value(child, location=location)
        return
    if isinstance(value, list):
        for child in value:
            _scan_portable_value(child, location=location)
        return
    if isinstance(value, str):
        _scan_portable_text(value, location=location)


def _scan_portable_text(value: str, *, location: str) -> None:
    if _LOCAL_PATH.search(value):
        raise DemoValidationError(
            f"machine-local absolute path found in generated demo: {location}"
        )
    if _HIGH_CONFIDENCE_SECRET.search(value):
        raise DemoValidationError(
            f"secret-like value found in generated demo: {location}"
        )


def _scan_text_fields(value: str, *, location: str) -> None:
    if _SECRET_FIELD_TEXT.search(value):
        raise DemoValidationError(
            f"secret-like field found in generated demo: {location}"
        )
    if _STACK_FIELD_TEXT.search(value):
        raise DemoValidationError(
            f"raw diagnostic stack found in generated demo: {location}"
        )
    if _PROHIBITED_OPERATION_FIELD.search(value):
        raise DemoValidationError(
            f"prohibited execution operation found in {location}"
        )


def _sanitized_reason(exc: BaseException) -> str:
    reason = str(exc).replace("\n", " ").strip() or type(exc).__name__
    reason = _LOCAL_PATH.sub("<local-path>", reason)
    reason = _HIGH_CONFIDENCE_SECRET.sub("<redacted>", reason)
    return reason[:512]
