"""Pure projection of native retained quotes and explicit cost assumptions.

The adapter makes no provider requests. It requires a complete forward page
chain, measures only regular quotes in each session's opening minute, and
never estimates slippage or fees from prices or historical profits.
"""
from decimal import Context, Decimal, ROUND_CEILING, localcontext
from bisect import bisect_right
import re

from .contracts.trading_cost_intake import (
    COST_INTAKE_EXPORT_VERSION, COST_INTAKE_LIMITATIONS, COST_INTAKE_METHOD_VERSION,
    CostAssumptionReview, CostIntakeRequest,
)
from .contracts.mission_request import ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_research import TradingResearchDataset
from .contracts.trading_shadow_research import TradingCostEvidence, TradingCostSource
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_historical_intake import parse_historical_json, validate_historical_dataset

QUOTES_URL = "https://data.alpaca.markets/v2/stocks/quotes"
_STAMP = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})$")
_QUANTUM = Decimal("0.000000000000000001")
_MAX_BYTES = 64 * 1024 * 1024


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ContractValidationError("cost intake evidence differs in hash or size")
    return raw


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retain(evidence, ref, blobs):
    raw = _blob(blobs, ref)
    if ref["path"] in evidence and evidence[ref["path"]] != raw:
        raise ContractValidationError("cost evidence paths bind conflicting retained bytes")
    evidence[ref["path"]] = raw
    if len(evidence) > 256 or sum(map(len, evidence.values())) > _MAX_BYTES:
        raise ContractValidationError("cost intake exceeds bounded retained evidence limits")
    return raw


def _nanos(stamp, name):
    """Compare timestamp nanoseconds without truncating the retained spelling."""
    match = _STAMP.fullmatch(stamp) if isinstance(stamp, str) else None
    if match is None:
        raise ContractValidationError(name + " must be explicit RFC3339 with at most nine fractional digits")
    whole = parse_rfc3339(match.group(1) + match.group(3), name)
    from datetime import datetime, timezone
    elapsed = whole - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000_000 + int((match.group(2) or "").ljust(9, "0") or "0")


def _number(value, name, *, integer=False):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0 or value > Decimal("1e20"):
        raise ContractValidationError(name + " must be an actual nonnegative bounded native JSON number")
    if integer and value != value.to_integral_value():
        raise ContractValidationError(name + " must be an actual whole native quote size")
    return value


def _query(value, universe):
    required = {"symbols", "start", "end", "limit", "feed", "currency", "sort", "asof"}
    if not isinstance(value, dict) or set(value) not in (required, required | {"page_token"}):
        raise ContractValidationError("quote query requires explicit symbols/window/feed/currency/sort/asof/limit")
    if value["symbols"] != ",".join(universe) or value["feed"] != "iex" or value["currency"] != "USD" or value["sort"] != "asc" or value["asof"] != "-":
        raise ContractValidationError("quote query must bind sorted dataset symbols, IEX, USD, ascending order and no symbol mapping")
    if type(value["limit"]) is not int or not 1 <= value["limit"] <= 10000:
        raise ContractValidationError("quote page limit must be an actual integer in [1,10000]")
    start, end = _nanos(value["start"], "query.start"), _nanos(value["end"], "query.end")
    if start > end:
        raise ContractValidationError("quote query window must be ordered")
    if "page_token" in value and (not isinstance(value["page_token"], str) or not 1 <= len(value["page_token"]) <= 2048):
        raise ContractValidationError("quote page_token must be a bounded opaque native string")
    return start, end


def _capture(raw):
    from .contracts.trading_evidence_capture import validate_capture_receipt
    return validate_capture_receipt(parse_strict_json_object_bytes(raw))


def build_cost_intake(request, blobs):
    """Rebuild every declaration from its retained source and exact dataset.

An incomplete chain/window or unavailable response is a recorded deferral.
Malformed/native schema mismatches, changed hashes and inconsistent clocks
reject the intake. Optional missing assumptions never become zero cost.
"""
    request = request if isinstance(request, CostIntakeRequest) else CostIntakeRequest.from_mapping(request)
    recorded = parse_rfc3339(request.recorded_at, "recorded_at")
    dataset = TradingResearchDataset.from_bytes(_blob(blobs, request.dataset_evidence))
    history = validate_historical_dataset(dataset, blobs)
    fixture = request.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
    if fixture and (not all(symbol.startswith("SYNTH") for symbol in dataset.universe)
                    or history["request"].availability_assumption["declared_by"] != "synthetic-fixture-author"):
        raise ContractValidationError("synthetic cost scope requires explicit fictional-symbol source intake")
    if parse_rfc3339(dataset.recorded_at, "dataset clock") > recorded:
        raise ContractValidationError("cost intake cannot predate its governed dataset capture")
    evidence = dict(history["evidence"])
    _retain(evidence, request.dataset_evidence, blobs)
    ids = [row["session_id"] for row in dataset.sessions]
    windows = [(row["session_id"], _nanos(row["open_at"], "session.open_at")) for row in dataset.sessions]
    window_opens = [item[1] for item in windows]
    coverage = {(symbol, identity): 0 for symbol in dataset.universe for identity in ids}
    bounds, summaries = {}, {}
    reasons, successful, unavailable, total_rows, included_rows = [], 0, 0, 0, 0
    query_base, next_token, previous_pair, seen_tokens = None, None, None, set()
    same_stamp_signatures = set()
    request_raw = request.to_bytes()
    request_ref = _reference("cost-intake/request.v1.json", request_raw)
    origin_refs = [request_ref]
    for index, page in enumerate(request.quote_pages):
        body_ref, receipt_ref = page["body_evidence"], page["receipt_evidence"]
        raw = _retain(evidence, body_ref, blobs)
        receipt = _capture(_retain(evidence, receipt_ref, blobs))
        if receipt["url"] != QUOTES_URL or receipt["method"] != "GET":
            raise ContractValidationError("quote receipt must bind the historical quotes GET endpoint")
        if receipt["body_sha256"] != body_ref["sha256"] or receipt["size_bytes"] != body_ref["size_bytes"]:
            raise ContractValidationError("quote receipt must bind the exact retained response body")
        captured = parse_rfc3339(receipt["captured_at"], "captured_at")
        if not parse_rfc3339(dataset.recorded_at, "dataset clock") <= captured <= recorded:
            raise ContractValidationError("quote capture must be between dataset capture and intake recording")
        start, end = _query(receipt["query"], dataset.universe)
        if end > _nanos(receipt["captured_at"], "captured_at"):
            raise ContractValidationError("quote query cannot end after capture")
        base = {field: value for field, value in receipt["query"].items() if field != "page_token"}
        if index == 0:
            if "page_token" in receipt["query"]:
                raise ContractValidationError("quote chain must begin with an unpaginated original request")
            query_base = base
        elif base != query_base or next_token is None or receipt["query"].get("page_token") != next_token:
            raise ContractValidationError("quote pages must follow the exact native next_page_token and original query")
        origin_refs.extend((body_ref, receipt_ref))
        if receipt["status"] != 200:
            unavailable += 1
            reasons.append("QUOTE_RESPONSE_UNAVAILABLE")
            if index != len(request.quote_pages) - 1:
                raise ContractValidationError("unavailable quote page cannot be followed by an invented continuation")
            continue
        successful += 1
        response = parse_historical_json(raw)
        if not isinstance(response, dict) or set(response) != {"quotes", "next_page_token"} or not isinstance(response["quotes"], dict):
            raise ContractValidationError("native quote response requires exact quotes and pagination fields")
        if any(symbol not in dataset.universe for symbol in response["quotes"]):
            raise ContractValidationError("native quote response contains an undeclared symbol")
        token = response["next_page_token"]
        if token is not None and (not isinstance(token, str) or not 1 <= len(token) <= 2048 or token in seen_tokens):
            raise ContractValidationError("native pagination tokens must be bounded and noncyclic")
        if token is not None:
            seen_tokens.add(token)
        next_token = token
        page_count = 0
        for symbol in sorted(response["quotes"]):
            quotes = response["quotes"][symbol]
            if not isinstance(quotes, list):
                raise ContractValidationError("native quotes by symbol must be an actual list")
            for row in quotes:
                page_count += 1
                total_rows += 1
                if total_rows > 200000:
                    raise ContractValidationError("quote intake exceeds its bounded native row count")
                if not isinstance(row, dict) or set(row) != {"t", "bp", "bs", "bx", "ap", "as", "ax", "c", "z"}:
                    raise ContractValidationError("native quote row must preserve exact bid/ask/size/exchange/condition/timestamp fields")
                if not isinstance(row["z"], str) or row["z"] not in {"A", "B", "C"}:
                    raise ContractValidationError("native quote tape must be an explicit A, B or C code")
                stamp = _nanos(row["t"], "quote.t")
                if not start <= stamp <= end:
                    raise ContractValidationError("native quote timestamp is outside its retained request window")
                pair = (symbol, stamp)
                if previous_pair is not None and pair < previous_pair:
                    raise ContractValidationError("quotes must be nondecreasing by symbol and exact nanosecond timestamp")
                if pair != previous_pair:
                    same_stamp_signatures.clear()
                for field in ("bx", "ax"):
                    if not isinstance(row[field], str) or not 1 <= len(row[field]) <= 16 or row[field].strip() != row[field]:
                        raise ContractValidationError("quote exchange codes must be explicit bounded native strings")
                conditions = row["c"]
                if not isinstance(conditions, list) or len(conditions) > 16 or any(not isinstance(item, str) or not 1 <= len(item) <= 16 or item.strip() != item for item in conditions) or len(set(conditions)) != len(conditions):
                    raise ContractValidationError("quote conditions must be distinct explicit bounded native strings")
                bid, ask = _number(row["bp"], "quote.bp"), _number(row["ap"], "quote.ap")
                bid_size, ask_size = _number(row["bs"], "quote.bs", integer=True), _number(row["as"], "quote.as", integer=True)
                # Several native updates can share an exchange timestamp.
                # Preserve every distinct update, including across pages; only
                # identical observations within that ordered timestamp group
                # are duplicate evidence. Do not deduplicate them silently.
                signature = (bid, ask, bid_size, ask_size, row["bx"], row["ax"], tuple(conditions), row["z"])
                if signature in same_stamp_signatures:
                    raise ContractValidationError("native quote chain contains an identical duplicate observation")
                same_stamp_signatures.add(signature)
                previous_pair = pair
                window_index = bisect_right(window_opens, stamp) - 1
                if (window_index < 0 or stamp > windows[window_index][1] + 60_000_000_000
                        or bid <= 0 or ask <= 0 or ask < bid or bid_size <= 0 or ask_size <= 0 or conditions != ["R"]):
                    continue
                identity = windows[window_index][0]
                coverage[(symbol, identity)] += 1
                included_rows += 1
                with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                    spread = ((ask - bid) * Decimal("20000") / (ask + bid)).quantize(_QUANTUM, rounding=ROUND_CEILING)
                bounds[symbol] = max(bounds.get(symbol, Decimal(0)), spread)
                summary = summaries.setdefault(symbol, {"eligible_quote_count": 0, "first_native_timestamp": row["t"], "last_native_timestamp": row["t"]})
                summary["eligible_quote_count"] += 1
                summary["last_native_timestamp"] = row["t"]
        if page_count > receipt["query"]["limit"]:
            raise ContractValidationError("native quote page exceeds its retained total-symbol limit")
    if next_token is not None:
        reasons.append("QUOTE_PAGINATION_INCOMPLETE")
    missing = [{"symbol": symbol, "session_id": identity} for (symbol, identity), count in sorted(coverage.items()) if not count]
    if missing:
        reasons.append("OPENING_MINUTE_COVERAGE_INCOMPLETE")
    assumptions = None
    if request.assumption_review_evidence is None:
        reasons.append("EXPLICIT_COST_ASSUMPTIONS_MISSING")
    else:
        ref = request.assumption_review_evidence
        assumptions = CostAssumptionReview.from_bytes(_retain(evidence, ref, blobs))
        if assumptions.dataset_evidence != request.dataset_evidence or assumptions.universe != dataset.universe:
            raise ContractValidationError("cost assumptions must bind the exact governed dataset and entire universe")
        if assumptions.evidence_scope != request.evidence_scope:
            raise ContractValidationError("cost assumptions scope must match the governed intake scope")
        if (assumptions.coverage_start_session_id, assumptions.coverage_end_session_id) != (ids[0], ids[-1]):
            raise ContractValidationError("cost assumptions must declare full dataset session coverage")
        if not parse_rfc3339(dataset.recorded_at, "dataset clock") <= parse_rfc3339(assumptions.recorded_at, "assumption clock") <= recorded:
            raise ContractValidationError("cost assumption clock must be between dataset capture and intake recording")
        for origin in assumptions.origin_evidence:
            if origin["path"] in {ref["path"], request_ref["path"]}:
                raise ContractValidationError("assumption origins cannot reference their own review or intake request")
            _retain(evidence, origin, blobs)
        origin_refs.append(ref)
        origin_refs.extend(assumptions.origin_evidence)
        if assumptions.status != "REVIEWED_SHADOW_ASSUMPTIONS" or assumptions.parameters is None:
            reasons.append("EXPLICIT_COST_ASSUMPTIONS_UNRESOLVED")
    if any(bound > Decimal("1000") for bound in bounds.values()):
        reasons.append("SPREAD_BOUND_EXCEEDS_SUPPORTED_MODEL_RANGE")
    complete = not missing and unavailable == 0 and next_token is None
    eligible = complete and not reasons
    if request_ref["path"] in evidence and evidence[request_ref["path"]] != request_raw:
        raise ContractValidationError("source collides with reserved cost request path")
    evidence[request_ref["path"]] = request_raw
    origins = []
    for ref in origin_refs:
        if ref["path"] not in {item["path"] for item in origins}:
            origins.append(ref)
    if len(origins) > 128:
        raise ContractValidationError("cost source closure exceeds legacy source-reference limit")
    identity = "cost-intake-" + sha256_bytes(request_raw)
    source, cost_model = None, None
    if eligible:
        observations = [{"symbol": symbol, "spread_bps": format(bounds[symbol], "f"), **assumptions.parameters} for symbol in dataset.universe]
        cost_model = {"spread_bps": format(max(bounds.values()), "f"), **assumptions.parameters}
        source = TradingCostSource.from_mapping({"schema_version": "blackpod.trading_cost_source.v1", "source_id": identity,
            "recorded_at": request.recorded_at, "basis": "SYNTHETIC_FIXTURE" if fixture else "RETAINED_REVIEW_SOURCE", "dataset_evidence": request.dataset_evidence,
            "universe": dataset.universe, "coverage_start_session_id": ids[0], "coverage_end_session_id": ids[-1],
            "coverage_complete": True, "origin_evidence": origins, "observations": observations,
            "sampling_policy": "DECLARED_REVIEW_BOUNDS_NOT_EXECUTABLE_QUOTES", "limitations": list(COST_INTAKE_LIMITATIONS),
            "auto_trading_enabled": False, "authority": request.authority})
        source_raw = source.to_bytes()
        source_ref = _reference("cost-intake/source.v1.json", source_raw)
        if source_ref["path"] in evidence:
            raise ContractValidationError("source collides with reserved derived cost source path")
        evidence[source_ref["path"]] = source_raw
        review_refs = [source_ref]
    else:
        # This direct request reference records an unresolved review; it cannot
        # be consumed as a legacy source or falsely claim invented zero bounds.
        source_ref, review_refs = None, [request_ref]
    review = TradingCostEvidence.from_mapping({"schema_version": "blackpod.trading_cost_evidence.v1", "evidence_id": identity + "-review",
        "recorded_at": request.recorded_at, "dataset_evidence": request.dataset_evidence, "coverage_start_session_id": ids[0],
        "coverage_end_session_id": ids[-1], "universe": dataset.universe, "basis": "SYNTHETIC_FIXTURE" if fixture else "RETAINED_COST_REVIEW",
        "status": "SUPPORTED" if eligible else "UNRESOLVED", "source_evidence": review_refs,
        "reviewer_id": request.reviewer_id, "review_notes": request.review_notes,
        "limitations": list(COST_INTAKE_LIMITATIONS), "cost_model": cost_model, "auto_trading_enabled": False, "authority": request.authority})
    review_raw = review.to_bytes()
    review_ref = _reference("cost-intake/review.v1.json", review_raw)
    if review_ref["path"] in evidence:
        raise ContractValidationError("source collides with reserved cost review path")
    evidence[review_ref["path"]] = review_raw
    assessment = {"status": "SUPPORTED" if eligible else ("UNAVAILABLE" if unavailable and not successful else "UNRESOLVED"),
        "eligible": eligible, "reason_codes": sorted(set(reasons)), "opening_minute_coverage_complete": complete,
        "missing_symbol_sessions": missing, "native_quote_count": total_rows, "eligible_opening_quote_count": included_rows,
        "measurements": [{"symbol": symbol, "spread_bps_upper_bound": format(bounds[symbol], "f") if symbol in bounds else None,
                          **summaries.get(symbol, {"eligible_quote_count": 0, "first_native_timestamp": None, "last_native_timestamp": None})} for symbol in dataset.universe],
        "quote_admission_policy": "POSITIVE_BID_ASK_SIZE_NONCROSSED_REGULAR_R_CONDITION_OPEN_THROUGH_OPEN_PLUS_60_SECONDS",
        "cost_assumption_semantics": "EXPLICIT_LOCAL_REVIEW_NOT_OBSERVED_FEES_OR_SLIPPAGE",
        "provider_authenticity_verified": False, "historical_point_in_time_verified": False}
    export = {"schema_version": COST_INTAKE_EXPORT_VERSION, "intake_id": identity, "method_version": COST_INTAKE_METHOD_VERSION,
        "request_evidence": request_ref, "dataset_evidence": request.dataset_evidence, "source_evidence": source_ref,
        "review_evidence": review_ref, "assessment": assessment, "limitations": list(COST_INTAKE_LIMITATIONS),
        "auto_trading_enabled": False, "authority": request.authority}
    export_raw = canonical_json_bytes(export)
    if "cost-intake/export.v1.json" in evidence:
        raise ContractValidationError("source collides with reserved cost export path")
    evidence["cost-intake/export.v1.json"] = export_raw
    if sum(map(len, evidence.values())) > _MAX_BYTES:
        raise ContractValidationError("derived cost intake exceeds retained byte bounds")
    return {"request": request, "export": export, "source": source, "review": review, "assessment": assessment,
            "evidence": evidence, "blobs": {sha256_bytes(raw): raw for raw in evidence.values()}}


def verify_cost_intake(export, blobs):
    """Verify exact replay, including measurements and unresolved dispositions."""
    if not isinstance(export, dict) or set(export) != {"schema_version", "intake_id", "method_version", "request_evidence", "dataset_evidence", "source_evidence", "review_evidence", "assessment", "limitations", "auto_trading_enabled", "authority"}:
        raise ContractValidationError("cost export requires its exact versioned fields")
    from .contracts.trading_reconciliation import evidence_reference
    request_ref = evidence_reference(export["request_evidence"], "request_evidence")
    review_ref = evidence_reference(export["review_evidence"], "review_evidence")
    evidence_reference(export["dataset_evidence"], "dataset_evidence")
    source_ref = evidence_reference(export["source_evidence"], "source_evidence") if export["source_evidence"] is not None else None
    request = CostIntakeRequest.from_bytes(_blob(blobs, request_ref))
    replay = build_cost_intake(request, blobs)
    if canonical_json_bytes(replay["export"]) != canonical_json_bytes(export):
        raise ContractValidationError("cost export differs from deterministic retained-source replay")
    if _blob(blobs, review_ref) != replay["review"].to_bytes():
        raise ContractValidationError("cost review bytes differ from native source replay")
    if source_ref is not None and _blob(blobs, source_ref) != replay["source"].to_bytes():
        raise ContractValidationError("cost source bytes differ from native source replay")
    return replay
