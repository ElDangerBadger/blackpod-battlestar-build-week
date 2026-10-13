"""Pure, training-only quote bounds and explicitly assumed capacity proxies.

Retrospective retained quotes do not establish fills, opening liquidity,
slippage, fees or historical publication times. A contaminated quote chain is
retained for audit but contributes no calibration measurements. No returns or
independent evaluation partitions are used to choose a cost or sizing value.
"""
from __future__ import annotations

from bisect import bisect_right
from decimal import Context, Decimal, ROUND_CEILING, localcontext

from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .contracts.trading_research import TradingResearchPlan, TradingResearchDataset
from .hashing import sha256_bytes
from .trading_cost_intake import QUOTES_URL, _capture, _nanos, _number, _query
from .trading_historical_intake import parse_historical_json, validate_historical_dataset
from .trading_research_evaluation import plan_chronological_splits

METHOD_VERSION = "blackpod.training_only_quote_calibration.v1"
SCHEMA_VERSION = "blackpod.trading_training_calibration.v1"
_QUANTUM = Decimal("0.000000000000000001")
_MAX_BYTES = 64 * 1024 * 1024
_STRESSES = ("1", "2", "4")
LIMITATIONS = (
    "TRAINING_SAMPLE_SPREAD_MAXIMUM_NOT_FUTURE_EXECUTION_GUARANTEE",
    "ONE_OR_MORE_OPENING_MINUTE_QUOTES_NOT_CONTINUOUS_MARKET_COVERAGE",
    "IEX_QUOTE_SAMPLE_NOT_CONSOLIDATED_OR_AUCTION_EXECUTION",
    "SLIPPAGE_AND_FEES_ARE_REVIEWED_DECLARATIONS_NOT_MEASURED_COSTS",
    "DAILY_VOLUME_PARTICIPATION_IS_A_RESEARCH_PROXY_NOT_OPENING_FILL_CAPACITY",
    "NATIVE_QUOTE_SIZE_UNITS_NOT_CONVERTED_OR_ASSUMED_EXECUTABLE",
    "RETROSPECTIVE_RECEIPTS_NOT_HISTORICAL_POINT_IN_TIME_PROOF",
    "RETAINED_BYTES_NOT_PROVIDER_OR_REVIEWER_AUTHENTICATION",
    "RAW_TRAINING_VOLUMES_NOT_CORPORATE_ACTION_ADJUSTED",
    "NO_PRICE_PERFORMANCE_SCORING_OR_PARAMETER_OPTIMIZATION",
    "NO_EXECUTION_OR_CAPITAL_AUTHORITY",
)


def _document(value, cls):
    return cls.from_mapping(value.to_dict() if hasattr(value, "to_dict") else value)


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ContractValidationError("training calibration evidence differs in hash or size")
    return raw


def _retain(evidence, ref, blobs):
    raw = _blob(blobs, ref)
    if ref["path"] in evidence and evidence[ref["path"]] != raw:
        raise ContractValidationError("training calibration source paths bind conflicting bytes")
    evidence[ref["path"]] = raw
    if len(evidence) > 512 or sum(map(len, evidence.values())) > _MAX_BYTES:
        raise ContractValidationError("training calibration exceeds its retained evidence bound")
    return raw


def _text(value):
    value = format(value, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _bind(reference, document, label):
    raw = document.to_bytes()
    if reference["sha256"] != sha256_bytes(raw) or reference["size_bytes"] != len(raw):
        raise ContractValidationError(label + " differs from its exact declared evidence")


def _native_rows(pages, universe, dataset, recorded, evidence, blobs):
    """Validate the entire forward chain before any training measurement.

    Every structurally valid row is returned, including rows outside an opening
    minute. Partition contamination is handled by the caller as an auditable
    deferral; malformed native source material never becomes a usable profile.
    """
    rows, queries, reasons = [], [], []
    base_query, next_token, previous_pair = None, None, None
    seen_tokens, same_stamp_signatures = set(), set()
    for page_index, page in enumerate(pages):
        body_ref, receipt_ref = page["body_evidence"], page["receipt_evidence"]
        body = _retain(evidence, body_ref, blobs)
        receipt = _capture(_retain(evidence, receipt_ref, blobs))
        if receipt["url"] != QUOTES_URL or receipt["method"] != "GET":
            raise ContractValidationError("training quotes require the exact allowed historical quote GET")
        if receipt["body_sha256"] != body_ref["sha256"] or receipt["size_bytes"] != body_ref["size_bytes"]:
            raise ContractValidationError("training quote receipt must bind its exact native response body")
        capture = parse_rfc3339(receipt["captured_at"], "quote capture")
        if not parse_rfc3339(dataset.recorded_at, "dataset capture") <= capture <= recorded:
            raise ContractValidationError("training quote capture must lie between dataset capture and policy freeze")
        start, end = _query(receipt["query"], universe)
        if end > _nanos(receipt["captured_at"], "quote capture"):
            raise ContractValidationError("training quote query cannot end after its capture")
        query = {key: value for key, value in receipt["query"].items() if key != "page_token"}
        if page_index == 0:
            if "page_token" in receipt["query"]:
                raise ContractValidationError("training quote chain must begin without a page token")
            base_query = query
        elif query != base_query or next_token is None or receipt["query"].get("page_token") != next_token:
            raise ContractValidationError("training quote pagination must preserve the exact base query and forward token")
        queries.append((start, end))
        if receipt["status"] != 200:
            reasons.append("TRAINING_QUOTE_RESPONSE_UNAVAILABLE")
            if page_index != len(pages) - 1:
                raise ContractValidationError("an unavailable training quote page cannot have an invented continuation")
            continue
        response = parse_historical_json(body)
        if not isinstance(response, dict) or set(response) != {"quotes", "next_page_token"} or not isinstance(response["quotes"], dict):
            raise ContractValidationError("training quote response requires exact native quotes and pagination fields")
        if any(symbol not in universe for symbol in response["quotes"]):
            raise ContractValidationError("training quote response contains an undeclared symbol")
        token = response["next_page_token"]
        if token is not None and (not isinstance(token, str) or not 1 <= len(token) <= 2048 or token in seen_tokens):
            raise ContractValidationError("training quote pagination token is malformed or cyclic")
        if token is not None:
            seen_tokens.add(token)
        next_token = token
        page_count = 0
        for symbol in sorted(response["quotes"]):
            native = response["quotes"][symbol]
            if not isinstance(native, list):
                raise ContractValidationError("native training quotes by symbol must be lists")
            for row in native:
                page_count += 1
                if len(rows) >= 200000:
                    raise ContractValidationError("training quote evidence exceeds 200000 native rows")
                if not isinstance(row, dict) or set(row) != {"t", "bp", "bs", "bx", "ap", "as", "ax", "c", "z"}:
                    raise ContractValidationError("training quote row must preserve the exact native fields")
                if not isinstance(row["z"], str) or row["z"] not in {"A", "B", "C"}:
                    raise ContractValidationError("training quote tape must be native A, B or C")
                stamp = _nanos(row["t"], "quote timestamp")
                if not start <= stamp <= end:
                    raise ContractValidationError("training quote timestamp is outside its retained query")
                pair = (symbol, stamp)
                if previous_pair is not None and pair < previous_pair:
                    raise ContractValidationError("training quotes must be nondecreasing by symbol and exact nanosecond timestamp")
                if pair != previous_pair:
                    same_stamp_signatures.clear()
                for key in ("bx", "ax"):
                    if not isinstance(row[key], str) or not 1 <= len(row[key]) <= 16 or row[key].strip() != row[key]:
                        raise ContractValidationError("training quote exchange codes must be bounded native strings")
                conditions = row["c"]
                if (not isinstance(conditions, list) or len(conditions) > 16
                        or any(not isinstance(value, str) or not 1 <= len(value) <= 16 or value.strip() != value for value in conditions)
                        or len(set(conditions)) != len(conditions)):
                    raise ContractValidationError("training quote conditions must be distinct bounded native strings")
                bid, ask = _number(row["bp"], "quote bid"), _number(row["ap"], "quote ask")
                bid_size, ask_size = _number(row["bs"], "quote bid size", integer=True), _number(row["as"], "quote ask size", integer=True)
                signature = (bid, ask, bid_size, ask_size, row["bx"], row["ax"], tuple(conditions), row["z"])
                if signature in same_stamp_signatures:
                    raise ContractValidationError("training quote chain contains an identical duplicate update")
                same_stamp_signatures.add(signature)
                previous_pair = pair
                rows.append({"symbol": symbol, "stamp": stamp, "native_timestamp": row["t"], "bid": bid, "ask": ask,
                             "bid_size": bid_size, "ask_size": ask_size, "conditions": conditions})
        if page_count > receipt["query"]["limit"]:
            raise ContractValidationError("training quote page exceeds its declared total-symbol limit")
    if next_token is not None:
        reasons.append("TRAINING_QUOTE_PAGINATION_INCOMPLETE")
    return rows, queries, reasons


def calibrate_training_evidence(policy, plan, dataset, blobs):
    """Retain native evidence and report training qualification, never execute.

    A READY result means the finite declared training inputs and shadow-only
    assumptions meet this method's form and coverage checks. Economic cost
    applicability and actual opening capacity remain unverified in every case.
    """
    from .contracts.trading_evidence_qualification import TradingEvidenceQualificationPolicy, TradingTrainingAssumptions
    policy = _document(policy, TradingEvidenceQualificationPolicy)
    plan, dataset = _document(plan, TradingResearchPlan), _document(dataset, TradingResearchDataset)
    if plan.schema_version != "blackpod.trading_research_plan.v2" or dataset.schema_version != "blackpod.trading_research_dataset.v2":
        raise ContractValidationError("training calibration requires immutable governed plan and dataset v2")
    _bind(policy.base_plan_evidence, plan, "training base plan")
    _bind(plan.dataset_evidence, dataset, "training dataset")
    if policy.dataset_evidence != plan.dataset_evidence or policy.hypothesis_evidence != plan.frozen_hypothesis_evidence:
        raise ContractValidationError("training policy must bind the plan's exact dataset and frozen hypothesis references")
    if plan.universe != dataset.universe:
        raise ContractValidationError("training plan and dataset universes differ")
    recorded = parse_rfc3339(policy.recorded_at, "policy freeze")
    if max(parse_rfc3339(value, "input clock") for value in (plan.registered_at, dataset.recorded_at)) > recorded:
        raise ContractValidationError("training policy cannot predate its immutable inputs")
    history = validate_historical_dataset(dataset, blobs)
    fixture = policy.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
    if fixture and (not all(symbol.startswith("SYNTH") for symbol in dataset.universe)
                    or history["request"].availability_assumption["declared_by"] != "synthetic-fixture-author"):
        raise ContractValidationError("synthetic training calibration requires the explicit controlled fixture source")
    if not fixture and any(symbol.startswith("SYNTH") for symbol in dataset.universe):
        raise ContractValidationError("retained-history training calibration cannot consume fictional fixture symbols")
    split = plan_chronological_splits(plan, dataset)
    evidence = {}
    reasons, assumptions = [], None
    ref = policy.training_cost_assumptions_evidence
    if ref is None:
        reasons.append("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING")
    else:
        assumptions = TradingTrainingAssumptions.from_bytes(_retain(evidence, ref, blobs))
        if (assumptions.base_plan_evidence != policy.base_plan_evidence or assumptions.dataset_evidence != plan.dataset_evidence
                or assumptions.evidence_scope != policy.evidence_scope):
            raise ContractValidationError("training assumptions must bind the exact original plan, dataset and evidence scope")
        if not max(parse_rfc3339(value, "input clock") for value in (plan.registered_at, dataset.recorded_at)) <= parse_rfc3339(assumptions.recorded_at, "assumption clock") <= recorded:
            raise ContractValidationError("training assumption clock is outside input-capture and policy-freeze bounds")
        for origin in assumptions.origin_evidence:
            if origin["path"] in {ref["path"], policy.base_plan_evidence["path"], plan.dataset_evidence["path"]}:
                raise ContractValidationError("training assumption support cannot be its own declaration, plan or dataset")
            _retain(evidence, origin, blobs)
        if assumptions.status != "REVIEWED_FOR_SHADOW_QUALIFICATION":
            reasons.append("TRAINING_ASSUMPTIONS_NOT_REVIEWED")
        if assumptions.parameters is None:
            reasons.append("TRAINING_COST_PARAMETERS_MISSING")
        if assumptions.capacity is None:
            reasons.append("TRAINING_CAPACITY_ASSUMPTION_MISSING")
    chains = {}
    for chain in policy.training_quote_chains:
        identity = chain["fold_id"]
        if identity in chains:
            raise ContractValidationError("training quote chains must bind distinct folds")
        chains[identity] = chain["pages"]
    fold_ids = {fold["fold_id"] for fold in plan.protocol["folds"]}
    if set(chains) - fold_ids:
        raise ContractValidationError("training quote chain names an unknown original fold")
    protected = set(range(plan.protocol["final_holdout"]["start_index"], plan.protocol["final_holdout"]["end_index"] + 1))
    for fold in plan.protocol["folds"]:
        for role in ("validation", "test"):
            protected.update(range(fold[role]["start_index"], fold[role]["end_index"] + 1))
    sessions, fold_rows = dataset.sessions, []
    all_opens = [_nanos(session["open_at"], "session open") for session in sessions]
    for fold in plan.protocol["folds"]:
        train = fold["train"]
        indices = list(range(train["start_index"], train["end_index"] + 1))
        if not indices or indices[-1] >= len(sessions):
            raise ContractValidationError("training interval exceeds the original returned dataset")
        ids = {index: sessions[index]["session_id"] for index in indices}
        coverage = {(symbol, index): 0 for symbol in dataset.universe for index in indices}
        fold_reasons = list(reasons)
        overlap = sorted(protected & set(indices))
        if overlap:
            fold_reasons.append("TRAIN_INTERVAL_OVERLAPS_HELD_OUT_PARTITION")
        pages = chains.get(fold["fold_id"], [])
        if not pages:
            fold_reasons.append("TRAINING_QUOTE_CHAIN_MISSING")
        rows, queries, native_reasons = _native_rows(pages, dataset.universe, dataset, recorded, evidence, blobs)
        fold_reasons.extend(native_reasons)
        lower, upper = all_opens[indices[0]], all_opens[indices[-1]] + 60_000_000_000
        contaminated = bool(overlap) or any(start < lower or end > upper for start, end in queries)
        for row in rows:
            index = bisect_right(all_opens, row["stamp"]) - 1
            if index not in ids or index in protected:
                contaminated = True
        if contaminated:
            fold_reasons.append("NONTRAINING_QUOTE_EVIDENCE_REJECTED")
        measured = {}
        if not contaminated:
            for row in rows:
                index = bisect_right(all_opens, row["stamp"]) - 1
                if (row["stamp"] > all_opens[index] + 60_000_000_000 or row["bid"] <= 0 or row["ask"] <= 0
                        or row["ask"] < row["bid"] or row["bid_size"] <= 0 or row["ask_size"] <= 0 or row["conditions"] != ["R"]):
                    continue
                coverage[(row["symbol"], index)] += 1
                with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                    spread = ((row["ask"] - row["bid"]) * Decimal("20000") / (row["ask"] + row["bid"])).quantize(_QUANTUM, rounding=ROUND_CEILING)
                size = min(row["bid_size"], row["ask_size"])
                prior = measured.setdefault(row["symbol"], {"max_spread_bps": spread, "min_reported_side_size_native_units": size,
                    "eligible_quote_count": 0, "first_native_timestamp": row["native_timestamp"], "last_native_timestamp": row["native_timestamp"]})
                prior["max_spread_bps"] = max(prior["max_spread_bps"], spread)
                prior["min_reported_side_size_native_units"] = min(prior["min_reported_side_size_native_units"], size)
                prior["eligible_quote_count"] += 1
                prior["last_native_timestamp"] = row["native_timestamp"]
        missing = [{"symbol": symbol, "session_index": index, "session_id": ids[index]}
                   for (symbol, index), count in sorted(coverage.items()) if not count]
        if missing:
            fold_reasons.append("TRAINING_OPENING_MINUTE_COVERAGE_INCOMPLETE")
        if any(item["fold_id"] == fold["fold_id"] for item in split["availability_failures"]):
            fold_reasons.append("TRAINING_CHRONOLOGICAL_AVAILABILITY_INVALID")
        capacities = []
        if not overlap:
            for symbol in dataset.universe:
                volumes = [Decimal(next(bar["volume"] for bar in sessions[index]["bars"] if bar["symbol"] == symbol)) for index in indices]
                minimum, maximum = min(volumes), max(volumes)
                fraction = (assumptions.capacity["max_daily_volume_participation_fraction"]
                            if assumptions is not None and assumptions.status == "REVIEWED_FOR_SHADOW_QUALIFICATION" and assumptions.capacity is not None else None)
                with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                    proxy = minimum * Decimal(fraction) if fraction is not None else None
                if proxy is not None and proxy <= 0:
                    fold_reasons.append("ZERO_DAILY_VOLUME_RESEARCH_PROXY")
                capacities.append({"symbol": symbol, "minimum_training_daily_volume": _text(minimum),
                    "maximum_training_daily_volume": _text(maximum), "reviewed_daily_volume_participation_fraction": fraction,
                    "daily_quantity_research_proxy": None if proxy is None else _text(proxy),
                    "semantics": "RAW_DAILY_VOLUME_RESEARCH_PROXY_NOT_OPENING_FILL_CAPACITY"})
        measurements = None if contaminated else [{"symbol": symbol,
            "max_spread_bps": None if symbol not in measured else _text(measured[symbol]["max_spread_bps"]),
            "min_reported_side_size_native_units": None if symbol not in measured else _text(measured[symbol]["min_reported_side_size_native_units"]),
            "eligible_quote_count": 0 if symbol not in measured else measured[symbol]["eligible_quote_count"],
            "first_native_timestamp": None if symbol not in measured else measured[symbol]["first_native_timestamp"],
            "last_native_timestamp": None if symbol not in measured else measured[symbol]["last_native_timestamp"]}
            for symbol in dataset.universe]
        declared_model, stresses = None, []
        reviewed = assumptions is not None and assumptions.status == "REVIEWED_FOR_SHADOW_QUALIFICATION" and assumptions.parameters is not None
        if not contaminated and not missing and not native_reasons and reviewed:
            declared_model = {"spread_bps": _text(max(item["max_spread_bps"] for item in measured.values())), **assumptions.parameters}
            with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                if Decimal(declared_model["spread_bps"]) + Decimal(declared_model["slippage_bps"]) <= 0:
                    fold_reasons.append("TRAINING_ZERO_PRICE_FRICTION_NOT_SUPPORTED")
                for multiplier in _STRESSES:
                    model = {key: _text(Decimal(value) * Decimal(multiplier)) for key, value in declared_model.items()}
                    exceeded = sorted(key for key in ("spread_bps", "slippage_bps", "fee_bps") if Decimal(model[key]) > Decimal("1000"))
                    stresses.append({"multiplier": multiplier, "declared_cost_model": model,
                        "within_existing_component_bounds": not exceeded, "exceeded_components": exceeded})
                    if exceeded:
                        fold_reasons.append("TRAINING_COST_STRESS_EXCEEDS_EXISTING_MODEL_BOUND")
        fold_reasons = sorted(set(fold_reasons))
        fold_rows.append({"fold_id": fold["fold_id"], "training_range": dict(train),
            "train_cutoff_at": sessions[indices[-1]]["available_at"],
            "excluded_global_held_out_indices": overlap, "eligible": not fold_reasons,
            "status": "READY_FOR_SHADOW_QUALIFICATION" if not fold_reasons else "DEFER_TRAINING_EVIDENCE",
            "reason_codes": fold_reasons, "native_quote_count": len(rows),
            "quote_evidence_contaminated": contaminated, "training_measurements": measurements,
            "missing_symbol_sessions": missing, "cost_model": declared_model if not fold_reasons else None,
            "cost_stress_assessment": stresses, "capacity_proxy": None if overlap else capacities,
            "cost_applicability_verified": False, "opening_execution_capacity_verified": False})
    reason_codes = sorted({reason for row in fold_rows for reason in row["reason_codes"]})
    assessment = {"schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
        "eligible": not reason_codes, "status": "READY_FOR_SHADOW_QUALIFICATION" if not reason_codes else "DEFER_TRAINING_EVIDENCE",
        "reason_codes": reason_codes, "evidence_scope": policy.evidence_scope,
        "folds": fold_rows, "sampling_policy": "ALL_RETAINED_ADMITTED_R_QUOTES_OPEN_THROUGH_OPEN_PLUS_60_SECONDS_NO_DOWNSAMPLING",
        "coverage_requirement": "AT_LEAST_ONE_ADMITTED_QUOTE_PER_TRAINING_SYMBOL_SESSION_NOT_CONTINUOUS_COVERAGE",
        "global_held_out_policy": "NO_VALIDATION_TEST_OR_FINAL_HOLDOUT_OBSERVATIONS_FROM_ANY_FOLD",
        "assumption_review_evidence": ref,
        "historical_point_in_time_verified": False, "source_authentication_verified": False,
        "cost_applicability_verified": False, "opening_execution_capacity_verified": False,
        "holdout_scored": False, "strategy_tuning_performed": False,
        "auto_trading_enabled": False, "authority": policy.authority, "limitations": list(LIMITATIONS)}
    return {"assessment": assessment, "evidence": evidence}
