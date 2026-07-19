"""Canonical mission snapshot contract for the Build Week submission."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_request import (
    ContractValidationError,
    RunMode,
    normalize_rfc3339,
    parse_rfc3339,
)


MISSION_SNAPSHOT_SCHEMA_VERSION = "blackpod.mission_snapshot.v1"
STAGE_NAMES = ("harbormaster", "oracle", "council", "governor", "navigator")
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "snapshot_id",
        "mission_id",
        "request_id",
        "revision",
        "previous_snapshot_sha256",
        "run_mode",
        "started_at",
        "observed_at",
        "mission_outcome",
        "current_phase",
        "terminal",
        "stages",
        "artifacts",
    }
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class MissionOutcome(str, Enum):
    APPROVED = "APPROVED"
    HELD = "HELD"
    VETOED = "VETOED"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class CurrentPhase(str, Enum):
    HARBORMASTER = "HARBORMASTER"
    ORACLE = "ORACLE"
    COUNCIL = "COUNCIL"
    GOVERNOR = "GOVERNOR"
    OPERATOR = "OPERATOR"
    NAVIGATOR = "NAVIGATOR"
    COMPLETE = "COMPLETE"


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    fields = set(value)
    missing = expected - fields
    unknown = fields - expected
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _parse_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(member.value for member in enum_type)
        raise ContractValidationError(
            f"unsupported {field_name}: {value!r}; expected one of {choices}"
        ) from exc


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    status: StageStatus
    native_state: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], stage_name: str) -> "StageSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError(f"stage {stage_name} must be an object")
        _require_exact_fields(value, {"status", "native_state"}, f"stage {stage_name}")
        status = _parse_enum(StageStatus, value["status"], f"{stage_name}.status")
        native_state = value["native_state"]
        if native_state is not None:
            if not isinstance(native_state, str) or not native_state.strip():
                raise ContractValidationError(
                    f"{stage_name}.native_state must be null or a nonblank string"
                )
            if native_state != native_state.strip():
                raise ContractValidationError(
                    f"{stage_name}.native_state may not have surrounding whitespace"
                )
            try:
                native_state.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ContractValidationError(
                    f"{stage_name}.native_state must contain valid Unicode text"
                ) from exc
        return cls(status=status, native_state=native_state)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "native_state": self.native_state}


def _validate_relative_artifact_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractValidationError("artifact path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ContractValidationError("artifact path must remain beneath the mission root")
    if any(part in {"", "."} for part in path.parts):
        raise ContractValidationError("artifact path contains an unsafe segment")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("artifact path must contain valid Unicode text") from exc
    return value


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    name: str
    path: str
    sha256: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactReference":
        if not isinstance(value, Mapping):
            raise ContractValidationError("artifact reference must be an object")
        _require_exact_fields(value, {"name", "path", "sha256"}, "artifact reference")
        try:
            name = validate_identifier(value["name"], "artifact name")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        digest = value["sha256"]
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ContractValidationError("artifact sha256 must be 64 lowercase hex characters")
        return cls(
            name=name,
            path=_validate_relative_artifact_path(value["path"]),
            sha256=digest,
        )

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    schema_version: str
    snapshot_id: str
    mission_id: str
    request_id: str
    revision: int
    previous_snapshot_sha256: str | None
    run_mode: RunMode
    started_at: str
    observed_at: str
    mission_outcome: MissionOutcome
    current_phase: CurrentPhase
    terminal: bool
    stages: dict[str, StageSnapshot]
    artifacts: tuple[ArtifactReference, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission snapshot must be an object")
        _require_exact_fields(value, set(_SNAPSHOT_FIELDS), "mission snapshot")
        if value["schema_version"] != MISSION_SNAPSHOT_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported schema_version: {value['schema_version']!r}; expected "
                f"{MISSION_SNAPSHOT_SCHEMA_VERSION!r}"
            )

        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if mission_id == request_id:
            raise ContractValidationError("mission_id must be distinct from request_id")

        revision = value["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ContractValidationError("revision must be an integer greater than zero")
        expected_snapshot_id = f"{mission_id}-r{revision:04d}"
        if value["snapshot_id"] != expected_snapshot_id:
            raise ContractValidationError(
                f"snapshot_id must be {expected_snapshot_id!r} for revision {revision}"
            )

        previous_digest = value["previous_snapshot_sha256"]
        if revision == 1:
            if previous_digest is not None:
                raise ContractValidationError(
                    "revision 1 previous_snapshot_sha256 must be null"
                )
        elif not isinstance(previous_digest, str) or not _SHA256_PATTERN.fullmatch(
            previous_digest
        ):
            raise ContractValidationError(
                "later revisions require a 64-character previous snapshot SHA-256"
            )

        started_at = normalize_rfc3339(value["started_at"], "started_at")
        observed_at = normalize_rfc3339(value["observed_at"], "observed_at")
        if parse_rfc3339(observed_at, "observed_at") < parse_rfc3339(
            started_at, "started_at"
        ):
            raise ContractValidationError("observed_at may not precede started_at")

        stages_value = value["stages"]
        if not isinstance(stages_value, Mapping):
            raise ContractValidationError("stages must be an object")
        if set(stages_value) != set(STAGE_NAMES):
            raise ContractValidationError(
                "stages must contain exactly: " + ", ".join(STAGE_NAMES)
            )
        stages = {
            stage_name: StageSnapshot.from_mapping(stages_value[stage_name], stage_name)
            for stage_name in STAGE_NAMES
        }

        artifacts_value = value["artifacts"]
        if not isinstance(artifacts_value, list):
            raise ContractValidationError("artifacts must be an array")
        artifacts = tuple(ArtifactReference.from_mapping(item) for item in artifacts_value)
        if len({item.name for item in artifacts}) != len(artifacts):
            raise ContractValidationError("artifact names must be unique")
        if len({item.path for item in artifacts}) != len(artifacts):
            raise ContractValidationError("artifact paths must be unique")

        terminal = value["terminal"]
        if type(terminal) is not bool:
            raise ContractValidationError("terminal must be a boolean")

        return cls(
            schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=expected_snapshot_id,
            mission_id=mission_id,
            request_id=request_id,
            revision=revision,
            previous_snapshot_sha256=previous_digest,
            run_mode=_parse_enum(RunMode, value["run_mode"], "run_mode"),
            started_at=started_at,
            observed_at=observed_at,
            mission_outcome=_parse_enum(
                MissionOutcome, value["mission_outcome"], "mission_outcome"
            ),
            current_phase=_parse_enum(
                CurrentPhase, value["current_phase"], "current_phase"
            ),
            terminal=terminal,
            stages=stages,
            artifacts=artifacts,
        )

    @classmethod
    def create_phase1(
        cls,
        *,
        mission_id: str,
        request_id: str,
        run_mode: RunMode,
        started_at: str,
        observed_at: str,
        request_artifact: ArtifactReference,
    ) -> "MissionSnapshot":
        stages = {
            "harbormaster": StageSnapshot(
                status=StageStatus.SUCCEEDED,
                native_state="INITIALIZED",
            ),
            "oracle": StageSnapshot(StageStatus.NOT_STARTED, None),
            "council": StageSnapshot(StageStatus.NOT_STARTED, None),
            "governor": StageSnapshot(StageStatus.NOT_STARTED, None),
            "navigator": StageSnapshot(StageStatus.NOT_STARTED, None),
        }
        outcome = derive_phase1_outcome(stages)
        return cls.from_mapping(
            {
                "schema_version": MISSION_SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": f"{mission_id}-r0001",
                "mission_id": mission_id,
                "request_id": request_id,
                "revision": 1,
                "previous_snapshot_sha256": None,
                "run_mode": run_mode.value,
                "started_at": started_at,
                "observed_at": observed_at,
                "mission_outcome": outcome.value,
                "current_phase": CurrentPhase.ORACLE.value,
                "terminal": False,
                "stages": {name: stage.to_dict() for name, stage in stages.items()},
                "artifacts": [request_artifact.to_dict()],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "revision": self.revision,
            "previous_snapshot_sha256": self.previous_snapshot_sha256,
            "run_mode": self.run_mode.value,
            "started_at": self.started_at,
            "observed_at": self.observed_at,
            "mission_outcome": self.mission_outcome.value,
            "current_phase": self.current_phase.value,
            "terminal": self.terminal,
            "stages": {name: self.stages[name].to_dict() for name in STAGE_NAMES},
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


def derive_phase1_outcome(stages: Mapping[str, StageSnapshot]) -> MissionOutcome:
    """Derive the only successful Phase 1 outcome without future policy."""

    if set(stages) != set(STAGE_NAMES):
        raise ContractValidationError("Phase 1 requires all canonical stages")
    if stages["harbormaster"].status is not StageStatus.SUCCEEDED:
        raise ContractValidationError("Phase 1 requires Harbormaster to succeed")
    if any(
        stages[name].status is not StageStatus.NOT_STARTED
        for name in STAGE_NAMES
        if name != "harbormaster"
    ):
        raise ContractValidationError(
            "Phase 1 requires all downstream stages to remain NOT_STARTED"
        )
    return MissionOutcome.INCOMPLETE
