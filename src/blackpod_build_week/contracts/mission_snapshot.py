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
_SNAPSHOT_BASE_FIELDS = frozenset(
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
_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")


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


class OracleTransportKind(str, Enum):
    LIVE_YFINANCE = "LIVE_YFINANCE"
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


class CouncilTransportKind(str, Enum):
    LIVE_MISSION_INPUTS = "LIVE_MISSION_INPUTS"
    REPLAY_FIXTURE = "REPLAY_FIXTURE"


def _require_exact_fields(
    value: Mapping[str, Any], expected: set[str], name: str
) -> None:
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


def _parse_enum(enum_type: type[Enum], value: object, field_name: str) -> Any:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(str(member.value) for member in enum_type)
        raise ContractValidationError(
            f"unsupported {field_name}: {value!r}; expected one of {choices}"
        ) from exc


def _validate_text(
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
        raise ContractValidationError(f"{field_name} may not have surrounding whitespace")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{field_name} must contain valid Unicode text") from exc
    return value


def _artifact_names(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be an array")
    names: list[str] = []
    for item in value:
        try:
            name = validate_identifier(item, field_name)
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        names.append(name)
    if len(set(names)) != len(names):
        raise ContractValidationError(f"{field_name} values must be unique")
    return tuple(names)


@dataclass(frozen=True, slots=True)
class StageError:
    code: str
    error_type: str
    message: str
    resumable: bool
    observed_at: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StageError":
        if not isinstance(value, Mapping):
            raise ContractValidationError("stage error must be an object")
        _require_exact_fields(
            value,
            {"code", "error_type", "message", "resumable", "observed_at"},
            "stage error",
        )
        try:
            code = validate_identifier(value["code"], "stage error code")
            error_type = validate_identifier(value["error_type"], "stage error type")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if type(value["resumable"]) is not bool:
            raise ContractValidationError("stage error resumable must be a boolean")
        return cls(
            code=code,
            error_type=error_type,
            message=str(_validate_text(value["message"], "stage error message")),
            resumable=value["resumable"],
            observed_at=normalize_rfc3339(value["observed_at"], "stage error observed_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "error_type": self.error_type,
            "message": self.message,
            "resumable": self.resumable,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    status: StageStatus
    native_state: str | None
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    error: StageError | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], stage_name: str) -> "StageSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError(f"stage {stage_name} must be an object")
        fields = set(value)
        legacy_fields = {"status", "native_state"}
        current_fields = legacy_fields | {"inputs", "outputs", "error"}
        if fields == legacy_fields:
            inputs: tuple[str, ...] = ()
            outputs: tuple[str, ...] = ()
            error = None
        elif fields == current_fields:
            inputs = _artifact_names(value["inputs"], f"{stage_name}.inputs")
            outputs = _artifact_names(value["outputs"], f"{stage_name}.outputs")
            error_value = value["error"]
            error = None if error_value is None else StageError.from_mapping(error_value)
        else:
            _require_exact_fields(value, current_fields, f"stage {stage_name}")
            raise AssertionError("unreachable")

        status = _parse_enum(StageStatus, value["status"], f"{stage_name}.status")
        native_state = _validate_text(
            value["native_state"],
            f"{stage_name}.native_state",
            allow_none=True,
            max_length=128,
        )
        if status is StageStatus.NOT_STARTED and (
            native_state is not None or inputs or outputs or error is not None
        ):
            raise ContractValidationError(
                f"{stage_name} NOT_STARTED may not contain native state, I/O, or an error"
            )
        if status is StageStatus.FAILED and error is None:
            raise ContractValidationError(f"{stage_name} FAILED requires a structured error")
        if status is not StageStatus.FAILED and error is not None:
            raise ContractValidationError(
                f"{stage_name} may contain an error only when status is FAILED"
            )
        return cls(
            status=status,
            native_state=native_state,
            inputs=inputs,
            outputs=outputs,
            error=error,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "native_state": self.native_state,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "error": None if self.error is None else self.error.to_dict(),
        }


def _validate_relative_artifact_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContractValidationError("artifact path must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ContractValidationError("artifact path must remain beneath the mission root")
    if any(part in {"", "."} for part in path.parts):
        raise ContractValidationError("artifact path contains an unsafe segment")
    _validate_text(value, "artifact path", max_length=512)
    return value


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    name: str
    path: str
    sha256: str
    producer: str | None = None
    byte_size: int | None = None
    schema_version: str | None = None
    observed_at: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactReference":
        if not isinstance(value, Mapping):
            raise ContractValidationError("artifact reference must be an object")
        fields = set(value)
        legacy_fields = {"name", "path", "sha256"}
        current_fields = legacy_fields | {
            "producer",
            "byte_size",
            "schema_version",
            "observed_at",
        }
        if fields == legacy_fields:
            producer = None
            byte_size = None
            schema_version = None
            observed_at = None
        elif fields == current_fields:
            producer_value = value["producer"]
            try:
                producer = validate_identifier(producer_value, "artifact producer")
            except IdentifierError as exc:
                raise ContractValidationError(str(exc)) from exc
            byte_size_value = value["byte_size"]
            if (
                isinstance(byte_size_value, bool)
                or not isinstance(byte_size_value, int)
                or byte_size_value < 0
            ):
                raise ContractValidationError(
                    "artifact byte_size must be a nonnegative integer"
                )
            byte_size = byte_size_value
            schema_version = _validate_text(
                value["schema_version"],
                "artifact schema_version",
                allow_none=True,
                max_length=128,
            )
            observed_value = value["observed_at"]
            observed_at = normalize_rfc3339(observed_value, "artifact observed_at")
        else:
            _require_exact_fields(value, current_fields, "artifact reference")
            raise AssertionError("unreachable")

        try:
            name = validate_identifier(value["name"], "artifact name")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        digest = value["sha256"]
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise ContractValidationError(
                "artifact sha256 must be 64 lowercase hex characters"
            )
        return cls(
            name=name,
            path=_validate_relative_artifact_path(value["path"]),
            sha256=digest,
            producer=producer,
            byte_size=byte_size,
            schema_version=schema_version,
            observed_at=observed_at,
        )

    def to_dict(self) -> dict[str, Any]:
        if (
            self.producer is None
            and self.byte_size is None
            and self.schema_version is None
            and self.observed_at is None
        ):
            return {"name": self.name, "path": self.path, "sha256": self.sha256}
        return {
            "name": self.name,
            "path": self.path,
            "sha256": self.sha256,
            "producer": self.producer,
            "byte_size": self.byte_size,
            "schema_version": self.schema_version,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class ComponentProvenance:
    git_revision: str
    git_branch: str | None
    dirty_worktree: bool
    oracle_entry_point: str
    run_mode: RunMode
    transport: OracleTransportKind
    replay_fixture_id: str | None
    replay_fixture_sha256: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ComponentProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError("component provenance must be an object")
        _require_exact_fields(
            value,
            {
                "git_revision",
                "git_branch",
                "dirty_worktree",
                "oracle_entry_point",
                "run_mode",
                "transport",
                "replay_fixture_id",
                "replay_fixture_sha256",
            },
            "component provenance",
        )
        revision = value["git_revision"]
        if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(revision):
            raise ContractValidationError("git_revision must be a hexadecimal Git object ID")
        branch = _validate_text(
            value["git_branch"], "git_branch", allow_none=True, max_length=256
        )
        if type(value["dirty_worktree"]) is not bool:
            raise ContractValidationError("dirty_worktree must be a boolean")
        run_mode = _parse_enum(RunMode, value["run_mode"], "component run_mode")
        transport = _parse_enum(
            OracleTransportKind, value["transport"], "Oracle transport"
        )
        fixture_id = _validate_text(
            value["replay_fixture_id"],
            "replay_fixture_id",
            allow_none=True,
            max_length=128,
        )
        fixture_sha = value["replay_fixture_sha256"]
        if fixture_sha is not None and (
            not isinstance(fixture_sha, str) or not _SHA256_PATTERN.fullmatch(fixture_sha)
        ):
            raise ContractValidationError(
                "replay_fixture_sha256 must be null or 64 lowercase hex characters"
            )
        if transport is OracleTransportKind.REPLAY_FIXTURE:
            if run_mode is not RunMode.REPLAY or fixture_id is None or fixture_sha is None:
                raise ContractValidationError(
                    "REPLAY_FIXTURE provenance requires REPLAY mode and fixture identity"
                )
        elif run_mode is not RunMode.LIVE or fixture_id is not None or fixture_sha is not None:
            raise ContractValidationError(
                "LIVE_YFINANCE provenance requires LIVE mode and no replay fixture"
            )
        return cls(
            git_revision=revision,
            git_branch=branch,
            dirty_worktree=value["dirty_worktree"],
            oracle_entry_point=str(
                _validate_text(
                    value["oracle_entry_point"],
                    "oracle_entry_point",
                    max_length=256,
                )
            ),
            run_mode=run_mode,
            transport=transport,
            replay_fixture_id=fixture_id,
            replay_fixture_sha256=fixture_sha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "git_branch": self.git_branch,
            "dirty_worktree": self.dirty_worktree,
            "oracle_entry_point": self.oracle_entry_point,
            "run_mode": self.run_mode.value,
            "transport": self.transport.value,
            "replay_fixture_id": self.replay_fixture_id,
            "replay_fixture_sha256": self.replay_fixture_sha256,
        }


@dataclass(frozen=True, slots=True)
class CouncilComponentProvenance:
    """Immutable provenance for the Battlestar Council evidence chain."""

    git_revision: str
    git_branch: str | None
    dirty_worktree: bool
    candidate_entry_point: str
    senate_review_entry_point: str
    senate_deliberation_entry_point: str
    mandate_entry_point: str
    runtime_validation_entry_point: str
    advisor_health_entry_point: str
    council_synthesis_entry_point: str
    council_executive_summary_entry_point: str
    run_mode: RunMode
    transport: CouncilTransportKind
    replay_fixture_id: str | None
    replay_fixture_sha256: str | None

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> "CouncilComponentProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Council component provenance must be an object")
        entry_point_fields = (
            "candidate_entry_point",
            "senate_review_entry_point",
            "senate_deliberation_entry_point",
            "mandate_entry_point",
            "runtime_validation_entry_point",
            "advisor_health_entry_point",
            "council_synthesis_entry_point",
            "council_executive_summary_entry_point",
        )
        _require_exact_fields(
            value,
            {
                "git_revision",
                "git_branch",
                "dirty_worktree",
                *entry_point_fields,
                "run_mode",
                "transport",
                "replay_fixture_id",
                "replay_fixture_sha256",
            },
            "Council component provenance",
        )
        revision = value["git_revision"]
        if not isinstance(revision, str) or not _GIT_REVISION_PATTERN.fullmatch(revision):
            raise ContractValidationError(
                "git_revision must be a hexadecimal Git object ID"
            )
        branch = _validate_text(
            value["git_branch"], "git_branch", allow_none=True, max_length=256
        )
        if type(value["dirty_worktree"]) is not bool:
            raise ContractValidationError("dirty_worktree must be a boolean")
        entry_points = {
            field_name: str(
                _validate_text(value[field_name], field_name, max_length=256)
            )
            for field_name in entry_point_fields
        }
        run_mode = _parse_enum(RunMode, value["run_mode"], "component run_mode")
        transport = _parse_enum(
            CouncilTransportKind, value["transport"], "Council transport"
        )
        fixture_id = _validate_text(
            value["replay_fixture_id"],
            "replay_fixture_id",
            allow_none=True,
            max_length=128,
        )
        fixture_sha = value["replay_fixture_sha256"]
        if fixture_sha is not None and (
            not isinstance(fixture_sha, str) or not _SHA256_PATTERN.fullmatch(fixture_sha)
        ):
            raise ContractValidationError(
                "replay_fixture_sha256 must be null or 64 lowercase hex characters"
            )
        if transport is CouncilTransportKind.REPLAY_FIXTURE:
            if run_mode is not RunMode.REPLAY or fixture_id is None or fixture_sha is None:
                raise ContractValidationError(
                    "Council REPLAY_FIXTURE provenance requires REPLAY mode and fixture identity"
                )
        elif run_mode is not RunMode.LIVE or fixture_id is not None or fixture_sha is not None:
            raise ContractValidationError(
                "LIVE_MISSION_INPUTS provenance requires LIVE mode and no replay fixture"
            )
        return cls(
            git_revision=revision,
            git_branch=branch,
            dirty_worktree=value["dirty_worktree"],
            candidate_entry_point=entry_points["candidate_entry_point"],
            senate_review_entry_point=entry_points["senate_review_entry_point"],
            senate_deliberation_entry_point=entry_points[
                "senate_deliberation_entry_point"
            ],
            mandate_entry_point=entry_points["mandate_entry_point"],
            runtime_validation_entry_point=entry_points[
                "runtime_validation_entry_point"
            ],
            advisor_health_entry_point=entry_points["advisor_health_entry_point"],
            council_synthesis_entry_point=entry_points[
                "council_synthesis_entry_point"
            ],
            council_executive_summary_entry_point=entry_points[
                "council_executive_summary_entry_point"
            ],
            run_mode=run_mode,
            transport=transport,
            replay_fixture_id=fixture_id,
            replay_fixture_sha256=fixture_sha,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "git_revision": self.git_revision,
            "git_branch": self.git_branch,
            "dirty_worktree": self.dirty_worktree,
            "candidate_entry_point": self.candidate_entry_point,
            "senate_review_entry_point": self.senate_review_entry_point,
            "senate_deliberation_entry_point": self.senate_deliberation_entry_point,
            "mandate_entry_point": self.mandate_entry_point,
            "runtime_validation_entry_point": self.runtime_validation_entry_point,
            "advisor_health_entry_point": self.advisor_health_entry_point,
            "council_synthesis_entry_point": self.council_synthesis_entry_point,
            "council_executive_summary_entry_point": (
                self.council_executive_summary_entry_point
            ),
            "run_mode": self.run_mode.value,
            "transport": self.transport.value,
            "replay_fixture_id": self.replay_fixture_id,
            "replay_fixture_sha256": self.replay_fixture_sha256,
        }


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
    components: dict[str, ComponentProvenance | CouncilComponentProvenance]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission snapshot must be an object")
        fields = set(value)
        missing = set(_SNAPSHOT_BASE_FIELDS) - fields
        unknown = fields - set(_SNAPSHOT_BASE_FIELDS) - {"components"}
        if missing:
            raise ContractValidationError(
                f"mission snapshot is missing fields: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ContractValidationError(
                f"mission snapshot contains unknown fields: {', '.join(sorted(unknown))}"
            )
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
        artifact_names = {item.name for item in artifacts}
        for stage_name, stage in stages.items():
            unknown_names = (set(stage.inputs) | set(stage.outputs)) - artifact_names
            if unknown_names:
                raise ContractValidationError(
                    f"{stage_name} references unknown artifacts: "
                    + ", ".join(sorted(unknown_names))
                )

        components_value = value.get("components", {})
        if not isinstance(components_value, Mapping):
            raise ContractValidationError("components must be an object")
        if set(components_value) - {"battlestar", "battlestar_council"}:
            raise ContractValidationError(
                "components supports battlestar and battlestar_council only"
            )
        components: dict[
            str, ComponentProvenance | CouncilComponentProvenance
        ] = {}
        if "battlestar" in components_value:
            components["battlestar"] = ComponentProvenance.from_mapping(
                components_value["battlestar"]
            )
        if "battlestar_council" in components_value:
            if "battlestar" not in components_value:
                raise ContractValidationError(
                    "battlestar_council provenance requires Battlestar Oracle provenance"
                )
            components["battlestar_council"] = (
                CouncilComponentProvenance.from_mapping(
                    components_value["battlestar_council"]
                )
            )

        run_mode = _parse_enum(RunMode, value["run_mode"], "run_mode")
        if any(component.run_mode is not run_mode for component in components.values()):
            raise ContractValidationError("component run_mode must match mission run_mode")
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
            run_mode=run_mode,
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
            components=components,
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
                inputs=(request_artifact.name,),
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
                "components": {},
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
            "components": {
                name: self.components[name].to_dict() for name in sorted(self.components)
            },
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
