"""Canonical, non-executing readiness preflight for the Build Week demo."""

from __future__ import annotations

import copy
import importlib
import multiprocessing
import os
import platform
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .battlestar_config import (
    ADVISOR_HEALTH_ENTRY_POINT,
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    CANDIDATE_ENTRY_POINT,
    CANDIDATE_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_ENTRY_POINT,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    GOVERNOR_DECISION_CONSUMER_ENTRY_POINT,
    GOVERNOR_DECISION_CONSUMER_MODULE_RELATIVE_PATH,
    GOVERNOR_DELIBERATION_ENTRY_POINT,
    GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH,
    GOVERNOR_PREPARATION_ENTRY_POINT,
    GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH,
    GOVERNOR_READINESS_ENTRY_POINT,
    GOVERNOR_READINESS_MODULE_RELATIVE_PATH,
    GOVERNOR_RENDERING_ENTRY_POINT,
    GOVERNOR_RENDERING_MODULE_RELATIVE_PATH,
    GOVERNOR_SENATE_INTAKE_ENTRY_POINT,
    GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH,
    MANDATE_ENTRY_POINT,
    MANDATE_MODULE_RELATIVE_PATH,
    NAVIGATOR_HANDOFF_ENTRY_POINT,
    NAVIGATOR_HANDOFF_MODULE_RELATIVE_PATH,
    NAVIGATOR_INTAKE_ENTRY_POINT,
    NAVIGATOR_INTAKE_MODULE_RELATIVE_PATH,
    NAVIGATOR_SHADOW_WORKFLOW_ENTRY_POINT,
    NAVIGATOR_SHADOW_WORKFLOW_MODULE_RELATIVE_PATH,
    OPERATOR_ACTION_ENTRY_POINT,
    OPERATOR_ACTION_MODULE_RELATIVE_PATH,
    ORACLE_ENTRY_POINT,
    ORACLE_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_ENTRY_POINT,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_ENTRY_POINT,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_ENTRY_POINT,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
    BattlestarConfig,
    BattlestarConfigurationError,
    load_navigator_battlestar_config,
)
from .contracts import (
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ApprovalScope,
    ContractValidationError,
    MissionRequest,
    NavigatorMode,
    OperatorAction,
    RunMode,
)
from .contracts.mission_request import format_rfc3339
from .contracts.oracle_narrative import ModelDockReplayPack
from .council_adapter import CouncilSupportingInput
from .governor_adapter import GovernorSupportingContext
from .modeldock_config import (
    ModelDockConfig,
    ModelDockConfigurationError,
    load_modeldock_config,
)
from .modeldock_preflight import ModelDockPreflightReport, run_modeldock_preflight
from .navigator_adapter import NavigatorReplayFixture
from .operator_adapter import OperatorActionInput
from .oracle_adapter import ReplayOracleInput
from .repository_state import (
    CommittedSecretFinding,
    GitWorktreeState,
    inspect_git_worktree,
    scan_committed_secrets,
)


PREFLIGHT_SCHEMA_VERSION = "blackpod.demo_preflight.v1"
_REQUIRED_PYTHON = (3, 11)
_INTERFACE_PROBE_TIMEOUT_SECONDS = 30.0
_EXPECTED_FAMILIES = ("oracle", "council", "governor", "operator", "navigator")


class PreflightError(ValueError):
    """Raised when the preflight invocation itself is malformed."""


class BattlestarInterfaceProbeError(RuntimeError):
    """Raised when the isolated read-only interface probe cannot complete."""


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True)
class PreflightSettings:
    mode: RunMode | str
    artifacts_root: Path
    strict_clean: bool = False

    def __post_init__(self) -> None:
        try:
            mode = (
                self.mode
                if isinstance(self.mode, RunMode)
                else RunMode(str(self.mode).upper())
            )
        except (TypeError, ValueError) as exc:
            raise PreflightError("preflight mode must be LIVE or REPLAY") from exc
        if not isinstance(self.strict_clean, bool):
            raise PreflightError("strict_clean must be a boolean")
        root = Path(self.artifacts_root)
        if not str(root):
            raise PreflightError("artifacts_root must be a nonblank path")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "artifacts_root", root)


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    component: str
    name: str
    status: CheckStatus
    required: bool
    message: str
    details: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return self.status in {CheckStatus.PASS, CheckStatus.WARN}

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "name": self.name,
            "status": self.status.value,
            "required": self.required,
            "message": self.message,
            "details": copy.deepcopy(dict(self.details)),
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    schema_version: str
    mode: RunMode
    observed_at: str
    checks: tuple[PreflightCheck, ...]

    @property
    def ready(self) -> bool:
        return all(not check.required or check.passed for check in self.checks)

    @property
    def issues(self) -> tuple[PreflightCheck, ...]:
        return tuple(
            check
            for check in self.checks
            if check.status in {CheckStatus.WARN, CheckStatus.FAIL}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode.value,
            "observed_at": self.observed_at,
            "ready": self.ready,
            "checks": [check.to_dict() for check in self.checks],
            "issues": [check.to_dict() for check in self.issues],
        }


@dataclass(frozen=True, slots=True)
class InterfaceSpec:
    family: str
    entry_point: str
    module_path: Path


@dataclass(frozen=True, slots=True)
class InterfaceProbeResult:
    family: str
    entry_point: str
    available: bool
    message: str


@dataclass(frozen=True, slots=True)
class FixtureProbeResult:
    path: str
    schema_version: str | None
    valid: bool
    message: str


class BattlestarLoader(Protocol):
    def __call__(
        self,
        *,
        artifacts_root: Path,
        environ: Mapping[str, str] | None,
        strict_clean: bool,
    ) -> BattlestarConfig: ...


class InterfaceProbe(Protocol):
    def __call__(
        self, config: BattlestarConfig
    ) -> Sequence[InterfaceProbeResult]: ...


class ModelDockConfigLoader(Protocol):
    def __call__(
        self, *, environ: Mapping[str, str] | None
    ) -> ModelDockConfig: ...


class ModelDockPreflightRunner(Protocol):
    def __call__(self, config: ModelDockConfig) -> ModelDockPreflightReport: ...


_INTERFACE_SPECS = (
    InterfaceSpec("oracle", ORACLE_ENTRY_POINT, ORACLE_MODULE_RELATIVE_PATH),
    InterfaceSpec("council", CANDIDATE_ENTRY_POINT, CANDIDATE_MODULE_RELATIVE_PATH),
    InterfaceSpec("council", SENATE_REVIEW_ENTRY_POINT, SENATE_REVIEW_MODULE_RELATIVE_PATH),
    InterfaceSpec(
        "council", SENATE_DELIBERATION_ENTRY_POINT, SENATE_DELIBERATION_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec("council", MANDATE_ENTRY_POINT, MANDATE_MODULE_RELATIVE_PATH),
    InterfaceSpec(
        "council", COUNCIL_SYNTHESIS_ENTRY_POINT, COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "council",
        COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT,
        COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    ),
    InterfaceSpec("council", ADVISOR_HEALTH_ENTRY_POINT, ADVISOR_HEALTH_MODULE_RELATIVE_PATH),
    InterfaceSpec(
        "council", RUNTIME_VALIDATION_ENTRY_POINT, RUNTIME_VALIDATION_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "governor", GOVERNOR_SENATE_INTAKE_ENTRY_POINT, GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "governor", GOVERNOR_PREPARATION_ENTRY_POINT, GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "governor", GOVERNOR_DELIBERATION_ENTRY_POINT, GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "governor", GOVERNOR_READINESS_ENTRY_POINT, GOVERNOR_READINESS_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "governor", GOVERNOR_RENDERING_ENTRY_POINT, GOVERNOR_RENDERING_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "operator",
        GOVERNOR_DECISION_CONSUMER_ENTRY_POINT,
        GOVERNOR_DECISION_CONSUMER_MODULE_RELATIVE_PATH,
    ),
    InterfaceSpec("operator", OPERATOR_ACTION_ENTRY_POINT, OPERATOR_ACTION_MODULE_RELATIVE_PATH),
    InterfaceSpec(
        "navigator", NAVIGATOR_HANDOFF_ENTRY_POINT, NAVIGATOR_HANDOFF_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "navigator", NAVIGATOR_INTAKE_ENTRY_POINT, NAVIGATOR_INTAKE_MODULE_RELATIVE_PATH
    ),
    InterfaceSpec(
        "navigator",
        NAVIGATOR_SHADOW_WORKFLOW_ENTRY_POINT,
        NAVIGATOR_SHADOW_WORKFLOW_MODULE_RELATIVE_PATH,
    ),
)


def run_preflight(
    settings: PreflightSettings,
    *,
    environ: Mapping[str, str] | None = None,
    battlestar_loader: BattlestarLoader = load_navigator_battlestar_config,
    import_probe: InterfaceProbe | None = None,
    modeldock_config_loader: ModelDockConfigLoader = load_modeldock_config,
    modeldock_preflight_runner: ModelDockPreflightRunner = run_modeldock_preflight,
    repository_inspector: Callable[
        [Path], GitWorktreeState
    ] = inspect_git_worktree,
    secret_scanner: Callable[
        [Path], Sequence[CommittedSecretFinding]
    ] = scan_committed_secrets,
    fixture_probe: Callable[[Path], Sequence[FixtureProbeResult]] | None = None,
    build_week_import_probe: (
        Callable[[Path, RunMode], tuple[bool, Mapping[str, Any], str]] | None
    ) = None,
    artifacts_probe: Callable[[Path, Path], Path] | None = None,
    build_week_root: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> PreflightReport:
    """Aggregate environment readiness without executing or mutating a mission.

    ModelDock configuration and network seams are never touched in REPLAY.
    Injection points keep the normal test suite independent from sibling repos
    and a running ModelDock appliance.
    """

    if not isinstance(settings, PreflightSettings):
        raise PreflightError("settings must be PreflightSettings")
    active_import_probe = import_probe or probe_battlestar_interfaces
    active_fixture_probe = fixture_probe or validate_demo_fixtures
    active_build_week_probe = build_week_import_probe or _probe_build_week_imports
    active_artifacts_probe = artifacts_probe or _probe_artifacts_root
    clock = now or (lambda: datetime.now(UTC))
    project_root = (
        Path(build_week_root).resolve(strict=False)
        if build_week_root is not None
        else Path(__file__).resolve().parents[2]
    )
    checks: list[PreflightCheck] = []

    python_ok = sys.version_info >= _REQUIRED_PYTHON
    checks.append(
        _check(
            "build_week",
            "python",
            CheckStatus.PASS if python_ok else CheckStatus.FAIL,
            True,
            (
                "Python runtime satisfies the Build Week requirement"
                if python_ok
                else "Python 3.11 or newer is required"
            ),
            {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
                "minimum": "3.11",
            },
        )
    )

    try:
        imports_ok, import_details, import_message = active_build_week_probe(
            project_root, settings.mode
        )
        checks.append(
            _check(
                "build_week",
                "imports",
                CheckStatus.PASS if imports_ok else CheckStatus.FAIL,
                True,
                import_message,
                import_details,
            )
        )
    except Exception:
        checks.append(
            _check(
                "build_week",
                "imports",
                CheckStatus.FAIL,
                True,
                "Build Week import readiness could not be inspected",
            )
        )

    try:
        active_artifacts_probe(settings.artifacts_root, project_root)
        checks.append(
            _check(
                "build_week",
                "artifact_root",
                CheckStatus.PASS,
                True,
                "Mission artifact root is contained and writable",
                {"write_probe": "exclusive-create-fsync-delete"},
            )
        )
    except Exception:
        checks.append(
            _check(
                "build_week",
                "artifact_root",
                CheckStatus.FAIL,
                True,
                "Mission artifact root is unsafe or not writable",
            )
        )

    try:
        repository = repository_inspector(project_root)
        git_status = (
            CheckStatus.FAIL
            if repository.dirty and settings.strict_clean
            else CheckStatus.WARN
            if repository.dirty
            else CheckStatus.PASS
        )
        checks.append(
            _check(
                "build_week",
                "git",
                git_status,
                True,
                _git_message("Build Week", repository.dirty, settings.strict_clean),
                repository.to_dict(),
            )
        )
    except Exception:
        checks.append(
            _check(
                "build_week",
                "git",
                CheckStatus.FAIL,
                True,
                "Build Week Git state could not be inspected",
            )
        )

    try:
        findings = tuple(secret_scanner(project_root))
        checks.append(
            _check(
                "safety",
                "committed_secrets",
                CheckStatus.FAIL if findings else CheckStatus.PASS,
                True,
                (
                    "High-confidence committed credential material was detected"
                    if findings
                    else "No high-confidence committed credential material was detected"
                ),
                {"findings": [finding.to_dict() for finding in findings]},
            )
        )
    except Exception:
        checks.append(
            _check(
                "safety",
                "committed_secrets",
                CheckStatus.FAIL,
                True,
                "Committed-secret inspection could not complete",
            )
        )

    try:
        fixture_results = tuple(active_fixture_probe(project_root))
        invalid = [result for result in fixture_results if not result.valid]
        checks.append(
            _check(
                "build_week",
                "fixtures_and_schemas",
                CheckStatus.FAIL if invalid else CheckStatus.PASS,
                True,
                (
                    "One or more deterministic fixtures failed current schema validation"
                    if invalid
                    else "Deterministic requests and fixtures match current schemas"
                ),
                {
                    "fixtures": [
                        {
                            "path": item.path,
                            "schema_version": item.schema_version,
                            "valid": item.valid,
                            "message": item.message,
                        }
                        for item in fixture_results
                    ]
                },
            )
        )
    except Exception:
        checks.append(
            _check(
                "build_week",
                "fixtures_and_schemas",
                CheckStatus.FAIL,
                True,
                "Deterministic fixture validation could not complete",
            )
        )

    checks.append(_safety_contract_check())

    battlestar_config: BattlestarConfig | None = None
    try:
        # Strictness is applied after loading so dirty provenance remains
        # visible in the aggregate report instead of becoming a first-error.
        battlestar_config = battlestar_loader(
            artifacts_root=settings.artifacts_root,
            environ=environ,
            strict_clean=False,
        )
        checks.append(
            _check(
                "battlestar",
                "configuration",
                CheckStatus.PASS,
                True,
                "Battlestar full-lifecycle configuration is valid",
                {"interface_families": list(_EXPECTED_FAMILIES)},
            )
        )
        battlestar_git_status = (
            CheckStatus.FAIL
            if battlestar_config.dirty_worktree and settings.strict_clean
            else CheckStatus.WARN
            if battlestar_config.dirty_worktree
            else CheckStatus.PASS
        )
        checks.append(
            _check(
                "battlestar",
                "git",
                battlestar_git_status,
                True,
                _git_message(
                    "Battlestar",
                    battlestar_config.dirty_worktree,
                    settings.strict_clean,
                ),
                {
                    "revision": battlestar_config.git_revision,
                    "branch": battlestar_config.git_branch,
                    "dirty": battlestar_config.dirty_worktree,
                },
            )
        )
    except BattlestarConfigurationError as exc:
        checks.append(
            _check(
                "battlestar",
                "configuration",
                CheckStatus.FAIL,
                True,
                _safe_configuration_message(exc),
            )
        )
    except Exception:
        checks.append(
            _check(
                "battlestar",
                "configuration",
                CheckStatus.FAIL,
                True,
                "Battlestar configuration could not be inspected",
            )
        )

    if battlestar_config is None:
        checks.append(
            _check(
                "battlestar",
                "interfaces",
                CheckStatus.SKIPPED,
                True,
                "Battlestar callable interfaces were not probed because configuration failed",
            )
        )
    else:
        try:
            results = tuple(active_import_probe(battlestar_config))
            seen_families = {result.family for result in results}
            missing_families = set(_EXPECTED_FAMILIES) - seen_families
            unavailable = [result for result in results if not result.available]
            available = not missing_families and not unavailable
            checks.append(
                _check(
                    "battlestar",
                    "interfaces",
                    CheckStatus.PASS if available else CheckStatus.FAIL,
                    True,
                    (
                        "All five Battlestar interface families are importable and callable"
                        if available
                        else "One or more Battlestar interfaces are unavailable"
                    ),
                    {
                        "families": sorted(seen_families),
                        "missing_families": sorted(missing_families),
                        "interfaces": [
                            {
                                "family": result.family,
                                "entry_point": result.entry_point,
                                "available": result.available,
                                "message": result.message,
                            }
                            for result in results
                        ],
                    },
                )
            )
        except Exception:
            checks.append(
                _check(
                    "battlestar",
                    "interfaces",
                    CheckStatus.FAIL,
                    True,
                    "Battlestar callable-interface probe could not complete",
                )
            )

    if settings.mode is RunMode.REPLAY:
        checks.extend(
            (
                _check(
                    "modeldock",
                    "replay_transport",
                    CheckStatus.PASS,
                    True,
                    "ModelDock replay is fixture-backed and network-free",
                    {"network_attempted": False},
                ),
                _check(
                    "modeldock",
                    "live_inference",
                    CheckStatus.SKIPPED,
                    False,
                    "LIVE ModelDock inference is not applicable to REPLAY preflight",
                ),
            )
        )
    else:
        _append_live_modeldock_checks(
            checks,
            environ=environ,
            config_loader=modeldock_config_loader,
            preflight_runner=modeldock_preflight_runner,
        )

    return PreflightReport(
        schema_version=PREFLIGHT_SCHEMA_VERSION,
        mode=settings.mode,
        observed_at=format_rfc3339(clock()),
        checks=tuple(checks),
    )


def probe_battlestar_interfaces(
    config: BattlestarConfig,
) -> tuple[InterfaceProbeResult, ...]:
    """Import and inspect configured entry points in an isolated child process."""

    try:
        root = config.root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BattlestarInterfaceProbeError(
            "Battlestar interface root could not be resolved"
        ) from exc
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    with tempfile.TemporaryDirectory(prefix="blackpod-preflight-") as scratch:
        process = context.Process(
            target=_interface_probe_worker,
            args=(sender, str(root), scratch),
            name="blackpod-battlestar-interface-preflight",
        )
        process.start()
        sender.close()
        try:
            if not receiver.poll(_INTERFACE_PROBE_TIMEOUT_SECONDS):
                process.terminate()
                process.join(timeout=2.0)
                raise BattlestarInterfaceProbeError(
                    "Battlestar interface probe exceeded its deadline"
                )
            payload = receiver.recv()
        except EOFError as exc:
            raise BattlestarInterfaceProbeError(
                "Battlestar interface probe exited without a result"
            ) from exc
        finally:
            receiver.close()
        process.join(timeout=2.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        if process.exitcode != 0 or not isinstance(payload, list):
            raise BattlestarInterfaceProbeError(
                "Battlestar interface probe returned an invalid result"
            )

    results: list[InterfaceProbeResult] = []
    expected = {(spec.family, spec.entry_point) for spec in _INTERFACE_SPECS}
    for item in payload:
        if not isinstance(item, dict) or set(item) != {
            "family",
            "entry_point",
            "available",
            "message",
        }:
            raise BattlestarInterfaceProbeError(
                "Battlestar interface probe returned an invalid result"
            )
        if (item["family"], item["entry_point"]) not in expected:
            raise BattlestarInterfaceProbeError(
                "Battlestar interface probe returned an unknown interface"
            )
        if not isinstance(item["available"], bool) or not isinstance(
            item["message"], str
        ):
            raise BattlestarInterfaceProbeError(
                "Battlestar interface probe returned an invalid result"
            )
        results.append(
            InterfaceProbeResult(
                family=item["family"],
                entry_point=item["entry_point"],
                available=item["available"],
                message=item["message"],
            )
        )
    if {(item.family, item.entry_point) for item in results} != expected:
        raise BattlestarInterfaceProbeError(
            "Battlestar interface probe omitted configured interfaces"
        )
    return tuple(results)


def validate_demo_fixtures(root: Path) -> tuple[FixtureProbeResult, ...]:
    """Validate every committed deterministic input with its current parser."""

    try:
        resolved_root = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise PreflightError("Build Week root could not be resolved") from exc
    parsers: tuple[tuple[str, str, Callable[[bytes], object]], ...] = (
        (
            "examples/mission_request.live.json",
            "blackpod.mission_request.v1",
            _parse_mission_request,
        ),
        (
            "examples/mission_request.replay.json",
            "blackpod.mission_request.v1",
            _parse_mission_request,
        ),
        (
            "examples/mission_request.replay-hold.json",
            "blackpod.mission_request.v1",
            _parse_mission_request,
        ),
        (
            "examples/mission_request.replay-stand-down.json",
            "blackpod.mission_request.v1",
            _parse_mission_request,
        ),
        (
            "fixtures/oracle_replay_quotes.v1.json",
            "blackpod.oracle_replay_input.v1",
            ReplayOracleInput.from_bytes,
        ),
        (
            "fixtures/oracle_replay_quotes.risk_off.v1.json",
            "blackpod.oracle_replay_input.v1",
            ReplayOracleInput.from_bytes,
        ),
        (
            "fixtures/modeldock_oracle_narrative.replay.v1.json",
            "blackpod.modeldock_replay_pack.v1",
            ModelDockReplayPack.from_json_bytes,
        ),
        (
            "fixtures/council_replay_policy.v1.json",
            "blackpod.council_supporting_input.v1",
            CouncilSupportingInput.from_bytes,
        ),
        (
            "fixtures/governor_replay_context.proceed.v1.json",
            "blackpod.governor_supporting_context.v1",
            GovernorSupportingContext.from_bytes,
        ),
        (
            "fixtures/governor_replay_context.hold.v1.json",
            "blackpod.governor_supporting_context.v1",
            GovernorSupportingContext.from_bytes,
        ),
        (
            "fixtures/governor_replay_context.stand_down.v1.json",
            "blackpod.governor_supporting_context.v1",
            GovernorSupportingContext.from_bytes,
        ),
        (
            "fixtures/operator_replay_action.approve.v1.json",
            "blackpod.operator_action_replay.v1",
            OperatorActionInput.from_replay_bytes,
        ),
        (
            "fixtures/operator_replay_action.reject.v1.json",
            "blackpod.operator_action_replay.v1",
            OperatorActionInput.from_replay_bytes,
        ),
        (
            "fixtures/navigator_replay.shadow.v1.json",
            "blackpod.navigator_replay.v1",
            NavigatorReplayFixture.from_bytes,
        ),
        (
            "fixtures/navigator_replay.intake-failure.v1.json",
            "blackpod.navigator_replay.v1",
            NavigatorReplayFixture.from_bytes,
        ),
    )
    results: list[FixtureProbeResult] = []
    parsed: dict[str, object] = {}

    # The scenario catalog is the canonical cross-fixture manifest. It checks
    # immutable SHA-256 pins, scenario coverage, correlations, outcome policy,
    # and the SHADOW-only safety declaration before individual diagnostics are
    # collected below.
    try:
        from .demo_catalog import load_demo_catalog

        catalog = load_demo_catalog(root=resolved_root)
        results.append(
            FixtureProbeResult(
                "fixtures/demo_scenarios.v1.json",
                catalog.schema_version,
                True,
                "valid",
            )
        )
    except (ImportError, OSError, ValueError, ContractValidationError):
        results.append(
            FixtureProbeResult(
                "fixtures/demo_scenarios.v1.json",
                "blackpod.demo_scenarios.v1",
                False,
                "missing, hash-invalid, unsafe, or malformed",
            )
        )

    for relative_path, expected_schema, parser in parsers:
        try:
            payload = _read_contained_regular_file(resolved_root, relative_path)
            value = parser(payload)
            parsed[relative_path] = value
            results.append(
                FixtureProbeResult(relative_path, expected_schema, True, "valid")
            )
        except (OSError, ValueError, ContractValidationError):
            results.append(
                FixtureProbeResult(
                    relative_path,
                    None,
                    False,
                    "missing, unsafe, or invalid",
                )
            )

    try:
        _validate_fixture_correlations(parsed)
        results.append(
            FixtureProbeResult(
                "fixtures/scenario-correlations",
                "blackpod.demo_fixture_correlation.v1",
                True,
                "valid",
            )
        )
    except (KeyError, TypeError, ValueError, ContractValidationError):
        results.append(
            FixtureProbeResult(
                "fixtures/scenario-correlations",
                "blackpod.demo_fixture_correlation.v1",
                False,
                "fixture correlation mismatch",
            )
        )
    return tuple(results)


def _append_live_modeldock_checks(
    checks: list[PreflightCheck],
    *,
    environ: Mapping[str, str] | None,
    config_loader: ModelDockConfigLoader,
    preflight_runner: ModelDockPreflightRunner,
) -> None:
    checks.append(
        _check(
            "modeldock",
            "replay_transport",
            CheckStatus.SKIPPED,
            False,
            "Replay transport is not applicable to LIVE preflight",
        )
    )
    try:
        config = config_loader(environ=environ)
    except ModelDockConfigurationError as exc:
        checks.append(
            _check(
                "modeldock",
                "configuration",
                CheckStatus.FAIL,
                True,
                _safe_modeldock_configuration_message(exc),
            )
        )
        checks.append(
            _check(
                "modeldock",
                "live_inference",
                CheckStatus.SKIPPED,
                False,
                "Deep inference was not attempted because configuration failed",
            )
        )
        return
    except Exception:
        checks.append(
            _check(
                "modeldock",
                "configuration",
                CheckStatus.FAIL,
                True,
                "ModelDock configuration could not be inspected",
            )
        )
        checks.append(
            _check(
                "modeldock",
                "live_inference",
                CheckStatus.SKIPPED,
                False,
                "Deep inference was not attempted because configuration failed",
            )
        )
        return

    checks.append(
        _check(
            "modeldock",
            "configuration",
            CheckStatus.PASS,
            True,
            "ModelDock local MLX configuration is valid",
            {
                "base_url": config.base_url,
                "timeout_seconds": config.timeout_seconds,
                "profile": config.profile,
                "provider": config.provider,
                "model": config.model,
            },
        )
    )
    try:
        report = preflight_runner(config)
    except Exception:
        checks.append(
            _check(
                "modeldock",
                "live_inference",
                CheckStatus.FAIL,
                True,
                "ModelDock deep inference preflight could not complete",
            )
        )
        return
    accepted = (
        getattr(report, "ready", False) is True
        and getattr(report, "inference_ready", False) is True
        and getattr(report, "provider", None) == "mlx"
        and getattr(report, "mocked", None) is False
    )
    to_dict = getattr(report, "to_dict", None)
    candidate_details = to_dict() if callable(to_dict) else {}
    details = candidate_details if isinstance(candidate_details, Mapping) else {}
    checks.append(
        _check(
            "modeldock",
            "live_inference",
            CheckStatus.PASS if accepted else CheckStatus.FAIL,
            True,
            (
                "ModelDock completed a real non-mocked MLX inference"
                if accepted
                else "ModelDock did not prove real non-mocked MLX inference readiness"
            ),
            details,
        )
    )


def _interface_probe_worker(sender: Any, root_text: str, scratch: str) -> None:
    results: list[dict[str, object]] = []
    try:
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        sys.dont_write_bytecode = True
        root = Path(root_text).resolve(strict=True)
        os.chdir(scratch)
        sys.path.insert(0, str(root))
        for spec in _INTERFACE_SPECS:
            module_name = spec.module_path.with_suffix("").as_posix().replace("/", ".")
            attribute_path = spec.entry_point.removeprefix(module_name + ".")
            try:
                module = importlib.import_module(module_name)
                module_file = getattr(module, "__file__", None)
                expected_path = (root / spec.module_path).resolve(strict=True)
                if module_file is None or Path(module_file).resolve(strict=True) != expected_path:
                    raise RuntimeError("module origin mismatch")
                target: object = module
                for name in attribute_path.split("."):
                    target = getattr(target, name)
                if not callable(target):
                    raise TypeError("entry point is not callable")
            except BaseException as exc:
                results.append(
                    {
                        "family": spec.family,
                        "entry_point": spec.entry_point,
                        "available": False,
                        "message": _safe_interface_failure(exc),
                    }
                )
            else:
                results.append(
                    {
                        "family": spec.family,
                        "entry_point": spec.entry_point,
                        "available": True,
                        "message": "callable",
                    }
                )
        sender.send(results)
    except BaseException:
        try:
            sender.send([])
        except Exception:
            pass
    finally:
        sender.close()


def _probe_build_week_imports(
    root: Path, mode: RunMode
) -> tuple[bool, Mapping[str, Any], str]:
    required = {
        "blackpod_build_week.mission_initialization": "initialize_mission",
        "blackpod_build_week.oracle_workflow": "run_oracle",
        "blackpod_build_week.oracle_enrichment_workflow": "run_oracle_enrichment",
        "blackpod_build_week.council_workflow": "run_council",
        "blackpod_build_week.governor_workflow": "run_governor",
        "blackpod_build_week.operator_workflow": "run_operator_action",
        "blackpod_build_week.navigator_workflow": "run_navigator",
        "blackpod_build_week.unified_mission_workflow": "run_unified_mission",
    }
    imported: list[str] = []
    failures: list[str] = []
    try:
        source_root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return False, {"imports": [], "missing": ["project_root"]}, "Build Week root is unavailable"
    for module_name, attribute_name in required.items():
        try:
            module = importlib.import_module(module_name)
            module_file = getattr(module, "__file__", None)
            if module_file is None or not Path(module_file).resolve(strict=True).is_relative_to(
                source_root
            ):
                raise ImportError("module origin mismatch")
            if not callable(getattr(module, attribute_name, None)):
                raise ImportError("workflow entry point is not callable")
            if module_name.endswith("unified_mission_workflow") and not callable(
                getattr(module, "resume_unified_mission", None)
            ):
                raise ImportError("resume entry point is not callable")
            imported.append(module_name)
        except (ImportError, OSError, RuntimeError):
            failures.append(module_name)

    dependencies = ["yaml"]
    if mode is RunMode.LIVE:
        dependencies.append("yfinance")
    for dependency in dependencies:
        try:
            importlib.import_module(dependency)
        except ImportError:
            failures.append(dependency)
        else:
            imported.append(dependency)
    ok = not failures
    return (
        ok,
        {"imports": imported, "missing": failures},
        (
            "Build Week workflow imports are ready"
            if ok
            else "Build Week workflow imports or runtime dependencies are unavailable"
        ),
    )


def _probe_artifacts_root(artifacts_root: Path, build_week_root: Path) -> Path:
    candidate = Path(artifacts_root).expanduser()
    # The configured root itself may not be a symlink. Parent aliases such as
    # macOS `/var` -> `/private/var` are normalized by `resolve` below.
    if candidate.exists() and candidate.is_symlink():
        raise PreflightError("artifact root must not be a symlink")
    missing_paths: list[Path] = []
    cursor = candidate.absolute()
    while not cursor.exists():
        missing_paths.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    descriptor: int | None = None
    probe_path: Path | None = None
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        if not candidate.is_dir():
            raise PreflightError("artifact root must be a directory")
        resolved = candidate.resolve(strict=True)
        git_dir = (
            Path(build_week_root).resolve(strict=True) / ".git"
        ).resolve(strict=False)
        if resolved == git_dir or resolved.is_relative_to(git_dir):
            raise PreflightError("artifact root must not be inside Git metadata")
        descriptor, path_text = tempfile.mkstemp(
            prefix=".blackpod-preflight-", suffix=".tmp", dir=resolved
        )
        probe_path = Path(path_text)
        os.write(descriptor, b"blackpod-preflight\n")
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if probe_path is not None:
            probe_path.unlink(missing_ok=True)
        # A readiness probe must not make a clean checkout dirty. Remove only
        # directories this call created and only while they remain empty.
        for created in missing_paths:
            try:
                created.rmdir()
            except OSError:
                break
    return resolved


def _safety_contract_check() -> PreflightCheck:
    valid = (
        tuple(item.value for item in NavigatorMode) == ("SHADOW",)
        and NAVIGATOR_ALLOWED_OPERATIONS == ("VALIDATE", "PLAN_ONLY")
        and NAVIGATOR_PROHIBITED_OPERATIONS
        == ("SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL")
        and tuple(item.value for item in ApprovalScope)
        == ("NAVIGATOR_SHADOW_HANDOFF",)
        and tuple(item.value for item in OperatorAction)
        == ("APPROVE_HANDOFF", "REJECT")
    )
    return _check(
        "safety",
        "shadow_boundary",
        CheckStatus.PASS if valid else CheckStatus.FAIL,
        True,
        (
            "Navigator remains inside the canonical SHADOW-only safety envelope"
            if valid
            else "Canonical Navigator or operator safety constants have changed"
        ),
        {
            "navigator_modes": [item.value for item in NavigatorMode],
            "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
            "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
            "approval_scopes": [item.value for item in ApprovalScope],
            "operator_actions": [item.value for item in OperatorAction],
        },
    )


def _validate_fixture_correlations(parsed: Mapping[str, object]) -> None:
    approved = parsed["examples/mission_request.replay.json"]
    held = parsed["examples/mission_request.replay-hold.json"]
    vetoed = parsed["examples/mission_request.replay-stand-down.json"]
    modeldock = parsed["fixtures/modeldock_oracle_narrative.replay.v1.json"]
    proceed = parsed["fixtures/governor_replay_context.proceed.v1.json"]
    hold = parsed["fixtures/governor_replay_context.hold.v1.json"]
    stand_down = parsed["fixtures/governor_replay_context.stand_down.v1.json"]
    navigator_success = parsed["fixtures/navigator_replay.shadow.v1.json"]
    navigator_failure = parsed["fixtures/navigator_replay.intake-failure.v1.json"]
    council = parsed["fixtures/council_replay_policy.v1.json"]
    operator_approve = parsed["fixtures/operator_replay_action.approve.v1.json"]
    operator_reject = parsed["fixtures/operator_replay_action.reject.v1.json"]
    if not all(
        isinstance(request, MissionRequest) and request.run_mode is RunMode.REPLAY
        for request in (approved, held, vetoed)
    ):
        raise ContractValidationError("demo requests must be REPLAY")
    for context, request in ((proceed, approved), (hold, held), (stand_down, vetoed)):
        if not isinstance(context, GovernorSupportingContext) or (
            context.mission_id,
            context.request_id,
            context.run_mode,
        ) != (request.mission_id, request.request_id, RunMode.REPLAY):
            raise ContractValidationError("Governor fixture correlation mismatch")
    if not isinstance(modeldock, ModelDockReplayPack) or (
        modeldock.oracle_input.mission_id,
        modeldock.oracle_input.request_id,
        modeldock.oracle_input.symbol,
        modeldock.oracle_input.run_mode,
    ) != (
        approved.mission_id,
        approved.request_id,
        approved.symbol,
        RunMode.REPLAY,
    ):
        raise ContractValidationError("ModelDock fixture correlation mismatch")
    for navigator in (navigator_success, navigator_failure):
        if not isinstance(navigator, NavigatorReplayFixture) or (
            navigator.mission_id,
            navigator.request_id,
            navigator.run_mode,
            navigator.mode,
        ) != (
            approved.mission_id,
            approved.request_id,
            RunMode.REPLAY,
            NavigatorMode.SHADOW,
        ):
            raise ContractValidationError("Navigator fixture correlation mismatch")
    if not isinstance(council, CouncilSupportingInput) or council.run_mode is not RunMode.REPLAY:
        raise ContractValidationError("Council fixture run mode mismatch")
    if not isinstance(operator_approve, OperatorActionInput) or (
        operator_approve.run_mode,
        operator_approve.action,
    ) != (RunMode.REPLAY, OperatorAction.APPROVE_HANDOFF):
        raise ContractValidationError("operator approval fixture mismatch")
    if not isinstance(operator_reject, OperatorActionInput) or (
        operator_reject.run_mode,
        operator_reject.action,
    ) != (RunMode.REPLAY, OperatorAction.REJECT):
        raise ContractValidationError("operator rejection fixture mismatch")


def _parse_mission_request(payload: bytes) -> MissionRequest:
    from .contracts.mission_request import parse_strict_json_object_bytes

    return MissionRequest.from_mapping(
        parse_strict_json_object_bytes(payload, document_name="mission request")
    )


def _read_contained_regular_file(root: Path, relative_path: str) -> bytes:
    candidate = root.joinpath(*Path(relative_path).parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise PreflightError("fixture must be a regular non-symlink file")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise PreflightError("fixture escapes the Build Week repository")
    if resolved.stat().st_size > 8 * 1024 * 1024:
        raise PreflightError("fixture exceeds the readiness size limit")
    return resolved.read_bytes()


def _check(
    component: str,
    name: str,
    status: CheckStatus,
    required: bool,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> PreflightCheck:
    return PreflightCheck(
        component=component,
        name=name,
        status=status,
        required=required,
        message=message,
        details={} if details is None else copy.deepcopy(dict(details)),
    )


def _git_message(component: str, dirty: bool, strict_clean: bool) -> str:
    if not dirty:
        return f"{component} Git worktree is clean"
    if strict_clean:
        return f"{component} Git worktree is dirty and strict mode rejects it"
    return f"{component} Git worktree is dirty; development mode permits it"


def _safe_configuration_message(exc: BattlestarConfigurationError) -> str:
    message = str(exc)
    safe_prefixes = (
        "BATTLESTAR_PATH",
        "Battlestar",
        "Oracle",
        "candidate",
        "Senate",
        "Mandate",
        "Council",
        "advisor",
        "runtime",
        "Governor",
        "operator",
        "Navigator",
        "configured paths",
    )
    if message.startswith(safe_prefixes) and not Path(message).is_absolute():
        return message
    return "Battlestar configuration failed validation"


def _safe_modeldock_configuration_message(exc: ModelDockConfigurationError) -> str:
    message = str(exc)
    if len(message) <= 300 and "http" not in message.lower() and "/" not in message:
        return message
    return "ModelDock configuration failed validation"


def _safe_interface_failure(exc: BaseException) -> str:
    if isinstance(exc, AttributeError):
        return "entry point is missing"
    if isinstance(exc, TypeError):
        return "entry point is not callable"
    if isinstance(exc, RuntimeError):
        return "module origin does not match BATTLESTAR_PATH"
    return f"{type(exc).__name__} while importing configured interface"
