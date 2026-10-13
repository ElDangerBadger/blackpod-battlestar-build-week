"""Pure segmented TRAIN quote export; every raw update remains retained.

Independent returned-session requests are separate pagination chains. They are
never concatenated into the older v18 consumer, sampled, or transformed into
an execution-cost or economic-performance claim.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, localcontext

from .contracts.mission_request import ContractValidationError, format_rfc3339, parse_rfc3339
from .contracts.train_market_evidence import TrainMarketCapturePlan, _failure, _pages
from .contracts.trading_research import TradingResearchDataset, TradingResearchPlan
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_cost_intake import _capture, _nanos
from .trading_training_calibration import _native_rows

SEGMENT_VERSION = "blackpod.train_market_segment_summary.v1"
EXPORT_VERSION = "blackpod.train_market_export.v1"
METHOD_VERSION = "blackpod.segmented_train_quote_export.v1"
_QUANTUM = Decimal("0.000000000000000001")
LIMITATIONS = (
    "FULL_CAPTURE_NOT_CONTINUOUS_MARKET_COVERAGE_OR_EXECUTION_GUARANTEE",
    "OPENING_MINUTE_IEX_SAMPLE_NOT_CONSOLIDATED_OR_AUCTION_LIQUIDITY",
    "RAW_REPORTED_SIDE_SIZE_UNITS_NOT_CONVERTED_TO_EXECUTABLE_CAPACITY",
    "SPREAD_EXTREMES_RETAINED_NOT_CLIPPED_OR_DOWNSAMPLED",
    "RETAINED_GET_RECEIPTS_NOT_PROVIDER_AUTHENTICATION_OR_HISTORICAL_POINT_IN_TIME_PROOF",
    "NO_SLIPPAGE_FEE_CAPACITY_OR_ECONOMIC_RETURN_ESTIMATION",
    "SEGMENTED_INPUT_NOT_COMPATIBLE_WITH_PINNED_V18_CONSUMER",
    "FINAL_HOLDOUT_WITHHELD_AND_NOT_ACCESS_SEALED",
)


def _mapping(value):
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def _document(value, kind):
    return value if isinstance(value, kind) else kind.from_mapping(_mapping(value))


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ContractValidationError("TRAIN export source differs in hash or size")
    return raw


def _bind(ref, document):
    raw = document.to_bytes()
    if sha256_bytes(raw) != ref["sha256"] or len(raw) != ref["size_bytes"]:
        raise ContractValidationError("TRAIN export does not bind the exact original document")


def _text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _extremum(value, *, positive=False, integer=False):
    try:
        if not isinstance(value, str):
            raise ValueError()
        number = Decimal(value)
        if not number.is_finite() or number < 0 or (positive and number <= 0) or (integer and number != number.to_integral_value()):
            raise ValueError()
    except (InvalidOperation, ValueError) as exc:
        raise ContractValidationError("TRAIN extrema require exact finite nonnegative decimal strings and positive whole native sizes") from exc
    return number


def _plan_context(plan, base, dataset):
    plan = _document(plan, TrainMarketCapturePlan)
    base = _document(base, TradingResearchPlan)
    dataset = _document(dataset, TradingResearchDataset)
    _bind(plan.base_plan_evidence, base)
    _bind(plan.dataset_evidence, dataset)
    if base.schema_version != "blackpod.trading_research_plan.v2" or dataset.schema_version != "blackpod.trading_research_dataset.v2":
        raise ContractValidationError("TRAIN export requires the original governed v2 inputs")
    if base.dataset_evidence != plan.dataset_evidence or base.universe != dataset.universe:
        raise ContractValidationError("TRAIN export cannot relabel the original dataset or universe")
    created = parse_rfc3339(plan.created_at, "capture plan freeze")
    if max(parse_rfc3339(value, "original source clock") for value in (base.registered_at, dataset.recorded_at)) > created:
        raise ContractValidationError("TRAIN capture plan cannot precede its original inputs")
    fixture = plan.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
    if fixture != all(symbol.startswith("SYNTH") for symbol in dataset.universe):
        raise ContractValidationError("TRAIN export scope must preserve real versus fictional input semantics")
    folds = {fold["fold_id"]: fold for fold in base.protocol["folds"]}
    if set(plan.fold_ids) - set(folds):
        raise ContractValidationError("TRAIN capture names an unknown original fold")
    protected = set(range(base.protocol["final_holdout"]["start_index"], base.protocol["final_holdout"]["end_index"] + 1))
    for fold in folds.values():
        for role in ("validation", "test"):
            protected.update(range(fold[role]["start_index"], fold[role]["end_index"] + 1))
    expected = {(fold_id, index) for fold_id in plan.fold_ids for index in range(
        folds[fold_id]["train"]["start_index"], folds[fold_id]["train"]["end_index"] + 1)}
    actual = {(segment["fold_id"], segment["session_index"]) for segment in plan.segments}
    if expected != actual:
        raise ContractValidationError("TRAIN plan must enumerate every original selected training session without sampling")
    for segment in plan.segments:
        index = segment["session_index"]
        if index >= len(dataset.sessions) or index in protected:
            raise ContractValidationError("TRAIN capture cannot access validation, TEST or final holdout sessions")
        session = dataset.sessions[index]
        query = segment["query"]
        if (segment["session_id"] != session["session_id"] or query["symbols"] != ",".join(dataset.universe)
                or query["start"] != session["open_at"]
                or query["end"] != format_rfc3339(parse_rfc3339(session["open_at"], "returned open") + timedelta(seconds=60))):
            raise ContractValidationError("TRAIN segment must preserve the exact returned-calendar opening-minute window")
    return plan, base, dataset


def _empty_symbol(symbol):
    return {"symbol": symbol, "raw_quote_count": 0, "eligible_quote_count": 0, "rejected_quote_count": 0,
        "max_spread_bps": None, "min_reported_side_size_native_units": None,
        "first_native_timestamp": None, "last_native_timestamp": None}


def project_training_segment(plan, segment, pages, blobs, *, exported_at, failure=None):
    """Reconstruct one frozen session's complete native chain with no writes."""
    plan = _document(plan, TrainMarketCapturePlan)
    base = TradingResearchPlan.from_bytes(_blob(blobs, plan.base_plan_evidence))
    dataset = TradingResearchDataset.from_bytes(_blob(blobs, plan.dataset_evidence))
    plan, base, dataset = _plan_context(plan, base, dataset)
    segment = dict(segment)
    if segment not in plan.segments:
        raise ContractValidationError("TRAIN segment is not an exact member of its frozen capture plan")
    pages, failure = _pages(pages), _failure(failure)
    if len(pages) > plan.limits["max_pages_per_segment"]:
        raise ContractValidationError("TRAIN segment exceeds its frozen page budget")
    exported = parse_rfc3339(exported_at, "TRAIN export clock")
    created = parse_rfc3339(plan.created_at, "capture plan freeze")
    if exported < created:
        raise ContractValidationError("TRAIN export cannot precede its capture plan")
    total_bytes = sum(ref["size_bytes"] for page in pages for ref in page.values())
    if total_bytes > plan.limits["max_segment_bytes"]:
        raise ContractValidationError("TRAIN segment exceeds its frozen source-byte budget")
    last_capture = None
    for page in pages:
        if page["body_evidence"]["size_bytes"] > plan.limits["max_response_bytes"]:
            raise ContractValidationError("TRAIN response exceeds its frozen response-byte budget")
        receipt = _capture(_blob(blobs, page["receipt_evidence"]))
        capture = parse_rfc3339(receipt["captured_at"], "page capture")
        if not created <= capture <= exported or (last_capture is not None and capture < last_capture):
            raise ContractValidationError("TRAIN page captures must follow plan freeze, progress chronologically and precede export")
        query = {key: value for key, value in receipt["query"].items() if key != "page_token"}
        if query != segment["query"]:
            raise ContractValidationError("TRAIN page query must match its exact frozen segment")
        last_capture = capture
    evidence = {}
    rows, _, native_reasons = _native_rows(pages, dataset.universe, dataset, exported, evidence, blobs)
    if len(rows) > plan.limits["max_rows_per_segment"]:
        raise ContractValidationError("TRAIN segment exceeds its frozen native-row budget")
    reasons = list(native_reasons)
    if not pages:
        reasons.append("SEGMENT_NOT_STARTED" if failure is None else "NO_RETAINED_CAPTURE_RESPONSE")
    if failure is not None:
        reasons.append("DECLARED_CAPTURE_FAILURE")
    stats = {symbol: _empty_symbol(symbol) for symbol in dataset.universe}
    for row in rows:
        item = stats[row["symbol"]]
        item["raw_quote_count"] += 1
        if item["first_native_timestamp"] is None:
            item["first_native_timestamp"] = row["native_timestamp"]
        item["last_native_timestamp"] = row["native_timestamp"]
        admissible = (row["bid"] > 0 and row["ask"] > 0 and row["ask"] >= row["bid"]
            and row["bid_size"] > 0 and row["ask_size"] > 0 and row["conditions"] == ["R"])
        if not admissible:
            item["rejected_quote_count"] += 1
            continue
        with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
            spread = ((row["ask"] - row["bid"]) * Decimal("20000") / (row["ask"] + row["bid"])).quantize(_QUANTUM, rounding=ROUND_CEILING)
        size = min(row["bid_size"], row["ask_size"])
        item["max_spread_bps"] = _text(spread if item["max_spread_bps"] is None else max(Decimal(item["max_spread_bps"]), spread))
        item["min_reported_side_size_native_units"] = _text(size if item["min_reported_side_size_native_units"] is None else min(Decimal(item["min_reported_side_size_native_units"]), size))
        item["eligible_quote_count"] += 1
    missing = [symbol for symbol, item in stats.items() if not item["eligible_quote_count"]]
    if missing:
        reasons.append("TRAINING_SYMBOL_SESSION_COVERAGE_INCOMPLETE")
    capture_complete = bool(pages) and not native_reasons and failure is None
    coverage_complete = capture_complete and not missing
    summary = {"schema_version": SEGMENT_VERSION, "method_version": METHOD_VERSION,
        "capture_id": plan.capture_id, **segment, "exported_at": exported_at,
        "status": "CAPTURE_COMPLETE" if capture_complete else "CAPTURE_INCOMPLETE",
        "capture_complete": capture_complete, "coverage_complete": coverage_complete,
        "pages": pages, "page_count": len(pages), "raw_quote_count": len(rows),
        "eligible_quote_count": sum(item["eligible_quote_count"] for item in stats.values()),
        "retained_source_bytes": total_bytes, "symbols": list(stats.values()), "missing_symbols": missing,
        "reason_codes": sorted(set(reasons)), "failure": failure,
        "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "auto_trading_enabled": False, "authority": plan.authority, "limitations": list(LIMITATIONS)}
    return {"summary": summary, "evidence": evidence}


def _checked_summary(plan, segment, summary, universe):
    if (summary.get("schema_version") != SEGMENT_VERSION or summary.get("method_version") != METHOD_VERSION
            or summary.get("capture_id") != plan.capture_id):
        raise ContractValidationError("TRAIN aggregation requires verified summaries from its exact capture plan and method")
    if any(summary.get(field) != value for field, value in segment.items()):
        raise ContractValidationError("TRAIN summary changes its original segment membership or query")
    if summary.get("auto_trading_enabled") is not False or summary.get("authority") != plan.authority:
        raise ContractValidationError("TRAIN summaries cannot acquire operational authority")
    if type(summary.get("capture_complete")) is not bool or type(summary.get("coverage_complete")) is not bool:
        raise ContractValidationError("TRAIN completion declarations must be exact booleans")
    if summary.get("status") != ("CAPTURE_COMPLETE" if summary["capture_complete"] else "CAPTURE_INCOMPLETE"):
        raise ContractValidationError("TRAIN summary status and capture completion disagree")
    stats = summary.get("symbols")
    if not isinstance(stats, list) or [item.get("symbol") for item in stats] != list(universe):
        raise ContractValidationError("TRAIN summary must inventory its full original sorted universe")
    for field in ("page_count", "raw_quote_count", "eligible_quote_count", "retained_source_bytes"):
        if type(summary.get(field)) is not int or summary[field] < 0:
            raise ContractValidationError("TRAIN summary counts must be nonnegative exact integers")
    if summary["page_count"] > plan.limits["max_pages_per_segment"] or summary["raw_quote_count"] > plan.limits["max_rows_per_segment"] or summary["retained_source_bytes"] > plan.limits["max_segment_bytes"]:
        raise ContractValidationError("TRAIN summary exceeds its frozen segment limits")
    pages = _pages(summary.get("pages"))
    if len(pages) != summary["page_count"] or sum(ref["size_bytes"] for page in pages for ref in page.values()) != summary["retained_source_bytes"]:
        raise ContractValidationError("TRAIN summary counts do not bind its exact retained page references")
    for item in stats:
        for field in ("raw_quote_count", "eligible_quote_count", "rejected_quote_count"):
            if type(item.get(field)) is not int or item[field] < 0:
                raise ContractValidationError("TRAIN symbol counts must be nonnegative exact integers")
        if item["raw_quote_count"] != item["eligible_quote_count"] + item["rejected_quote_count"]:
            raise ContractValidationError("TRAIN symbol row accounting is inconsistent")
        if item["eligible_quote_count"]:
            _extremum(item.get("max_spread_bps"))
            _extremum(item.get("min_reported_side_size_native_units"), positive=True, integer=True)
        elif item.get("max_spread_bps") is not None or item.get("min_reported_side_size_native_units") is not None:
            raise ContractValidationError("missing admitted TRAIN observations cannot have invented extrema")
    if summary["raw_quote_count"] != sum(item["raw_quote_count"] for item in stats) or summary["eligible_quote_count"] != sum(item["eligible_quote_count"] for item in stats):
        raise ContractValidationError("TRAIN summary total row counts do not match its full symbol inventory")
    missing = [item["symbol"] for item in stats if not item["eligible_quote_count"]]
    if summary.get("missing_symbols") != missing or summary["coverage_complete"] != (summary["capture_complete"] and not missing):
        raise ContractValidationError("TRAIN coverage declaration cannot hide missing symbol sessions")
    if summary["capture_complete"] and not summary["page_count"]:
        raise ContractValidationError("an uncaptured TRAIN segment cannot be complete")
    return summary


def aggregate_training_segments(plan, plan_document, dataset, segment_summaries):
    """Merge verified segment summaries without duplicating their raw corpus.

    Journal callers replay every selected segment first. This aggregation
    checks identity, declared bounds and arithmetic consistency; it does not
    turn unverified arbitrary summaries into evidence or emulate v18 inputs.
    """
    plan, base, dataset = _plan_context(plan, plan_document, dataset)
    if not isinstance(segment_summaries, (list, tuple)):
        raise ContractValidationError("TRAIN summaries must be an explicit list")
    expected = {segment["segment_id"]: segment for segment in plan.segments}
    provided = {}
    for summary in segment_summaries:
        if not isinstance(summary, dict) or summary.get("segment_id") not in expected or summary["segment_id"] in provided:
            raise ContractValidationError("TRAIN summaries require unique original planned segment identities")
        provided[summary["segment_id"]] = _checked_summary(plan, expected[summary["segment_id"]], summary, dataset.universe)
    total_pages = sum(summary["page_count"] for summary in provided.values())
    total_bytes = sum(summary["retained_source_bytes"] for summary in provided.values())
    if total_pages > plan.limits["max_total_requests"] or total_bytes > plan.limits["max_capture_bytes"]:
        raise ContractValidationError("TRAIN aggregate exceeds its frozen lifetime request or source-byte budget")
    segment_rows, missing_pairs = [], []
    for segment in plan.segments:
        summary = provided.get(segment["segment_id"])
        covered = [] if summary is None or not summary["capture_complete"] else [item["symbol"] for item in summary["symbols"] if item["eligible_quote_count"]]
        for symbol in dataset.universe:
            if symbol not in covered:
                missing_pairs.append({"fold_id": segment["fold_id"], "session_index": segment["session_index"],
                    "session_id": segment["session_id"], "segment_id": segment["segment_id"], "symbol": symbol})
        segment_rows.append({**segment,
            "status": "CAPTURE_INCOMPLETE" if summary is None else summary["status"],
            "capture_complete": False if summary is None else summary["capture_complete"],
            "coverage_complete": False if summary is None else summary["coverage_complete"],
            "reason_codes": ["SEGMENT_NOT_EXPORTED"] if summary is None else summary["reason_codes"],
            "summary_sha256": None if summary is None else sha256_bytes(canonical_json_bytes(summary))})
    folds = []
    for fold_id in plan.fold_ids:
        members = [segment for segment in plan.segments if segment["fold_id"] == fold_id]
        captured = all(segment["segment_id"] in provided and provided[segment["segment_id"]]["capture_complete"] for segment in members)
        covered = captured and all(provided[segment["segment_id"]]["coverage_complete"] for segment in members)
        profile = None
        if covered:
            profile = []
            for symbol in dataset.universe:
                rows = [next(item for item in provided[segment["segment_id"]]["symbols"] if item["symbol"] == symbol) for segment in members]
                profile.append({"symbol": symbol, "max_spread_bps": _text(max(Decimal(item["max_spread_bps"]) for item in rows)),
                    "min_reported_side_size_native_units": _text(min(Decimal(item["min_reported_side_size_native_units"]) for item in rows)),
                    "raw_quote_count": sum(item["raw_quote_count"] for item in rows),
                    "eligible_quote_count": sum(item["eligible_quote_count"] for item in rows),
                    "covered_training_sessions": len(members)})
        folds.append({"fold_id": fold_id, "planned_segments": len(members), "capture_complete": captured,
            "coverage_complete": covered, "missing_symbol_sessions": [pair for pair in missing_pairs if pair["fold_id"] == fold_id],
            "training_spread_profile": profile})
    capture_complete = all(row["capture_complete"] for row in segment_rows)
    coverage_complete = capture_complete and not missing_pairs
    counts = {"planned_segments": len(expected), "provided_segments": len(provided),
        "capture_complete_segments": sum(row["capture_complete"] for row in segment_rows),
        "coverage_complete_segments": sum(row["coverage_complete"] for row in segment_rows),
        "missing_segments": len(expected) - len(provided), "planned_symbol_sessions": len(expected) * len(dataset.universe),
        "covered_symbol_sessions": len(expected) * len(dataset.universe) - len(missing_pairs),
        "missing_symbol_sessions": len(missing_pairs), "total_pages": total_pages,
        "raw_quote_count": sum(summary["raw_quote_count"] for summary in provided.values()),
        "eligible_quote_count": sum(summary["eligible_quote_count"] for summary in provided.values()),
        "retained_source_bytes": total_bytes}
    return {"schema_version": EXPORT_VERSION, "method_version": METHOD_VERSION,
        "capture_id": plan.capture_id, "base_plan_evidence": plan.base_plan_evidence, "dataset_evidence": plan.dataset_evidence,
        "status": "CAPTURE_COMPLETE" if capture_complete else "CAPTURE_INCOMPLETE", "capture_complete": capture_complete,
        "coverage_complete": coverage_complete, "counts": counts, "segments": segment_rows, "retained_source_bytes": total_bytes,
        "missing_symbol_sessions": missing_pairs, "folds": folds,
        "reason_codes": ([] if capture_complete else ["TRAIN_SEGMENT_CAPTURE_INCOMPLETE"]) + ([] if coverage_complete else ["TRAIN_SYMBOL_SESSION_COVERAGE_INCOMPLETE"]),
        "consumer_v18": "INCOMPATIBLE_SEGMENTED_INPUT", "existing_gate_override": False,
        "economic_hypothesis_supported": False, "uncertainty_computed": False,
        "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "slippage_estimated": False, "fees_estimated": False, "opening_execution_capacity_verified": False,
        "final_holdout": {**base.protocol["final_holdout"], "scoring_status": "WITHHELD", "access_sealed": False},
        "auto_trading_enabled": False, "authority": plan.authority, "limitations": list(LIMITATIONS)}
