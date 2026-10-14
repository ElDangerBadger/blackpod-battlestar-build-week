"""Pure applicability matrix from retained metadata, without pricing or trading.

The caller verifies the original journal graph and full receipt inventory.
This module verifies supplied metadata leaves and declared scopes. It does not
read quote bodies, interpret prose as facts or assign historical parameters.
"""
from itertools import combinations
from decimal import Decimal

from .contracts.historical_feed_cost_applicability import (
    HistoricalFeedCostApplicabilityPacket, HistoricalFeedCostContext, CATEGORIES,
    RESULT_VERSION, METHOD_VERSION, FALSE_FIELDS, DERIVED_NULL_FIELDS, LIMITATIONS,
    evidence_references, validate_result,
)
from .contracts.historical_intake import validate_historical_capture
from .contracts.mission_request import ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes
from .contracts.train_market_evidence import TrainMarketCapturePlan
from .contracts.trading_research import TradingResearchDataset
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_cost_intake import _capture

CODE_PATHS = ("contracts/historical_feed_cost_applicability.py", "historical_feed_cost_applicability.py")
AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _document(value, kind):
    return kind.from_mapping(value.to_dict() if hasattr(value, "to_dict") else value)


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ContractValidationError("applicability source bytes differ in hash or size")
    return raw


def _time(value):
    return parse_rfc3339(value, "applicability clock")


def _same_interval(left, right):
    return all(_time(left[key]) == _time(right[key]) for key in ("start_at", "end_at"))


def _metadata(context, blobs):
    dataset = TradingResearchDataset.from_bytes(_blob(blobs, context.dataset_evidence))
    capture = TrainMarketCapturePlan.from_bytes(_blob(blobs, context.capture_plan_evidence))
    if (dataset.schema_version != "blackpod.trading_research_dataset.v2" or capture.dataset_evidence != context.dataset_evidence
            or dataset.universe != context.universe or capture.base_plan_event_id != context.base_plan_event_id):
        raise ContractValidationError("applicability context must preserve the original governed dataset and capture plan")
    if context.bars_receipt_evidence not in dataset.provenance["source_evidence"]:
        raise ContractValidationError("applicability bars receipt must belong to the exact original dataset")
    bars = validate_historical_capture(parse_strict_json_object_bytes(_blob(blobs, context.bars_receipt_evidence)), "bars")
    if bars["query"]["symbols"] != ",".join(context.universe) or bars["query"]["feed"] != context.feed:
        raise ContractValidationError("applicability bars metadata changes the original feed or universe")
    if not _time(bars["captured_at"]) <= _time(dataset.recorded_at) <= _time(capture.created_at) <= _time(context.recorded_at):
        raise ContractValidationError("applicability original source clocks are inconsistent")
    segments = capture.segments
    market = {"start_at": min((segment["query"]["start"] for segment in segments), key=_time),
        "end_at": max((segment["query"]["end"] for segment in segments), key=_time)}
    if not _same_interval(market, context.market_event_interval):
        raise ContractValidationError("applicability market interval must bind every original planned TRAIN window")
    queries = [segment["query"] for segment in segments]
    clocks, reasons = [], []
    for ref in context.quote_receipt_evidence:
        receipt = _capture(_blob(blobs, ref))
        base = {key: value for key, value in receipt["query"].items() if key != "page_token"}
        if (receipt["url"] != context.endpoint or receipt["method"] != "GET" or base not in queries
                or base["feed"] != context.feed or base["symbols"] != ",".join(context.universe) or base["currency"] != context.currency):
            raise ContractValidationError("applicability receipt must match an exact frozen native TRAIN query")
        if not _time(capture.created_at) <= _time(receipt["captured_at"]) <= _time(context.recorded_at):
            raise ContractValidationError("applicability quote capture lies outside plan/context clocks")
        if _time(base["end"]) > _time(receipt["captured_at"]):
            raise ContractValidationError("applicability source cannot capture a future market interval")
        clocks.append(receipt["captured_at"])
        if receipt["status"] != 200: reasons.append("SOURCE_QUOTE_RECEIPT_UNAVAILABLE")
    delivery = {"start_at": min(clocks, key=_time), "end_at": max(clocks, key=_time)}
    if not _same_interval(delivery, context.delivery_interval):
        raise ContractValidationError("applicability delivery interval must bind all supplied original receipt clocks")
    return capture, sorted(set(reasons))


def _gaps(target, declared, basis):
    if declared is None:
        return [{"time_basis": basis, **target, "start_inclusive": True, "end_inclusive": True}]
    a, b, c, d = (_time(value) for value in (target["start_at"], target["end_at"], declared["start_at"], declared["end_at"]))
    if d < a or c > b:
        return [{"time_basis": basis, **target, "start_inclusive": True, "end_inclusive": True}]
    gaps = []
    if c > a:
        gaps.append({"time_basis": basis, "start_at": target["start_at"], "end_at": declared["start_at"], "start_inclusive": True, "end_inclusive": False})
    if d < b:
        gaps.append({"time_basis": basis, "start_at": declared["end_at"], "end_at": target["end_at"], "start_inclusive": False, "end_inclusive": True})
    return gaps


def _assertion(assertion, document, category, context, context_reasons):
    scope, reasons, mismatches, gaps = assertion["scope"], list(context_reasons), [], []
    target = context.to_dict()
    for key in ("provider", "endpoint", "feed", "universe", "currency", "collection_mode", "declared_evaluation_mode"):
        if scope[key] is None: reasons.append("UNRESOLVED_" + key.upper())
        elif scope[key] != target[key]: mismatches.append(key)
    if category in {"FEE_SCHEDULE", "SLIPPAGE", "OPENING_CAPACITY"}:
        if scope["account_evidence"] is None or context.account_evidence is None:
            reasons.append("ACCOUNT_SCOPE_UNRESOLVED")
        elif scope["account_evidence"] != context.account_evidence: mismatches.append("account_evidence")
    elif scope["account_evidence"] is not None and scope["account_evidence"] != context.account_evidence:
        mismatches.append("account_evidence")
    basis = scope["effective_time_basis"]
    if basis == "UNRESOLVED": reasons.append("EFFECTIVE_TIME_BASIS_UNRESOLVED")
    # Unit formatting and numeric costs cannot be mapped merely by matching
    # one clock: the source must explicitly bind event and delivery semantics.
    if category != "FEED_IDENTITY" and basis != "BOTH": reasons.append("CROSS_TIME_APPLICABILITY_UNRESOLVED")
    for field, clock_basis in (("market_event_interval", "MARKET_EVENT_TIME"), ("delivery_interval", "DELIVERY_TIME")):
        if basis in {clock_basis, "BOTH"}:
            missing = _gaps(target[field], scope[field], clock_basis)
            if missing: reasons.append(clock_basis + "_COVERAGE_GAP")
            gaps.extend(missing)
    if document["document_kind"] != "RAW_PRIMARY_DOCUMENT": reasons.append("AUTHORED_REVIEW_NOTE_NOT_RAW_PRIMARY_DOCUMENT")
    if document["published_at"] is None: reasons.append("PUBLICATION_TIME_UNRESOLVED")
    if document["document_version"] is None: reasons.append("DOCUMENT_VERSION_UNRESOLVED")
    if assertion["claim_value"] is None and assertion["numeric_assertion"] is None: reasons.append("CLAIM_VALUE_UNRESOLVED")
    if category == "FEE_SCHEDULE" and assertion["fee_formula_shape"] != "CONSTANT_BPS_PLUS_PER_FILL":
        reasons.append("OLD_COST_MODEL_EXPRESSIVITY_UNVERIFIED")
    if mismatches: reasons.append("DECLARED_SCOPE_MISMATCH")
    status = "SCOPE_MISMATCH" if mismatches else "UNRESOLVED" if reasons else "DECLARED_SCOPE_MATCHED_NOT_VERIFIED"
    return {"assertion_id": assertion["assertion_id"], "document_id": assertion["document_id"],
        "claim_key": assertion["claim_key"], "claim_value": assertion["claim_value"], "numeric_assertion": assertion["numeric_assertion"],
        "scope_status": status, "reason_codes": sorted(set(reasons)), "mismatched_fields": sorted(mismatches), "interval_gaps": gaps}


def _overlaps(left, right):
    for key in ("provider", "endpoint", "feed", "universe", "currency", "collection_mode", "declared_evaluation_mode", "account_evidence"):
        if left[key] is not None and right[key] is not None and left[key] != right[key]: return False
    for key in ("market_event_interval", "delivery_interval"):
        a, b = left[key], right[key]
        if a is not None and b is not None and (_time(a["end_at"]) < _time(b["start_at"]) or _time(b["end_at"]) < _time(a["start_at"])):
            return False
    return True


def _different_claims(left, right):
    # Distinct numeric spellings such as 1e2 and 100 remain retained but are
    # not contradictory values. Different units are not silently converted.
    if left["claim_value"] is not None and right["claim_value"] is not None and left["claim_value"] != right["claim_value"]:
        return True
    a, b = left["numeric_assertion"], right["numeric_assertion"]
    return (a is not None and b is not None and a["unit"] == b["unit"] and Decimal(a["value"]) != Decimal(b["value"]))


def assess_historical_applicability(packet, context, blobs):
    """Retain source claims and compute only scope, time gaps and conflicts."""
    packet = _document(packet, HistoricalFeedCostApplicabilityPacket)
    context = _document(context, HistoricalFeedCostContext)
    if _blob(blobs, packet.context_evidence) != context.to_bytes():
        raise ContractValidationError("applicability packet must bind its exact canonical native context")
    if _time(context.recorded_at) > _time(packet.data_cutoff_at):
        raise ContractValidationError("applicability cutoff excludes its original context")
    for ref in evidence_references(packet, context): _blob(blobs, ref)
    capture, context_reasons = _metadata(context, blobs)
    evidence = {"historical-applicability/context.v1.json": context.to_bytes(),
        "historical-applicability/packet.v1.json": packet.to_bytes()}
    documents = {document["document_id"]: document for document in packet.source_documents}
    support = [document["evidence"] for document in packet.source_documents]
    if context.account_evidence is not None: support.append(context.account_evidence)
    support.extend(assertion["scope"]["account_evidence"] for category in packet.categories for assertion in category["assertions"] if assertion["scope"]["account_evidence"] is not None)
    if sum(ref["size_bytes"] for ref in {ref["sha256"]: ref for ref in support}.values()) > 64 * 1024 * 1024:
        raise ContractValidationError("applicability source documents exceed retained byte bound")
    for ref in support: evidence["historical-applicability/support/" + ref["sha256"] + ".raw"] = _blob(blobs, ref)
    categories, global_reasons = [], set(context_reasons)
    for category in packet.categories:
        assertions = category["assertions"]
        results = [_assertion(assertion, documents[assertion["document_id"]], category["category"], context, context_reasons) for assertion in assertions]
        conflicts = []
        for left, right in combinations(assertions, 2):
            if (left["claim_key"] == right["claim_key"] and _different_claims(left, right)
                    and _overlaps(left["scope"], right["scope"])):
                conflicts.append({"claim_key": left["claim_key"], "assertion_ids": sorted((left["assertion_id"], right["assertion_id"]))})
        reasons = {reason for result in results for reason in result["reason_codes"]}
        if not assertions: reasons.add("SOURCE_ASSERTION_MISSING")
        if conflicts: reasons.add("CONFLICTING_DECLARED_SOURCE_CLAIMS")
        statuses = {result["scope_status"] for result in results}
        status = ("CONFLICTING_SOURCES" if conflicts else "UNRESOLVED" if not assertions else
            "SCOPE_MISMATCH" if "SCOPE_MISMATCH" in statuses else "UNRESOLVED" if "UNRESOLVED" in statuses else "DECLARED_SCOPE_MATCHED_NOT_VERIFIED")
        categories.append({"category": category["category"], "status": status, "reason_codes": sorted(reasons),
            "assertion_results": results, "conflicts": sorted(conflicts, key=lambda row: (row["claim_key"], row["assertion_ids"]))})
        global_reasons.update(reasons)
    result = validate_result({"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION,
        "packet_id": packet.packet_id, "context_id": context.context_id, "packet_sha256": sha256_bytes(packet.to_bytes()),
        "context_sha256": sha256_bytes(context.to_bytes()), "evidence_scope": capture.evidence_scope,
        "status": "DESCRIPTIVE_APPLICABILITY_REVIEW_ONLY", "category_results": categories,
        "reason_codes": sorted(global_reasons), "source_documents": packet.source_documents,
        **{key: None for key in DERIVED_NULL_FIELDS}, **{key: False for key in FALSE_FIELDS},
        "limitations": list(LIMITATIONS), "authority": dict(AUTHORITY)})
    return {"result": result, "evidence": evidence}
