"""Strict derived research state; v17 assessments remain immutable evidence."""
from .decision_journal import _ImmutableDocument, _evidence, _hash, _object
from .investment_review import disabled_authority
from .mission_request import ContractValidationError
from .research_assessment import ResearchAssessment, GOVERNANCE_STATUS, _event_id, _fixed_false
from ..hashing import sha256_bytes

SCHEMA_VERSION = "blackpod.research_acceptance_state.v1"
METHOD_VERSION = "blackpod.research_acceptance_state_projection.v1"
OUTCOMES = frozenset({"INCONCLUSIVE", "SUPPORTED", "CONTRADICTED"})


def evaluation_state(assessment):
    """Eligibility comes from scope and frozen prerequisites, not outcome signs."""
    request = assessment["request"]
    reasons = []
    if request["assessment_scope"] == "ECONOMIC_VALIDATION":
        eligibility = "NOT_EVALUABLE"
        reasons.append("FROZEN_METHOD_ECONOMIC_PREREQUISITES_UNESTABLISHED")
    elif request["domain"] == "TRADING":
        registrations = [row for row in assessment["native_status_mapping"]
                         if row["source_event_id"] == request["research_event_id"]]
        if len(registrations) != 1:
            raise ContractValidationError("Trading state requires its exact registration prerequisite mapping")
        eligibility = ("EVALUABLE" if registrations[0]["mapped_classification"] == "EVALUABLE"
                       else "NOT_EVALUABLE")
        reasons.append("NATIVE_REGISTRATION_PREREQUISITES_SATISFIED" if eligibility == "EVALUABLE"
                       else "NATIVE_REGISTRATION_PREREQUISITES_MISSING")
    elif request["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES" and request["evaluation_event_id"] is None:
        eligibility = "NOT_EVALUABLE"
        reasons.append("EXACT_DEADLINE_EVALUATION_MISSING")
    else:
        eligibility = "EVALUABLE"
        reasons.append("VALIDATED_INVESTMENT_SPECIFICATION_FOR_DECLARED_SCOPE")
    integrity = "INVALID" if assessment["classification"] == "INVALID" else "VALID"
    outcome = (assessment["classification"] if integrity == "VALID" and eligibility == "EVALUABLE"
               and assessment["evaluation_performed"] and assessment["classification"] in OUTCOMES else None)
    classification = ("INVALID" if integrity == "INVALID" else "NOT_EVALUABLE" if eligibility == "NOT_EVALUABLE"
                      else outcome or "EVALUABLE")
    return {"eligibility": eligibility, "eligibility_reason_codes": reasons, "integrity": integrity,
            "outcome": outcome, "classification": classification,
            "evaluation_performed": outcome is not None,
            "native_evaluation_performed": assessment["evaluation_performed"]}


def _state(value):
    fields = {"schema_version", "method_version", "domain", "source_assessment_event", "source_assessment",
              "original_classification", "hypothesis", "trading_plan", "implementation_evidence", "governance_status",
              "auto_trading_enabled", "authority"}
    fields |= {"eligibility", "eligibility_reason_codes", "integrity", "outcome", "classification",
               "evaluation_performed", "native_evaluation_performed"}
    row = _object(value, fields, "research acceptance state")
    if row["schema_version"] != SCHEMA_VERSION or row["method_version"] != METHOD_VERSION:
        raise ContractValidationError("unsupported research acceptance state version")
    assessment = ResearchAssessment.from_mapping(row["source_assessment"])
    row["source_assessment"] = assessment.to_dict()
    if row["domain"] != assessment.request["domain"] or row["original_classification"] != assessment.classification:
        raise ContractValidationError("state must preserve its original desk and classification")
    for key, expected in evaluation_state(assessment.to_dict()).items():
        if type(row[key]) is not type(expected) or row[key] != expected:
            raise ContractValidationError("state " + key + " differs from deterministic source projection")
    source = _object(row["source_assessment_event"], {"event_id", "event_sha256", "assessment_evidence"}, "source assessment event")
    source["event_id"] = _event_id(source["event_id"], "source assessment event")
    source["event_sha256"] = _hash(source["event_sha256"], "source assessment event hash")
    source["assessment_evidence"] = _evidence([source["assessment_evidence"]])[0]
    if (source["assessment_evidence"]["sha256"] != sha256_bytes(assessment.to_bytes())
            or source["assessment_evidence"]["size_bytes"] != len(assessment.to_bytes())):
        raise ContractValidationError("state must bind exact original assessment bytes")
    row["source_assessment_event"] = source
    hypothesis = _object(row["hypothesis"], {"source_event_id", "document_evidence", "document", "market_scope"}, "state hypothesis")
    request_hypothesis = assessment.request["hypothesis"]
    if (hypothesis["source_event_id"] != request_hypothesis["source_event_id"]
            or hypothesis["document_evidence"] != request_hypothesis["evidence"]):
        raise ContractValidationError("state hypothesis must preserve exact original source")
    if row["domain"] == "TRADING":
        from .trading_hypothesis import TradingHypothesis
        from .trading_research import TradingResearchPlan
        document = TradingHypothesis.from_mapping(hypothesis["document"])
        plan_source = _object(row["trading_plan"], {"document_evidence", "document"}, "original Trading plan")
        plan_ref = _evidence([plan_source["document_evidence"]])[0]
        plan = TradingResearchPlan.from_mapping(plan_source["document"])
        if (plan_ref not in assessment.evidence
                or sha256_bytes(plan.to_bytes()) != plan_ref["sha256"]
                or len(plan.to_bytes()) != plan_ref["size_bytes"]
                or plan.frozen_hypothesis_evidence != request_hypothesis["evidence"]):
            raise ContractValidationError("Trading state requires its original retained source-bound plan")
        row["trading_plan"] = {"document_evidence": plan_ref, "document": plan.to_dict()}
        scope = {"kind": "SYMBOL", "identifiers": plan.universe}
        if hypothesis["market_scope"] != scope:
            raise ContractValidationError("Trading state scope differs from its original plan universe")
    else:
        from .investment_hypothesis import InvestmentHypothesis
        document = InvestmentHypothesis.from_mapping(hypothesis["document"])
        scope = document.scope
        if hypothesis["market_scope"] != scope:
            raise ContractValidationError("state cannot replace original Investment scope")
        if row["trading_plan"] is not None:
            raise ContractValidationError("Investment state cannot acquire a Trading plan")
    if (document.hypothesis_id != request_hypothesis["hypothesis_id"]
            or sha256_bytes(document.to_bytes()) != request_hypothesis["evidence"]["sha256"]
            or len(document.to_bytes()) != request_hypothesis["evidence"]["size_bytes"]):
        raise ContractValidationError("state hypothesis differs from original retained document")
    hypothesis["document"], hypothesis["market_scope"] = document.to_dict(), scope
    row["hypothesis"] = hypothesis
    row["implementation_evidence"] = _evidence(row["implementation_evidence"])
    if {ref["path"] for ref in row["implementation_evidence"]} != {
            "research-acceptance-state/implementation/contracts/research_acceptance_state.py",
            "research-acceptance-state/implementation/research_acceptance_state.py"}:
        raise ContractValidationError("state requires both projection method source identities")
    if row["governance_status"] != GOVERNANCE_STATUS:
        raise ContractValidationError("research state has no authorization")
    row["auto_trading_enabled"] = _fixed_false(row["auto_trading_enabled"], "auto_trading_enabled")
    row["authority"] = disabled_authority(row["authority"])
    return row


class ResearchAcceptanceState(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_state)
