"""Strict, portable presentation manifest for a rehearsed Build Week demo."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_request import ContractValidationError, RunMode, normalize_rfc3339
from .mission_snapshot import (
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ArtifactReference,
    MissionOutcome,
)
from .presentation import (
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    CANONICAL_SNAPSHOT_PATH,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_SCHEMA_VERSION,
)


DEMO_MANIFEST_SCHEMA_VERSION = "blackpod.demo_manifest.v1"
DEMO_MANIFEST_PATH = "presentation/demo_manifest.json"
SHADOW_ONLY_DECLARATION = "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION"

_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_SECRET_LIKE = re.compile(
    r"(?:api[_-]?key|authorization|password|secret|token)\s*[:=]",
    re.IGNORECASE,
)


class DemoScenario(str, Enum):
    APPROVED = "approved"
    HELD = "held"
    VETOED = "vetoed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class DemoModelDockMode(str, Enum):
    REPLAYED = "REPLAYED"
    LIVE = "LIVE"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], name: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _text(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
    max_length: int = 512,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank string")
    if value != value.strip():
        raise ContractValidationError(
            f"{field_name} may not have surrounding whitespace"
        )
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise ContractValidationError(
            f"{field_name} exceeds the portable text safety envelope"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(
            f"{field_name} must contain valid Unicode text"
        ) from exc
    return value


def _identity(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
    allow_url: bool = False,
) -> str | None:
    identity = _text(value, field_name, allow_none=allow_none)
    if identity is None:
        return None
    if (
        identity.startswith(("/", "~"))
        or _WINDOWS_ABSOLUTE_PATH.match(identity)
        or "\\" in identity
        or _SECRET_LIKE.search(identity)
    ):
        raise ContractValidationError(
            f"{field_name} may not contain local paths or credential-like material"
        )
    if "://" not in identity:
        path = PurePosixPath(identity)
        if ".." in path.parts or any(part in {"", "."} for part in path.parts):
            raise ContractValidationError(
                f"{field_name} may not contain a traversing path"
            )
    elif not allow_url:
        raise ContractValidationError(f"{field_name} may not contain a URL")
    return identity


def _git_revision(value: object, field_name: str) -> str:
    revision = _text(value, field_name, max_length=64)
    if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(revision):
        raise ContractValidationError(
            f"{field_name} must be 7 to 64 lowercase hexadecimal characters"
        )
    return revision


def _complete_reference(
    value: object,
    *,
    field_name: str,
    expected_name: str,
    expected_path: str,
    expected_schema: str,
    generated_at: str,
) -> ArtifactReference:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field_name} must be an object")
    reference = ArtifactReference.from_mapping(value)
    if (
        reference.name != expected_name
        or reference.path != expected_path
        or reference.producer != "harbormaster"
        or reference.byte_size is None
        or reference.byte_size == 0
        or reference.schema_version != expected_schema
        or reference.observed_at != generated_at
    ):
        raise ContractValidationError(
            f"{field_name} must be a complete Harbormaster reference to "
            f"{expected_path}"
        )
    return reference


def _operations(
    value: object, *, field_name: str, expected: tuple[str, ...]
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractValidationError(f"{field_name} must be an array of strings")
    operations = tuple(value)
    if operations != expected:
        raise ContractValidationError(
            f"{field_name} must preserve the exact Navigator SHADOW safety policy"
        )
    return operations


@dataclass(frozen=True, slots=True)
class DemoManifest:
    schema_version: str
    demo_scenario: DemoScenario
    mission_id: str
    symbol: str
    run_mode: RunMode
    build_week_revision: str
    battlestar_revision: str
    modeldock_mode: DemoModelDockMode
    modeldock_revision_or_service_identity: str | None
    modeldock_provider: str | None
    modeldock_model: str | None
    modeldock_trace_id: str | None
    final_outcome: MissionOutcome
    snapshot_count: int
    captains_log: ArtifactReference
    mission_summary: ArtifactReference
    final_snapshot: ArtifactReference
    generated_at: str
    shadow_only_declaration: str
    allowed_operations: tuple[str, ...]
    prohibited_operations: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DemoManifest":
        if not isinstance(value, Mapping):
            raise ContractValidationError("demo manifest must be an object")
        fields = {
            "schema_version",
            "demo_scenario",
            "mission_id",
            "symbol",
            "run_mode",
            "build_week_revision",
            "battlestar_revision",
            "modeldock_mode",
            "modeldock_revision_or_service_identity",
            "modeldock_provider",
            "modeldock_model",
            "modeldock_trace_id",
            "final_outcome",
            "snapshot_count",
            "captains_log",
            "mission_summary",
            "final_snapshot",
            "generated_at",
            "shadow_only_declaration",
            "allowed_operations",
            "prohibited_operations",
        }
        _require_exact_fields(value, fields, "demo manifest")
        if value["schema_version"] != DEMO_MANIFEST_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported demo manifest schema_version: {value['schema_version']!r}"
            )
        try:
            scenario = DemoScenario(value["demo_scenario"])
            run_mode = RunMode(value["run_mode"])
            modeldock_mode = DemoModelDockMode(value["modeldock_mode"])
            final_outcome = MissionOutcome(value["final_outcome"])
            mission_id = validate_mission_id(value["mission_id"])
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "demo manifest contains an unsupported enum"
            ) from exc
        if scenario.value.upper() != final_outcome.value:
            raise ContractValidationError(
                "demo_scenario must match the canonical final_outcome"
            )
        snapshot_count = value["snapshot_count"]
        if (
            isinstance(snapshot_count, bool)
            or not isinstance(snapshot_count, int)
            or snapshot_count < 1
        ):
            raise ContractValidationError("snapshot_count must be a positive integer")
        generated_at = normalize_rfc3339(
            value["generated_at"], "demo manifest generated_at"
        )
        provider = _identity(
            value["modeldock_provider"], "modeldock_provider", allow_none=True
        )
        model = _identity(
            value["modeldock_model"], "modeldock_model", allow_none=True
        )
        trace = value["modeldock_trace_id"]
        if trace is not None:
            try:
                trace = validate_identifier(trace, "modeldock_trace_id")
            except IdentifierError as exc:
                raise ContractValidationError(str(exc)) from exc
        revision_or_identity = _identity(
            value["modeldock_revision_or_service_identity"],
            "modeldock_revision_or_service_identity",
            allow_none=True,
            allow_url=True,
        )
        response_identity = (provider, model, trace)
        if modeldock_mode in {DemoModelDockMode.REPLAYED, DemoModelDockMode.LIVE}:
            if revision_or_identity is None or any(
                item is None for item in response_identity
            ):
                raise ContractValidationError(
                    "successful ModelDock demo modes require service identity, "
                    "provider, model, and trace_id"
                )
        elif modeldock_mode is DemoModelDockMode.DISABLED:
            if revision_or_identity is not None or any(
                item is not None for item in response_identity
            ):
                raise ContractValidationError(
                    "DISABLED ModelDock mode may not claim ModelDock response identity"
                )
        elif final_outcome is not MissionOutcome.FAILED:
            raise ContractValidationError(
                "FAILED ModelDock mode requires canonical FAILED outcome"
            )
        if run_mode is RunMode.REPLAY and modeldock_mode is DemoModelDockMode.LIVE:
            raise ContractValidationError("REPLAY missions may not claim LIVE ModelDock")
        if run_mode is RunMode.LIVE and modeldock_mode is DemoModelDockMode.REPLAYED:
            raise ContractValidationError("LIVE missions may not claim replayed ModelDock")
        if value["shadow_only_declaration"] != SHADOW_ONLY_DECLARATION:
            raise ContractValidationError(
                "demo manifest must carry the canonical SHADOW-only declaration"
            )
        return cls(
            schema_version=DEMO_MANIFEST_SCHEMA_VERSION,
            demo_scenario=scenario,
            mission_id=mission_id,
            symbol=str(_text(value["symbol"], "demo symbol", max_length=64)),
            run_mode=run_mode,
            build_week_revision=_git_revision(
                value["build_week_revision"], "build_week_revision"
            ),
            battlestar_revision=_git_revision(
                value["battlestar_revision"], "battlestar_revision"
            ),
            modeldock_mode=modeldock_mode,
            modeldock_revision_or_service_identity=revision_or_identity,
            modeldock_provider=provider,
            modeldock_model=model,
            modeldock_trace_id=trace,
            final_outcome=final_outcome,
            snapshot_count=snapshot_count,
            captains_log=_complete_reference(
                value["captains_log"],
                field_name="captains_log",
                expected_name="captains_log",
                expected_path=CAPTAINS_LOG_PATH,
                expected_schema=CAPTAINS_LOG_SCHEMA_VERSION,
                generated_at=generated_at,
            ),
            mission_summary=_complete_reference(
                value["mission_summary"],
                field_name="mission_summary",
                expected_name="mission_summary",
                expected_path=MISSION_SUMMARY_PATH,
                expected_schema=MISSION_SUMMARY_SCHEMA_VERSION,
                generated_at=generated_at,
            ),
            final_snapshot=_complete_reference(
                value["final_snapshot"],
                field_name="final_snapshot",
                expected_name="mission_snapshot",
                expected_path=CANONICAL_SNAPSHOT_PATH,
                expected_schema=MISSION_SNAPSHOT_SCHEMA_VERSION,
                generated_at=generated_at,
            ),
            generated_at=generated_at,
            shadow_only_declaration=SHADOW_ONLY_DECLARATION,
            allowed_operations=_operations(
                value["allowed_operations"],
                field_name="allowed_operations",
                expected=NAVIGATOR_ALLOWED_OPERATIONS,
            ),
            prohibited_operations=_operations(
                value["prohibited_operations"],
                field_name="prohibited_operations",
                expected=NAVIGATOR_PROHIBITED_OPERATIONS,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "demo_scenario": self.demo_scenario.value,
            "mission_id": self.mission_id,
            "symbol": self.symbol,
            "run_mode": self.run_mode.value,
            "build_week_revision": self.build_week_revision,
            "battlestar_revision": self.battlestar_revision,
            "modeldock_mode": self.modeldock_mode.value,
            "modeldock_revision_or_service_identity": (
                self.modeldock_revision_or_service_identity
            ),
            "modeldock_provider": self.modeldock_provider,
            "modeldock_model": self.modeldock_model,
            "modeldock_trace_id": self.modeldock_trace_id,
            "final_outcome": self.final_outcome.value,
            "snapshot_count": self.snapshot_count,
            "captains_log": self.captains_log.to_dict(),
            "mission_summary": self.mission_summary.to_dict(),
            "final_snapshot": self.final_snapshot.to_dict(),
            "generated_at": self.generated_at,
            "shadow_only_declaration": self.shadow_only_declaration,
            "allowed_operations": list(self.allowed_operations),
            "prohibited_operations": list(self.prohibited_operations),
        }
