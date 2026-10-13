"""Pure frozen TRAIN planning and bounded retained-input journal projections."""
from datetime import timedelta
from pathlib import Path

from .contracts.train_market_evidence import TrainMarketCapturePlan, TrainMarketSegmentRequest, TrainMarketExportRequest, DEFAULT_LIMITS, PLAN_VERSION, PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE
from .contracts.trading_research import TradingResearchPlan, TradingResearchDataset
from .contracts.mission_request import parse_rfc3339, format_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, research_inputs, registered_context, validate_research_event, evidence_for_research
from .trading_research_intake_journal import validate_intake_event

AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
CODE_PATHS = ("contracts/train_market_evidence.py", "train_market_evidence.py", "train_market_export.py", "train_market_evidence_journal.py", "train_market_capture.py",
    "contracts/trading_evidence_capture.py", "trading_training_calibration.py", "trading_cost_intake.py",
    "contracts/trading_cost_intake.py", "trading_historical_intake.py", "contracts/historical_intake.py",
    "trading_research_journal.py", "trading_research_intake_journal.py", "contracts/trading_research.py",
    "contracts/trading_hypothesis.py", "paper_account_probe.py", "hashing.py")


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"train-evidence/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def merge(target, material, maximum=64 * 1024 * 1024, maximum_files=1024):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw): raise ValueError("TRAIN evidence paths bind conflicting bytes")
        target[path] = raw
    if len(target) > maximum_files or sum(map(len, target.values())) > maximum: raise ValueError("TRAIN event evidence exceeds its bounded closure")


def event_by_id(events, identity, event_types):
    matches = [event for event in events if event.event_id == identity and event.domain == "TRADING" and event.event_type in event_types]
    if len(matches) != 1: raise ValueError("TRAIN evidence requires unique preceding Trading records")
    return matches[0]


def _prefix(document, events, event_type):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events): raise ValueError("TRAIN evidence history has duplicate identities")
    key = "capture_id" if event_type == PLAN_TYPE else "export_id"
    existing = [event for event in events if event.event_type == event_type and event.source[key] == getattr(document, key) and (event_type != SEGMENT_TYPE or event.source["segment_id"] == document.segment_id)]
    if len(existing) > 1: raise ValueError("TRAIN evidence export identity is ambiguous")
    if existing:
        if existing[0].payload["plan" if event_type == PLAN_TYPE else "request"] != document.to_dict(): raise ValueError("TRAIN evidence identity is immutable")
        events = events[:events.index(existing[0])]
    return events


def _segments(base_plan, dataset, fold_ids):
    folds = {fold["fold_id"]: fold for fold in base_plan.protocol["folds"]}
    if not fold_ids or any(identity not in folds for identity in fold_ids): raise ValueError("capture selects unknown or empty original folds")
    protected = set(range(base_plan.protocol["final_holdout"]["start_index"], base_plan.protocol["final_holdout"]["end_index"] + 1))
    for fold in folds.values():
        for role in ("validation", "test"): protected.update(range(fold[role]["start_index"], fold[role]["end_index"] + 1))
    result = []
    for identity in fold_ids:
        fold = folds[identity]
        for index in range(fold["train"]["start_index"], fold["train"]["end_index"] + 1):
            if index in protected: raise ValueError("TRAIN capture cannot reuse any validation, TEST or final-holdout session")
            session = dataset.sessions[index]
            query = {"symbols": ",".join(dataset.universe), "start": session["open_at"],
                "end": format_rfc3339(parse_rfc3339(session["open_at"], "session open") + timedelta(seconds=60)),
                "limit": 10000, "feed": "iex", "currency": "USD", "sort": "asc", "asof": "-"}
            segment_id = "train-window-" + sha256_bytes(canonical_json_bytes({"dataset_sha256": base_plan.dataset_evidence["sha256"], "fold_id": identity, "session_index": index, "session_id": session["session_id"], "query": query}))
            result.append({"segment_id": segment_id, "fold_id": identity, "session_index": index, "session_id": session["session_id"], "query": query})
    return result


def prepare_capture_plan(events, blobs, *, capture_id, created_at, base_plan_event_id, fold_ids=None, limits=None):
    base = event_by_id(events, base_plan_event_id, {"TRADING_RESEARCH_PLAN_REGISTERED"})
    plan, dataset, _, _ = registered_context(base.payload["plan"], events, blobs)
    if plan.schema_version != "blackpod.trading_research_plan.v2": raise ValueError("TRAIN capture requires original governed v2 research")
    reference = next((ref for ref in base.evidence if ref["sha256"] == base.source["source_sha256"]), None)
    if reference is None: raise ValueError("original plan source is not retained")
    selected = [fold["fold_id"] for fold in plan.protocol["folds"]] if fold_ids is None else list(fold_ids)
    return TrainMarketCapturePlan.from_mapping({"schema_version": PLAN_VERSION, "capture_id": capture_id, "created_at": created_at,
        "domain": "TRADING", "mode": "MARKET_DATA_GET_ONLY", "scope": "TRAIN_OPENING_MINUTE_QUOTES_ONLY",
        "base_plan_event_id": base.event_id, "base_plan_evidence": reference, "dataset_evidence": plan.dataset_evidence,
        "evidence_scope": "SYNTHETIC_FIXTURE_ONLY" if all(symbol.startswith("SYNTH") for symbol in dataset.universe) else "RETAINED_HISTORY_RESEARCH",
        "fold_ids": selected, "segments": _segments(plan, dataset, selected), "limits": dict(DEFAULT_LIMITS if limits is None else limits),
        "auto_trading_enabled": False, "authority": AUTHORITY})


def validate_capture_inputs(plan, source_blobs):
    plan = plan if isinstance(plan, TrainMarketCapturePlan) else TrainMarketCapturePlan.from_mapping(plan)
    base = TradingResearchPlan.from_bytes(_blob(source_blobs, plan.base_plan_evidence))
    if base.schema_version != "blackpod.trading_research_plan.v2" or base.dataset_evidence != plan.dataset_evidence: raise ValueError("capture source plan/dataset binding differs")
    base, dataset, _ = research_inputs(base, source_blobs)
    if plan.segments != _segments(base, dataset, plan.fold_ids): raise ValueError("capture queries must match every exact original TRAIN opening window")
    if parse_rfc3339(plan.created_at, "capture freeze") < max(parse_rfc3339(value, "source clock") for value in (base.registered_at, dataset.recorded_at)):
        raise ValueError("capture plan cannot precede its original source declarations")
    if (plan.evidence_scope == "SYNTHETIC_FIXTURE_ONLY") != all(symbol.startswith("SYNTH") for symbol in dataset.universe): raise ValueError("capture evidence scope differs from source symbols")
    evidence = evidence_for_research(base, source_blobs)
    merge(evidence, {plan.base_plan_evidence["path"]: _blob(source_blobs, plan.base_plan_evidence)})
    return {"plan": plan, "base_plan": base, "dataset": dataset, "evidence": evidence}


def plan_context(plan, events, blobs):
    plan = plan if isinstance(plan, TrainMarketCapturePlan) else TrainMarketCapturePlan.from_mapping(plan)
    events = _prefix(plan, events, PLAN_TYPE)
    base = event_by_id(events, plan.base_plan_event_id, {"TRADING_RESEARCH_PLAN_REGISTERED"})
    validate_research_event(base, events[:events.index(base)], blobs)
    if plan.base_plan_evidence not in base.evidence or _blob(blobs, plan.base_plan_evidence) != canonical_json_bytes(base.payload["plan"]): raise ValueError("capture requires the exact registered source plan")
    context = validate_capture_inputs(plan, blobs)
    parent = event_by_id(events, base.payload["hypothesis_event_id"], {"TRADING_HYPOTHESIS_CATALOG_RECORDED"})
    validate_intake_event(parent, events[:events.index(parent)], blobs)
    if parse_rfc3339(plan.created_at, "capture clock") < parse_rfc3339(base.recorded_at, "base clock"): raise ValueError("capture cannot predate original journal plan")
    evidence = dict(context["evidence"]); merge(evidence, {ref["path"]: _blob(blobs, ref) for ref in parent.evidence})
    merge(evidence, implementation_evidence()); merge(evidence, {"train-evidence/capture-plan.v1.json": plan.to_bytes()})
    return {**context, "events": events, "base": base, "parent": parent, "evidence": evidence,
        "links": {"base_plan_event_id": base.event_id, "hypothesis_event_id": parent.event_id, "intake_event_id": base.payload["intake_event_id"]}}


def registered_capture_context(identity, events, blobs):
    event = event_by_id(events, identity, {PLAN_TYPE})
    context = plan_context(event.payload["plan"], tuple(events)[:tuple(events).index(event)], blobs)
    if event.payload["links"] != context["links"] or event.payload["implementation_evidence"] != refs(implementation_evidence()): raise ValueError("registered capture links or installed method changed")
    return {**context, "capture_plan_event": event}


def segment_context(request, events, blobs):
    request = request if isinstance(request, TrainMarketSegmentRequest) else TrainMarketSegmentRequest.from_mapping(request)
    events = _prefix(request, events, SEGMENT_TYPE)
    context = registered_capture_context(request.capture_plan_event_id, events, blobs)
    segments = [segment for segment in context["plan"].segments if segment["segment_id"] == request.segment_id]
    if len(segments) != 1: raise ValueError("segment export cannot invent a query or source window")
    if parse_rfc3339(request.exported_at, "export clock") < parse_rfc3339(context["plan"].created_at, "freeze"): raise ValueError("segment export cannot predate capture freeze")
    from .train_market_export import project_training_segment
    projected = project_training_segment(context["plan"], segments[0], request.pages, blobs, exported_at=request.exported_at, failure=request.failure)
    # A bounded raw segment may be 64 MiB, in addition to its original source
    # proof. This new event closure has separate metadata headroom; individual
    # store files and every old consumer keep their existing 64 MiB limits.
    evidence = dict(context["evidence"]); merge(evidence, projected["evidence"], maximum=128 * 1024 * 1024)
    merge(evidence, {"train-evidence/segment-request.v1.json": request.to_bytes(), "train-evidence/segment-summary.v1.json": canonical_json_bytes(projected["summary"])}, maximum=128 * 1024 * 1024)
    return {**context, "request": request, "events": events, "result": projected["summary"], "evidence": evidence}


def _coverage(request, context, selected, events, blobs):
    from .contracts.trading_continuity_intake import ContinuityCoverageReview
    evidence = {}
    native = None
    if request.continuity_event_id is not None:
        native = event_by_id(events, request.continuity_event_id, {"TRADING_CONTINUITY_INTAKE_RECORDED"})
        from .trading_shadow_review_journal import validate_reviewed_event
        validate_reviewed_event(native, tuple(events)[:tuple(events).index(native)], blobs)
        source = native.payload["request"]
        if source["dataset_evidence"] != context["plan"].dataset_evidence or source["universe"] != context["dataset"].universe or source["evidence_scope"] != context["plan"].evidence_scope:
            raise ValueError("native continuity source must match the capture dataset, universe and scope")
        if parse_rfc3339(native.recorded_at, "native continuity clock") > parse_rfc3339(request.exported_at, "export clock"):
            raise ValueError("export cannot predate native continuity source")
    if request.coverage_review_evidence is None:
        return {"status": "UNRESOLVED", "independent_effective_date_coverage_supplied": False, "review_evidence": None, "source_authentication_verified": False, "reason_codes": ["INDEPENDENT_EFFECTIVE_DATE_COVERAGE_NOT_SUPPLIED"]}, evidence
    if request.continuity_event_id is None: raise ValueError("independent coverage packet requires its original native continuity event")
    review = ContinuityCoverageReview.from_bytes(_blob(blobs, request.coverage_review_evidence))
    dataset = context["dataset"]
    if (review.dataset_evidence != context["plan"].dataset_evidence or review.universe != dataset.universe
            or (review.coverage_start_session_id, review.coverage_end_session_id) != (dataset.sessions[0]["session_id"], dataset.sessions[-1]["session_id"])):
        raise ValueError("coverage review must bind original dataset, universe and complete effective-date span")
    if not parse_rfc3339(dataset.recorded_at, "dataset clock") <= parse_rfc3339(review.recorded_at, "review clock") <= parse_rfc3339(request.exported_at, "export clock"):
        raise ValueError("coverage support clock is outside source/export bounds")
    forbidden = {request.coverage_review_evidence["sha256"], context["plan"].dataset_evidence["sha256"], context["plan"].base_plan_evidence["sha256"]}
    forbidden |= {ref["sha256"] for ref in native.evidence}
    forbidden |= {ref["sha256"] for event in selected for ref in event.evidence}
    if any(ref["sha256"] in forbidden for ref in review.source_evidence): raise ValueError("effective-date support must be independent of process response, quote capture and declarations")
    merge(evidence, {ref["path"]: _blob(blobs, ref) for ref in [request.coverage_review_evidence, *review.source_evidence]})
    return {"status": "SUPPLIED_REVIEW_SUPPORTED_NOT_AUTHENTICATED" if review.status == "SUPPORTED" else "UNRESOLVED", "independent_effective_date_coverage_supplied": review.status == "SUPPORTED",
        "review_evidence": request.coverage_review_evidence, "reviewer_id": review.reviewer_id, "source_authentication_verified": False,
        "reason_codes": [] if review.status == "SUPPORTED" else ["INDEPENDENT_EFFECTIVE_DATE_REVIEW_UNRESOLVED"]}, evidence


def export_context(request, events, blobs):
    request = request if isinstance(request, TrainMarketExportRequest) else TrainMarketExportRequest.from_mapping(request)
    events = _prefix(request, events, EXPORT_TYPE)
    context = registered_capture_context(request.capture_plan_event_id, events, blobs)
    if parse_rfc3339(request.exported_at, "export clock") < parse_rfc3339(context["plan"].created_at, "freeze"): raise ValueError("aggregate export cannot predate capture freeze")
    candidates = [event for event in events if event.event_type == SEGMENT_TYPE and event.payload["request"]["capture_plan_event_id"] == request.capture_plan_event_id and event.source["export_id"] == request.export_id]
    if sorted(event.event_id for event in candidates) != request.segment_event_ids: raise ValueError("aggregate must disclose every preceding segment of this frozen export, without cherry-picking")
    if len({event.source["segment_id"] for event in candidates}) != len(candidates): raise ValueError("aggregate export contains duplicate segment identities")
    if any(parse_rfc3339(event.recorded_at, "segment clock") > parse_rfc3339(request.exported_at, "export clock") for event in candidates): raise ValueError("aggregate cannot predate selected captures")
    from .train_market_export import aggregate_training_segments
    # The store has already replayed preceding segment records. Do not load
    # their full raw closure again into this aggregate event.
    result = aggregate_training_segments(context["plan"], context["base_plan"], context["dataset"], [event.payload["result"] for event in candidates])
    coverage, support = _coverage(request, context, candidates, events, blobs)
    result = {**result, "export_id": request.export_id, "exported_at": request.exported_at, "segment_event_ids": request.segment_event_ids, "continuity_coverage": coverage,
        "economic_hypothesis_supported": False, "uncertainty_computed": False, "existing_gate_override": False,
        "cost_assumptions_supplied": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None}
    evidence = dict(context["evidence"]); merge(evidence, support)
    if request.capture_snapshot_evidence is not None:
        from .contracts.train_market_evidence import TrainMarketCaptureSnapshot
        snapshot = TrainMarketCaptureSnapshot.from_bytes(_blob(blobs, request.capture_snapshot_evidence))
        from .train_market_capture import validate_capture_snapshot
        validate_capture_snapshot(context["plan"], snapshot, blobs)
        if snapshot.capture_id != context["plan"].capture_id or snapshot.exported_at != request.exported_at or snapshot.checkpoint_evidence != request.capture_checkpoint_evidence:
            raise ValueError("aggregate audit snapshot identities or checkpoint references differ")
        if _blob(blobs, snapshot.capture_plan_evidence) != context["plan"].to_bytes(): raise ValueError("audit snapshot must bind the exact frozen capture plan")
        mapped = {item["segment_id"]: item for item in snapshot.segments}
        if set(mapped) != {segment["segment_id"] for segment in context["plan"].segments}: raise ValueError("audit snapshot must retain every original planned window")
        attempted = {key for key, value in mapped.items() if value["status"] != "NOT_STARTED"}
        if attempted != {event.source["segment_id"] for event in candidates}: raise ValueError("aggregate cannot hide attempted source windows")
        for event in candidates:
            item = mapped[event.source["segment_id"]]
            if item["pages"] != event.payload["request"]["pages"] or item["failure"] != event.payload["request"]["failure"]:
                raise ValueError("aggregate cannot replace captured pages or failure dispositions")
        result["capture_audit"] = {"snapshot_evidence": request.capture_snapshot_evidence, "checkpoint_evidence": request.capture_checkpoint_evidence,
            "attempt_count": snapshot.attempt_count, "retained_bytes": snapshot.retained_bytes, "source_authentication_verified": False}
        merge(evidence, {ref["path"]: _blob(blobs, ref) for ref in [request.capture_snapshot_evidence, snapshot.capture_plan_evidence, *request.capture_checkpoint_evidence]}, maximum_files=20000)
    else: result["capture_audit"] = None
    merge(evidence, {"train-evidence/export-request.v1.json": request.to_bytes(), "train-evidence/export-summary.v1.json": canonical_json_bytes(result)}, maximum_files=20000)
    return {**context, "request": request, "events": events, "result": result, "evidence": evidence}
