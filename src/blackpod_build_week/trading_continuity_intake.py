"""Pure native Alpaca corporate-action projection into continuity reviews.

No network, provider SDK, price repair or strategy rules are used. Exact source
responses and GET declarations remain retained; process-date pagination is
never promoted to effective-date coverage without independent review.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from .contracts.historical_intake import historical_date
from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .contracts.trading_continuity_intake import (
    ContinuityIntakeRequest, ContinuityIntakeExport, ContinuityCoverageReview,
    CONTINUITY_INTAKE_EXPORT_VERSION, CONTINUITY_LIMITATIONS, CORPORATE_ACTION_URL,
)
from .contracts.trading_research import TradingResearchDataset, research_symbol
from .contracts.trading_shadow_research import PriceContinuitySource, PriceContinuityEvidence
from .hashing import sha256_bytes
from .trading_historical_intake import parse_historical_json, validate_historical_dataset

METHOD_VERSION = "blackpod.native_corporate_action_continuity_projection.v1"
REQUEST_PATH = "continuity-intake/request.v1.json"
SOURCE_PATH = "continuity-intake/source.v1.json"
REVIEW_PATH = "continuity-intake/review.v1.json"

# Field names and optional dates follow the vendor's public alpaca-py models.
# Corporate action type is injected by the SDK, not a native response field.
_SCHEMAS = {
    "forward_splits": ({"symbol", "cusip", "new_rate", "old_rate", "ex_date"}, {"record_date", "payable_date", "due_bill_redemption_date"}, "SPLIT", "ex_date"),
    "reverse_splits": ({"symbol", "old_cusip", "new_cusip", "new_rate", "old_rate", "ex_date"}, {"record_date", "payable_date"}, "SPLIT", "ex_date"),
    "unit_splits": ({"old_symbol", "old_cusip", "old_rate", "new_symbol", "new_cusip", "new_rate", "alternate_symbol", "alternate_cusip", "alternate_rate", "effective_date"}, {"payable_date"}, "SPLIT", "effective_date"),
    "cash_dividends": ({"symbol", "cusip", "rate", "special", "foreign", "ex_date"}, {"record_date", "payable_date", "due_bill_on_date", "due_bill_off_date"}, "CASH_DISTRIBUTION", "ex_date"),
    "stock_dividends": ({"symbol", "cusip", "rate", "ex_date"}, {"record_date", "payable_date"}, "STOCK_DISTRIBUTION", "ex_date"),
    "spin_offs": ({"source_symbol", "source_cusip", "source_rate", "new_symbol", "new_cusip", "new_rate", "ex_date"}, {"record_date", "payable_date", "due_bill_redemption_date"}, "STOCK_DISTRIBUTION", "ex_date"),
    "cash_mergers": ({"acquiree_symbol", "acquiree_cusip", "rate", "effective_date"}, {"acquirer_symbol", "acquirer_cusip", "payable_date"}, "MERGER", "effective_date"),
    "stock_mergers": ({"acquirer_symbol", "acquirer_cusip", "acquirer_rate", "acquiree_symbol", "acquiree_cusip", "acquiree_rate", "effective_date"}, {"payable_date"}, "MERGER", "effective_date"),
    "stock_and_cash_mergers": ({"acquirer_symbol", "acquirer_cusip", "acquirer_rate", "acquiree_symbol", "acquiree_cusip", "acquiree_rate", "cash_rate", "effective_date"}, {"payable_date"}, "MERGER", "effective_date"),
    "redemptions": ({"symbol", "cusip", "rate"}, {"payable_date"}, "OTHER_PRICE_DISCONTINUITY", None),
    "name_changes": ({"old_symbol", "old_cusip", "new_symbol", "new_cusip"}, set(), "SYMBOL_CHANGE", None),
    "worthless_removals": ({"symbol", "cusip"}, set(), "OTHER_PRICE_DISCONTINUITY", None),
    "rights_distributions": ({"source_symbol", "source_cusip", "new_symbol", "new_cusip", "rate", "ex_date"}, {"payable_date", "record_date", "expiration_date"}, "STOCK_DISTRIBUTION", "ex_date"),
}


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ContractValidationError("continuity evidence differs in hash or size")
    return raw


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _action(group, row, query, universe):
    required, optional, kind, effective_field = _SCHEMAS[group]
    required = required | {"id", "process_date"}
    if not isinstance(row, dict) or not required <= set(row) <= required | optional:
        raise ContractValidationError("unsupported native corporate-action fields for " + group)
    try:
        if not isinstance(row["id"], str) or str(UUID(row["id"])) != row["id"]:
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise ContractValidationError("native corporate-action id must preserve canonical UUID") from exc
    process_date = historical_date(row["process_date"], "process_date")
    if not query["start"] <= process_date <= query["end"]:
        raise ContractValidationError("native process date lies outside its retained query")
    symbols = []
    for field, value in row.items():
        if field in {"id", "process_date"}:
            continue
        if value is None and field in optional:
            continue
        if field.endswith("date"):
            historical_date(value, field)
        elif field == "symbol" or field.endswith("_symbol"):
            symbols.append(research_symbol(value))
        elif field.endswith("cusip"):
            if not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise ContractValidationError("native CUSIP must be an explicit bounded string")
        elif field in {"special", "foreign"}:
            if type(value) is not bool:
                raise ContractValidationError("native dividend flags must be booleans")
        elif field == "rate" or field.endswith("_rate"):
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ContractValidationError("native action rate must be a finite nonnegative raw number")
            if kind == "SPLIT" and value <= 0:
                raise ContractValidationError("native split ratio must be positive")
    symbols = sorted(set(symbols))
    if not set(symbols) & set(universe):
        raise ContractValidationError("native action does not concern the requested universe")
    return {"native_id": row["id"], "native_type": group, "process_date": process_date,
        "effective_date": row[effective_field] if effective_field else None,
        "effective_date_basis": "EX_DATE" if effective_field == "ex_date" else "EFFECTIVE_DATE" if effective_field else "UNKNOWN",
        "affected_symbols": symbols}, kind


def _pages(request, blobs, recorded):
    from .contracts.trading_evidence_capture import CaptureReceipt
    actions, seen_ids, prior_token, seen_tokens = [], set(), None, set()
    unavailable, complete, prior_capture = False, False, None
    for index, page in enumerate(request.pages):
        response = _blob(blobs, page["response_evidence"])
        receipt = CaptureReceipt.from_bytes(_blob(blobs, page["capture_receipt_evidence"]))
        if receipt.url != CORPORATE_ACTION_URL or receipt.body_sha256 != page["response_evidence"]["sha256"] or receipt.size_bytes != len(response):
            raise ContractValidationError("corporate-action GET receipt must bind exact native endpoint and bytes")
        capture = parse_rfc3339(receipt.captured_at, "capture clock")
        if capture > recorded or (prior_capture is not None and capture < prior_capture):
            raise ContractValidationError("corporate-action capture clocks must be ordered and precede recording")
        prior_capture = capture
        expected = {"symbols": ",".join(request.universe), "start": request.process_date_range["start"],
            "end": request.process_date_range["end"], "limit": 1000, "sort": "asc"}
        if index:
            if prior_token is None:
                raise ContractValidationError("no additional corporate-action page is authorized by preceding response")
            expected["page_token"] = prior_token
        if receipt.query != expected or type(receipt.query.get("limit")) is not int:
            raise ContractValidationError("corporate-action query must preserve universe, process interval, all types and token chain")
        if receipt.status != 200:
            if index != len(request.pages) - 1:
                raise ContractValidationError("unavailable corporate-action capture must end the retained sequence")
            unavailable = True
            break
        source = parse_historical_json(response)
        if not isinstance(source, dict) or set(source) != {"corporate_actions", "next_page_token"}:
            raise ContractValidationError("native corporate-action response requires exact grouped actions and token")
        groups = source["corporate_actions"]
        if not isinstance(groups, dict) or not set(groups) <= set(_SCHEMAS):
            raise ContractValidationError("unknown native corporate-action group")
        page_actions = []
        for group, rows in groups.items():
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ContractValidationError("native corporate-action groups must be bounded arrays")
            for row in rows:
                action, kind = _action(group, row, expected, request.universe)
                if action["native_id"] in seen_ids:
                    raise ContractValidationError("duplicate native corporate-action identity across retained pages")
                seen_ids.add(action["native_id"])
                page_actions.append((action, kind))
        if len(page_actions) > 1000 or len(actions) + len(page_actions) > 10000:
            raise ContractValidationError("corporate-action total pagination count exceeds supported limit")
        # The native response groups by type and symbol (observed QQQ then SPY),
        # so ascending request sort does not imply a globally ascending array.
        # Do not infer pagination completeness from row order or date extrema.
        actions.extend(page_actions)
        token = source["next_page_token"]
        if token is not None:
            if not isinstance(token, str) or not 1 <= len(token) <= 4096 or token in seen_tokens:
                raise ContractValidationError("native pagination token must be bounded and never repeat")
            seen_tokens.add(token)
        prior_token, complete = token, token is None
    return actions, unavailable, complete and not unavailable


def build_continuity_intake(request, blobs):
    request = request if isinstance(request, ContinuityIntakeRequest) else ContinuityIntakeRequest.from_mapping(request)
    declared_refs = [request.dataset_evidence] + [ref for page in request.pages for ref in page.values()]
    if request.coverage_review_evidence is not None:
        declared_refs.append(request.coverage_review_evidence)
    if sum(ref["size_bytes"] for ref in declared_refs) > 64 * 1024 * 1024:
        raise ContractValidationError("continuity intake exceeds its combined retained evidence byte limit")
    recorded = parse_rfc3339(request.recorded_at, "recorded_at")
    dataset = TradingResearchDataset.from_bytes(_blob(blobs, request.dataset_evidence))
    if dataset.schema_version != "blackpod.trading_research_dataset.v2" or dataset.universe != request.universe:
        raise ContractValidationError("continuity intake requires the exact governed dataset v2 and universe")
    if parse_rfc3339(dataset.recorded_at, "dataset recorded_at") > recorded:
        raise ContractValidationError("continuity intake cannot predate retained dataset")
    material = validate_historical_dataset(dataset, blobs)
    fixture = request.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
    if fixture and (not all(symbol.startswith("SYNTH") for symbol in dataset.universe)
                    or material["request"].availability_assumption["declared_by"] != "synthetic-fixture-author"):
        raise ContractValidationError("synthetic continuity scope requires a controlled declared fictional dataset")
    evidence = dict(material["evidence"])
    dates = [parse_rfc3339(session["open_at"], "session open").astimezone(ZoneInfo("America/New_York")).date().isoformat() for session in dataset.sessions]
    if not request.process_date_range["start"] <= dates[0] <= dates[-1] <= request.process_date_range["end"]:
        raise ContractValidationError("process-date request must at least surround the entire dataset interval")
    refs = [ref for page in request.pages for ref in page.values()]
    covered = False
    if request.coverage_review_evidence is not None:
        coverage = ContinuityCoverageReview.from_bytes(_blob(blobs, request.coverage_review_evidence))
        if coverage.dataset_evidence != request.dataset_evidence or coverage.universe != dataset.universe or (
                coverage.coverage_start_session_id, coverage.coverage_end_session_id) != (
                    dataset.sessions[0]["session_id"], dataset.sessions[-1]["session_id"]):
            raise ContractValidationError("coverage review must bind the exact dataset, whole universe and entire session span")
        if not parse_rfc3339(dataset.recorded_at, "dataset clock") <= parse_rfc3339(coverage.recorded_at, "coverage clock") <= recorded:
            raise ContractValidationError("coverage review clock must lie between dataset and intake")
        forbidden = {ref["sha256"] for ref in refs} | {request.dataset_evidence["sha256"], request.coverage_review_evidence["sha256"]}
        if any(ref["sha256"] in forbidden for ref in coverage.source_evidence):
            raise ContractValidationError("coverage source evidence must be independent of process-filter responses and declarations")
        refs += [request.coverage_review_evidence] + coverage.source_evidence
        covered = coverage.status == "SUPPORTED"
    if len(refs) > 126 or sum(ref["size_bytes"] for ref in refs) + sum(map(len, evidence.values())) > 64 * 1024 * 1024:
        raise ContractValidationError("continuity origin closure exceeds its retained file or combined byte limit")
    native, unavailable, complete = _pages(request, blobs, recorded)
    audits, events = [], []
    for action, kind in native:
        day = action["effective_date"]
        if day is None:
            disposition, session_id = "UNKNOWN_EFFECTIVE_DATE", dataset.sessions[0]["session_id"]
        elif day < dates[0]:
            disposition, session_id = "BEFORE_DATASET", None
        elif day > dates[-1]:
            disposition, session_id = "AFTER_DATASET", None
        else:
            index = next(index for index, date in enumerate(dates) if date >= day)
            disposition, session_id = "IN_DATASET", dataset.sessions[index]["session_id"]
        audits.append({**action, "dataset_disposition": disposition, "mapped_session_id": session_id})
        if session_id is not None and not unavailable:
            for symbol in sorted(set(action["affected_symbols"]) & set(dataset.universe)):
                events.append({"event_id": "alpaca-action-" + action["native_id"] + "-" + symbol,
                    "symbol": symbol, "effective_session_id": session_id, "kind": kind})
    audits.sort(key=lambda row: row["native_id"]); events.sort(key=lambda row: row["event_id"])
    request_raw = request.to_bytes(); request_ref = _reference(REQUEST_PATH, request_raw)
    refs = [request_ref] + refs
    all_refs = refs + [request.dataset_evidence]
    if len({ref["path"] for ref in all_refs}) != len(all_refs) or any(ref["path"] in {SOURCE_PATH, REVIEW_PATH} for ref in all_refs):
        raise ContractValidationError("continuity source paths collide with reserved derived evidence")
    for ref in all_refs:
        raw = request_raw if ref == request_ref else _blob(blobs, ref)
        if ref["path"] in evidence and evidence[ref["path"]] != raw:
            raise ContractValidationError("continuity evidence path binds conflicting bytes")
        evidence[ref["path"]] = raw
    intake_id = "continuity-intake-" + sha256_bytes(request_raw)
    coverage_complete = covered and complete and not unavailable
    span = {"coverage_start_session_id": dataset.sessions[0]["session_id"], "coverage_end_session_id": dataset.sessions[-1]["session_id"]}
    source = PriceContinuitySource.from_mapping({"schema_version": "blackpod.trading_price_continuity_source.v1",
        "source_id": "continuity-source-" + sha256_bytes(request_raw), "recorded_at": request.recorded_at,
        "basis": "SYNTHETIC_FIXTURE" if fixture else "RETAINED_REVIEW_SOURCE", "dataset_evidence": request.dataset_evidence,
        "universe": dataset.universe, **span, "coverage_complete": coverage_complete,
        "origin_evidence": refs, "limitations": list(CONTINUITY_LIMITATIONS),
        "events": events, "price_policy": "RAW_NO_SPLITS_DISTRIBUTIONS_OR_SYMBOL_CHANGES",
        "auto_trading_enabled": False, "authority": request.authority})
    source_raw = source.to_bytes(); source_ref = _reference(SOURCE_PATH, source_raw)
    review = PriceContinuityEvidence.from_mapping({"schema_version": "blackpod.price_continuity_evidence.v1",
        "evidence_id": "continuity-review-" + sha256_bytes(request_raw), "recorded_at": request.recorded_at,
        "dataset_evidence": request.dataset_evidence, "universe": dataset.universe, **span,
        "basis": "SYNTHETIC_FIXTURE" if fixture else "RETAINED_CORPORATE_ACTION_REVIEW", "status": "CONTINUITY_SUPPORTED" if coverage_complete and not events else "UNRESOLVED",
        "source_evidence": [source_ref], "reviewer_id": request.reviewer_id, "review_notes": request.review_notes,
        "limitations": list(CONTINUITY_LIMITATIONS), "auto_trading_enabled": False, "authority": request.authority})
    review_raw = review.to_bytes(); review_ref = _reference(REVIEW_PATH, review_raw)
    export = ContinuityIntakeExport.from_mapping({"schema_version": CONTINUITY_INTAKE_EXPORT_VERSION,
        "intake_id": intake_id, "recorded_at": request.recorded_at,
        "evidence_scope": request.evidence_scope,
        "status": "UNAVAILABLE" if unavailable else "AVAILABLE" if complete else "INCOMPLETE",
        "request_evidence": request_ref, "dataset_evidence": request.dataset_evidence, "source_evidence": all_refs,
        "price_continuity_source_evidence": source_ref, "price_continuity_review_evidence": review_ref,
        "pagination_complete": complete, "coverage_review_supported": covered, "native_actions": audits,
        "derived_event_count": len(events), "limitations": list(CONTINUITY_LIMITATIONS),
        "auto_trading_enabled": False, "authority": request.authority})
    evidence[SOURCE_PATH], evidence[REVIEW_PATH] = source_raw, review_raw
    return {"export": export, "source": source, "review": review, "request": request, "dataset": dataset,
        "evidence": evidence, "blobs": {sha256_bytes(raw): raw for raw in evidence.values()}}


def verify_continuity_intake(export, blobs):
    export = export if isinstance(export, ContinuityIntakeExport) else ContinuityIntakeExport.from_mapping(export)
    request = ContinuityIntakeRequest.from_bytes(_blob(blobs, export.request_evidence))
    material = build_continuity_intake(request, blobs)
    if material["export"].to_bytes() != export.to_bytes():
        raise ContractValidationError("continuity export differs from deterministic source reconstruction")
    for field in ("price_continuity_source_evidence", "price_continuity_review_evidence"):
        ref = export.to_dict()[field]
        if _blob(blobs, ref) != material["evidence"][ref["path"]]:
            raise ContractValidationError("derived continuity evidence differs from native replay")
    return material


def verify_continuity_review(review, blobs):
    """Verify native adapter semantics when a gate receives only the review."""
    review = review if isinstance(review, PriceContinuityEvidence) else PriceContinuityEvidence.from_mapping(review)
    if len(review.source_evidence) != 1:
        raise ContractValidationError("native continuity review must retain its one derived source")
    source = PriceContinuitySource.from_bytes(_blob(blobs, review.source_evidence[0]))
    # Support bytes remain opaque. A .json suffix does not establish an object
    # schema (independent coverage evidence may legitimately be a JSON array).
    # The adapter itself reserves the exact request path, so only that document
    # is interpreted; the full rebuild below retains and verifies every origin.
    candidates = [ref for ref in source.origin_evidence if ref["path"] == REQUEST_PATH]
    if len(candidates) != 1:
        raise ContractValidationError("native continuity review requires one exact retained intake request")
    request = ContinuityIntakeRequest.from_bytes(_blob(blobs, candidates[0]))
    material = build_continuity_intake(request, blobs)
    if material["review"].to_bytes() != review.to_bytes() or material["source"].to_bytes() != source.to_bytes():
        raise ContractValidationError("continuity gate differs from deterministic native source reconstruction")
    return material
