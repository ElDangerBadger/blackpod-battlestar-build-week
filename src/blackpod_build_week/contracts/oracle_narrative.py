"""Strict contracts for Oracle narrative enrichment through ModelDock.

Oracle evidence remains authoritative.  These contracts deliberately make every
rendered fact traceable to one of five immutable Oracle artifacts and reject
language that attempts to turn an explanatory narrative into an approval,
Governor disposition, or execution recommendation.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_request import (
    ContractValidationError,
    RunMode,
    normalize_rfc3339,
    parse_rfc3339,
    parse_strict_json_object_bytes,
)
from .mission_snapshot import ArtifactReference


ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION = "blackpod.oracle_narrative_request.v1"
ORACLE_NARRATIVE_SCHEMA_VERSION = "blackpod.oracle_narrative.v1"
ORACLE_FACT_CATALOG_SCHEMA_VERSION = "blackpod.oracle_fact_catalog.v1"
ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION = (
    "blackpod.oracle_narrative_selection.v1"
)
MODELDOCK_REPLAY_PACK_SCHEMA_VERSION = "blackpod.modeldock_replay_pack.v1"
MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION = (
    "blackpod.modeldock_replay_expected_provenance.v1"
)
MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION = (
    "blackpod.modeldock_replay_expected_snapshot_changes.v1"
)

# Backwards-friendly spelling for callers that use ``VERSION`` rather than
# ``SCHEMA_VERSION``.  Both names identify exactly the same contract.
ORACLE_NARRATIVE_REQUEST_VERSION = ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION
ORACLE_NARRATIVE_VERSION = ORACLE_NARRATIVE_SCHEMA_VERSION
MODELDOCK_REPLAY_PACK_VERSION = MODELDOCK_REPLAY_PACK_SCHEMA_VERSION

EVIDENCE_ARTIFACT_NAMES: dict[str, str] = {
    "measurements": "oracle_measurements",
    "diagnostics": "oracle_measurement_diagnostics",
    "readiness": "oracle_readiness_report",
    "assessment": "oracle_assessment",
    "report": "oracle_report",
}

# This is a narrative-only vocabulary over existing Oracle facts. It is
# deliberately small, ordered, scalar-only, and value-independent so Gemma
# chooses evidence rather than manufacturing paths or measurements.
_ALLOWED_ORACLE_FACT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("oracle.assessment.breadth_posture", "oracle_assessment", "/breadth_posture"),
    (
        "oracle.assessment.leadership_posture",
        "oracle_assessment",
        "/leadership_posture",
    ),
    ("oracle.assessment.rotation_posture", "oracle_assessment", "/rotation_posture"),
    (
        "oracle.assessment.risk_regime_posture",
        "oracle_assessment",
        "/risk_regime_posture",
    ),
    ("oracle.assessment.confidence", "oracle_assessment", "/confidence"),
    ("oracle.measurements.breadth_score", "oracle_measurements", "/breadth_score"),
    (
        "oracle.measurements.cyclical_strength",
        "oracle_measurements",
        "/cyclical_strength",
    ),
    (
        "oracle.measurements.defensive_strength",
        "oracle_measurements",
        "/defensive_strength",
    ),
    (
        "oracle.measurements.leadership_concentration",
        "oracle_measurements",
        "/leadership_concentration",
    ),
    ("oracle.measurements.risk_off_score", "oracle_measurements", "/risk_off_score"),
    ("oracle.measurements.risk_on_score", "oracle_measurements", "/risk_on_score"),
    (
        "oracle.measurements.rotation_velocity",
        "oracle_measurements",
        "/rotation_velocity",
    ),
    (
        "oracle.measurements.sector_dispersion",
        "oracle_measurements",
        "/sector_dispersion",
    ),
    (
        "oracle.diagnostics.diagnostics_state",
        "oracle_measurement_diagnostics",
        "/diagnostics_state",
    ),
    (
        "oracle.diagnostics.provenance_complete",
        "oracle_measurement_diagnostics",
        "/provenance_complete",
    ),
    (
        "oracle.diagnostics.fallback_count",
        "oracle_measurement_diagnostics",
        "/fallback_count",
    ),
    (
        "oracle.readiness.readiness_state",
        "oracle_readiness_report",
        "/readiness_state",
    ),
    (
        "oracle.readiness.downstream_ready",
        "oracle_readiness_report",
        "/downstream_ready",
    ),
    ("oracle.readiness.coverage_ok", "oracle_readiness_report", "/coverage_ok"),
    (
        "oracle.readiness.completeness_ok",
        "oracle_readiness_report",
        "/completeness_ok",
    ),
    ("oracle.readiness.freshness_ok", "oracle_readiness_report", "/freshness_ok"),
    ("oracle.report.headline", "oracle_report", "/headline"),
)

_REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "mission_id",
        "request_id",
        "symbol",
        "run_mode",
        "oracle_native_state",
        *EVIDENCE_ARTIFACT_NAMES,
        "warnings",
        "source_artifacts",
    }
)
_NARRATIVE_FIELDS = frozenset(
    {
        "schema_version",
        "mission_id",
        "request_id",
        "symbol",
        "summary",
        "observed_facts",
        "interpretation",
        "uncertainties",
        "warnings",
        "confidence_explanation",
        "prohibited_actions_acknowledged",
    }
)
_NARRATIVE_SELECTION_FIELDS = frozenset(
    {
        "schema_version",
        "selected_fact_ids",
        "summary",
        "interpretation",
        "uncertainties",
        "confidence_explanation",
        "prohibited_actions_acknowledged",
    }
)
_OBSERVED_FACT_FIELDS = frozenset(
    {"source_artifact", "json_pointer", "value", "statement"}
)
_REPLAY_PACK_FIELDS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "created_at",
        "observed_at",
        "oracle_input",
        "request",
        "response",
        "expected_narrative",
        "expected_provenance",
        "expected_snapshot_changes",
    }
)
_EXPECTED_PROVENANCE_FIELDS = frozenset(
    {"schema_version", "provider", "model", "model_revision", "trace_id", "mocked"}
)
_EXPECTED_SNAPSHOT_CHANGE_FIELDS = frozenset(
    {
        "schema_version",
        "oracle_status",
        "modeldock_call_status",
        "current_phase",
        "mission_outcome",
        "terminal",
        "narrative_output",
    }
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FACT_ID_PATTERN = re.compile(
    r"^oracle\.(?:measurements|diagnostics|readiness|assessment|report)\.[a-z0-9_]+$"
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_EMBEDDED_LOCAL_PATH = re.compile(
    r"(?:^|[\s\"'=:(\[])(?:/(?!/)[^\s\"'<>|,;]+|"
    r"[A-Za-z]:[\\/][^\s\"'<>|,;]+|file:(?://)?/[^\s\"'<>|,;]+)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:"
    r"\b(?:api[_ -]?key|access[_ -]?token|auth(?:orization)?|bearer|password|"
    r"passwd|private[_ -]?key|client[_ -]?secret|secret)\b\s*[:=]\s*\S+|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\bsk-[A-Za-z0-9_-]{8,}|"
    r"\bgh[pousr]_[A-Za-z0-9]{8,}|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    r")",
    re.IGNORECASE,
)
_SECRET_KEY = re.compile(
    r"^(?:api[_-]?key|access[_-]?token|authorization|password|passwd|"
    r"private[_-]?key|client[_-]?secret|secret)$",
    re.IGNORECASE,
)
_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    r"(?![A-Za-z0-9_])"
)
_INVALID_POINTER_ESCAPE = re.compile(r"~(?![01])")
_PROHIBITED_DISPOSITION = re.compile(
    r"\b(?:PROCEED|HOLD|STAND[ _-]?DOWN|BLOCKED|REVIEW[ _-]?REQUIRED|"
    r"APPROVED[ _-]?FOR[ _-]?HANDOFF|APPROVED|VETOED)\b",
    re.IGNORECASE,
)
_PROHIBITED_OPERATION = re.compile(
    r"\b(?:SUBMIT[ _-]?ORDER|CANCEL[ _-]?ORDER|MODIFY[ _-]?PORTFOLIO|"
    r"BROKER[ _-]?CALL)\b",
    re.IGNORECASE,
)
_AUTHORITY_CLAIM = re.compile(
    r"(?:"
    r"\b(?:mission|trade|handoff|order)\s+(?:is\s+|has\s+been\s+)?approved\b|"
    r"\bapprove(?:s|d)?\s+(?:the\s+|an?\s+)?(?:mission|trade|handoff|order)\b|"
    r"\b(?:recommend(?:s|ed)?|should|must)\s+(?:now\s+)?"
    r"(?:buy|sell|trade|execute|submit|place|cancel|approve)\b|"
    r"\b(?:submit|place|cancel)\s+(?:an?\s+|the\s+)?order\b|"
    r"\bexecute\s+(?:the\s+|an?\s+)?(?:trade|order)\b|"
    r"\b(?:buy|sell)\s+(?:the\s+)?(?:stock|shares|position)\b"
    r")",
    re.IGNORECASE,
)
_POSITION_RECOMMENDATION = re.compile(
    r"(?:"
    r"\b(?:accumulate|reduce|increase|decrease|add|trim)\s+"
    r"(?:the\s+|an?\s+)?(?:position|exposure|holding|holdings|shares?)\b|"
    r"\b(?:enter|exit|open|close)\s+(?:the\s+|an?\s+)?(?:position|trade)\b|"
    r"\bgo(?:ing)?\s+(?:long|short)\b|"
    r"\b(?:take|establish)\s+(?:the\s+|an?\s+)?(?:long|short\s+)?position\b"
    r")",
    re.IGNORECASE,
)
_FACTUAL_ASSERTION = re.compile(
    r"\b(?:the\s+)?(?:validated\s+)?(?:oracle\s+)?"
    r"(?P<subject>evidence|diagnostics?(?: state| quality)?|"
    r"readiness(?: state)?|coverage|assessment|report|measurements?|"
    r"market posture|analytical posture|risk posture|momentum)\s*"
    r"(?:is|are|was|were|remains?|shows?|indicates?|reports?|demonstrates?|:|=)\s+"
    r"(?P<claim>[^.;\n]+)",
    re.IGNORECASE,
)
_WORD_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_GENERIC_NARRATIVE_WORDS = frozenset(
    {
        "a", "about", "absent", "adds", "against", "aligned", "and",
        "are", "as", "at", "available", "based", "be", "because",
        "bounded", "broad", "broader", "by", "cautious", "compared",
        "comparison", "complete", "completeness", "confidence",
        "consistent", "contains", "context", "covers", "current", "data",
        "describes", "different", "does", "evidence", "exceeds", "execution", "explanation",
        "fact", "facts",
        "false", "fixed", "flag", "from", "has", "in", "includes",
        "indicates", "input", "inputs", "interpretation", "is", "limited",
        "linked", "market", "material", "measurement", "measurements",
        "more", "narrative", "new", "no", "not", "observation",
        "observations", "observed", "of", "on", "only", "participation",
        "period", "prior", "record", "reflect", "reflects", "relative", "remains",
        "security", "shows", "source", "specific", "statement", "suggests",
        "suggest", "supplies", "supports", "taken", "than", "that", "the",
        "these", "this", "tilt", "to", "together", "trade", "true",
        "summary", "uncertainty", "validated", "validation", "warning",
        "warnings", "while", "with", "within", "approval", "authority",
    }
)

_MAX_REQUEST_BYTES = 512 * 1024
_MAX_NARRATIVE_BYTES = 256 * 1024
_MAX_EVIDENCE_BYTES = 512 * 1024
_MAX_ARRAY_ITEMS = 64
_MAX_FACT_CATALOG_ITEMS = 32
_MAX_SELECTED_FACTS = 5


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str] | set[str], name: str
) -> None:
    fields = set(value)
    missing = set(expected) - fields
    unknown = fields - set(expected)
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _strict_identifier(value: object, field_name: str) -> str:
    try:
        return validate_identifier(value, field_name)
    except IdentifierError as exc:
        raise ContractValidationError(str(exc)) from exc


def _strict_text(
    value: object,
    field_name: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        raise ContractValidationError(f"{field_name} must be nonblank")
    if value != value.strip() and not allow_empty:
        raise ContractValidationError(f"{field_name} may not have surrounding whitespace")
    if len(value) > max_length:
        raise ContractValidationError(f"{field_name} exceeds {max_length} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{field_name} must contain valid UTF-8 text") from exc
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ContractValidationError(f"{field_name} contains unsupported control text")
    return value


def _strict_symbol(value: object) -> str:
    return _strict_text(value, "symbol", max_length=64)


def _validate_json_value(
    value: object,
    field_name: str,
    *,
    reject_absolute_paths: bool = True,
    active: set[int] | None = None,
) -> None:
    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractValidationError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, str):
        _strict_text(value, field_name, max_length=_MAX_EVIDENCE_BYTES, allow_empty=True)
        if reject_absolute_paths and _looks_like_absolute_local_path(value):
            raise ContractValidationError(f"{field_name} contains an absolute local path")
        if _SECRET_VALUE.search(value):
            raise ContractValidationError(
                f"{field_name} contains credential- or secret-like text"
            )
        return
    if not isinstance(value, (Mapping, list, tuple)):
        raise ContractValidationError(f"{field_name} contains a non-JSON value")

    seen = active if active is not None else set()
    identity = id(value)
    if identity in seen:
        raise ContractValidationError(f"{field_name} contains a circular value")
    seen.add(identity)
    try:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ContractValidationError(f"{field_name} object keys must be strings")
                _strict_text(key, f"{field_name} key", max_length=256, allow_empty=True)
                if _SECRET_KEY.fullmatch(key):
                    raise ContractValidationError(
                        f"{field_name} contains a credential- or secret-like field"
                    )
                _validate_json_value(
                    child,
                    f"{field_name}.{key}",
                    reject_absolute_paths=reject_absolute_paths,
                    active=seen,
                )
        else:
            for index, child in enumerate(value):
                _validate_json_value(
                    child,
                    f"{field_name}[{index}]",
                    reject_absolute_paths=reject_absolute_paths,
                    active=seen,
                )
    finally:
        seen.remove(identity)


def _canonical_json_bytes(
    value: object,
    *,
    field_name: str,
    limit: int,
    reject_absolute_paths: bool = True,
) -> bytes:
    _validate_json_value(
        value, field_name, reject_absolute_paths=reject_absolute_paths
    )
    try:
        result = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractValidationError(f"{field_name} must contain strict JSON") from exc
    if len(result) > limit:
        raise ContractValidationError(f"{field_name} exceeds {limit} UTF-8 bytes")
    return result


def _looks_like_absolute_local_path(value: str) -> bool:
    return (
        value.startswith(("/", "~/", "~\\", "\\\\", "file://"))
        or _WINDOWS_ABSOLUTE_PATH.match(value) is not None
        or _EMBEDDED_LOCAL_PATH.search(value) is not None
    )


def _reject_absolute_local_text(value: str, field_name: str) -> None:
    if _looks_like_absolute_local_path(value):
        raise ContractValidationError(f"{field_name} contains an absolute local path")
    if _SECRET_VALUE.search(value):
        raise ContractValidationError(
            f"{field_name} contains credential- or secret-like text"
        )


def _strict_text_array(
    value: object, field_name: str, *, item_limit: int = 1000
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ContractValidationError(f"{field_name} must be an array")
    if len(value) > _MAX_ARRAY_ITEMS:
        raise ContractValidationError(
            f"{field_name} exceeds {_MAX_ARRAY_ITEMS} entries"
        )
    items = tuple(
        _strict_text(item, f"{field_name}[{index}]", max_length=item_limit)
        for index, item in enumerate(value)
    )
    if len(set(items)) != len(items):
        raise ContractValidationError(f"{field_name} contains duplicate entries")
    return items


def _parse_run_mode(value: object) -> RunMode:
    if not isinstance(value, str):
        raise ContractValidationError("run_mode must be LIVE or REPLAY")
    try:
        return RunMode(value)
    except ValueError as exc:
        raise ContractValidationError(f"unsupported run_mode: {value!r}") from exc


def _parse_source_artifacts(value: object) -> dict[str, ArtifactReference]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("source_artifacts must be an object")
    _require_exact_fields(value, frozenset(EVIDENCE_ARTIFACT_NAMES), "source_artifacts")
    result: dict[str, ArtifactReference] = {}
    paths: set[str] = set()
    for evidence_name, expected_artifact_name in EVIDENCE_ARTIFACT_NAMES.items():
        reference = ArtifactReference.from_mapping(value[evidence_name])
        if reference.name != expected_artifact_name:
            raise ContractValidationError(
                f"source_artifacts.{evidence_name}.name must be "
                f"{expected_artifact_name!r}"
            )
        if (
            reference.producer != "oracle"
            or reference.byte_size is None
            or reference.observed_at is None
        ):
            raise ContractValidationError(
                f"source_artifacts.{evidence_name} must be a full Oracle artifact reference"
            )
        if reference.path in paths:
            raise ContractValidationError("source_artifacts contains duplicate paths")
        paths.add(reference.path)
        result[evidence_name] = reference
    return result


def _validate_replay_correlation(
    section: Mapping[str, Any],
    field_name: str,
    oracle_input: "OracleNarrativeRequest",
) -> None:
    metadata = section.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ContractValidationError(
            f"ModelDock replay pack {field_name}.metadata must be an object"
        )
    correlation = metadata.get("blackpod_correlation")
    if not isinstance(correlation, Mapping):
        raise ContractValidationError(
            f"ModelDock replay pack {field_name} lacks blackpod_correlation"
        )
    expected_fields = frozenset({"mission_id", "request_id", "symbol", "run_mode"})
    _require_exact_fields(
        correlation,
        expected_fields,
        f"ModelDock replay pack {field_name} blackpod_correlation",
    )
    expected = {
        "mission_id": oracle_input.mission_id,
        "request_id": oracle_input.request_id,
        "symbol": oracle_input.symbol,
        "run_mode": oracle_input.run_mode.value,
    }
    if dict(correlation) != expected:
        raise ContractValidationError(
            f"ModelDock replay pack {field_name} correlation mismatch"
        )


def _parse_expected_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("expected_provenance must be an object")
    _require_exact_fields(
        value, _EXPECTED_PROVENANCE_FIELDS, "expected_provenance"
    )
    if value["schema_version"] != MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION:
        raise ContractValidationError(
            "unsupported expected_provenance schema_version"
        )
    provider = _strict_text(value["provider"], "expected provider", max_length=128)
    model = _strict_text(value["model"], "expected model", max_length=256)
    trace_id = _strict_identifier(value["trace_id"], "expected trace_id")
    revision_value = value["model_revision"]
    model_revision = (
        None
        if revision_value is None
        else _strict_text(
            revision_value, "expected model_revision", max_length=256
        )
    )
    mocked = value["mocked"]
    if type(mocked) is not bool:
        raise ContractValidationError("expected mocked must be a boolean")
    result = {
        "schema_version": MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION,
        "provider": provider,
        "model": model,
        "model_revision": model_revision,
        "trace_id": trace_id,
        "mocked": mocked,
    }
    _canonical_json_bytes(
        result, field_name="expected_provenance", limit=16 * 1024
    )
    return result


def _parse_expected_snapshot_changes(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("expected_snapshot_changes must be an object")
    _require_exact_fields(
        value, _EXPECTED_SNAPSHOT_CHANGE_FIELDS, "expected_snapshot_changes"
    )
    if (
        value["schema_version"]
        != MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION
    ):
        raise ContractValidationError(
            "unsupported expected_snapshot_changes schema_version"
        )
    expected = {
        "schema_version": MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION,
        "oracle_status": "SUCCEEDED",
        "modeldock_call_status": "SUCCEEDED",
        "current_phase": "COUNCIL",
        "mission_outcome": "INCOMPLETE",
        "terminal": False,
        "narrative_output": "oracle_modeldock_narrative",
    }
    if dict(value) != expected:
        raise ContractValidationError(
            "expected_snapshot_changes must describe only the successful strict "
            "Oracle-to-Council narrative transition"
        )
    return expected


def _response_model_revision(value: Mapping[str, Any]) -> str | None:
    for container_name in ("metadata", "data"):
        container = value.get(container_name)
        if isinstance(container, Mapping):
            candidate = container.get("model_revision")
            if candidate is not None:
                return _strict_text(
                    candidate,
                    "ModelDock replay response model_revision",
                    max_length=256,
                )
    return None


def _validate_expected_response_provenance(
    response: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    actual = {
        "provider": response.get("provider"),
        "model": response.get("model"),
        "model_revision": _response_model_revision(response),
        "trace_id": response.get("trace_id"),
        "mocked": response.get("mocked"),
    }
    expected_identity = {
        key: expected[key]
        for key in ("provider", "model", "model_revision", "trace_id", "mocked")
    }
    if actual != expected_identity:
        raise ContractValidationError(
            "ModelDock replay response identity does not match expected_provenance"
        )


def _validate_wire_section_without_payload(
    value: Mapping[str, Any], *, omitted_field: str, field_name: str
) -> None:
    projected = {
        key: copy.deepcopy(child)
        for key, child in value.items()
        if key != omitted_field
    }
    _canonical_json_bytes(
        projected,
        field_name=field_name,
        limit=_MAX_REQUEST_BYTES,
    )


@dataclass(frozen=True, slots=True)
class OracleNarrativeRequest:
    """Canonical, bounded Oracle evidence sent for narrative synthesis."""

    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    oracle_native_state: str
    measurements: dict[str, Any]
    diagnostics: dict[str, Any]
    readiness: dict[str, Any]
    assessment: dict[str, Any]
    report: dict[str, Any]
    warnings: tuple[str, ...]
    source_artifacts: dict[str, ArtifactReference]

    @classmethod
    def from_file(cls, path: Path) -> "OracleNarrativeRequest":
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ContractValidationError(f"cannot read Oracle narrative request: {exc}") from exc
        return cls.from_json_bytes(source)

    @classmethod
    def from_json_bytes(cls, source: bytes) -> "OracleNarrativeRequest":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                source, document_name="Oracle narrative request"
            )
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OracleNarrativeRequest":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Oracle narrative request must be an object")
        _require_exact_fields(value, _REQUEST_FIELDS, "Oracle narrative request")
        if value["schema_version"] != ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported Oracle narrative request schema_version: "
                f"{value['schema_version']!r}"
            )
        try:
            mission_id = validate_mission_id(value["mission_id"])
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        request_id = _strict_identifier(value["request_id"], "request_id")
        if mission_id == request_id:
            raise ContractValidationError("mission_id must remain distinct from request_id")

        evidence: dict[str, dict[str, Any]] = {}
        for name in EVIDENCE_ARTIFACT_NAMES:
            item = value[name]
            if not isinstance(item, Mapping):
                raise ContractValidationError(f"{name} must be an Oracle evidence object")
            copied = copy.deepcopy(dict(item))
            _canonical_json_bytes(
                copied,
                field_name=name,
                limit=_MAX_EVIDENCE_BYTES,
            )
            evidence[name] = copied

        request = cls(
            schema_version=ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION,
            mission_id=mission_id,
            request_id=request_id,
            symbol=_strict_symbol(value["symbol"]),
            run_mode=_parse_run_mode(value["run_mode"]),
            oracle_native_state=_strict_text(
                value["oracle_native_state"],
                "oracle_native_state",
                max_length=128,
            ),
            measurements=evidence["measurements"],
            diagnostics=evidence["diagnostics"],
            readiness=evidence["readiness"],
            assessment=evidence["assessment"],
            report=evidence["report"],
            warnings=_strict_text_array(value["warnings"], "warnings"),
            source_artifacts=_parse_source_artifacts(value["source_artifacts"]),
        )
        _canonical_json_bytes(
            request.to_dict(),
            field_name="Oracle narrative request",
            limit=_MAX_REQUEST_BYTES,
        )
        return request

    @property
    def evidence(self) -> dict[str, dict[str, Any]]:
        return {
            name: copy.deepcopy(getattr(self, name))
            for name in EVIDENCE_ARTIFACT_NAMES
        }

    @property
    def evidence_by_artifact(self) -> dict[str, dict[str, Any]]:
        return {
            artifact_name: copy.deepcopy(getattr(self, evidence_name))
            for evidence_name, artifact_name in EVIDENCE_ARTIFACT_NAMES.items()
        }

    def resolve_pointer(self, source_artifact: str, json_pointer: str) -> Any:
        """Resolve an RFC 6901 pointer within one declared Oracle artifact."""

        if source_artifact not in self.evidence_by_artifact:
            raise ContractValidationError(
                f"unknown observed-fact source artifact: {source_artifact!r}"
            )
        return copy.deepcopy(
            resolve_json_pointer(
                self.evidence_by_artifact[source_artifact], json_pointer
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "run_mode": self.run_mode.value,
            "oracle_native_state": self.oracle_native_state,
            **self.evidence,
            "warnings": list(self.warnings),
            "source_artifacts": {
                name: self.source_artifacts[name].to_dict()
                for name in EVIDENCE_ARTIFACT_NAMES
            },
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_dict(),
            field_name="Oracle narrative request",
            limit=_MAX_REQUEST_BYTES,
        )

    def to_canonical_json(self) -> str:
        return self.canonical_json_bytes().decode("utf-8")

    def build_prompt(self) -> str:
        return build_oracle_narrative_prompt(self)


@dataclass(frozen=True, slots=True)
class ObservedFact:
    source_artifact: str
    json_pointer: str
    value: None | bool | int | float | str
    statement: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ObservedFact":
        if not isinstance(value, Mapping):
            raise ContractValidationError("observed fact must be an object")
        _require_exact_fields(value, _OBSERVED_FACT_FIELDS, "observed fact")
        source_artifact = _strict_identifier(
            value["source_artifact"], "observed fact source_artifact"
        )
        if source_artifact not in set(EVIDENCE_ARTIFACT_NAMES.values()):
            raise ContractValidationError(
                f"observed fact uses unknown source artifact: {source_artifact!r}"
            )
        pointer = validate_json_pointer(value["json_pointer"])
        scalar = value["value"]
        if not (
            scalar is None
            or type(scalar) is bool
            or type(scalar) is int
            or (type(scalar) is float and math.isfinite(scalar))
            or isinstance(scalar, str)
        ):
            raise ContractValidationError("observed fact value must be an exact JSON scalar")
        _validate_json_value(scalar, "observed fact value")
        statement = _strict_text(
            value["statement"], "observed fact statement", max_length=1000
        )
        _reject_absolute_local_text(statement, "observed fact statement")
        return cls(
            source_artifact=source_artifact,
            json_pointer=pointer,
            value=copy.deepcopy(scalar),
            statement=statement,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_artifact": self.source_artifact,
            "json_pointer": self.json_pointer,
            "value": copy.deepcopy(self.value),
            "statement": self.statement,
        }


@dataclass(frozen=True, slots=True)
class OracleNarrative:
    """Validated structured narrative; never an analytical authority."""

    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    summary: str
    observed_facts: tuple[ObservedFact, ...]
    interpretation: str
    uncertainties: tuple[str, ...]
    warnings: tuple[str, ...]
    confidence_explanation: str
    prohibited_actions_acknowledged: bool

    @classmethod
    def from_file(cls, path: Path) -> "OracleNarrative":
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ContractValidationError(f"cannot read Oracle narrative: {exc}") from exc
        return cls.from_json_bytes(source)

    @classmethod
    def from_json_bytes(cls, source: bytes) -> "OracleNarrative":
        return cls.from_mapping(
            parse_strict_json_object_bytes(source, document_name="Oracle narrative")
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OracleNarrative":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Oracle narrative must be an object")
        _require_exact_fields(value, _NARRATIVE_FIELDS, "Oracle narrative")
        if value["schema_version"] != ORACLE_NARRATIVE_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported Oracle narrative schema_version: {value['schema_version']!r}"
            )
        try:
            mission_id = validate_mission_id(value["mission_id"])
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        request_id = _strict_identifier(value["request_id"], "request_id")

        facts_value = value["observed_facts"]
        if not isinstance(facts_value, list):
            raise ContractValidationError("observed_facts must be an array")
        if not facts_value:
            raise ContractValidationError("observed_facts must not be empty")
        if len(facts_value) > 128:
            raise ContractValidationError("observed_facts exceeds 128 entries")
        facts = tuple(ObservedFact.from_mapping(item) for item in facts_value)
        fact_keys = tuple((fact.source_artifact, fact.json_pointer) for fact in facts)
        if len(set(fact_keys)) != len(fact_keys):
            raise ContractValidationError("observed_facts contains duplicate source pointers")

        acknowledged = value["prohibited_actions_acknowledged"]
        if acknowledged is not True:
            raise ContractValidationError(
                "prohibited_actions_acknowledged must be true"
            )
        summary = _strict_text(value["summary"], "summary", max_length=2000)
        interpretation = _strict_text(
            value["interpretation"], "interpretation", max_length=4000
        )
        uncertainties = _strict_text_array(
            value["uncertainties"], "uncertainties"
        )
        warnings = _strict_text_array(value["warnings"], "warnings")
        confidence_explanation = _strict_text(
            value["confidence_explanation"],
            "confidence_explanation",
            max_length=2000,
        )
        for field_name, field_value in (
            ("summary", summary),
            ("interpretation", interpretation),
            ("confidence_explanation", confidence_explanation),
            *[("uncertainties", item) for item in uncertainties],
            *[("warnings", item) for item in warnings],
        ):
            _reject_absolute_local_text(field_value, field_name)

        narrative = cls(
            schema_version=ORACLE_NARRATIVE_SCHEMA_VERSION,
            mission_id=mission_id,
            request_id=request_id,
            symbol=_strict_symbol(value["symbol"]),
            summary=summary,
            observed_facts=facts,
            interpretation=interpretation,
            uncertainties=uncertainties,
            warnings=warnings,
            confidence_explanation=confidence_explanation,
            prohibited_actions_acknowledged=True,
        )
        _canonical_json_bytes(
            narrative.to_dict(),
            field_name="Oracle narrative",
            limit=_MAX_NARRATIVE_BYTES,
            reject_absolute_paths=False,
        )
        return narrative

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "summary": self.summary,
            "observed_facts": [fact.to_dict() for fact in self.observed_facts],
            "interpretation": self.interpretation,
            "uncertainties": list(self.uncertainties),
            "warnings": list(self.warnings),
            "confidence_explanation": self.confidence_explanation,
            "prohibited_actions_acknowledged": self.prohibited_actions_acknowledged,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_dict(),
            field_name="Oracle narrative",
            limit=_MAX_NARRATIVE_BYTES,
            reject_absolute_paths=False,
        )

    def to_canonical_json(self) -> str:
        return self.canonical_json_bytes().decode("utf-8")

    def validate_against(self, request: OracleNarrativeRequest) -> "OracleNarrative":
        """Validate correlation, lineage, numeric support, and authority limits."""

        if not isinstance(request, OracleNarrativeRequest):
            raise ContractValidationError(
                "Oracle narrative validation requires an OracleNarrativeRequest"
            )
        if (
            self.mission_id != request.mission_id
            or self.request_id != request.request_id
            or self.symbol != request.symbol
        ):
            raise ContractValidationError("Oracle narrative correlation mismatch")

        for fact in self.observed_facts:
            resolved = request.resolve_pointer(
                fact.source_artifact, fact.json_pointer
            )
            if isinstance(resolved, (Mapping, list, tuple)):
                raise ContractValidationError(
                    "observed fact JSON pointer must resolve to a scalar"
                )
            if type(resolved) is not type(fact.value) or resolved != fact.value:
                raise ContractValidationError(
                    "observed fact value does not exactly match its Oracle source"
                )

        free_texts: list[str] = [
            self.summary,
            self.interpretation,
            *self.uncertainties,
            *self.warnings,
            self.confidence_explanation,
        ]
        all_texts = [*free_texts, *(fact.statement for fact in self.observed_facts)]
        all_texts.extend(
            fact.value for fact in self.observed_facts if isinstance(fact.value, str)
        )
        _reject_prohibited_authority(all_texts)
        _validate_source_bound_numbers(free_texts, self.observed_facts)
        _validate_observed_fact_statements(self.observed_facts)
        # Observed-fact statements are validated structurally against their
        # exact pointer/value above. Fuzzy prose checks apply only to the
        # explicitly interpretive fields, avoiding cross-domain inference from
        # a source-linked fact label.
        _validate_semantic_claims(free_texts, request)
        _validate_symbol_attribution(all_texts, request)
        _validate_source_bound_vocabulary(all_texts, request)
        return self


@dataclass(frozen=True, slots=True)
class OracleAllowedFact:
    """One deterministic, source-bound fact offered to ModelDock by ID."""

    fact_id: str
    source_artifact: str
    json_pointer: str
    value: None | bool | int | float | str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "source_artifact": self.source_artifact,
            "json_pointer": self.json_pointer,
            "value": copy.deepcopy(self.value),
        }

    def to_observed_fact(self) -> ObservedFact:
        return ObservedFact.from_mapping(
            {
                "source_artifact": self.source_artifact,
                "json_pointer": self.json_pointer,
                "value": copy.deepcopy(self.value),
                "statement": _render_observed_fact_statement(
                    self.json_pointer, self.value
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class OracleFactCatalog:
    """Finite deterministic fact vocabulary derived from validated Oracle input.

    IDs are explicit semantic names paired with one source artifact and one
    canonical RFC 6901 pointer, never values or prose supplied by a model.  A
    location therefore keeps the same ID when its observed value changes.
    """

    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    source_artifacts: dict[str, ArtifactReference]
    facts: tuple[OracleAllowedFact, ...]

    @classmethod
    def from_request(cls, request: OracleNarrativeRequest) -> "OracleFactCatalog":
        if not isinstance(request, OracleNarrativeRequest):
            raise ContractValidationError(
                "Oracle fact catalog requires an OracleNarrativeRequest"
            )
        candidates: list[OracleAllowedFact] = []
        for fact_id, source_artifact, pointer in _ALLOWED_ORACLE_FACT_SPECS:
            value = request.resolve_pointer(source_artifact, pointer)
            if isinstance(value, (Mapping, list, tuple)):
                raise ContractValidationError(
                    f"allowed Oracle fact is not scalar: {fact_id}"
                )
            fact = OracleAllowedFact(
                fact_id=fact_id,
                source_artifact=source_artifact,
                json_pointer=pointer,
                value=copy.deepcopy(value),
            )
            if not _is_safe_observed_fact(fact, request):
                raise ContractValidationError(
                    f"allowed Oracle fact cannot produce a canonical observation: {fact_id}"
                )
            candidates.append(fact)
        if not candidates:
            raise ContractValidationError(
                "validated Oracle input produced no safe narrative facts"
            )
        if len(candidates) > _MAX_FACT_CATALOG_ITEMS:
            raise ContractValidationError(
                f"Oracle fact catalog exceeds {_MAX_FACT_CATALOG_ITEMS} entries"
            )
        ids = tuple(item.fact_id for item in candidates)
        if len(set(ids)) != len(ids):
            raise ContractValidationError("Oracle fact catalog contains an ID collision")
        return cls(
            schema_version=ORACLE_FACT_CATALOG_SCHEMA_VERSION,
            mission_id=request.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            source_artifacts={
                artifact_name: request.source_artifacts[evidence_name]
                for evidence_name, artifact_name in EVIDENCE_ARTIFACT_NAMES.items()
            },
            facts=tuple(candidates),
        )

    @property
    def by_id(self) -> Mapping[str, OracleAllowedFact]:
        return {fact.fact_id: fact for fact in self.facts}

    def require(self, fact_id: str) -> OracleAllowedFact:
        try:
            return self.by_id[fact_id]
        except KeyError as exc:
            raise ContractValidationError(
                f"ModelDock selected an unknown Oracle fact ID: {fact_id!r}"
            ) from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "source_artifacts": {
                artifact_name: self.source_artifacts[artifact_name].to_dict()
                for artifact_name in EVIDENCE_ARTIFACT_NAMES.values()
            },
            "facts": [fact.to_dict() for fact in self.facts],
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_dict(),
            field_name="Oracle fact catalog",
            limit=_MAX_REQUEST_BYTES,
            reject_absolute_paths=False,
        )

    def to_canonical_json(self) -> str:
        return self.canonical_json_bytes().decode("utf-8")

    def model_json_bytes(self) -> bytes:
        """Return only the catalog ModelDock needs for fact selection.

        Mission correlation remains in the validated transport envelope and is
        applied to the canonical narrative by deterministic code. The model
        never needs to reproduce those identifiers.
        """

        return _canonical_json_bytes(
            {
                "schema_version": self.schema_version,
                "source_artifacts": {
                    artifact_name: self.source_artifacts[artifact_name].to_dict()
                    for artifact_name in EVIDENCE_ARTIFACT_NAMES.values()
                },
                "facts": [fact.to_dict() for fact in self.facts],
            },
            field_name="ModelDock Oracle fact catalog",
            limit=_MAX_REQUEST_BYTES,
            reject_absolute_paths=False,
        )

    def to_model_json(self) -> str:
        return self.model_json_bytes().decode("utf-8")


@dataclass(frozen=True, slots=True)
class OracleNarrativeSelection:
    """Untrusted ModelDock prose plus IDs from a deterministic fact catalog."""

    schema_version: str
    selected_fact_ids: tuple[str, ...]
    summary: str
    interpretation: str
    uncertainties: tuple[str, ...]
    confidence_explanation: str
    prohibited_actions_acknowledged: bool

    @classmethod
    def from_json_bytes(cls, source: bytes) -> "OracleNarrativeSelection":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                source, document_name="Oracle narrative selection"
            )
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "OracleNarrativeSelection":
        if not isinstance(value, Mapping):
            raise ContractValidationError(
                "Oracle narrative selection must be an object"
            )
        _require_exact_fields(
            value,
            _NARRATIVE_SELECTION_FIELDS,
            "Oracle narrative selection",
        )
        if value["schema_version"] != ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION:
            raise ContractValidationError(
                "unsupported Oracle narrative selection schema_version: "
                f"{value['schema_version']!r}"
            )
        raw_ids = value["selected_fact_ids"]
        if not isinstance(raw_ids, list):
            raise ContractValidationError("selected_fact_ids must be an array")
        if not raw_ids:
            raise ContractValidationError("selected_fact_ids must not be empty")
        if len(raw_ids) > _MAX_SELECTED_FACTS:
            raise ContractValidationError(
                f"selected_fact_ids exceeds {_MAX_SELECTED_FACTS} entries"
            )
        selected_ids: list[str] = []
        for index, raw_id in enumerate(raw_ids):
            if not isinstance(raw_id, str) or not _FACT_ID_PATTERN.fullmatch(raw_id):
                raise ContractValidationError(
                    f"selected_fact_ids[{index}] is not a canonical fact ID"
                )
            selected_ids.append(raw_id)
        if len(set(selected_ids)) != len(selected_ids):
            raise ContractValidationError("selected_fact_ids contains duplicates")
        acknowledged = value["prohibited_actions_acknowledged"]
        if acknowledged is not True:
            raise ContractValidationError(
                "prohibited_actions_acknowledged must be true"
            )
        selection = cls(
            schema_version=ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
            selected_fact_ids=tuple(selected_ids),
            summary=_strict_text(value["summary"], "summary", max_length=2000),
            interpretation=_strict_text(
                value["interpretation"], "interpretation", max_length=4000
            ),
            uncertainties=_strict_text_array(
                value["uncertainties"], "uncertainties"
            ),
            confidence_explanation=_strict_text(
                value["confidence_explanation"],
                "confidence_explanation",
                max_length=2000,
            ),
            prohibited_actions_acknowledged=True,
        )
        for field_name, field_value in (
            ("summary", selection.summary),
            ("interpretation", selection.interpretation),
            ("confidence_explanation", selection.confidence_explanation),
            *[("uncertainties", item) for item in selection.uncertainties],
        ):
            _reject_absolute_local_text(field_value, field_name)
        _canonical_json_bytes(
            selection.to_dict(),
            field_name="Oracle narrative selection",
            limit=_MAX_NARRATIVE_BYTES,
            reject_absolute_paths=False,
        )
        return selection

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "selected_fact_ids": list(self.selected_fact_ids),
            "summary": self.summary,
            "interpretation": self.interpretation,
            "uncertainties": list(self.uncertainties),
            "confidence_explanation": self.confidence_explanation,
            "prohibited_actions_acknowledged": self.prohibited_actions_acknowledged,
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_dict(),
            field_name="Oracle narrative selection",
            limit=_MAX_NARRATIVE_BYTES,
            reject_absolute_paths=False,
        )

    def expand(
        self,
        catalog: OracleFactCatalog,
        request: OracleNarrativeRequest,
    ) -> OracleNarrative:
        if not isinstance(catalog, OracleFactCatalog) or not isinstance(
            request, OracleNarrativeRequest
        ):
            raise ContractValidationError(
                "Oracle narrative expansion requires a fact catalog and request"
            )
        if (request.mission_id, request.request_id, request.symbol) != (
            catalog.mission_id,
            catalog.request_id,
            catalog.symbol,
        ):
            raise ContractValidationError("Oracle fact catalog correlation mismatch")
        selected = set(self.selected_fact_ids)
        catalog_by_id = catalog.by_id
        unknown = next(
            (
                fact_id
                for fact_id in self.selected_fact_ids
                if fact_id not in catalog_by_id
            ),
            None,
        )
        if unknown is not None:
            catalog.require(unknown)
        facts = tuple(
            fact.to_observed_fact() for fact in catalog.facts if fact.fact_id in selected
        )
        narrative = OracleNarrative.from_mapping(
            {
                "schema_version": ORACLE_NARRATIVE_SCHEMA_VERSION,
                "mission_id": request.mission_id,
                "request_id": request.request_id,
                "symbol": request.symbol,
                "summary": self.summary,
                "observed_facts": [fact.to_dict() for fact in facts],
                "interpretation": self.interpretation,
                "uncertainties": list(self.uncertainties),
                "warnings": list(request.warnings),
                "confidence_explanation": self.confidence_explanation,
                "prohibited_actions_acknowledged": True,
            }
        )
        return narrative.validate_against(request)


def _render_observed_fact_statement(
    json_pointer: str, value: None | bool | int | float | str
) -> str:
    parts = [
        part.replace("~1", "/").replace("~0", "~")
        for part in json_pointer[1:].split("/")
    ]
    label_part = next(
        (part for part in reversed(parts) if not part.isdigit()),
        "value",
    )
    label = " ".join(re.sub(r"[_-]+", " ", label_part).split()) or "value"
    if value is None:
        rendered = "null"
    elif type(value) is bool:
        rendered = "true" if value else "false"
    elif type(value) in {int, float}:
        rendered = json.dumps(value, allow_nan=False)
    else:
        rendered = value
    suffix = "" if isinstance(rendered, str) and rendered.endswith(".") else "."
    return f"The source-linked {label} is {rendered}{suffix}"


def _is_safe_observed_fact(
    fact: OracleAllowedFact, request: OracleNarrativeRequest
) -> bool:
    if isinstance(fact.value, str) and not fact.value.strip():
        return False
    try:
        observed = fact.to_observed_fact()
        _validate_source_bound_numbers((), (observed,))
        _validate_observed_fact_statements((observed,))
        texts = [observed.statement]
        if isinstance(observed.value, str):
            texts.append(observed.value)
        _reject_prohibited_authority(texts)
        _validate_symbol_attribution(texts, request)
        _validate_source_bound_vocabulary(texts, request)
    except ContractValidationError:
        return False
    return True


def validate_json_pointer(value: object) -> str:
    if not isinstance(value, str):
        raise ContractValidationError("json_pointer must be a string")
    if not value.startswith("/"):
        raise ContractValidationError("json_pointer must be a non-root RFC 6901 pointer")
    if len(value) > 1024:
        raise ContractValidationError("json_pointer exceeds 1024 characters")
    if _INVALID_POINTER_ESCAPE.search(value):
        raise ContractValidationError("json_pointer contains an invalid RFC 6901 escape")
    _strict_text(value, "json_pointer", max_length=1024)
    return value


def resolve_json_pointer(document: object, pointer: str) -> Any:
    """Resolve a strict RFC 6901 pointer, rejecting ambiguous array indexes."""

    pointer = validate_json_pointer(pointer)
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                raise ContractValidationError(
                    f"json_pointer does not resolve at object key {part!r}"
                )
            current = current[part]
        elif isinstance(current, list):
            if part == "-" or not part.isdigit() or (
                len(part) > 1 and part.startswith("0")
            ):
                raise ContractValidationError(
                    f"json_pointer contains an invalid array index: {part!r}"
                )
            index = int(part)
            if index >= len(current):
                raise ContractValidationError("json_pointer array index is out of range")
            current = current[index]
        else:
            raise ContractValidationError("json_pointer traverses through a scalar value")
    return current


def _validate_source_bound_numbers(
    free_texts: Sequence[str], facts: Sequence[ObservedFact]
) -> None:
    for text in free_texts:
        if _NUMERIC_TOKEN.search(text):
            raise ContractValidationError(
                "Oracle narrative free text may not contain numeric claims; "
                "numbers must be source-linked observed facts"
            )
    for fact in facts:
        tokens = _NUMERIC_TOKEN.findall(fact.statement)
        if not tokens:
            continue
        if type(fact.value) not in {int, float}:
            raise ContractValidationError(
                "numeric observed-fact statements require a numeric source scalar"
            )
        expected = Decimal(str(fact.value)).normalize()
        for token in tokens:
            try:
                actual = Decimal(token).normalize()
            except InvalidOperation as exc:
                raise ContractValidationError(
                    "observed-fact statement contains an invalid numeric token"
                ) from exc
            if actual != expected:
                raise ContractValidationError(
                    "observed-fact statement numeric claim does not match its "
                    "source-linked scalar"
                )


def _validate_observed_fact_statements(facts: Sequence[ObservedFact]) -> None:
    for fact in facts:
        statement = fact.statement
        if re.search(r"[!?;\n\r]|\.(?:\s+\S)", statement):
            raise ContractValidationError(
                "observed-fact statement must be one bounded source-linked clause"
            )
        pointer_tokens: set[str] = set()
        for raw_part in fact.json_pointer[1:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            pointer_tokens.update(
                token.lower() for token in _WORD_TOKEN.findall(part)
            )
        statement_tokens = {
            token.lower() for token in _WORD_TOKEN.findall(statement)
        }
        if pointer_tokens and not pointer_tokens.intersection(statement_tokens):
            raise ContractValidationError(
                "observed-fact statement must name its source-linked field"
            )

        if type(fact.value) in {int, float}:
            if not _NUMERIC_TOKEN.search(statement):
                raise ContractValidationError(
                    "numeric observed-fact statement must include its exact source value"
                )
        elif isinstance(fact.value, bool):
            expected = "true" if fact.value else "false"
            if expected not in statement_tokens:
                raise ContractValidationError(
                    "boolean observed-fact statement must include its exact source value"
                )
        elif isinstance(fact.value, str):
            if _normalized_claim_text(fact.value) not in _normalized_claim_text(
                statement
            ):
                raise ContractValidationError(
                    "text observed-fact statement must include its exact source value"
                )
        elif fact.value is None and "null" not in statement_tokens:
            raise ContractValidationError(
                "null observed-fact statement must identify its source value"
            )


def _normalized_claim_text(value: str) -> str:
    return " ".join(re.sub(r"[_-]+", " ", value.lower()).split())


def _oracle_text_evidence(request: OracleNarrativeRequest) -> tuple[str, ...]:
    values: list[str] = [request.oracle_native_state, *request.warnings]

    def collect(value: object) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Mapping):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(request.evidence)
    return tuple(_normalized_claim_text(value) for value in values if value.strip())


def _oracle_vocabulary(request: OracleNarrativeRequest) -> frozenset[str]:
    """Return the finite domain vocabulary explicitly present in Oracle input.

    ModelDock is allowed to connect and explain those terms, but introducing a
    new market domain (for example volatility, rates, or an unobserved sector)
    is rejected instead of being treated as harmless prose.
    """

    tokens: set[str] = set(_GENERIC_NARRATIVE_WORDS)

    def collect(value: object) -> None:
        if isinstance(value, str):
            tokens.update(token.lower() for token in _WORD_TOKEN.findall(value))
        elif isinstance(value, Mapping):
            for key, child in value.items():
                tokens.update(token.lower() for token in _WORD_TOKEN.findall(str(key)))
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(request.oracle_native_state)
    collect(request.warnings)
    collect(request.evidence)
    return frozenset(tokens)


def _validate_source_bound_vocabulary(
    texts: Sequence[str], request: OracleNarrativeRequest
) -> None:
    vocabulary = _oracle_vocabulary(request)
    for text in texts:
        unsupported = sorted(
            {
                token.lower()
                for token in _WORD_TOKEN.findall(text)
                if token.lower() not in vocabulary
            }
        )
        if unsupported:
            raise ContractValidationError(
                "Oracle narrative contains vocabulary absent from the validated "
                f"Oracle input: {', '.join(unsupported)}"
            )


def _validate_semantic_claims(
    texts: Sequence[str], request: OracleNarrativeRequest
) -> None:
    for text in texts:
        for match in _FACTUAL_ASSERTION.finditer(text):
            claim = _normalized_claim_text(match.group("claim"))
            claim = re.sub(r"^(?:that\s+|a\s+|an\s+|the\s+)", "", claim)
            if not claim:
                raise ContractValidationError(
                    "Oracle narrative contains an empty factual assertion"
                )
            subject = _normalized_claim_text(match.group("subject"))
            evidence_text = _semantic_evidence_for_subject(subject, request)
            if not any(claim in source for source in evidence_text):
                raise ContractValidationError(
                    "Oracle narrative contains a factual readiness, diagnostic, "
                    "posture, or momentum claim not supported by Oracle evidence"
                )


def _semantic_evidence_for_subject(
    subject: str, request: OracleNarrativeRequest
) -> tuple[str, ...]:
    if subject.startswith("readiness") or subject == "coverage":
        selected: object = {
            "readiness": request.readiness,
            "warnings": request.warnings,
        }
    elif subject.startswith("diagnostic"):
        selected = request.diagnostics
    elif subject.startswith("measurement"):
        selected = request.measurements
    elif subject == "report":
        selected = request.report
    elif subject in {
        "assessment",
        "market posture",
        "analytical posture",
        "risk posture",
        "momentum",
    }:
        selected = {"assessment": request.assessment, "report": request.report}
    else:
        return _oracle_text_evidence(request)

    values: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            values.append(_normalized_claim_text(value))
        elif isinstance(value, Mapping):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(selected)
    return tuple(value for value in values if value)


def _validate_symbol_attribution(
    texts: Sequence[str], request: OracleNarrativeRequest
) -> None:
    symbol_pattern = re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(request.symbol)}(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    )
    if not any(symbol_pattern.search(source) for source in _oracle_text_evidence(request)):
        if any(symbol_pattern.search(text) for text in texts):
            raise ContractValidationError(
                "mission symbol is correlation-only because no Oracle evidence "
                "attributes facts to that symbol"
            )


def _reject_prohibited_authority(texts: Sequence[str]) -> None:
    for text in texts:
        if _PROHIBITED_DISPOSITION.search(text):
            raise ContractValidationError(
                "Oracle narrative contains a Governor disposition or approval claim"
            )
        if (
            _PROHIBITED_OPERATION.search(text)
            or _AUTHORITY_CLAIM.search(text)
            or _POSITION_RECOMMENDATION.search(text)
        ):
            raise ContractValidationError(
                "Oracle narrative contains an order, execution, or trading recommendation"
            )


def build_oracle_narrative_prompt(request: OracleNarrativeRequest) -> str:
    """Build a fact-selection prompt without delegating source linkage."""

    if not isinstance(request, OracleNarrativeRequest):
        raise ContractValidationError("prompt input must be an OracleNarrativeRequest")
    catalog = OracleFactCatalog.from_request(request)
    expected_shape = {
        "schema_version": ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
        "selected_fact_ids": [
            "one to five exact fact_id values copied from the catalog"
        ],
        "summary": "Validated Oracle facts reflect qualitative catalog terms.",
        "interpretation": "The source-linked facts suggest a bounded interpretation.",
        "uncertainties": [],
        "confidence_explanation": "Confidence is bounded by the source-linked facts.",
        "prohibited_actions_acknowledged": True,
    }
    connective_vocabulary = ",".join(sorted(_GENERIC_NARRATIVE_WORDS))
    instructions = (
        "You are a local narrative renderer over a deterministic catalog of "
        "validated BlackPod Oracle facts.\n"
        "Return exactly one JSON object and no markdown or surrounding text.\n"
        "Select between one and five unique fact_id values from the supplied "
        "catalog and copy each selected ID exactly.\n"
        "Write only summary, interpretation, uncertainties, and "
        "confidence_explanation prose. Do not write observed_facts, source "
        "artifacts, JSON pointers, values, statements, or canonical warnings. "
        "Do not write mission_id, request_id, symbol, run_mode, or any other "
        "correlation field; Build Week applies validated transport correlation. "
        "Build Week expands selected IDs and copies Oracle warnings "
        "deterministically after your response.\n"
        "Treat the catalog as the only source of market facts. It may describe "
        "a fixed validation fleet rather than a single security.\n"
        "Do not place digits or numerical claims in any prose field. Do not invent "
        "or alter measurements, diagnostics, readiness, or analytical conclusions.\n"
        "The selected IDs carry every factual status and posture. In prose, do "
        "not make a new subject-predicate assertion beginning with evidence, "
        "diagnostics, readiness, coverage, assessment, report, measurements, "
        "market posture, analytical posture, risk posture, or momentum. Use "
        "interpretive phrasing. summary must be one sentence beginning exactly "
        "'Validated Oracle facts reflect '. interpretation must be one sentence "
        "beginning exactly 'The source-linked facts suggest '. Set uncertainties "
        "to []. Set confidence_explanation exactly to 'Confidence is bounded by "
        "the source-linked facts.'.\n"
        "Outside exact qualitative words copied from catalog field names or "
        "values, prose may use only this approved connective vocabulary; do not "
        "substitute synonyms:\n"
        + connective_vocabulary
        + "\n"
        "Do not approve a mission, choose a Governor disposition, recommend an "
        "order or trade, or claim execution authority.\n"
        "Return every field in the expected shape exactly once. uncertainties "
        "must always be a JSON array; use [] when none apply. Unknown fields are "
        "forbidden. prohibited_actions_acknowledged must be true.\n"
        "Expected output shape:\n"
        + json.dumps(
            expected_shape,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\nCanonical allowed-fact catalog:\n"
        + catalog.to_model_json()
    )
    if len(instructions.encode("utf-8")) > _MAX_REQUEST_BYTES:
        raise ContractValidationError("Oracle narrative prompt exceeds the size limit")
    return instructions


@dataclass(frozen=True, slots=True)
class ModelDockReplayPack:
    """Deterministic replay pack containing inputs, wire data, and expectations."""

    schema_version: str
    fixture_id: str
    created_at: str
    observed_at: str
    oracle_input: OracleNarrativeRequest
    request: dict[str, Any]
    response: dict[str, Any]
    expected_narrative: OracleNarrative
    expected_provenance: dict[str, Any]
    expected_snapshot_changes: dict[str, Any]

    @classmethod
    def from_file(cls, path: Path) -> "ModelDockReplayPack":
        try:
            source = path.read_bytes()
        except OSError as exc:
            raise ContractValidationError(f"cannot read ModelDock replay pack: {exc}") from exc
        return cls.from_json_bytes(source)

    @classmethod
    def from_json_bytes(cls, source: bytes) -> "ModelDockReplayPack":
        return cls.from_mapping(
            parse_strict_json_object_bytes(source, document_name="ModelDock replay pack")
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ModelDockReplayPack":
        if not isinstance(value, Mapping):
            raise ContractValidationError("ModelDock replay pack must be an object")
        _require_exact_fields(value, _REPLAY_PACK_FIELDS, "ModelDock replay pack")
        if value["schema_version"] != MODELDOCK_REPLAY_PACK_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported ModelDock replay pack schema_version: "
                f"{value['schema_version']!r}"
            )
        fixture_id = _strict_identifier(value["fixture_id"], "fixture_id")
        created_at = normalize_rfc3339(value["created_at"], "created_at")
        observed_at = normalize_rfc3339(value["observed_at"], "observed_at")
        if parse_rfc3339(observed_at, "observed_at") < parse_rfc3339(
            created_at, "created_at"
        ):
            raise ContractValidationError("observed_at may not precede created_at")
        oracle_input = OracleNarrativeRequest.from_mapping(value["oracle_input"])
        expected_narrative = OracleNarrative.from_mapping(value["expected_narrative"])
        expected_narrative.validate_against(oracle_input)

        generic_sections: dict[str, dict[str, Any]] = {}
        for section in ("request", "response"):
            section_value = value[section]
            if not isinstance(section_value, Mapping) or not section_value:
                raise ContractValidationError(f"{section} must be a nonempty object")
            section_copy = copy.deepcopy(dict(section_value))
            _canonical_json_bytes(
                section_copy,
                field_name=f"ModelDock replay pack {section}",
                limit=_MAX_REQUEST_BYTES,
                # The deterministic prompt contains RFC 6901 pointers and the
                # response content contains the same pointers.  Their parsed
                # contracts enforce path safety; all other wire fields are
                # checked independently immediately below.
                reject_absolute_paths=False,
            )
            _validate_wire_section_without_payload(
                section_copy,
                omitted_field="prompt" if section == "request" else "content",
                field_name=f"ModelDock replay pack {section}",
            )
            generic_sections[section] = section_copy

        expected_provenance = _parse_expected_provenance(
            value["expected_provenance"]
        )
        expected_snapshot_changes = _parse_expected_snapshot_changes(
            value["expected_snapshot_changes"]
        )

        _validate_replay_correlation(
            generic_sections["request"], "request", oracle_input
        )
        _validate_replay_correlation(
            generic_sections["response"], "response", oracle_input
        )
        prompt = generic_sections["request"].get("prompt")
        if prompt != oracle_input.build_prompt():
            raise ContractValidationError(
                "ModelDock replay pack request prompt does not match oracle_input"
            )
        content = generic_sections["response"].get("content")
        if not isinstance(content, str):
            raise ContractValidationError(
                "ModelDock replay pack response.content must be a JSON string"
            )
        replay_mapping = parse_strict_json_object_bytes(
            content.encode("utf-8"),
            document_name="ModelDock replay response content",
        )
        replay_narrative = OracleNarrativeSelection.from_mapping(
            replay_mapping
        ).expand(OracleFactCatalog.from_request(oracle_input), oracle_input)
        if replay_narrative.to_dict() != expected_narrative.to_dict():
            raise ContractValidationError(
                "ModelDock replay response content does not match expected_narrative"
            )
        _validate_expected_response_provenance(
            generic_sections["response"], expected_provenance
        )

        pack = cls(
            schema_version=MODELDOCK_REPLAY_PACK_SCHEMA_VERSION,
            fixture_id=fixture_id,
            created_at=created_at,
            observed_at=observed_at,
            oracle_input=oracle_input,
            request=generic_sections["request"],
            response=generic_sections["response"],
            expected_narrative=expected_narrative,
            expected_provenance=expected_provenance,
            expected_snapshot_changes=expected_snapshot_changes,
        )
        _canonical_json_bytes(
            pack.to_dict(),
            field_name="ModelDock replay pack",
            limit=5 * 1024 * 1024,
            reject_absolute_paths=False,
        )
        return pack

    def raw_section(self, name: str) -> dict[str, Any]:
        """Return a defensive copy of an exact raw replay section."""

        if name not in {
            "request",
            "response",
            "expected_provenance",
            "expected_snapshot_changes",
        }:
            raise ContractValidationError(f"unknown replay pack raw section: {name!r}")
        return copy.deepcopy(getattr(self, name))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "created_at": self.created_at,
            "observed_at": self.observed_at,
            "oracle_input": self.oracle_input.to_dict(),
            "request": copy.deepcopy(self.request),
            "response": copy.deepcopy(self.response),
            "expected_narrative": self.expected_narrative.to_dict(),
            "expected_provenance": copy.deepcopy(self.expected_provenance),
            "expected_snapshot_changes": copy.deepcopy(self.expected_snapshot_changes),
        }

    def canonical_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_dict(),
            field_name="ModelDock replay pack",
            limit=5 * 1024 * 1024,
            reject_absolute_paths=False,
        )

    def to_canonical_json(self) -> str:
        return self.canonical_json_bytes().decode("utf-8")
