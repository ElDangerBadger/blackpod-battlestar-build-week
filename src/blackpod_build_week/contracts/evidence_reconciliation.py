"""Strict passive reconciliation records; source matching grants no authority."""
from .decision_journal import _object, _identifier, _hash, _evidence, _journal_id, _enum
from .investment_review import _event_id, _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from ..hashing import canonical_json_bytes, sha256_bytes

REQUEST_VERSION = "blackpod.independent_evidence_reconciliation_request.v1"
RESULT_VERSION = "blackpod.independent_evidence_reconciliation.v1"
METHOD_VERSION = RESULT_VERSION
JOURNAL_VERSION = "blackpod.decision_journal_event.v22"
REVIEW_TYPE = "TRADING_INDEPENDENT_EVIDENCE_RECONCILIATION_RECORDED"
SOURCE_KIND = "TRADING_INDEPENDENT_EVIDENCE_RECONCILIATION"
SCOPE = "INDEPENDENT_EVIDENCE_RECONCILIATION_ONLY"
EVALUATION_MODES = {"SHADOW_RESEARCH", "PAPER_SIMULATION", "LIVE_BROKERAGE"}
LINK_FIELDS = {"anchor_review_event_id", "selected_qualification_event_id", "continuity_event_id",
    "capture_plan_event_id", "aggregate_export_event_id", "base_plan_event_id",
    "hypothesis_event_id", "intake_event_id"}
LIMITATIONS = (
    "MATCHING_OBSERVED_ACTIONS_DOES_NOT_ESTABLISH_COMPLETE_ALL_TYPE_COVERAGE",
    "INDEPENDENT_ACTIONS_ARE_NOT_INSERTED_INTO_OLD_NATIVE_ACTION_MASKS",
    "SOURCE_DECLARATIONS_AND_HASHES_DO_NOT_AUTHENTICATE_PUBLISHERS_OR_APPLICABILITY",
    "MARKET_EVENT_TIME_AND_DELIVERY_TIME_ARE_DISTINCT",
    "NO_FEE_UNIT_SLIPPAGE_OR_FILL_CAPACITY_PARAMETERS_ARE_APPLIED",
    "OLD_NATIVE_QUALIFICATION_IS_RETAINED_NOT_RECOMPUTED_OR_OVERRIDDEN",
    "FULL_HISTORY_VERIFICATION_REMAINS_REQUIRED_AT_JOURNAL_BOUNDARIES",
    "FINAL_HOLDOUT_IS_UNSCORED_NOT_ACCESS_SEALED",
    "NO_PROVIDER_BROKER_INFERENCE_RETURN_SCORING_OR_EXECUTION",
)


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _request(value):
    row = _object(value, {"schema_version", "review_id", "recorded_at", "data_cutoff_at",
        "domain", "mode", "scope", "anchor_review_event_id", "effective_date_request_evidence",
        "applicability_packet_evidence", "declared_evaluation_mode", "account_profile_evidence",
        "supersedes_event_id", "auto_trading_enabled", "authority"}, "independent evidence request")
    for key, expected in (("schema_version", REQUEST_VERSION), ("domain", "TRADING"),
            ("mode", "SHADOW_RESEARCH"), ("scope", SCOPE)):
        _constant(row, key, expected)
    row["review_id"] = _identifier(row["review_id"], "review_id")
    for key in ("recorded_at", "data_cutoff_at"):
        row[key] = accounting_timestamp(row[key], key)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"):
        raise ContractValidationError("cutoff must not follow the record clock")
    row["anchor_review_event_id"] = _event_id(row["anchor_review_event_id"], "anchor review")
    if row["supersedes_event_id"] is not None:
        row["supersedes_event_id"] = _event_id(row["supersedes_event_id"], "superseded review")
    for key in ("effective_date_request_evidence", "applicability_packet_evidence", "account_profile_evidence"):
        if row[key] is not None:
            row[key] = evidence_reference(row[key], key)
        elif key != "account_profile_evidence":
            raise ContractValidationError(key + " is required")
    references = [row[key] for key in ("effective_date_request_evidence", "applicability_packet_evidence", "account_profile_evidence") if row[key] is not None]
    if len({ref["path"] for ref in references}) != len(references):
        raise ContractValidationError("request source paths must be distinct")
    row["declared_evaluation_mode"] = _enum(row["declared_evaluation_mode"], EVALUATION_MODES, "evaluation mode")
    return _safe(row)


class EvidenceReconciliationRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def validate_links(value):
    row = _object(value, LINK_FIELDS, "independent reconciliation links")
    return {key: _event_id(item, key) for key, item in row.items()}


def _ids(value):
    if not isinstance(value, list) or len(value) > 1024:
        raise ContractValidationError("prior reviews require a bounded list")
    result = [_event_id(item, "prior review") for item in value]
    if result != sorted(set(result)):
        raise ContractValidationError("prior review identities must be sorted and distinct")
    return result


RESULT_FIELDS = {"schema_version", "method_version", "review_id", "status", "anchor_review_event_id",
    "anchor_event_sha256", "selected_qualification_event_id", "native_qualification_snapshot",
    "native_qualification_result_sha256", "native_reason_codes", "source_context",
    "effective_date_reconciliation", "historical_feed_cost_applicability", "native_coverage_proposal",
    "cost_assumptions_proposal", "native_coverage_proposal_applied", "native_qualification_recomputed",
    "native_gate_override", "source_authentication_verified", "historical_point_in_time_verified",
    "source_applicability_verified", "opening_execution_capacity_verified", "uncertainty_computed",
    "economic_hypothesis_supported", "execution_status", "realized_trade_pnl", "limitations",
    "auto_trading_enabled", "authority"}


def validate_result(value):
    from .effective_date_reconciliation import validate_result as validate_effective
    from .historical_feed_cost_applicability import HistoricalFeedCostContext, validate_result as validate_cost
    from .segmented_evidence_qualification import validate_result as validate_native
    from .trading_continuity_intake import ContinuityCoverageReview
    row = _object(value, RESULT_FIELDS, "independent reconciliation result")
    for key, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION),
            ("status", "DESCRIPTIVE_EVIDENCE_RECONCILIATION_ONLY"), ("execution_status", "NOT_EXECUTED"),
            ("realized_trade_pnl", None), ("cost_assumptions_proposal", None)):
        _constant(row, key, expected)
    row["review_id"] = _identifier(row["review_id"], "review_id")
    for key in ("anchor_review_event_id", "selected_qualification_event_id"):
        row[key] = _event_id(row[key], key)
    for key in ("anchor_event_sha256", "native_qualification_result_sha256"):
        row[key] = _hash(row[key], key)
    native = validate_native(row["native_qualification_snapshot"])
    if row["native_qualification_result_sha256"] != sha256_bytes(canonical_json_bytes(native)):
        raise ContractValidationError("native snapshot hash differs")
    if row["native_reason_codes"] != sorted(set(native["reason_codes"])):
        raise ContractValidationError("native reasons must preserve the exact reported qualification")
    row["native_qualification_snapshot"] = native
    row["source_context"] = HistoricalFeedCostContext.from_mapping(row["source_context"]).to_dict()
    row["effective_date_reconciliation"] = validate_effective(row["effective_date_reconciliation"])
    row["historical_feed_cost_applicability"] = validate_cost(row["historical_feed_cost_applicability"])
    effective, context = row["effective_date_reconciliation"], row["source_context"]
    if effective["dataset_evidence"] != context["dataset_evidence"] or effective["universe"] != context["universe"]:
        raise ContractValidationError("reconciliation and applicability must preserve the same original dataset")
    if row["historical_feed_cost_applicability"]["context_sha256"] != sha256_bytes(canonical_json_bytes(context)):
        raise ContractValidationError("applicability result must preserve the exact source context")
    proposal = ContinuityCoverageReview.from_mapping(row["native_coverage_proposal"])
    if proposal.status != "UNRESOLVED":
        raise ContractValidationError("coverage proposal cannot upgrade native support")
    if proposal.to_dict() != effective["coverage_proposal"]:
        raise ContractValidationError("coverage proposal must retain the exact reconciliation output")
    row["native_coverage_proposal"] = proposal.to_dict()
    for key in ("native_coverage_proposal_applied", "native_qualification_recomputed", "native_gate_override",
            "source_authentication_verified", "historical_point_in_time_verified", "source_applicability_verified",
            "opening_execution_capacity_verified", "uncertainty_computed", "economic_hypothesis_supported"):
        _fixed_boolean(row, key, False)
    if row["limitations"] != list(LIMITATIONS):
        raise ContractValidationError("independent evidence limitations must remain explicit")
    return _safe(row)


def validate_journal_event(value):
    row = dict(value)
    _constant(row, "schema_version", JOURNAL_VERSION)
    _constant(row, "domain", "TRADING")
    _constant(row, "event_type", REVIEW_TYPE)
    row["event_id"] = _journal_id(row["event_id"], "event_id")
    row["decision_id"] = _journal_id(row["decision_id"], "decision_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    payload = _object(row["payload"], {"request", "result", "links", "prior_review_event_ids", "implementation_evidence"}, "independent reconciliation payload")
    request = EvidenceReconciliationRequest.from_mapping(payload["request"])
    result = validate_result(payload["result"])
    links = validate_links(payload["links"])
    source = _object(row["source"], {"kind", "review_id", "source_sha256"}, "independent reconciliation source")
    _constant(source, "kind", SOURCE_KIND)
    if source["review_id"] != request.review_id or source["source_sha256"] != sha256_bytes(request.to_bytes()):
        raise ContractValidationError("journal source differs from its strict request")
    if row["recorded_at"] != request.recorded_at or result["review_id"] != request.review_id:
        raise ContractValidationError("journal request/result identity or clock differs")
    if links["anchor_review_event_id"] != request.anchor_review_event_id or result["anchor_review_event_id"] != request.anchor_review_event_id:
        raise ContractValidationError("journal anchor differs")
    if links["selected_qualification_event_id"] != result["selected_qualification_event_id"]:
        raise ContractValidationError("journal selected native source differs")
    context = result["source_context"]
    for key in ("capture_plan_event_id", "aggregate_export_event_id", "base_plan_event_id"):
        if links[key] != context[key]:
            raise ContractValidationError("journal links differ from the exact source context")
    if context["declared_evaluation_mode"] != request.declared_evaluation_mode or context["account_evidence"] != request.account_profile_evidence:
        raise ContractValidationError("source context must preserve the requested target mode and account scope")
    if parse_rfc3339(context["recorded_at"], "source context clock") > parse_rfc3339(request.data_cutoff_at, "review cutoff"):
        raise ContractValidationError("source context cannot follow the review cutoff")
    payload.update(request=request.to_dict(), result=result, links=links,
        prior_review_event_ids=_ids(payload["prior_review_event_ids"]),
        implementation_evidence=_evidence(payload["implementation_evidence"]))
    row.update(payload=payload, source=source, evidence=_evidence(row["evidence"]))
    return row
