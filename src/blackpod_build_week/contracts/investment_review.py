"""Strict source-bound SHADOW challenge and deadline-point review contracts.

Reviewer identities and evidence-role/provenance labels are supplied claims,
not authentication or proof of economic independence. These documents cannot
authorize execution, capital activation, allocation, or policy changes.
"""

from __future__ import annotations

from typing import Any

from ..hashing import canonical_json_bytes
from .decision_journal import (
    _ImmutableDocument, _boolean, _enum, _hash, _identifier, _journal_id,
    _object, _string,
)
from .investment_hypothesis import HYPOTHESIS_AUTHORITY_FIELDS, _observations, _scalar
from .mission_request import (
    ContractValidationError, normalize_rfc3339, parse_rfc3339,
    parse_strict_json_object_bytes,
)

INVESTMENT_CHALLENGE_SCHEMA_VERSION = "blackpod.investment_challenge.v1"
INVESTMENT_OUTCOME_EVALUATION_SCHEMA_VERSION = "blackpod.investment_outcome_evaluation.v1"
ASSESSMENT_METHOD_VERSION = "blackpod.source_relationship_assessment.v1"
COMPARISON_METHOD_VERSION = "blackpod.deadline_point_comparison.v1"
EVIDENCE_ROLES = frozenset({"FUNDAMENTAL", "STATISTICAL", "MACRO", "MARKET", "OPERATIONAL"})
REQUIRED_EVIDENCE_ROLES = frozenset({"FUNDAMENTAL", "STATISTICAL"})
SOURCE_RELATIONSHIPS = frozenset({"SAME_VALUE_BINDING", "SHARED_ARTIFACT", "DISTINCT_RETAINED_ARTIFACT"})
CHECK_TYPES = frozenset({"OUTCOME", "INVALIDATION"})
CHECK_STATUSES = frozenset({"NOT_DUE", "MISSING", "INCONCLUSIVE", "MET", "NOT_MET", "TRIGGERED", "NOT_TRIGGERED"})
COMPARISON_SUMMARIES = frozenset({
    "PENDING", "INCONCLUSIVE", "INVALIDATION_TRIGGERED", "EXPECTATIONS_NOT_MET",
    "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION",
})
OBSERVATION_FIELDS = frozenset({
    "observation_id", "source_event_id", "artifact_path", "artifact_sha256", "value_pointer",
    "value", "unit", "as_of_pointer", "as_of", "time_role",
})
_BASE_FIELDS = frozenset({
    "schema_version", "hypothesis_event_id", "hypothesis_id", "hypothesis_sha256", "recorded_at",
    "domain", "mode", "evidence_cutoff_at", "supersedes_event_id", "authority",
})
_CHALLENGE_FIELDS = _BASE_FIELDS | {
    "challenge_id", "reviewer_id", "observations", "assumption_reviews", "counter_hypotheses",
    "disposition", "unresolved_questions", "risk_notes",
}
_EVALUATION_FIELDS = _BASE_FIELDS | {
    "evaluation_id", "challenge_event_id", "evaluator_id", "evaluator_role", "evaluation_stage",
    "measurements", "conclusion",
}


def _list(value: object, name: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractValidationError(f"{name} must be a {'nonempty ' if nonempty else ''}list")
    return value


def _texts(value: object, name: str, *, identifiers: bool = False) -> list[str]:
    entries = [(_identifier(item, name) if identifiers else _string(item, name, 10000))
               for item in _list(value, name)]
    if len(set(entries)) != len(entries):
        raise ContractValidationError(f"{name} contains duplicate values")
    return entries


def _event_id(value: object, name: str) -> str:
    result = _journal_id(value, name)
    if not result.startswith("journal-event-"):
        raise ContractValidationError(f"{name} must have the journal-event prefix")
    return result


def disabled_authority(value: object) -> dict[str, bool]:
    result = _object(value, HYPOTHESIS_AUTHORITY_FIELDS, "authority")
    for field in result:
        if _boolean(result[field], "authority." + field):
            raise ContractValidationError(f"authority.{field} must remain disabled")
    return result


def _fixed_boolean(result: dict[str, Any], field: str, expected: bool) -> None:
    if _boolean(result[field], field) is not expected:
        raise ContractValidationError(f"{field} must be {expected}")


def _base(value: object, fields: frozenset[str] | set[str], schema: str, name: str) -> dict[str, Any]:
    result = _object(value, fields, name)
    for field, expected in {"schema_version": schema, "domain": "INVESTMENT", "mode": "SHADOW"}.items():
        if result[field] != expected:
            raise ContractValidationError(f"{name}.{field} must be {expected!r}")
    result["hypothesis_event_id"] = _event_id(result["hypothesis_event_id"], "hypothesis_event_id")
    result["hypothesis_id"] = _identifier(result["hypothesis_id"], "hypothesis_id")
    result["hypothesis_sha256"] = _hash(result["hypothesis_sha256"], "hypothesis_sha256")
    for field in ("recorded_at", "evidence_cutoff_at"):
        result[field] = normalize_rfc3339(result[field], field)
    if parse_rfc3339(result["evidence_cutoff_at"], "evidence_cutoff_at") > parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("evidence_cutoff_at must not be after recorded_at")
    if result["supersedes_event_id"] is not None:
        result["supersedes_event_id"] = _event_id(result["supersedes_event_id"], "supersedes_event_id")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _check_observation_cutoff(observations: list[dict[str, Any]], cutoff: str) -> None:
    if any(parse_rfc3339(item["as_of"], "as_of") > parse_rfc3339(cutoff, "evidence_cutoff_at") for item in observations):
        raise ContractValidationError("observation.as_of must not be after evidence_cutoff_at")


def _challenge(value: object) -> dict[str, Any]:
    result = _base(value, _CHALLENGE_FIELDS, INVESTMENT_CHALLENGE_SCHEMA_VERSION, "investment challenge")
    for field in ("challenge_id", "reviewer_id"):
        result[field] = _identifier(result[field], field)
    observations, basic = [], []
    for entry in _list(result["observations"], "observations"):
        item = _object(entry, OBSERVATION_FIELDS | {"evidence_role", "provenance_group"}, "challenge observation")
        basic.append({key: item[key] for key in OBSERVATION_FIELDS})
        observations.append({
            "evidence_role": _enum(item["evidence_role"], EVIDENCE_ROLES, "evidence_role"),
            "provenance_group": _string(item["provenance_group"], "provenance_group"),
        })
    normalized = _observations(basic) if basic else []
    result["observations"] = [{**item, **metadata} for item, metadata in zip(normalized, observations)]
    _check_observation_cutoff(normalized, result["evidence_cutoff_at"])
    known = {item["observation_id"] for item in normalized}
    assumptions, indices = [], set()
    for entry in _list(result["assumption_reviews"], "assumption_reviews", nonempty=True):
        item = _object(entry, {"assumption_index", "status", "reason", "observation_ids"}, "assumption review")
        index = item["assumption_index"]
        if type(index) is not int or index < 0:
            raise ContractValidationError("assumption_index must be a nonnegative integer")
        if index in indices:
            raise ContractValidationError("assumption_reviews contains duplicate assumption_index")
        indices.add(index)
        item["status"] = _enum(item["status"], {"SUPPORTED", "CONTESTED", "UNTESTED"}, "assumption status")
        item["reason"] = _string(item["reason"], "assumption reason", 10000)
        item["observation_ids"] = _texts(item["observation_ids"], "assumption observation_ids", identifiers=True)
        if not set(item["observation_ids"]) <= known:
            raise ContractValidationError("assumption review references unknown observation_ids")
        assumptions.append(item)
    result["assumption_reviews"] = assumptions
    counters, identities = [], set()
    for entry in _list(result["counter_hypotheses"], "counter_hypotheses", nonempty=True):
        item = _object(entry, {"counter_id", "statement", "discriminating_test", "observation_ids"}, "counter hypothesis")
        item["counter_id"] = _identifier(item["counter_id"], "counter_id")
        if item["counter_id"] in identities:
            raise ContractValidationError("counter_hypotheses contains duplicate counter_id")
        identities.add(item["counter_id"])
        for field in ("statement", "discriminating_test"):
            item[field] = _string(item[field], field, 10000)
        item["observation_ids"] = _texts(item["observation_ids"], "counter observation_ids", identifiers=True)
        if not set(item["observation_ids"]) <= known:
            raise ContractValidationError("counter hypothesis references unknown observation_ids")
        counters.append(item)
    result["counter_hypotheses"] = counters
    result["disposition"] = _enum(result["disposition"], {"REVIEW_SUPPORTS", "REVIEW_CONTESTS", "INSUFFICIENT_EVIDENCE"}, "disposition")
    for field in ("unresolved_questions", "risk_notes"):
        result[field] = _texts(result[field], field)
    return result


def _evaluation(value: object) -> dict[str, Any]:
    result = _base(value, _EVALUATION_FIELDS, INVESTMENT_OUTCOME_EVALUATION_SCHEMA_VERSION, "investment outcome evaluation")
    for field in ("evaluation_id", "evaluator_id"):
        result[field] = _identifier(result[field], field)
    result["evaluator_role"] = _string(result["evaluator_role"], "evaluator_role")
    result["challenge_event_id"] = _event_id(result["challenge_event_id"], "challenge_event_id")
    result["evaluation_stage"] = _enum(result["evaluation_stage"], {"INTERIM", "FINAL"}, "evaluation_stage")
    measurements, identities, observations = [], set(), {}
    for entry in _list(result["measurements"], "measurements"):
        item = _object(entry, {"check_type", "check_id", "metric", "unit", "observation"}, "measurement")
        item["check_type"] = _enum(item["check_type"], CHECK_TYPES, "check_type")
        item["check_id"] = _identifier(item["check_id"], "check_id")
        key = item["check_type"], item["check_id"]
        if key in identities:
            raise ContractValidationError("measurements contains duplicate check_type/check_id")
        identities.add(key)
        for field in ("metric", "unit"):
            item[field] = _string(item[field], field)
        item["observation"] = _observations([item["observation"]])[0]
        observation_id = item["observation"]["observation_id"]
        if observation_id in observations and canonical_json_bytes(observations[observation_id]) != canonical_json_bytes(item["observation"]):
            raise ContractValidationError("measurements reuse an observation_id with a different binding")
        observations[observation_id] = item["observation"]
        if item["unit"] != item["observation"]["unit"]:
            raise ContractValidationError("measurement unit must match observation unit")
        measurements.append(item)
    result["measurements"] = measurements
    _check_observation_cutoff([item["observation"] for item in measurements], result["evidence_cutoff_at"])
    result["conclusion"] = _string(result["conclusion"], "conclusion", 10000)
    return result


def validate_challenge_assessment(value: object, challenge: ChallengeInput) -> dict[str, Any]:
    """Validate the shape and conservative claims of a computed assessment."""
    result = _object(value, {
        "assessment_method_version", "reviewer_distinct", "reviewer_identity_authenticated", "source_relationships", "declared_evidence_roles",
        "missing_evidence_roles", "source_independence_verified", "economic_truth_evaluated", "execution_status", "authority",
    }, "challenge assessment")
    if result["assessment_method_version"] != ASSESSMENT_METHOD_VERSION:
        raise ContractValidationError("unsupported assessment_method_version")
    _fixed_boolean(result, "reviewer_distinct", True)
    for field in ("reviewer_identity_authenticated", "source_independence_verified", "economic_truth_evaluated"):
        _fixed_boolean(result, field, False)
    relationships, identities = [], set()
    observations = {item["observation_id"]: item for item in challenge.observations}
    for entry in _list(result["source_relationships"], "source_relationships"):
        item = _object(entry, {"observation_id", "relationship", "independence_verified", "evidence_role", "provenance_group"}, "source relationship")
        item["observation_id"] = _identifier(item["observation_id"], "observation_id")
        if item["observation_id"] in identities or item["observation_id"] not in observations:
            raise ContractValidationError("source_relationships contains duplicate or unknown observation_id")
        identities.add(item["observation_id"])
        item["relationship"] = _enum(item["relationship"], SOURCE_RELATIONSHIPS, "relationship")
        _fixed_boolean(item, "independence_verified", False)
        item["evidence_role"] = _enum(item["evidence_role"], EVIDENCE_ROLES, "evidence_role")
        item["provenance_group"] = _string(item["provenance_group"], "provenance_group")
        if any(item[field] != observations[item["observation_id"]][field] for field in ("evidence_role", "provenance_group")):
            raise ContractValidationError("source relationship metadata must match challenge observation")
        relationships.append(item)
    if identities != set(observations):
        raise ContractValidationError("source_relationships must cover every challenge observation")
    result["source_relationships"] = relationships
    for field, allowed in (("declared_evidence_roles", EVIDENCE_ROLES), ("missing_evidence_roles", REQUIRED_EVIDENCE_ROLES)):
        result[field] = [_enum(item, allowed, field) for item in _texts(result[field], field)]
    roles = {item["evidence_role"] for item in observations.values()}
    if set(result["declared_evidence_roles"]) != roles or set(result["missing_evidence_roles"]) != REQUIRED_EVIDENCE_ROLES - roles:
        raise ContractValidationError("assessment evidence roles must match challenge observations")
    if result["execution_status"] != "NOT_EXECUTED":
        raise ContractValidationError("challenge execution_status must be NOT_EXECUTED")
    result["authority"] = disabled_authority(result["authority"])
    return result


def validate_outcome_result(value: object, evaluation: OutcomeEvaluationInput) -> dict[str, Any]:
    """Validate a report of source-bound deadline points, never trade P&L."""
    result = _object(value, {
        "comparison_method_version", "plan_id", "evaluation_stage", "comparison_summary", "check_results", "measurement_basis",
        "whole_horizon_invalidation_established", "manual_review_required", "hypothesis_research_mode",
        "economic_truth_evaluated", "execution_status", "realized_trade_pnl", "authority",
    }, "outcome result")
    if result["comparison_method_version"] != COMPARISON_METHOD_VERSION:
        raise ContractValidationError("unsupported comparison_method_version")
    result["plan_id"] = _identifier(result["plan_id"], "plan_id")
    result["evaluation_stage"] = _enum(result["evaluation_stage"], {"INTERIM", "FINAL"}, "evaluation_stage")
    if result["evaluation_stage"] != evaluation.evaluation_stage:
        raise ContractValidationError("outcome result evaluation_stage must match evaluation")
    result["comparison_summary"] = _enum(result["comparison_summary"], COMPARISON_SUMMARIES, "comparison_summary")
    checks, identities = [], set()
    for entry in _list(result["check_results"], "check_results"):
        item = _object(entry, {"check_type", "check_id", "status", "metric", "unit", "due_at", "observed_value", "observation_id"}, "check result")
        item["check_type"] = _enum(item["check_type"], CHECK_TYPES, "check_type")
        item["check_id"] = _identifier(item["check_id"], "check_id")
        identity = item["check_type"], item["check_id"]
        if identity in identities:
            raise ContractValidationError("check_results contains duplicate check_type/check_id")
        identities.add(identity)
        item["status"] = _enum(item["status"], CHECK_STATUSES, "check status")
        if ((item["check_type"] == "OUTCOME" and item["status"] in {"TRIGGERED", "NOT_TRIGGERED"}) or
                (item["check_type"] == "INVALIDATION" and item["status"] in {"MET", "NOT_MET"})):
            raise ContractValidationError("check status does not match check_type")
        for field in ("metric", "unit"):
            item[field] = _string(item[field], field)
        item["due_at"] = normalize_rfc3339(item["due_at"], "due_at")
        item["observed_value"] = _scalar(item["observed_value"], "observed_value")
        if item["observation_id"] is not None:
            item["observation_id"] = _identifier(item["observation_id"], "observation_id")
        if item["status"] in {"NOT_DUE", "MISSING"} and (item["observed_value"] is not None or item["observation_id"] is not None):
            raise ContractValidationError("NOT_DUE/MISSING checks require null observed_value and observation_id")
        checks.append(item)
    result["check_results"] = checks
    if result["measurement_basis"] != "RECORDED_DEADLINE_POINTS_ONLY":
        raise ContractValidationError("measurement_basis must be RECORDED_DEADLINE_POINTS_ONLY")
    for field, expected in (("whole_horizon_invalidation_established", False), ("manual_review_required", True), ("economic_truth_evaluated", False)):
        _fixed_boolean(result, field, expected)
    result["hypothesis_research_mode"] = _enum(result["hypothesis_research_mode"], {"PROSPECTIVE", "RETROSPECTIVE"}, "hypothesis_research_mode")
    if result["execution_status"] != "NOT_EXECUTED" or result["realized_trade_pnl"] is not None:
        raise ContractValidationError("SHADOW outcome results require NOT_EXECUTED and null realized_trade_pnl")
    result["authority"] = disabled_authority(result["authority"])
    return result


class _ReviewDocument(_ImmutableDocument):
    __slots__ = ()

    def __init__(self, value) -> None:
        try:
            super().__init__(value)
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("investment review nesting or numeric representation exceeds supported limits") from exc

    @classmethod
    def from_bytes(cls, value: bytes):
        try:
            parsed = parse_strict_json_object_bytes(value, document_name=cls.__name__)
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("investment review JSON nesting or numeric representation exceeds supported limits") from exc
        return cls.from_mapping(parsed)


class ChallengeInput(_ReviewDocument):
    """Immutable supplied adversarial review, with no authorization authority."""

    __slots__ = ()
    _validator = staticmethod(_challenge)


class OutcomeEvaluationInput(_ReviewDocument):
    """Immutable supplied observations against the original fixed review plan."""

    __slots__ = ()
    _validator = staticmethod(_evaluation)
