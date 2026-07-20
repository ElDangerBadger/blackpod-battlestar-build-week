"""Strict committed catalog for deterministic Build Week demonstrations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .contracts import (
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    ModelDockReplayPack,
    OperatorAction,
    RunMode,
)
from .contracts.mission_request import (
    ContractValidationError,
    load_strict_json_object,
)
from .council_adapter import CouncilSupportingInput
from .governor_adapter import GovernorSupportingContext
from .hashing import sha256_file
from .navigator_adapter import NavigatorReplayFixture
from .operator_adapter import OperatorActionInput
from .oracle_adapter import ReplayOracleInput
from .unified_mission_workflow import MissionThrough


DEMO_CATALOG_SCHEMA_VERSION = "blackpod.demo_scenarios.v1"
DEMO_CATALOG_PATH = "fixtures/demo_scenarios.v1.json"
DEMO_SCENARIO_NAMES = (
    "approved",
    "held",
    "vetoed",
    "failed",
    "incomplete",
    "without-modeldock",
)
DEMO_ALLOWED_OPERATIONS = ("VALIDATE", "PLAN_ONLY")
DEMO_PROHIBITED_OPERATIONS = (
    "SUBMIT_ORDER",
    "CANCEL_ORDER",
    "MODIFY_PORTFOLIO",
    "BROKER_CALL",
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_PATH = re.compile(r"(?:/Users/|/private/|/home/|[A-Za-z]:\\)")
_HIGH_CONFIDENCE_SECRET = re.compile(
    r"(?i)(?:sk-proj-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_-]{8,}"
    r"|github_pat_[A-Za-z0-9_-]{8,}|xox[baprs]-[A-Za-z0-9_-]{8,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{8,})"
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


class DemoCatalogError(ContractValidationError):
    """Raised when committed demonstration inputs are not canonical."""


@dataclass(frozen=True, slots=True)
class DemoInputReference:
    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: object, field_name: str) -> "DemoInputReference":
        if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
            raise DemoCatalogError(f"{field_name} must contain path and sha256")
        path = value["path"]
        digest = value["sha256"]
        if not isinstance(path, str) or not path or "\\" in path:
            raise DemoCatalogError(f"{field_name}.path must be a relative POSIX path")
        relative = PurePosixPath(path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != path
            or any(part in {"", "."} for part in relative.parts)
        ):
            raise DemoCatalogError(f"{field_name}.path escapes the repository root")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise DemoCatalogError(f"{field_name}.sha256 must be lowercase SHA-256")
        return cls(path=path, sha256=digest)

    def resolve(self, repository_root: Path) -> Path:
        root = repository_root.resolve(strict=True)
        candidate = root.joinpath(*PurePosixPath(self.path).parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise DemoCatalogError(f"committed demo input is missing or unsafe: {self.path}")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise DemoCatalogError(f"committed demo input escapes the repository: {self.path}")
        if sha256_file(resolved) != self.sha256:
            raise DemoCatalogError(f"committed demo input hash mismatch: {self.path}")
        return resolved

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class DemoScenarioSpec:
    name: str
    request: DemoInputReference
    with_modeldock: bool
    through: MissionThrough
    operator_action: OperatorAction | None
    operator_id: str | None
    operator_reason: str | None
    oracle_fixture: DemoInputReference
    modeldock_fixture: DemoInputReference | None
    council_fixture: DemoInputReference | None
    governor_fixture: DemoInputReference | None
    operator_fixture: DemoInputReference | None
    navigator_fixture: DemoInputReference | None
    expected_outcome: MissionOutcome
    expected_phase: CurrentPhase
    expected_terminal: bool
    expected_snapshot_count: int
    expected_exit_code: int

    @classmethod
    def from_mapping(cls, value: object) -> "DemoScenarioSpec":
        fields = {
            "name",
            "request",
            "with_modeldock",
            "through",
            "operator_action",
            "operator_id",
            "operator_reason",
            "oracle_fixture",
            "modeldock_fixture",
            "council_fixture",
            "governor_fixture",
            "operator_fixture",
            "navigator_fixture",
            "expected_outcome",
            "expected_phase",
            "expected_terminal",
            "expected_snapshot_count",
            "expected_exit_code",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise DemoCatalogError("demo scenario contains missing or unknown fields")
        name = value["name"]
        if name not in DEMO_SCENARIO_NAMES:
            raise DemoCatalogError(f"unsupported demo scenario: {name!r}")
        try:
            through = MissionThrough(value["through"])
            action = (
                None
                if value["operator_action"] is None
                else OperatorAction(value["operator_action"])
            )
            outcome = MissionOutcome(value["expected_outcome"])
            phase = CurrentPhase(value["expected_phase"])
        except (TypeError, ValueError) as exc:
            raise DemoCatalogError("demo scenario contains an unsupported enum") from exc
        with_modeldock = value["with_modeldock"]
        terminal = value["expected_terminal"]
        if type(with_modeldock) is not bool or type(terminal) is not bool:
            raise DemoCatalogError("demo scenario booleans must be true or false")
        snapshot_count = value["expected_snapshot_count"]
        exit_code = value["expected_exit_code"]
        if (
            isinstance(snapshot_count, bool)
            or not isinstance(snapshot_count, int)
            or snapshot_count < 1
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code < 0
        ):
            raise DemoCatalogError("demo expected counts and exit code are invalid")
        operator_id = _optional_text(value["operator_id"], "operator_id", 128)
        operator_reason = _optional_text(
            value["operator_reason"], "operator_reason", 1024
        )
        scenario = cls(
            name=name,
            request=DemoInputReference.from_mapping(value["request"], "request"),
            with_modeldock=with_modeldock,
            through=through,
            operator_action=action,
            operator_id=operator_id,
            operator_reason=operator_reason,
            oracle_fixture=DemoInputReference.from_mapping(
                value["oracle_fixture"], "oracle_fixture"
            ),
            modeldock_fixture=_optional_reference(
                value["modeldock_fixture"], "modeldock_fixture"
            ),
            council_fixture=_optional_reference(
                value["council_fixture"], "council_fixture"
            ),
            governor_fixture=_optional_reference(
                value["governor_fixture"], "governor_fixture"
            ),
            operator_fixture=_optional_reference(
                value["operator_fixture"], "operator_fixture"
            ),
            navigator_fixture=_optional_reference(
                value["navigator_fixture"], "navigator_fixture"
            ),
            expected_outcome=outcome,
            expected_phase=phase,
            expected_terminal=terminal,
            expected_snapshot_count=snapshot_count,
            expected_exit_code=exit_code,
        )
        _validate_canonical_policy(scenario)
        return scenario

    def references(self) -> tuple[DemoInputReference, ...]:
        optional = (
            self.modeldock_fixture,
            self.council_fixture,
            self.governor_fixture,
            self.operator_fixture,
            self.navigator_fixture,
        )
        return (self.request, self.oracle_fixture, *(item for item in optional if item))

    def resolve(self, repository_root: Path) -> "ResolvedDemoScenario":
        paths = {
            reference.path: reference.resolve(repository_root)
            for reference in self.references()
        }
        resolved = ResolvedDemoScenario(
            spec=self,
            request=paths[self.request.path],
            oracle_fixture=paths[self.oracle_fixture.path],
            modeldock_fixture=(
                None
                if self.modeldock_fixture is None
                else paths[self.modeldock_fixture.path]
            ),
            council_fixture=(
                None
                if self.council_fixture is None
                else paths[self.council_fixture.path]
            ),
            governor_fixture=(
                None
                if self.governor_fixture is None
                else paths[self.governor_fixture.path]
            ),
            operator_fixture=(
                None
                if self.operator_fixture is None
                else paths[self.operator_fixture.path]
            ),
            navigator_fixture=(
                None
                if self.navigator_fixture is None
                else paths[self.navigator_fixture.path]
            ),
        )
        resolved.validate_contracts()
        return resolved


@dataclass(frozen=True, slots=True)
class ResolvedDemoScenario:
    spec: DemoScenarioSpec
    request: Path
    oracle_fixture: Path
    modeldock_fixture: Path | None
    council_fixture: Path | None
    governor_fixture: Path | None
    operator_fixture: Path | None
    navigator_fixture: Path | None

    def validate_contracts(self) -> None:
        request = MissionRequest.from_file(self.request)
        if request.run_mode is not RunMode.REPLAY:
            raise DemoCatalogError("demo requests must use REPLAY mode")
        ReplayOracleInput.from_file(self.oracle_fixture)
        if self.modeldock_fixture is not None:
            pack = ModelDockReplayPack.from_file(self.modeldock_fixture)
            if (
                pack.oracle_input.mission_id != request.mission_id
                or pack.oracle_input.request_id != request.request_id
                or pack.oracle_input.symbol != request.symbol
                or pack.oracle_input.run_mode is not RunMode.REPLAY
            ):
                raise DemoCatalogError("ModelDock fixture correlation is inconsistent")
        if self.council_fixture is not None:
            council = CouncilSupportingInput.from_bytes(
                self.council_fixture.read_bytes()
            )
            if council.run_mode is not RunMode.REPLAY:
                raise DemoCatalogError("Council fixture must use REPLAY mode")
        if self.governor_fixture is not None:
            governor = GovernorSupportingContext.from_bytes(
                self.governor_fixture.read_bytes()
            )
            if (
                governor.mission_id != request.mission_id
                or governor.request_id != request.request_id
                or governor.run_mode is not RunMode.REPLAY
            ):
                raise DemoCatalogError("Governor fixture correlation is inconsistent")
        if self.operator_fixture is not None:
            operator = OperatorActionInput.from_replay_bytes(
                self.operator_fixture.read_bytes()
            )
            if (
                operator.action is not self.spec.operator_action
                or operator.operator_id != self.spec.operator_id
                or operator.reason != self.spec.operator_reason
            ):
                raise DemoCatalogError("operator fixture differs from scenario controls")
        if self.navigator_fixture is not None:
            navigator = NavigatorReplayFixture.from_bytes(
                self.navigator_fixture.read_bytes()
            )
            if (
                navigator.mission_id != request.mission_id
                or navigator.request_id != request.request_id
                or navigator.run_mode is not RunMode.REPLAY
                or navigator.mode.value != "SHADOW"
            ):
                raise DemoCatalogError("Navigator fixture correlation is inconsistent")
        fixture_paths = (
            self.request,
            self.oracle_fixture,
            self.modeldock_fixture,
            self.council_fixture,
            self.governor_fixture,
            self.operator_fixture,
            self.navigator_fixture,
        )
        for path in fixture_paths:
            if path is not None:
                _scan_security(load_strict_json_object(path))


@dataclass(frozen=True, slots=True)
class DemoCatalog:
    schema_version: str
    shadow_only: bool
    allowed_operations: tuple[str, ...]
    prohibited_operations: tuple[str, ...]
    scenarios: tuple[DemoScenarioSpec, ...]
    repository_root: Path

    def scenario(self, name: str) -> DemoScenarioSpec:
        for scenario in self.scenarios:
            if scenario.name == name:
                return scenario
        raise DemoCatalogError(f"demo scenario is not committed: {name}")


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "pyproject.toml").is_file():
        raise DemoCatalogError(
            "demo commands require a BlackPod Build Week source checkout"
        )
    return root


def load_demo_catalog(
    *,
    root: Path | None = None,
    catalog_path: Path | None = None,
) -> DemoCatalog:
    active_root = (root or repository_root()).resolve(strict=True)
    path = catalog_path or active_root / DEMO_CATALOG_PATH
    if path.is_symlink() or not path.is_file():
        raise DemoCatalogError("demo scenario catalog is missing or unsafe")
    resolved_path = path.resolve(strict=True)
    if not resolved_path.is_relative_to(active_root):
        raise DemoCatalogError("demo scenario catalog must remain in the repository")
    value = load_strict_json_object(resolved_path)
    if set(value) != {"schema_version", "safety", "scenarios"}:
        raise DemoCatalogError("demo scenario catalog contains unknown fields")
    if value["schema_version"] != DEMO_CATALOG_SCHEMA_VERSION:
        raise DemoCatalogError("unsupported demo scenario catalog schema_version")
    safety = value["safety"]
    if not isinstance(safety, Mapping) or set(safety) != {
        "shadow_only",
        "allowed_operations",
        "prohibited_operations",
    }:
        raise DemoCatalogError("demo safety declaration is malformed")
    if safety["shadow_only"] is not True:
        raise DemoCatalogError("demo catalog must declare SHADOW-only operation")
    allowed = _string_tuple(safety["allowed_operations"], "allowed_operations")
    prohibited = _string_tuple(
        safety["prohibited_operations"], "prohibited_operations"
    )
    if allowed != DEMO_ALLOWED_OPERATIONS:
        raise DemoCatalogError("demo allowed operations exceed VALIDATE and PLAN_ONLY")
    if prohibited != DEMO_PROHIBITED_OPERATIONS:
        raise DemoCatalogError("demo prohibited operation declaration is incomplete")
    raw_scenarios = value["scenarios"]
    if not isinstance(raw_scenarios, list):
        raise DemoCatalogError("demo scenarios must be an array")
    scenarios = tuple(DemoScenarioSpec.from_mapping(item) for item in raw_scenarios)
    if tuple(item.name for item in scenarios) != DEMO_SCENARIO_NAMES:
        raise DemoCatalogError("demo scenarios must use canonical order and coverage")
    _scan_security(value)
    catalog = DemoCatalog(
        schema_version=DEMO_CATALOG_SCHEMA_VERSION,
        shadow_only=True,
        allowed_operations=allowed,
        prohibited_operations=prohibited,
        scenarios=scenarios,
        repository_root=active_root,
    )
    for scenario in scenarios:
        scenario.resolve(active_root)
    return catalog


def _optional_reference(value: object, field_name: str) -> DemoInputReference | None:
    if value is None:
        return None
    return DemoInputReference.from_mapping(value, field_name)


def _optional_text(value: object, field_name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise DemoCatalogError(f"{field_name} must be a bounded trimmed string")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise DemoCatalogError(f"{field_name} must be a string array")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise DemoCatalogError(f"{field_name} values must be unique")
    return result


_POLICIES: dict[str, tuple[object, ...]] = {
    "approved": (
        True,
        "NAVIGATOR",
        "APPROVE_HANDOFF",
        "APPROVED",
        "COMPLETE",
        True,
        13,
        0,
    ),
    "held": (True, "GOVERNOR", None, "HELD", "OPERATOR", False, 9, 0),
    "vetoed": (True, "OPERATOR", "REJECT", "VETOED", "COMPLETE", True, 11, 0),
    "failed": (True, "NAVIGATOR", "APPROVE_HANDOFF", "FAILED", "NAVIGATOR", True, 13, 11),
    "incomplete": (True, "ORACLE", None, "INCOMPLETE", "COUNCIL", False, 5, 0),
    "without-modeldock": (
        False,
        "NAVIGATOR",
        "APPROVE_HANDOFF",
        "APPROVED",
        "COMPLETE",
        True,
        11,
        0,
    ),
}


def _validate_canonical_policy(scenario: DemoScenarioSpec) -> None:
    actual = (
        scenario.with_modeldock,
        scenario.through.value,
        None if scenario.operator_action is None else scenario.operator_action.value,
        scenario.expected_outcome.value,
        scenario.expected_phase.value,
        scenario.expected_terminal,
        scenario.expected_snapshot_count,
        scenario.expected_exit_code,
    )
    if actual != _POLICIES[scenario.name]:
        raise DemoCatalogError(
            f"demo scenario policy changed unexpectedly: {scenario.name}"
        )
    needs_operator = scenario.through in {
        MissionThrough.OPERATOR,
        MissionThrough.NAVIGATOR,
    }
    if needs_operator != (scenario.operator_action is not None):
        raise DemoCatalogError("demo operator controls do not match the target stage")
    if needs_operator and (
        scenario.operator_id is None
        or scenario.operator_reason is None
        or scenario.operator_fixture is None
    ):
        raise DemoCatalogError("demo operator controls are incomplete")
    if not needs_operator and any(
        item is not None
        for item in (
            scenario.operator_id,
            scenario.operator_reason,
            scenario.operator_fixture,
        )
    ):
        raise DemoCatalogError("demo contains unused operator controls")
    if scenario.with_modeldock != (scenario.modeldock_fixture is not None):
        raise DemoCatalogError("demo ModelDock mode and fixture disagree")


def _scan_security(value: object, *, parent_key: str | None = None) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS:
                raise DemoCatalogError("demo pack contains a secret-like field")
            if normalized in {"allowed_operations", "operation", "action"}:
                candidates = item if isinstance(item, list) else [item]
                if any(
                    candidate in DEMO_PROHIBITED_OPERATIONS
                    for candidate in candidates
                ):
                    raise DemoCatalogError(
                        "demo pack attempts to authorize a prohibited operation"
                    )
            _scan_security(item, parent_key=normalized)
        return
    if isinstance(value, list):
        for item in value:
            _scan_security(item, parent_key=parent_key)
        return
    if isinstance(value, str):
        if _LOCAL_PATH.search(value):
            raise DemoCatalogError("demo pack contains a machine-local absolute path")
        if _HIGH_CONFIDENCE_SECRET.search(value):
            raise DemoCatalogError("demo pack contains a secret-like value")
