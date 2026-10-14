"""Closed descriptive source-applicability claims; never trading parameters."""
from decimal import Decimal
from urllib.parse import urlsplit

from .decision_journal import _object, _identifier, _string, _enum, _hash
from .investment_review import disabled_authority, _event_id
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _universe
from ..hashing import canonical_json_bytes
from ..trading_historical_intake import parse_historical_json

CONTEXT_VERSION = "blackpod.historical_feed_cost_context.v1"
PACKET_VERSION = "blackpod.historical_feed_cost_applicability_packet.v1"
RESULT_VERSION = "blackpod.historical_feed_cost_applicability.v1"
METHOD_VERSION = RESULT_VERSION
CATEGORIES = ("FEED_IDENTITY", "QUOTE_SIZE_UNITS", "FEE_SCHEDULE", "SLIPPAGE", "OPENING_CAPACITY")
MODES = {"SHADOW_RESEARCH", "PAPER_SIMULATION", "LIVE_BROKERAGE"}
STATUSES = {"DECLARED_SCOPE_MATCHED_NOT_VERIFIED", "UNRESOLVED", "SCOPE_MISMATCH", "CONFLICTING_SOURCES"}
QUOTE_URL = "https://data.alpaca.markets/v2/stocks/quotes"
DERIVED_NULL_FIELDS = ("derived_fee_rates", "derived_unit_multiplier", "derived_slippage", "derived_fill_capacity")
FALSE_FIELDS = ("source_applicability_verified", "source_authentication_verified", "historical_point_in_time_verified",
    "independent_issuer_evidence_established", "native_gate_override", "old_assumptions_populated",
    "economic_hypothesis_supported", "uncertainty_computed", "auto_trading_enabled")
LIMITATIONS = (
    "CALLER_VERIFIES_ORIGINAL_JOURNAL_AND_FULL_RECEIPT_INVENTORY",
    "DECLARED_SCOPE_MATCH_NOT_DOCUMENT_SEMANTIC_VERIFICATION_OR_AUTHENTICATION",
    "MARKET_EVENT_TIME_AND_DELIVERY_TIME_ARE_DISTINCT",
    "SOURCE_NUMERIC_ASSERTIONS_RETAINED_NOT_CONVERTED_OR_APPLIED",
    "MARKET_DATA_COLLECTION_MODE_NOT_BROKER_ACCOUNT_OR_EXECUTION_MODE_PROOF",
    "CURRENT_DOCUMENTATION_NOT_HISTORICAL_RATE_UNIT_OR_FILL_CAPACITY_PROOF",
    "SAME_PUBLISHER_DATA_DOCUMENTATION_NOT_INDEPENDENT_ISSUER_ACTION_COVERAGE",
    "NO_NATIVE_POLICY_RISK_COST_OR_QUALIFICATION_GATE_CHANGES",
    "NO_REALIZED_FEES_SLIPPAGE_CAPACITY_RETURNS_OR_EXECUTION",
)


def _constant(row, key, expected):
    if type(row[key]) is not type(expected) or row[key] != expected:
        raise ContractValidationError(key + " must equal " + repr(expected))


def _safe(row):
    _constant(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _url(value, name):
    value = _string(value, name, 2048)
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.fragment or any(char.isspace() for char in value):
            raise ValueError()
        url.port
    except ValueError as exc:
        raise ContractValidationError(name + " requires an explicit public HTTPS URL without credentials or fragment") from exc
    return value


def interval(value, name):
    row = _object(value, {"start_at", "end_at"}, name)
    for key in row: row[key] = accounting_timestamp(row[key], name + "." + key)
    if parse_rfc3339(row["start_at"], name) > parse_rfc3339(row["end_at"], name):
        raise ContractValidationError(name + " must be chronological")
    return row


def _refs(value, name, maximum=4096):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ContractValidationError(name + " requires a bounded nonempty reference list")
    refs = [evidence_reference(item, name) for item in value]
    if len({item["path"] for item in refs}) != len(refs) or len({item["sha256"] for item in refs}) != len(refs):
        raise ContractValidationError(name + " source paths and hashes must be distinct")
    return refs


def _context(value):
    row = _object(value, {"schema_version", "context_id", "recorded_at", "capture_plan_event_id", "aggregate_export_event_id",
        "base_plan_event_id", "dataset_evidence", "bars_receipt_evidence", "capture_plan_evidence", "quote_receipt_evidence",
        "provider", "endpoint", "feed", "universe", "currency", "market_event_interval", "delivery_interval",
        "collection_mode", "declared_evaluation_mode", "account_evidence", "auto_trading_enabled", "authority"}, "historical feed context")
    for key, expected in (("schema_version", CONTEXT_VERSION), ("provider", "ALPACA"), ("endpoint", QUOTE_URL),
        ("feed", "iex"), ("currency", "USD"), ("collection_mode", "MARKET_DATA_GET_ONLY")): _constant(row, key, expected)
    row["context_id"] = _identifier(row["context_id"], "context_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    for key in ("capture_plan_event_id", "aggregate_export_event_id", "base_plan_event_id"): row[key] = _event_id(row[key], key)
    for key in ("dataset_evidence", "bars_receipt_evidence", "capture_plan_evidence"): row[key] = evidence_reference(row[key], key)
    row["quote_receipt_evidence"] = _refs(row["quote_receipt_evidence"], "quote_receipt_evidence")
    row["universe"] = _universe(row["universe"])
    row["declared_evaluation_mode"] = _enum(row["declared_evaluation_mode"], MODES, "declared_evaluation_mode")
    for key in ("market_event_interval", "delivery_interval"): row[key] = interval(row[key], key)
    if row["account_evidence"] is not None: row["account_evidence"] = evidence_reference(row["account_evidence"], "account_evidence")
    return _safe(row)


def _numeric(value):
    if value is None: return None
    row = _object(value, {"value", "unit"}, "source numeric assertion")
    token = _string(row["value"], "source numeric value", 128)
    number = parse_historical_json(token.encode("utf-8"))
    if not isinstance(number, Decimal): raise ContractValidationError("source numeric assertion must preserve an exact JSON number token")
    row["unit"] = _string(row["unit"], "source numeric unit", 128)
    return row


def _scope(value):
    row = _object(value, {"provider", "endpoint", "feed", "universe", "currency", "collection_mode", "declared_evaluation_mode",
        "account_evidence", "market_event_interval", "delivery_interval", "effective_time_basis"}, "declared applicability scope")
    for key in ("provider", "feed"):
        if row[key] is not None: row[key] = _string(row[key], key, 128)
    if row["endpoint"] is not None: row["endpoint"] = _url(row["endpoint"], "endpoint")
    if row["universe"] is not None: row["universe"] = _universe(row["universe"])
    if row["currency"] is not None: _constant(row, "currency", "USD")
    if row["collection_mode"] is not None: _constant(row, "collection_mode", "MARKET_DATA_GET_ONLY")
    if row["declared_evaluation_mode"] is not None: row["declared_evaluation_mode"] = _enum(row["declared_evaluation_mode"], MODES, "declared_evaluation_mode")
    if row["account_evidence"] is not None: row["account_evidence"] = evidence_reference(row["account_evidence"], "account_evidence")
    for key in ("market_event_interval", "delivery_interval"):
        if row[key] is not None: row[key] = interval(row[key], key)
    row["effective_time_basis"] = _enum(row["effective_time_basis"], {"MARKET_EVENT_TIME", "DELIVERY_TIME", "BOTH", "UNRESOLVED"}, "effective_time_basis")
    return row


def _packet(value):
    row = _object(value, {"schema_version", "packet_id", "recorded_at", "data_cutoff_at", "context_evidence", "reviewer_id",
        "review_notes", "source_documents", "categories", "auto_trading_enabled", "authority"}, "historical applicability packet")
    _constant(row, "schema_version", PACKET_VERSION)
    for key in ("packet_id", "reviewer_id"): row[key] = _identifier(row[key], key)
    for key in ("recorded_at", "data_cutoff_at"): row[key] = accounting_timestamp(row[key], key)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "recorded"):
        raise ContractValidationError("applicability cutoff cannot follow recording")
    row["context_evidence"] = evidence_reference(row["context_evidence"], "context_evidence")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    if not isinstance(row["source_documents"], list) or len(row["source_documents"]) > 128:
        raise ContractValidationError("source documents require a bounded explicit list")
    documents, ids = [], set()
    for item in row["source_documents"]:
        item = _object(item, {"document_id", "evidence", "source_url", "publisher", "document_version", "published_at", "observed_at", "document_kind"}, "applicability source document")
        item["document_id"] = _identifier(item["document_id"], "document_id")
        if item["document_id"] in ids: raise ContractValidationError("source document identities must be distinct")
        ids.add(item["document_id"])
        item["evidence"] = evidence_reference(item["evidence"], "source document evidence")
        item["source_url"] = _url(item["source_url"], "source_url")
        item["publisher"] = _string(item["publisher"], "publisher", 256)
        if item["document_version"] is not None: item["document_version"] = _string(item["document_version"], "document_version", 256)
        item["observed_at"] = accounting_timestamp(item["observed_at"], "observed_at")
        if item["published_at"] is not None:
            item["published_at"] = accounting_timestamp(item["published_at"], "published_at")
            if parse_rfc3339(item["published_at"], "published") > parse_rfc3339(item["observed_at"], "observed"):
                raise ContractValidationError("source publication cannot follow its declared observation")
        if parse_rfc3339(item["observed_at"], "observed") > parse_rfc3339(row["data_cutoff_at"], "cutoff"):
            raise ContractValidationError("source observation is excluded by applicability cutoff")
        item["document_kind"] = _enum(item["document_kind"], {"RAW_PRIMARY_DOCUMENT", "AUTHORED_REVIEW_NOTE"}, "document_kind")
        documents.append(item)
    row["source_documents"] = documents
    if not isinstance(row["categories"], list) or len(row["categories"]) != len(CATEGORIES):
        raise ContractValidationError("all five fixed applicability categories must be retained")
    categories, assertion_ids = [], set()
    for index, item in enumerate(row["categories"]):
        item = _object(item, {"category", "assertions"}, "applicability category")
        _constant(item, "category", CATEGORIES[index])
        if not isinstance(item["assertions"], list) or len(item["assertions"]) > 64:
            raise ContractValidationError("category assertions must be bounded explicit lists")
        assertions = []
        for assertion in item["assertions"]:
            assertion = _object(assertion, {"assertion_id", "document_id", "claim_key", "claim_value", "numeric_assertion", "fee_formula_shape", "scope"}, "source applicability assertion")
            for key in ("assertion_id", "document_id", "claim_key"): assertion[key] = _identifier(assertion[key], key)
            if assertion["assertion_id"] in assertion_ids or assertion["document_id"] not in ids:
                raise ContractValidationError("assertions require distinct identities and retained source documents")
            assertion_ids.add(assertion["assertion_id"])
            if assertion["claim_value"] is not None: assertion["claim_value"] = _string(assertion["claim_value"], "claim_value", 4000)
            assertion["numeric_assertion"] = _numeric(assertion["numeric_assertion"])
            assertion["fee_formula_shape"] = _enum(assertion["fee_formula_shape"], {"UNRESOLVED", "CONSTANT_BPS_PLUS_PER_FILL", "SIDE_PER_SHARE_CAP_ROUNDING", "OTHER"}, "fee_formula_shape")
            if item["category"] != "FEE_SCHEDULE" and assertion["fee_formula_shape"] != "UNRESOLVED":
                raise ContractValidationError("fee formula shape belongs only to fee schedule claims")
            assertion["scope"] = _scope(assertion["scope"]); assertions.append(assertion)
        item["assertions"] = assertions; categories.append(item)
    row["categories"] = categories
    return _safe(row)


class HistoricalFeedCostContext(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_context)


class HistoricalFeedCostApplicabilityPacket(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_packet)


def evidence_references(packet, context):
    packet = HistoricalFeedCostApplicabilityPacket.from_mapping(packet.to_dict() if hasattr(packet, "to_dict") else packet)
    context = HistoricalFeedCostContext.from_mapping(context.to_dict() if hasattr(context, "to_dict") else context)
    refs = [packet.context_evidence, context.dataset_evidence, context.bars_receipt_evidence, context.capture_plan_evidence,
        *context.quote_receipt_evidence, *[document["evidence"] for document in packet.source_documents]]
    if context.account_evidence is not None: refs.append(context.account_evidence)
    refs.extend(assertion["scope"]["account_evidence"] for category in packet.categories for assertion in category["assertions"] if assertion["scope"]["account_evidence"] is not None)
    paths, result = {}, []
    for ref in refs:
        if ref["path"] in paths and paths[ref["path"]] != ref: raise ContractValidationError("applicability leaf paths bind conflicting identities")
        if ref["path"] not in paths: result.append(ref); paths[ref["path"]] = ref
    return result


def _strings(value, name):
    if not isinstance(value, list) or len(value) > 4096 or any(not isinstance(item, str) for item in value) or value != sorted(set(value)):
        raise ContractValidationError(name + " must be a bounded sorted unique string list")
    for item in value: _string(item, name, 256)


def validate_result(value):
    row = _object(value, {"schema_version", "method_version", "packet_id", "context_id", "packet_sha256", "context_sha256", "evidence_scope",
        "status", "category_results", "reason_codes", "source_documents", "limitations", "authority", *DERIVED_NULL_FIELDS, *FALSE_FIELDS}, "historical applicability result")
    for key, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION), ("status", "DESCRIPTIVE_APPLICABILITY_REVIEW_ONLY")): _constant(row, key, expected)
    for key in ("packet_id", "context_id"): _identifier(row[key], key)
    for key in ("packet_sha256", "context_sha256"): _hash(row[key], key)
    _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    _strings(row["reason_codes"], "reason_codes")
    if not isinstance(row["source_documents"], list) or len(row["source_documents"]) > 128:
        raise ContractValidationError("result source documents must be bounded")
    document_ids = set()
    for document in row["source_documents"]:
        document = _object(document, {"document_id", "evidence", "source_url", "publisher", "document_version", "published_at", "observed_at", "document_kind"}, "result document")
        _identifier(document["document_id"], "document_id")
        if document["document_id"] in document_ids: raise ContractValidationError("result documents must have distinct identities")
        document_ids.add(document["document_id"])
        evidence_reference(document["evidence"], "evidence"); _url(document["source_url"], "source_url"); _string(document["publisher"], "publisher", 256)
        if document["document_version"] is not None: _string(document["document_version"], "document_version", 256)
        for key in ("published_at", "observed_at"):
            if document[key] is not None: accounting_timestamp(document[key], key)
        if document["observed_at"] is None: raise ContractValidationError("source observation clock is required")
        if document["published_at"] is not None and parse_rfc3339(document["published_at"], "publication") > parse_rfc3339(document["observed_at"], "observation"):
            raise ContractValidationError("source publication cannot follow observation")
        _enum(document["document_kind"], {"RAW_PRIMARY_DOCUMENT", "AUTHORED_REVIEW_NOTE"}, "document_kind")
    if not isinstance(row["category_results"], list) or len(row["category_results"]) != len(CATEGORIES):
        raise ContractValidationError("result must retain every fixed category")
    seen, all_reasons = set(), set()
    for index, category in enumerate(row["category_results"]):
        category = _object(category, {"category", "status", "reason_codes", "assertion_results", "conflicts"}, "applicability category result")
        _constant(category, "category", CATEGORIES[index]); _enum(category["status"], STATUSES, "status"); _strings(category["reason_codes"], "category reasons")
        if not isinstance(category["assertion_results"], list) or len(category["assertion_results"]) > 64:
            raise ContractValidationError("assertion results must be bounded")
        local_ids, assertion_reasons, assertion_statuses = set(), set(), set()
        for assertion in category["assertion_results"]:
            assertion = _object(assertion, {"assertion_id", "document_id", "claim_key", "claim_value", "numeric_assertion", "scope_status", "reason_codes", "mismatched_fields", "interval_gaps"}, "assertion result")
            for key in ("assertion_id", "document_id", "claim_key"): _identifier(assertion[key], key)
            if assertion["assertion_id"] in seen or assertion["document_id"] not in document_ids: raise ContractValidationError("result assertions require unique IDs and retained documents")
            seen.add(assertion["assertion_id"]); local_ids.add(assertion["assertion_id"])
            if assertion["claim_value"] is not None: _string(assertion["claim_value"], "claim_value", 4000)
            _numeric(assertion["numeric_assertion"]); _enum(assertion["scope_status"], STATUSES, "scope_status")
            _strings(assertion["reason_codes"], "assertion reasons"); _strings(assertion["mismatched_fields"], "mismatched_fields")
            expected_status = ("SCOPE_MISMATCH" if assertion["mismatched_fields"] else "UNRESOLVED" if assertion["reason_codes"] else "DECLARED_SCOPE_MATCHED_NOT_VERIFIED")
            if assertion["scope_status"] != expected_status:
                raise ContractValidationError("assertion scope status cannot hide declared mismatches or unresolved reasons")
            if bool(assertion["mismatched_fields"]) != ("DECLARED_SCOPE_MISMATCH" in assertion["reason_codes"]):
                raise ContractValidationError("scope mismatch fields and reasons must agree")
            assertion_reasons.update(assertion["reason_codes"]); assertion_statuses.add(assertion["scope_status"])
            if not isinstance(assertion["interval_gaps"], list) or len(assertion["interval_gaps"]) > 4: raise ContractValidationError("interval gaps must be bounded")
            for gap in assertion["interval_gaps"]:
                gap = _object(gap, {"time_basis", "start_at", "end_at", "start_inclusive", "end_inclusive"}, "interval gap")
                _enum(gap["time_basis"], {"MARKET_EVENT_TIME", "DELIVERY_TIME"}, "time_basis")
                interval({key: gap[key] for key in ("start_at", "end_at")}, "gap")
                if any(type(gap[key]) is not bool for key in ("start_inclusive", "end_inclusive")): raise ContractValidationError("gap boundaries require exact booleans")
        conflicts = category["conflicts"]
        if not isinstance(conflicts, list) or len(conflicts) > 2016: raise ContractValidationError("claim conflicts must be bounded")
        for conflict in conflicts:
            conflict = _object(conflict, {"claim_key", "assertion_ids"}, "conflicting claims")
            _identifier(conflict["claim_key"], "claim_key"); _strings(conflict["assertion_ids"], "conflict assertion IDs")
            if len(conflict["assertion_ids"]) != 2 or not set(conflict["assertion_ids"]) <= local_ids: raise ContractValidationError("conflicts must link two retained same-category assertions")
            if any(assertion["claim_key"] != conflict["claim_key"] for assertion in category["assertion_results"] if assertion["assertion_id"] in conflict["assertion_ids"]):
                raise ContractValidationError("conflicts must preserve the original same-category claim key")
        if conflicts != sorted(conflicts, key=lambda item: (item["claim_key"], item["assertion_ids"])) or len({canonical_json_bytes(item) for item in conflicts}) != len(conflicts):
            raise ContractValidationError("conflicts must be deterministically sorted and distinct")
        if not category["assertion_results"]: assertion_reasons.add("SOURCE_ASSERTION_MISSING")
        if conflicts: assertion_reasons.add("CONFLICTING_DECLARED_SOURCE_CLAIMS")
        if category["reason_codes"] != sorted(assertion_reasons):
            raise ContractValidationError("category reasons cannot hide or invent assertion gaps")
        expected_status = ("CONFLICTING_SOURCES" if conflicts else "UNRESOLVED" if not category["assertion_results"] else
            "SCOPE_MISMATCH" if "SCOPE_MISMATCH" in assertion_statuses else "UNRESOLVED" if "UNRESOLVED" in assertion_statuses else "DECLARED_SCOPE_MATCHED_NOT_VERIFIED")
        if category["status"] != expected_status: raise ContractValidationError("category status must preserve every assertion disposition")
        all_reasons.update(category["reason_codes"])
    if not all_reasons <= set(row["reason_codes"]): raise ContractValidationError("global applicability reasons cannot hide category gaps")
    for key in FALSE_FIELDS: _constant(row, key, False)
    for key in DERIVED_NULL_FIELDS: _constant(row, key, None)
    disabled_authority(row["authority"])
    if row["limitations"] != list(LIMITATIONS): raise ContractValidationError("applicability limitations must remain explicit")
    if len(canonical_json_bytes(row)) > 8 * 1024 * 1024: raise ContractValidationError("applicability result exceeds compact byte bound")
    return row
