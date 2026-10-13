"""Closed descriptive reviews of exact native qualification records.

Supplemental review identities, source URLs, capture clocks and applicability
notes are retained declarations. They do not replace any native prerequisite.
"""
from urllib.parse import urlsplit

from .decision_journal import _object, _identifier, _enum, _string, _hash, _evidence, _journal_id
from .investment_review import _event_id, _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .segmented_evidence_qualification import validate_result as validate_native_result

REQUEST_VERSION = "blackpod.native_evidence_closure_review_request.v1"
SUPPLEMENTAL_VERSION = "blackpod.native_evidence_supplemental_review.v1"
RESULT_VERSION = "blackpod.native_evidence_closure_review.v1"
METHOD_VERSION = "blackpod.native_evidence_closure_review.v1"
JOURNAL_VERSION = "blackpod.decision_journal_event.v21"
REVIEW_TYPE = "TRADING_NATIVE_EVIDENCE_CLOSURE_REVIEW_RECORDED"
CATEGORIES = ("CONTINUITY", "COST_CAPACITY", "SHADOW_RISK", "UNCERTAINTY", "WIDE_SPREAD")
SCOPE = "NATIVE_EVIDENCE_CLOSURE_REVIEW_ONLY"
LINK_FIELDS = {"anchor_qualification_event_id", "candidate_qualification_event_id", "selected_qualification_event_id", "base_plan_event_id", "hypothesis_event_id", "capture_plan_event_id", "selected_qualification_policy_event_id", "selected_aggregate_export_event_id"}
LIMITATIONS = (
    "DESCRIPTIVE_REVIEW_NEVER_REPLACES_NATIVE_QUALIFICATION_GATES",
    "SUPPLEMENTAL_REVIEW_CLAIMS_NOT_AUTHENTICATED_APPROVAL_OR_APPLICABILITY_PROOF",
    "SOURCE_URL_CAPTURE_AND_EFFECTIVE_COVERAGE_METADATA_ARE_DECLARATIONS",
    "WIDE_SPREAD_DIAGNOSTICS_RETAIN_NATIVE_EXTREMA_WITHOUT_CLIPPING_OR_NEW_TRADING_RULES",
    "QUOTES_CANNOT_ESTIMATE_SLIPPAGE_FEES_OR_OPENING_EXECUTION_CAPACITY",
    "NATIVE_CONTINUITY_REQUIRES_ITS_ORIGINAL_INDEPENDENT_COVERAGE_RECORD",
    "UNCERTAINTY_REMAINS_DECLARED_NOT_COMPUTED",
    "FINAL_HOLDOUT_UNSCORED_NOT_ACCESS_SEALED",
    "NO_PROVIDER_BROKER_INFERENCE_RETURN_SCORING_OR_EXECUTION",
)


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _texts(value, name, maximum=1024):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(name + " requires a bounded list")
    result = [_string(item, name, 10000) for item in value]
    if result != sorted(set(result)):
        raise ContractValidationError(name + " requires sorted distinct values")
    return result


def _ids(value, name, maximum=1024):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(name + " requires a bounded list")
    result = [_event_id(item, name) for item in value]
    if result != sorted(set(result)):
        raise ContractValidationError(name + " requires sorted distinct event identities")
    return result


def _optional_id(row, field):
    if row[field] is not None: row[field] = _event_id(row[field], field)


def _clock(row, field):
    row[field] = accounting_timestamp(row[field], field)


def _request(value):
    row = _object(value, {"schema_version", "review_id", "recorded_at", "data_cutoff_at", "domain", "mode", "scope", "anchor_qualification_event_id", "candidate_qualification_event_id", "supplemental_review_evidence", "supersedes_event_id", "auto_trading_enabled", "authority"}, "native evidence closure request")
    for field, expected in (("schema_version", REQUEST_VERSION), ("domain", "TRADING"), ("mode", "SHADOW_RESEARCH"), ("scope", SCOPE)):
        _constant(row, field, expected)
    row["review_id"] = _identifier(row["review_id"], "review_id")
    row["anchor_qualification_event_id"] = _event_id(row["anchor_qualification_event_id"], "anchor qualification")
    for field in ("candidate_qualification_event_id", "supersedes_event_id"): _optional_id(row, field)
    if row["candidate_qualification_event_id"] == row["anchor_qualification_event_id"]:
        raise ContractValidationError("candidate must be a distinct later native qualification")
    for field in ("recorded_at", "data_cutoff_at"): _clock(row, field)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"):
        raise ContractValidationError("native closure cutoff cannot follow record clock")
    if row["supplemental_review_evidence"] is not None:
        row["supplemental_review_evidence"] = evidence_reference(row["supplemental_review_evidence"], "supplemental review")
    return _safe(row)


def _source_document(value):
    row = _object(value, {"evidence", "source_url", "captured_at", "effective_coverage_start_at", "effective_coverage_end_at"}, "supplemental source declaration")
    row["evidence"] = evidence_reference(row["evidence"], "supplemental source")
    if row["source_url"] is not None:
        row["source_url"] = _string(row["source_url"], "declared source URL", 2048)
        try: url = urlsplit(row["source_url"])
        except ValueError as exc: raise ContractValidationError("declared source URL must be an ordinary HTTP(S) URL") from exc
        if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.password is not None or any(char.isspace() for char in row["source_url"]):
            raise ContractValidationError("declared source URL must be an ordinary HTTP(S) URL without credentials")
    for field in ("captured_at", "effective_coverage_start_at", "effective_coverage_end_at"):
        if row[field] is not None: _clock(row, field)
    start, end = row["effective_coverage_start_at"], row["effective_coverage_end_at"]
    if (start is None) != (end is None) or (start is not None and parse_rfc3339(start, "coverage start") > parse_rfc3339(end, "coverage end")):
        raise ContractValidationError("declared effective coverage must be paired and chronologically ordered")
    return row


def _supplemental(value):
    row = _object(value, {"schema_version", "supplemental_review_id", "recorded_at", "anchor_qualification_event_id", "candidate_qualification_event_id", "reviewer_id", "review_notes", "categories", "auto_trading_enabled", "authority"}, "native supplemental review")
    _constant(row, "schema_version", SUPPLEMENTAL_VERSION)
    for field in ("supplemental_review_id", "reviewer_id"): row[field] = _identifier(row[field], field)
    _clock(row, "recorded_at")
    row["anchor_qualification_event_id"] = _event_id(row["anchor_qualification_event_id"], "anchor qualification")
    _optional_id(row, "candidate_qualification_event_id")
    if row["candidate_qualification_event_id"] == row["anchor_qualification_event_id"]:
        raise ContractValidationError("supplemental candidate must be distinct")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    if not isinstance(row["categories"], list) or len(row["categories"]) != len(CATEGORIES):
        raise ContractValidationError("supplemental review requires exactly five categories")
    categories = []
    for index, value in enumerate(row["categories"]):
        item = _object(value, {"category", "status", "source_event_ids", "source_documents", "notes"}, "supplemental category")
        _constant(item, "category", CATEGORIES[index])
        item["status"] = _enum(item["status"], {"UNRESOLVED", "SOURCE_REVIEW_RECORDED"}, "review status")
        item["source_event_ids"] = _ids(item["source_event_ids"], "review source events", 32)
        if not isinstance(item["source_documents"], list) or len(item["source_documents"]) > 16:
            raise ContractValidationError("source documents require a bounded explicit list")
        documents = [_source_document(document) for document in item["source_documents"]]
        identities = [(document["evidence"]["path"], document["evidence"]["sha256"]) for document in documents]
        if len(identities) != len(set(identities)):
            raise ContractValidationError("supplemental category contains duplicate source documents")
        for document in documents:
            if document["captured_at"] is not None and parse_rfc3339(document["captured_at"], "declared capture") > parse_rfc3339(row["recorded_at"], "review clock"):
                raise ContractValidationError("supplemental review cannot precede its declared source captures")
        item["source_documents"] = documents
        if item["status"] == "SOURCE_REVIEW_RECORDED" and not (documents or item["source_event_ids"]):
            raise ContractValidationError("a recorded source review requires explicit source evidence")
        item["notes"] = _string(item["notes"], "review category notes", 10000)
        categories.append(item)
    row["categories"] = categories
    return _safe(row)


class NativeEvidenceClosureReviewRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


class NativeEvidenceSupplementalReview(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_supplemental)


def validate_links(value):
    row = _object(value, LINK_FIELDS, "native closure links")
    for field in row:
        if field == "candidate_qualification_event_id": _optional_id(row, field)
        else: row[field] = _event_id(row[field], field)
    expected = row["candidate_qualification_event_id"] or row["anchor_qualification_event_id"]
    if row["selected_qualification_event_id"] != expected:
        raise ContractValidationError("selected qualification must be the explicit candidate or anchor")
    return row


NATIVE_FIELDS = {"qualification_event_id", "recorded_at", "result_sha256", "binding_event_id", "qualification_policy_event_id", "capture_plan_event_id", "aggregate_export_event_id", "policy_status", "continuity_event_id", "cost_event_id", "risk_review_event_id", "training_cost_assumptions_evidence", "result"}


def _native(value):
    from ..hashing import canonical_json_bytes, sha256_bytes
    row = _object(value, NATIVE_FIELDS, "exact native qualification snapshot")
    for field in ("qualification_event_id", "binding_event_id", "qualification_policy_event_id", "capture_plan_event_id", "aggregate_export_event_id"):
        row[field] = _event_id(row[field], field)
    for field in ("continuity_event_id", "cost_event_id", "risk_review_event_id"): _optional_id(row, field)
    _clock(row, "recorded_at")
    row["policy_status"] = _enum(row["policy_status"], {"PROPOSED", "REVIEWED_FOR_SHADOW_QUALIFICATION", "REJECTED"}, "native policy status")
    if row["training_cost_assumptions_evidence"] is not None:
        row["training_cost_assumptions_evidence"] = evidence_reference(row["training_cost_assumptions_evidence"], "native training assumptions")
    row["result"] = validate_native_result(row["result"])
    for field in ("continuity", "risk"):
        section = row["result"][field]
        if not isinstance(section.get("reason_codes"), list):
            raise ContractValidationError("native " + field + " must retain reason codes")
        _texts(section["reason_codes"], "native " + field + " reasons")
    if not isinstance(row["result"]["continuity"].get("status"), str):
        raise ContractValidationError("native continuity must retain its status")
    if "native_assessment" not in row["result"]["risk"]:
        raise ContractValidationError("native risk must retain its assessment or explicit null")
    risk = row["result"]["risk"]["native_assessment"]
    if risk is not None and (not isinstance(risk, dict) or not isinstance(risk.get("status"), str)):
        raise ContractValidationError("native risk assessment must retain its status")
    row["result_sha256"] = _hash(row["result_sha256"], "native result hash")
    if row["result_sha256"] != sha256_bytes(canonical_json_bytes(row["result"])):
        raise ContractValidationError("native result snapshot differs from its retained hash")
    return row


RESULT_FIELDS = {"schema_version", "method_version", "review_id", "status", "selected_qualification_event_id", "anchor_qualification", "candidate_qualification", "reason_comparison", "missing_prerequisites", "source_findings", "supplemental_review", "anchor_diagnostics", "candidate_diagnostics", "native_gate_override", "supplemental_review_applied_to_native_gates", "reviewer_identity_authenticated", "source_applicability_verified", "source_authentication_verified", "historical_point_in_time_verified", "uncertainty_computed", "economic_hypothesis_supported", "execution_status", "realized_trade_pnl", "limitations", "auto_trading_enabled", "authority"}


def validate_result(value):
    from ..hashing import canonical_json_bytes, sha256_bytes
    from ..native_quote_diagnostics import validate_diagnostics
    row = _object(value, RESULT_FIELDS, "native evidence closure result")
    for field, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION), ("status", "DESCRIPTIVE_REVIEW_ONLY"), ("execution_status", "NOT_EXECUTED"), ("realized_trade_pnl", None)):
        _constant(row, field, expected)
    row["review_id"] = _identifier(row["review_id"], "review_id")
    row["selected_qualification_event_id"] = _event_id(row["selected_qualification_event_id"], "selected qualification")
    row["anchor_qualification"] = _native(row["anchor_qualification"])
    if row["candidate_qualification"] is not None: row["candidate_qualification"] = _native(row["candidate_qualification"])
    anchor, candidate = row["anchor_qualification"], row["candidate_qualification"]
    selected = candidate or anchor
    if row["selected_qualification_event_id"] != selected["qualification_event_id"]:
        raise ContractValidationError("closure selection differs from exact native source")
    if candidate is not None and (candidate["qualification_event_id"] == anchor["qualification_event_id"] or candidate["capture_plan_event_id"] != anchor["capture_plan_event_id"] or parse_rfc3339(candidate["recorded_at"], "candidate clock") < parse_rfc3339(anchor["recorded_at"], "anchor clock")):
        raise ContractValidationError("candidate snapshot must preserve capture plan and chronology")
    comparison = _object(row["reason_comparison"], {"resolved_reason_codes", "persisting_reason_codes", "new_reason_codes"}, "native reason comparison")
    previous, current = set(anchor["result"]["reason_codes"]), set(selected["result"]["reason_codes"])
    expected = {"resolved_reason_codes": sorted(previous - current), "persisting_reason_codes": sorted(previous & current), "new_reason_codes": sorted(current - previous)}
    for field in comparison:
        comparison[field] = _texts(comparison[field], field)
        if comparison[field] != expected[field]: raise ContractValidationError("reason comparison must use exact native outputs")
    row["reason_comparison"] = comparison
    row["missing_prerequisites"] = _texts(row["missing_prerequisites"], "missing prerequisites")
    if row["missing_prerequisites"] != sorted(current): raise ContractValidationError("missing prerequisites must retain selected native reasons")
    if row["supplemental_review"] is not None:
        row["supplemental_review"] = NativeEvidenceSupplementalReview.from_mapping(row["supplemental_review"]).to_dict()
        review = row["supplemental_review"]
        if review["anchor_qualification_event_id"] != anchor["qualification_event_id"] or review["candidate_qualification_event_id"] != (None if candidate is None else candidate["qualification_event_id"]):
            raise ContractValidationError("supplemental review must bind the exact selected native records")
    row["anchor_diagnostics"] = validate_diagnostics(row["anchor_diagnostics"])
    if row["candidate_diagnostics"] is not None: row["candidate_diagnostics"] = validate_diagnostics(row["candidate_diagnostics"])
    if (candidate is None) != (row["candidate_diagnostics"] is None):
        raise ContractValidationError("candidate diagnostic presence must match the selected native record")
    for role in ("anchor", "candidate"):
        native, diagnostic = row[role + "_qualification"], row[role + "_diagnostics"]
        if native is not None and (diagnostic["source"]["aggregate_export_event_id"] != native["aggregate_export_event_id"] or diagnostic["source"]["capture_plan_event_id"] != native["capture_plan_event_id"]):
            raise ContractValidationError("quote diagnostics must bind the exact native export and capture plan")
    findings = row["source_findings"]
    if not isinstance(findings, list) or len(findings) != len(CATEGORIES): raise ContractValidationError("source findings require all five native categories")
    sections = ("continuity", "training_calibration", "risk", "uncertainty_protocol", "training_calibration")
    native = selected["result"]
    statuses = (native["continuity"]["status"], native["training_calibration"]["status"],
        None if native["risk"]["native_assessment"] is None else native["risk"]["native_assessment"]["status"],
        native["uncertainty_status"], native["training_calibration"]["status"])
    reasons = (native["continuity"]["reason_codes"], native["training_calibration"]["reason_codes"], native["risk"]["reason_codes"],
        [reason for reason in native["reason_codes"] if "UNCERTAINTY" in reason or "STABILITY" in reason],
        [reason for reason in native["training_calibration"]["reason_codes"] if "COST" in reason or "SPREAD" in reason])
    checked = []
    for index, value in enumerate(findings):
        item = _object(value, {"category", "source_qualification_event_id", "source_event_ids", "native_value_pointer", "native_value_sha256", "native_status", "native_reason_codes", "statement"}, "native source finding")
        _constant(item, "category", CATEGORIES[index])
        _constant(item, "source_qualification_event_id", selected["qualification_event_id"])
        item["source_event_ids"] = _ids(item["source_event_ids"], "native source event identities", 1024)
        _constant(item, "native_value_pointer", "/payload/result/" + sections[index])
        item["native_value_sha256"] = _hash(item["native_value_sha256"], "native source value hash")
        if item["native_value_sha256"] != sha256_bytes(canonical_json_bytes(selected["result"][sections[index]])):
            raise ContractValidationError("native source finding cannot rewrite the selected source value")
        if item["native_status"] is not None: item["native_status"] = _string(item["native_status"], "native status", 128)
        item["native_reason_codes"] = _texts(item["native_reason_codes"], "native category reasons")
        if item["native_status"] != statuses[index] or item["native_reason_codes"] != sorted(set(reasons[index])):
            raise ContractValidationError("native findings must retain exact source status and reasons")
        item["statement"] = _string(item["statement"], "native source statement", 10000)
        checked.append(item)
    row["source_findings"] = checked
    row["limitations"] = _texts(row["limitations"], "limitations")
    if not set(LIMITATIONS) <= set(row["limitations"]): raise ContractValidationError("closure review must retain every authority and source limitation")
    for field in ("native_gate_override", "supplemental_review_applied_to_native_gates", "reviewer_identity_authenticated", "source_applicability_verified", "source_authentication_verified", "historical_point_in_time_verified", "uncertainty_computed", "economic_hypothesis_supported"):
        _fixed_boolean(row, field, False)
    return _safe(row)


def validate_journal_event(value):
    from ..hashing import sha256_bytes
    row = dict(value)
    _constant(row, "schema_version", JOURNAL_VERSION); _constant(row, "domain", "TRADING"); _constant(row, "event_type", REVIEW_TYPE)
    for field in ("event_id", "decision_id"): row[field] = _journal_id(row[field], field)
    _clock(row, "recorded_at")
    source = _object(row["source"], {"kind", "review_id", "source_sha256"}, "native closure source")
    _constant(source, "kind", "TRADING_NATIVE_EVIDENCE_CLOSURE_REVIEW")
    source["review_id"] = _identifier(source["review_id"], "review_id"); source["source_sha256"] = _hash(source["source_sha256"], "source hash")
    payload = _object(row["payload"], {"request", "result", "links", "prior_review_event_ids", "implementation_evidence"}, "native closure payload")
    request = NativeEvidenceClosureReviewRequest.from_mapping(payload["request"])
    payload["request"] = request.to_dict(); payload["result"] = validate_result(payload["result"]); payload["links"] = validate_links(payload["links"])
    if source["review_id"] != request.review_id or source["source_sha256"] != sha256_bytes(request.to_bytes()) or row["recorded_at"] != request.recorded_at or payload["result"]["review_id"] != request.review_id:
        raise ContractValidationError("closure source identity/hash/clock differs from its exact request")
    if payload["links"]["anchor_qualification_event_id"] != request.anchor_qualification_event_id or payload["links"]["candidate_qualification_event_id"] != request.candidate_qualification_event_id or payload["result"]["selected_qualification_event_id"] != payload["links"]["selected_qualification_event_id"]:
        raise ContractValidationError("closure payload source links differ from its request")
    result = payload["result"]
    if result["anchor_qualification"]["qualification_event_id"] != request.anchor_qualification_event_id or (None if result["candidate_qualification"] is None else result["candidate_qualification"]["qualification_event_id"]) != request.candidate_qualification_event_id:
        raise ContractValidationError("closure native snapshots differ from request sources")
    selected = result["candidate_qualification"] or result["anchor_qualification"]
    for link, native in (("capture_plan_event_id", "capture_plan_event_id"), ("selected_qualification_policy_event_id", "qualification_policy_event_id"), ("selected_aggregate_export_event_id", "aggregate_export_event_id")):
        if payload["links"][link] != selected[native]: raise ContractValidationError("closure source links differ from selected native snapshot")
    if any(parse_rfc3339(native["recorded_at"], "native clock") > parse_rfc3339(request.data_cutoff_at, "cutoff") for native in (result["anchor_qualification"], result["candidate_qualification"]) if native is not None):
        raise ContractValidationError("closure cutoff excludes a native source snapshot")
    if (request.supplemental_review_evidence is None) != (result["supplemental_review"] is None):
        raise ContractValidationError("closure supplemental review presence differs from request")
    payload["prior_review_event_ids"] = _ids(payload["prior_review_event_ids"], "prior closure reviews")
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    row["evidence"] = _evidence(row["evidence"])
    row["source"], row["payload"] = source, payload
    return row
