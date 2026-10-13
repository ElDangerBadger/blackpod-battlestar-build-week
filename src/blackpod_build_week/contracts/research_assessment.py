"""Immutable research classifications; no decision or execution authority.

V1 maps existing frozen research without changing native result vocabularies.
Its only supported conclusion is an Investment Desk's explicitly scoped,
recorded deadline predicate, never a validated economic thesis or strategy.
"""
from __future__ import annotations

import re

from .decision_journal import (
    _ImmutableDocument, _boolean, _enum, _evidence, _finite_number,
    _identifier, _journal_id, _object, _string,
)
from .investment_review import disabled_authority
from .mission_request import ContractValidationError, normalize_rfc3339, parse_rfc3339

REQUEST_VERSION = "blackpod.research_assessment_request.v1"
ASSESSMENT_VERSION = "blackpod.research_assessment.v1"
EVENT_VERSION = "blackpod.decision_journal_event.v17"
EVENT_TYPE = "RESEARCH_ASSESSMENT_RECORDED"
CLASSIFICATIONS = frozenset({"NOT_EVALUABLE", "EVALUABLE", "INCONCLUSIVE", "SUPPORTED", "CONTRADICTED", "INVALID"})
SCOPES = frozenset({"EXPLORATORY_RESEARCH", "ECONOMIC_VALIDATION", "DECLARED_DEADLINE_PREDICATES"})
METHODS = {"TRADING": "blackpod.trading_research_acceptance.v1", "INVESTMENT": "blackpod.investment_research_acceptance.v1"}
GOVERNANCE_STATUS = "RESEARCH_ONLY_NOT_AUTHORIZATION"
REQUEST_FIELDS = frozenset({"schema_version", "assessment_id", "domain", "recorded_at", "data_cutoff_at", "assessment_scope", "methodology_version", "hypothesis", "research_event_id", "evaluation_event_id", "candidate_result_evidence", "supersedes_event_id", "governance_status", "auto_trading_enabled", "authority"})
ADAPTER_FIELDS = frozenset({"classification", "evaluation_performed", "native_status_mapping", "findings", "limitations", "unresolved_questions", "next_evidence_requirements", "economic_hypothesis_supported", "source_authentication_verified", "historical_point_in_time_verified", "claim_scope", "maturity"})
ASSESSMENT_FIELDS = ADAPTER_FIELDS | {"schema_version", "request", "hypothesis_revision", "evaluation_timestamp", "evidence", "supporting_findings", "contradictory_findings", "governance_status", "auto_trading_enabled", "authority"}


def _event_id(value, name):
    value = _journal_id(value, name)
    if not value.startswith("journal-event-"):
        raise ContractValidationError(name + " must identify a journal event")
    return value


def _fixed_false(value, name):
    if _boolean(value, name):
        raise ContractValidationError(name + " must remain false")
    return False


def _texts(value, name, maximum=128):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(name + " must be a bounded list")
    result = [_string(item, name, 10000) for item in value]
    if len(set(result)) != len(result):
        raise ContractValidationError(name + " contains duplicate entries")
    return result


def _request(value):
    result = _object(value, REQUEST_FIELDS, "research assessment request")
    if result["schema_version"] != REQUEST_VERSION:
        raise ContractValidationError("unsupported research assessment request schema_version")
    result["assessment_id"] = _identifier(result["assessment_id"], "assessment_id")
    result["domain"] = _enum(result["domain"], set(METHODS), "domain")
    result["assessment_scope"] = _enum(result["assessment_scope"], SCOPES, "assessment_scope")
    if result["domain"] == "TRADING" and result["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES":
        raise ContractValidationError("deadline predicates belong to the Investment Desk")
    if result["methodology_version"] != METHODS[result["domain"]]:
        raise ContractValidationError("methodology_version must match research domain")
    for field in ("recorded_at", "data_cutoff_at"):
        result[field] = normalize_rfc3339(result[field], field)
    if parse_rfc3339(result["data_cutoff_at"], "cutoff") > parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("data cutoff cannot follow assessment record clock")
    hypothesis = _object(result["hypothesis"], {"hypothesis_id", "source_event_id", "document_schema_version", "evidence"}, "hypothesis")
    hypothesis["hypothesis_id"] = _identifier(hypothesis["hypothesis_id"], "hypothesis_id")
    hypothesis["source_event_id"] = _event_id(hypothesis["source_event_id"], "hypothesis.source_event_id")
    expected = "blackpod.trading_hypothesis.v1" if result["domain"] == "TRADING" else "blackpod.investment_hypothesis.v1"
    if hypothesis["document_schema_version"] != expected:
        raise ContractValidationError("hypothesis document schema must match research domain")
    hypothesis["evidence"] = _evidence([hypothesis["evidence"]])[0]
    result["hypothesis"] = hypothesis
    result["research_event_id"] = _event_id(result["research_event_id"], "research_event_id")
    for field in ("evaluation_event_id", "supersedes_event_id"):
        if result[field] is not None:
            result[field] = _event_id(result[field], field)
    if result["candidate_result_evidence"] is not None:
        if result["evaluation_event_id"] is None:
            raise ContractValidationError("candidate result requires an original evaluation event")
        result["candidate_result_evidence"] = _evidence([result["candidate_result_evidence"]])[0]
        if result["candidate_result_evidence"]["path"].startswith("research-acceptance/"):
            raise ContractValidationError("candidate evidence cannot use reserved acceptance paths")
    if result["governance_status"] != GOVERNANCE_STATUS:
        raise ContractValidationError("research assessment cannot acquire governance authority")
    result["auto_trading_enabled"] = _fixed_false(result["auto_trading_enabled"], "auto_trading_enabled")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _assessment(value):
    result = _object(value, ASSESSMENT_FIELDS, "research assessment")
    if result["schema_version"] != ASSESSMENT_VERSION:
        raise ContractValidationError("unsupported research assessment schema_version")
    request = _request(result["request"])
    result["request"] = request
    revision = _object(result["hypothesis_revision"], {"document_schema_version", "sha256"}, "hypothesis_revision")
    if revision != {"document_schema_version": request["hypothesis"]["document_schema_version"], "sha256": request["hypothesis"]["evidence"]["sha256"]}:
        raise ContractValidationError("hypothesis revision must preserve exact native schema and document hash")
    result["hypothesis_revision"] = revision
    result["classification"] = _enum(result["classification"], CLASSIFICATIONS, "classification")
    result["evaluation_performed"] = _boolean(result["evaluation_performed"], "evaluation_performed")
    if result["classification"] in {"SUPPORTED", "CONTRADICTED", "INCONCLUSIVE"} and not result["evaluation_performed"]:
        raise ContractValidationError("this classification requires a performed evaluation")
    if result["classification"] == "EVALUABLE" and result["evaluation_performed"]:
        raise ContractValidationError("performed evaluations require a conclusion, not EVALUABLE")
    if result["classification"] == "SUPPORTED" and (request["domain"] != "INVESTMENT" or request["assessment_scope"] != "DECLARED_DEADLINE_PREDICATES"):
        raise ContractValidationError("v1 supports only declared Investment deadline predicates")
    if result["evaluation_timestamp"] is not None:
        result["evaluation_timestamp"] = normalize_rfc3339(result["evaluation_timestamp"], "evaluation_timestamp")
        if parse_rfc3339(result["evaluation_timestamp"], "evaluation clock") > parse_rfc3339(request["data_cutoff_at"], "cutoff"):
            raise ContractValidationError("evaluation timestamp cannot exceed data cutoff")
    if (request["evaluation_event_id"] is None) != (result["evaluation_timestamp"] is None):
        raise ContractValidationError("evaluation timestamp must reflect an existing source evaluation")
    if not isinstance(result["native_status_mapping"], list) or not 1 <= len(result["native_status_mapping"]) <= 32:
        raise ContractValidationError("native_status_mapping must be a nonempty bounded list")
    mappings = []
    for entry in result["native_status_mapping"]:
        item = _object(entry, {"source_event_id", "native_status", "mapped_classification", "reason"}, "native status mapping")
        item["source_event_id"] = _event_id(item["source_event_id"], "source_event_id")
        item["native_status"] = _string(item["native_status"], "native_status")
        item["mapped_classification"] = _enum(item["mapped_classification"], CLASSIFICATIONS, "mapped_classification")
        item["reason"] = _string(item["reason"], "mapping reason", 10000)
        mappings.append(item)
    result["native_status_mapping"] = mappings
    if not isinstance(result["findings"], list) or not 1 <= len(result["findings"]) <= 4096:
        raise ContractValidationError("findings must be a nonempty list of at most 4096 entries")
    findings, ids = [], set()
    for entry in result["findings"]:
        item = _object(entry, {"finding_id", "criterion", "effect", "evidence_event_id", "value_pointer", "observed", "statement"}, "finding")
        item["finding_id"] = _identifier(item["finding_id"], "finding_id")
        if item["finding_id"] in ids:
            raise ContractValidationError("duplicate finding identity")
        ids.add(item["finding_id"])
        if not isinstance(item["criterion"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", item["criterion"]):
            raise ContractValidationError("criterion must be a bounded uppercase token")
        item["effect"] = _enum(item["effect"], {"SUPPORTS", "CONTRADICTS", "LIMITATION", "INVALID", "PREREQUISITE", "UNKNOWN"}, "effect")
        if item["evidence_event_id"] is not None:
            item["evidence_event_id"] = _event_id(item["evidence_event_id"], "evidence_event_id")
        if item["value_pointer"] is not None:
            item["value_pointer"] = _string(item["value_pointer"], "value_pointer", 4096)
            if not item["value_pointer"].startswith("/") or item["evidence_event_id"] is None:
                raise ContractValidationError("finding pointer requires a source event and JSON pointer")
            if re.search(r"~(?![01])", item["value_pointer"]):
                raise ContractValidationError("invalid JSON pointer escaping")
        observed = item["observed"]
        if observed is not None and type(observed) is not bool and not _finite_number(observed):
            _string(observed, "observed", 10000)
        item["statement"] = _string(item["statement"], "finding.statement", 10000)
        findings.append(item)
    result["findings"] = findings
    for field, effect in (("supporting_findings", "SUPPORTS"), ("contradictory_findings", "CONTRADICTS")):
        expected = [item["finding_id"] for item in findings if item["effect"] == effect]
        if result[field] != expected:
            raise ContractValidationError(field + " must index the exact corresponding findings")
    for field in ("limitations", "unresolved_questions", "next_evidence_requirements"):
        result[field] = _texts(result[field], field)
    if not result["limitations"] or not result["next_evidence_requirements"]:
        raise ContractValidationError("assessment must state limitations and next evidence requirements")
    result["claim_scope"] = _string(result["claim_scope"], "claim_scope", 10000)
    if result["maturity"] != "DESCRIPTIVE_ONLY":
        raise ContractValidationError("v1 has descriptive maturity only")
    for field in ("economic_hypothesis_supported", "source_authentication_verified", "historical_point_in_time_verified", "auto_trading_enabled"):
        result[field] = _fixed_false(result[field], field)
    if result["governance_status"] != GOVERNANCE_STATUS:
        raise ContractValidationError("assessment cannot authorize decisions")
    result["authority"] = disabled_authority(result["authority"])
    result["evidence"] = _evidence(result["evidence"])
    if request["hypothesis"]["evidence"] not in result["evidence"]:
        raise ContractValidationError("assessment must retain its exact hypothesis evidence")
    if request["candidate_result_evidence"] is not None and request["candidate_result_evidence"] not in result["evidence"]:
        raise ContractValidationError("assessment must retain the untrusted candidate result")
    return result


class ResearchAssessmentRequest(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


class ResearchAssessment(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_assessment)


def validate_journal_event(result):
    """Additive envelope validation, leaving v1–v16 semantics untouched."""
    result = dict(result)
    if result["schema_version"] != EVENT_VERSION or result["event_type"] != EVENT_TYPE:
        raise ContractValidationError("unsupported research assessment event")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["domain"] = _enum(result["domain"], set(METHODS), "domain")
    source = _object(result["source"], {"kind", "assessment_id", "hypothesis_id", "source_sha256"}, "research assessment source")
    from .decision_journal import _hash
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    if source["kind"] != "RESEARCH_ASSESSMENT":
        raise ContractValidationError("research assessment source kind mismatch")
    payload = _object(result["payload"], {"request", "assessment", "prior_assessment_event_ids"}, "research assessment payload")
    request = ResearchAssessmentRequest.from_mapping(payload["request"])
    assessment = ResearchAssessment.from_mapping(payload["assessment"])
    if assessment.request != request.to_dict():
        raise ContractValidationError("assessment request differs from canonical payload request")
    from ..hashing import sha256_bytes
    if source != {"kind": "RESEARCH_ASSESSMENT", "assessment_id": request.assessment_id, "hypothesis_id": request.hypothesis["hypothesis_id"], "source_sha256": sha256_bytes(request.to_bytes())}:
        raise ContractValidationError("assessment source identity or hash differs from request")
    if result["domain"] != request.domain or result["recorded_at"] != request.recorded_at:
        raise ContractValidationError("assessment domain and record clock must match request")
    previous = payload["prior_assessment_event_ids"]
    if not isinstance(previous, list) or len(previous) > 1024 or previous != sorted(set(previous)):
        raise ContractValidationError("prior assessments must be sorted unique bounded event identities")
    for entry in previous:
        _event_id(entry, "prior assessment event")
    result["source"] = source
    result["payload"] = {"request": request.to_dict(), "assessment": assessment.to_dict(), "prior_assessment_event_ids": previous}
    result["evidence"] = _evidence(result["evidence"])
    if not all(ref in result["evidence"] for ref in assessment.evidence):
        raise ContractValidationError("event must retain complete assessment evidence")
    return result
