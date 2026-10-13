"""Strict human-supplied investment research drafts with no decision authority.

The document states testable expectations and an evaluation plan. Evidence
bindings are verified separately against retained journal sources; validation
of this document alone does not establish that its causal interpretation is
true, independent, or precommitted.
"""

from __future__ import annotations

import re
from typing import Any

from .decision_journal import (
    _ImmutableDocument,
    _boolean,
    _enum,
    _finite_number,
    _hash,
    _identifier,
    _journal_id,
    _object,
    _string,
    validate_evidence_path,
)
from .mission_request import (
    ContractValidationError,
    normalize_rfc3339,
    parse_rfc3339,
    parse_strict_json_object_bytes,
)

INVESTMENT_HYPOTHESIS_SCHEMA_VERSION = "blackpod.investment_hypothesis.v1"
HYPOTHESIS_OPERATORS = frozenset({"GT", "GTE", "LT", "LTE", "EQ", "NE"})
HYPOTHESIS_AUTHORITY_FIELDS = frozenset({
    "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
})
_POINTER_ESCAPE = re.compile(r"~(?![01])")
_ROOT_FIELDS = frozenset({
    "schema_version", "hypothesis_id", "recorded_at", "author_id", "domain", "mode", "status",
    "research_mode", "evidence_cutoff_at", "scope", "observations", "hypothesis", "horizon",
    "expected_outcomes", "alternatives", "invalidation_conditions", "evaluation_plan", "authority",
})


def validate_json_pointer(value: object, name: str = "JSON pointer") -> str:
    """Validate RFC 6901 string syntax; URI fragments and bad escapes fail."""
    if not isinstance(value, str) or (value and not value.startswith("/")):
        raise ContractValidationError(f"{name} must be an RFC 6901 string pointer")
    if len(value) > 4096 or _POINTER_ESCAPE.search(value):
        raise ContractValidationError(f"{name} contains an invalid RFC 6901 escape or is too long")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{name} must contain valid Unicode text") from exc
    return value


def _entries(value: object, name: str) -> list:
    if not isinstance(value, list) or not value:
        raise ContractValidationError(f"{name} must be a nonempty list")
    return value


def _unique_text_list(value: object, name: str, *, identifiers: bool = False) -> list[str]:
    result = []
    for entry in _entries(value, name):
        result.append(_identifier(entry, name) if identifiers else _string(entry, name, 10000))
    if len(set(result)) != len(result):
        raise ContractValidationError(f"{name} contains duplicate values")
    return result


def _scalar(value: object, name: str) -> Any:
    if value is None or type(value) is bool or _finite_number(value):
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ContractValidationError(f"{name} must contain valid Unicode text") from exc
        return value
    raise ContractValidationError(f"{name} must be a finite JSON scalar")


def _observations(value: object) -> list[dict[str, Any]]:
    result, identities = [], set()
    fields = {"observation_id", "source_event_id", "artifact_path", "artifact_sha256", "value_pointer",
              "value", "unit", "as_of_pointer", "as_of", "time_role"}
    for entry in _entries(value, "observations"):
        item = _object(entry, fields, "observation")
        item["observation_id"] = _identifier(item["observation_id"], "observation_id")
        if item["observation_id"] in identities:
            raise ContractValidationError("observations contains duplicate observation_id")
        identities.add(item["observation_id"])
        item["source_event_id"] = _journal_id(item["source_event_id"], "source_event_id")
        if not item["source_event_id"].startswith("journal-event-"):
            raise ContractValidationError("source_event_id must have the journal-event prefix")
        item["artifact_path"] = validate_evidence_path(item["artifact_path"])
        item["artifact_sha256"] = _hash(item["artifact_sha256"], "artifact_sha256")
        for field in ("value_pointer", "as_of_pointer"):
            item[field] = validate_json_pointer(item[field], field)
        item["value"] = _scalar(item["value"], "observation.value")
        item["unit"] = _string(item["unit"], "observation.unit")
        item["as_of"] = normalize_rfc3339(item["as_of"], "observation.as_of")
        item["time_role"] = _enum(item["time_role"], {"AS_OF", "GENERATED_AT", "OBSERVED_AT", "REQUESTED_AT"}, "time_role")
        result.append(item)
    return result


def _metric_checks(value: object, *, invalidation: bool) -> list[dict[str, Any]]:
    name = "invalidation_conditions" if invalidation else "expected_outcomes"
    identity = "condition_id" if invalidation else "outcome_id"
    date_field = "check_by" if invalidation else "due_at"
    fields = {identity, "description", "metric", "unit", "operator", "threshold", date_field}
    result, identities = [], set()
    for entry in _entries(value, name):
        item = _object(entry, fields, name + " entry")
        item[identity] = _identifier(item[identity], identity)
        if item[identity] in identities:
            raise ContractValidationError(f"{name} contains duplicate {identity}")
        identities.add(item[identity])
        for field in ("description", "metric", "unit"):
            item[field] = _string(item[field], f"{name}.{field}", 10000 if field == "description" else 256)
        item["operator"] = _enum(item["operator"], HYPOTHESIS_OPERATORS, "operator")
        threshold = item["threshold"]
        if _finite_number(threshold):
            pass
        elif type(threshold) is str and item["operator"] in {"EQ", "NE"}:
            item["threshold"] = _string(threshold, "threshold", 10000)
        else:
            raise ContractValidationError("threshold must be a finite number; EQ/NE also support nonblank strings")
        item[date_field] = normalize_rfc3339(item[date_field], date_field)
        result.append(item)
    return result


def _hypothesis(value: object) -> dict[str, Any]:
    result = _object(value, _ROOT_FIELDS, "investment hypothesis")
    constants = {"schema_version": INVESTMENT_HYPOTHESIS_SCHEMA_VERSION,
                 "domain": "INVESTMENT", "mode": "SHADOW", "status": "SHADOW_DRAFT"}
    for field, expected in constants.items():
        if result[field] != expected:
            raise ContractValidationError(f"investment hypothesis {field} must be {expected!r}")
    for field in ("hypothesis_id", "author_id"):
        result[field] = _identifier(result[field], field)
    for field in ("recorded_at", "evidence_cutoff_at"):
        result[field] = normalize_rfc3339(result[field], field)
    result["research_mode"] = _enum(result["research_mode"], {"PROSPECTIVE", "RETROSPECTIVE"}, "research_mode")
    scope = _object(result["scope"], {"kind", "identifiers"}, "scope")
    scope["kind"] = _enum(scope["kind"], {"SYMBOL", "SECTOR", "PORTFOLIO"}, "scope.kind")
    scope["identifiers"] = _unique_text_list(scope["identifiers"], "scope.identifiers")
    result["scope"] = scope
    result["observations"] = _observations(result["observations"])
    observation_ids = {item["observation_id"] for item in result["observations"]}
    hypothesis = _object(result["hypothesis"], {"statement", "causal_mechanism", "assumptions", "observation_ids"}, "hypothesis")
    for field in ("statement", "causal_mechanism"):
        hypothesis[field] = _string(hypothesis[field], "hypothesis." + field, 10000)
    hypothesis["assumptions"] = _unique_text_list(hypothesis["assumptions"], "hypothesis.assumptions")
    hypothesis["observation_ids"] = _unique_text_list(hypothesis["observation_ids"], "hypothesis.observation_ids", identifiers=True)
    if not set(hypothesis["observation_ids"]) <= observation_ids:
        raise ContractValidationError("hypothesis references unknown observation_ids")
    result["hypothesis"] = hypothesis
    horizon = _object(result["horizon"], {"start_at", "review_at", "end_at"}, "horizon")
    for field in horizon:
        horizon[field] = normalize_rfc3339(horizon[field], "horizon." + field)
    result["horizon"] = horizon
    result["expected_outcomes"] = _metric_checks(result["expected_outcomes"], invalidation=False)
    result["invalidation_conditions"] = _metric_checks(result["invalidation_conditions"], invalidation=True)
    alternatives, identities = [], set()
    for entry in _entries(result["alternatives"], "alternatives"):
        item = _object(entry, {"alternative_id", "statement", "distinguishing_observation", "observation_ids"}, "alternative")
        item["alternative_id"] = _identifier(item["alternative_id"], "alternative_id")
        if item["alternative_id"] in identities:
            raise ContractValidationError("alternatives contains duplicate alternative_id")
        identities.add(item["alternative_id"])
        for field in ("statement", "distinguishing_observation"):
            item[field] = _string(item[field], "alternative." + field, 10000)
        item["observation_ids"] = _unique_text_list(item["observation_ids"], "alternative.observation_ids", identifiers=True)
        if not set(item["observation_ids"]) <= observation_ids:
            raise ContractValidationError("alternative references unknown observation_ids")
        alternatives.append(item)
    result["alternatives"] = alternatives
    plan = _object(result["evaluation_plan"], {"plan_id", "method", "evaluate_at", "outcome_ids", "condition_ids",
                                            "success_rule", "missing_data_policy", "evaluator_role"}, "evaluation_plan")
    plan["plan_id"] = _identifier(plan["plan_id"], "plan_id")
    for field, expected in {"method": "MANUAL_SOURCE_BOUND_REVIEW", "success_rule": "ALL_EXPECTED_OUTCOMES_AND_NO_INVALIDATION",
                            "missing_data_policy": "INCONCLUSIVE"}.items():
        if plan[field] != expected:
            raise ContractValidationError(f"evaluation_plan.{field} must be {expected!r}")
    plan["evaluate_at"] = normalize_rfc3339(plan["evaluate_at"], "evaluation_plan.evaluate_at")
    plan["evaluator_role"] = _string(plan["evaluator_role"], "evaluator_role")
    for field, collection, identity in (("outcome_ids", "expected_outcomes", "outcome_id"),
                                        ("condition_ids", "invalidation_conditions", "condition_id")):
        plan[field] = _unique_text_list(plan[field], "evaluation_plan." + field, identifiers=True)
        if set(plan[field]) != {item[identity] for item in result[collection]}:
            raise ContractValidationError(f"evaluation_plan.{field} must reference every {collection} entry exactly once")
    result["evaluation_plan"] = plan
    authority = _object(result["authority"], HYPOTHESIS_AUTHORITY_FIELDS, "authority")
    for field in authority:
        if _boolean(authority[field], "authority." + field):
            raise ContractValidationError(f"authority.{field} must remain disabled")
    result["authority"] = authority

    recorded = parse_rfc3339(result["recorded_at"], "recorded_at")
    cutoff = parse_rfc3339(result["evidence_cutoff_at"], "evidence_cutoff_at")
    start = parse_rfc3339(horizon["start_at"], "start_at")
    review = parse_rfc3339(horizon["review_at"], "review_at")
    end = parse_rfc3339(horizon["end_at"], "end_at")
    if cutoff > recorded:
        raise ContractValidationError("evidence_cutoff_at must not be after recorded_at")
    if result["research_mode"] == "PROSPECTIVE" and cutoff != recorded:
        raise ContractValidationError("PROSPECTIVE evidence_cutoff_at must equal recorded_at")
    if any(parse_rfc3339(item["as_of"], "as_of") > cutoff for item in result["observations"]):
        raise ContractValidationError("observation.as_of must not be after evidence_cutoff_at")
    if start != cutoff or review <= start or end < review:
        raise ContractValidationError("horizon requires start_at == evidence_cutoff_at, review_at > start_at, end_at >= review_at")
    if plan["evaluate_at"] != horizon["end_at"]:
        raise ContractValidationError("evaluation_plan.evaluate_at must equal horizon.end_at")
    for collection, date_field in (("expected_outcomes", "due_at"), ("invalidation_conditions", "check_by")):
        if any(not start < parse_rfc3339(item[date_field], date_field) <= end for item in result[collection]):
            raise ContractValidationError(f"{collection}.{date_field} must be within the horizon after start_at")
    return result


class InvestmentHypothesis(_ImmutableDocument):
    """Immutable offline draft, never a recommendation, authorization, or order."""

    __slots__ = ()
    _validator = staticmethod(_hypothesis)

    @classmethod
    def from_bytes(cls, value: bytes):
        """Translate excessive JSON nesting into a bounded contract rejection."""
        try:
            parsed = parse_strict_json_object_bytes(value, document_name=cls.__name__)
        except RecursionError as exc:
            raise ContractValidationError("investment hypothesis JSON nesting exceeds the supported depth") from exc
        return cls.from_mapping(parsed)
