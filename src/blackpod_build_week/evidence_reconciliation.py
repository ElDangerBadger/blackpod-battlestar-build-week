"""Pure source reconciliation against selected, previously verified history.

Journal storage verifies the complete preceding history. This consumer checks
selected native inputs and source identities without repeating quote diagnostics
or pretending to issue a new native qualification.
"""
from pathlib import Path

from .contracts.evidence_reconciliation import (
    EvidenceReconciliationRequest, RESULT_VERSION, METHOD_VERSION, REVIEW_TYPE,
    LIMITATIONS, validate_result, validate_links, EVALUATION_MODES,
)
from .contracts.native_evidence_closure import REVIEW_TYPE as ANCHOR_TYPE
from .contracts.train_market_evidence import PLAN_TYPE, EXPORT_TYPE, SEGMENT_TYPE
from .contracts.trading_evidence_capture import CaptureReceipt
from .contracts.mission_request import parse_rfc3339
from .contracts.historical_intake import HistoricalIntakeRequest
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, identity
from .train_market_evidence import registered_capture_context, CODE_PATHS as CAPTURE_CODE

AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
CODE_PATHS = tuple(dict.fromkeys((
    "contracts/evidence_reconciliation.py", "evidence_reconciliation.py", "evidence_reconciliation_journal.py",
    "contracts/effective_date_reconciliation.py", "effective_date_reconciliation.py", "independent_action_sources.py",
    "contracts/historical_feed_cost_applicability.py", "historical_feed_cost_applicability.py",
    "contracts/trading_continuity_intake.py", "trading_continuity_intake.py",
    "contracts/mission_request.py", "contracts/trading_reconciliation.py", "contracts/investment_review.py",
    "contracts/trading_accounting.py", *CAPTURE_CODE,
)))


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"independent-evidence/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def merge(target, material):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw):
            raise ValueError("independent evidence paths bind conflicting bytes")
        target[path] = raw
    if len(target) > 8192 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("independent evidence exceeds its compact retained bounds")


def _event(events, event_id, event_type):
    selected = [item for item in events if item.event_id == event_id and item.domain == "TRADING" and item.event_type == event_type]
    if len(selected) != 1:
        raise ValueError("independent review requires an exact unique preceding TRADING source")
    return selected[0]


def _leaf(event, path, blobs):
    selected = [ref for ref in event.evidence if ref["path"] == path]
    if len(selected) != 1:
        raise ValueError("selected source must retain its exact typed document")
    return selected[0], _blob(blobs, selected[0])


def _source_selection(anchor_review_event_id, events, blobs):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("source history has ambiguous identities")
    anchor = _event(events, anchor_review_event_id, ANCHOR_TYPE)
    earlier = events[:events.index(anchor)]
    anchor_ref, raw = _leaf(anchor, "native-closure/result.v1.json", blobs)
    if raw != canonical_json_bytes(anchor.payload["result"]):
        raise ValueError("anchor result differs from its retained original bytes")
    report = anchor.payload["result"]
    snapshot = report["candidate_qualification"] or report["anchor_qualification"]
    native = _event(earlier, snapshot["qualification_event_id"], "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_RECORDED")
    if native.decision_id != anchor.decision_id or native.payload["result"] != snapshot["result"]:
        raise ValueError("anchor does not retain the exact selected native decision result")
    if sha256_bytes(canonical_json_bytes(native.payload["result"])) != snapshot["result_sha256"]:
        raise ValueError("native qualification snapshot hash differs")
    native_ref, native_raw = _leaf(native, "segmented-qualification/result.v1.json", blobs)
    if native_raw != canonical_json_bytes(native.payload["result"]):
        raise ValueError("native result leaf differs from the selected journal source")
    links = anchor.payload["links"]
    for field, key in (("capture_plan_event_id", "capture_plan_event_id"),
            ("selected_aggregate_export_event_id", "aggregate_export_event_id"),
            ("selected_qualification_policy_event_id", "qualification_policy_event_id")):
        if links[field] != snapshot[key]:
            raise ValueError("anchor links differ from the selected native scope")
    if links["selected_qualification_event_id"] != native.event_id:
        raise ValueError("anchor selected qualification differs")
    context = registered_capture_context(snapshot["capture_plan_event_id"], earlier, blobs)
    aggregate = _event(earlier, snapshot["aggregate_export_event_id"], EXPORT_TYPE)
    if aggregate.payload["request"]["capture_plan_event_id"] != context["capture_plan_event"].event_id:
        raise ValueError("aggregate belongs to a different capture plan")
    if aggregate.decision_id != anchor.decision_id or context["parent"].decision_id != anchor.decision_id:
        raise ValueError("selected sources do not belong to the original research decision")
    if any(context["links"][key] != links[key] for key in ("base_plan_event_id", "hypothesis_event_id")):
        raise ValueError("anchor research links differ from the original frozen plan")
    continuity = _event(earlier, snapshot["continuity_event_id"], "TRADING_CONTINUITY_INTAKE_RECORDED")
    from .trading_continuity_intake import verify_continuity_intake
    native_material = verify_continuity_intake(continuity.payload["export"], blobs)
    if (native_material["request"].to_dict() != continuity.payload["request"]
            or native_material["dataset"].to_bytes() != context["dataset"].to_bytes()
            or native_material["request"].evidence_scope != context["plan"].evidence_scope):
        raise ValueError("selected continuity source differs from the frozen dataset and scope")
    continuity_ref, continuity_raw = _leaf(continuity, "continuity-intake/export.v1.json", blobs)
    if continuity_raw != canonical_json_bytes(continuity.payload["export"]):
        raise ValueError("native continuity export leaf differs")
    for event in (anchor, native, continuity, context["capture_plan_event"], aggregate):
        for reference in event.evidence:
            _blob(blobs, reference)
    return {"anchor": anchor, "native": native, "snapshot": snapshot, "capture": context,
        "aggregate": aggregate, "continuity": continuity, "continuity_reference": continuity_ref,
        "native_material": native_material, "events": events, "earlier": earlier}


def build_source_context(anchor_review_event_id, events, blobs, *, recorded_at,
                         declared_evaluation_mode, account_profile_evidence=None):
    """Derive receipt scope only; this does not replay quotes or approve costs."""
    from .contracts.historical_feed_cost_applicability import HistoricalFeedCostContext
    selected = _source_selection(anchor_review_event_id, events, blobs)
    cutoff = parse_rfc3339(recorded_at, "context clock")
    if declared_evaluation_mode not in EVALUATION_MODES:
        raise ValueError("declared target evaluation mode is unsupported")
    capture, aggregate = selected["capture"], selected["aggregate"]
    plan, dataset = capture["plan"], capture["dataset"]
    plan_ref, plan_raw = _leaf(capture["capture_plan_event"], "train-evidence/capture-plan.v1.json", blobs)
    if plan_raw != plan.to_bytes():
        raise ValueError("capture plan source bytes differ")
    segments = {segment["segment_id"]: segment for segment in plan.segments}
    ids = aggregate.payload["result"]["segment_event_ids"]
    if len(ids) != len(set(ids)):
        raise ValueError("aggregate source receipt inventory is ambiguous")
    evidence, receipts, clocks, seen = {}, [], [], set()
    for event_id in ids:
        event = _event(selected["earlier"], event_id, SEGMENT_TYPE)
        source = event.payload["request"]
        if source["capture_plan_event_id"] != capture["capture_plan_event"].event_id or source["segment_id"] not in segments:
            raise ValueError("aggregate selects a receipt from a different frozen capture")
        segment = segments[source["segment_id"]]
        for page in source["pages"]:
            reference = page["receipt_evidence"]
            receipt = CaptureReceipt.from_bytes(_blob(blobs, reference))
            query = receipt.query
            if {key: value for key, value in query.items() if key != "page_token"} != segment["query"]:
                raise ValueError("source receipt query differs from its exact frozen TRAIN window")
            if receipt.url != "https://data.alpaca.markets/v2/stocks/quotes":
                raise ValueError("quote context requires the original quotes endpoint")
            if (receipt.body_sha256, receipt.size_bytes) != (page["body_evidence"]["sha256"], page["body_evidence"]["size_bytes"]):
                raise ValueError("source receipt body binding differs")
            _blob(blobs, page["body_evidence"])
            clock = parse_rfc3339(receipt.captured_at, "delivery clock")
            if clock > cutoff:
                raise ValueError("context cannot predate selected source delivery")
            clocks.append((clock, receipt.captured_at))
            key = (reference["path"], reference["sha256"], reference["size_bytes"])
            if key in seen:
                raise ValueError("a quote receipt is selected more than once")
            seen.add(key); receipts.append(reference)
            merge(evidence, {reference["path"]: _blob(blobs, reference)})
    if not receipts:
        raise ValueError("context requires retained quote receipt evidence; missing capture remains unresolved")
    historical_request = HistoricalIntakeRequest.from_bytes(_blob(blobs, dataset.provenance["governed_intake"]["request_evidence"]))
    bars_ref = historical_request.sources["bars_receipt_evidence"]
    context_value = {"schema_version": "blackpod.historical_feed_cost_context.v1",
        "context_id": identity("source-context", {"anchor": anchor_review_event_id, "recorded_at": recorded_at,
            "declared_evaluation_mode": declared_evaluation_mode, "account": account_profile_evidence}),
        "recorded_at": recorded_at, "capture_plan_event_id": capture["capture_plan_event"].event_id,
        "aggregate_export_event_id": aggregate.event_id, "base_plan_event_id": capture["base"].event_id,
        "dataset_evidence": plan.dataset_evidence, "bars_receipt_evidence": bars_ref,
        "capture_plan_evidence": plan_ref, "quote_receipt_evidence": receipts,
        "provider": "ALPACA", "endpoint": "https://data.alpaca.markets/v2/stocks/quotes",
        "feed": "iex", "universe": dataset.universe, "currency": "USD",
        "market_event_interval": {"start_at": min(plan.segments, key=lambda s: parse_rfc3339(s["query"]["start"], "start"))["query"]["start"],
            "end_at": max(plan.segments, key=lambda s: parse_rfc3339(s["query"]["end"], "end"))["query"]["end"]},
        "delivery_interval": {"start_at": min(clocks)[1], "end_at": max(clocks)[1]},
        "collection_mode": "MARKET_DATA_GET_ONLY", "declared_evaluation_mode": declared_evaluation_mode,
        "account_evidence": account_profile_evidence, "auto_trading_enabled": False, "authority": AUTHORITY}
    context = HistoricalFeedCostContext.from_mapping(context_value)
    for reference in (bars_ref, plan_ref, plan.dataset_evidence):
        merge(evidence, {reference["path"]: _blob(blobs, reference)})
    if account_profile_evidence is not None:
        merge(evidence, {account_profile_evidence["path"]: _blob(blobs, account_profile_evidence)})
    for event in (selected["anchor"], selected["native"], selected["continuity"], capture["capture_plan_event"], aggregate):
        if parse_rfc3339(event.recorded_at, "source record clock") > cutoff:
            raise ValueError("context clock excludes a selected source record")
    links = validate_links({"anchor_review_event_id": selected["anchor"].event_id,
        "selected_qualification_event_id": selected["native"].event_id,
        "continuity_event_id": selected["continuity"].event_id,
        "capture_plan_event_id": capture["capture_plan_event"].event_id,
        "aggregate_export_event_id": aggregate.event_id, **capture["links"]})
    return {"context": context, "evidence": evidence, "parent": capture["parent"], "links": links, "selected": selected}


def _prefix(request, events):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("reconciliation history contains ambiguous identities")
    matches = [event for event in events if event.event_type == REVIEW_TYPE and event.source["review_id"] == request.review_id]
    if len(matches) > 1:
        raise ValueError("review identity is ambiguous")
    if matches:
        if matches[0].payload["request"] != request.to_dict():
            raise ValueError("review identity is immutable")
        events = events[:events.index(matches[0])]
    return events


def assess_evidence_reconciliation(request, events, blobs):
    from .contracts.effective_date_reconciliation import EffectiveDateReconciliationRequest
    from .contracts.historical_feed_cost_applicability import HistoricalFeedCostApplicabilityPacket, HistoricalFeedCostContext
    from .effective_date_reconciliation import reconcile_effective_dates
    from .historical_feed_cost_applicability import assess_historical_applicability
    request = request if isinstance(request, EvidenceReconciliationRequest) else EvidenceReconciliationRequest.from_mapping(request)
    events = _prefix(request, events)
    packet_raw = _blob(blobs, request.applicability_packet_evidence)
    packet = HistoricalFeedCostApplicabilityPacket.from_bytes(packet_raw)
    retained_context = HistoricalFeedCostContext.from_bytes(_blob(blobs, packet.context_evidence))
    cutoff = parse_rfc3339(request.data_cutoff_at, "review cutoff")
    if parse_rfc3339(retained_context.recorded_at, "source context clock") > cutoff:
        raise ValueError("review cutoff excludes the frozen source context")
    context_material = build_source_context(request.anchor_review_event_id, events, blobs,
        recorded_at=retained_context.recorded_at, declared_evaluation_mode=request.declared_evaluation_mode,
        account_profile_evidence=request.account_profile_evidence)
    selected = context_material["selected"]
    context = context_material["context"]
    if parse_rfc3339(context.delivery_interval["end_at"], "delivery end") > cutoff:
        raise ValueError("review cutoff excludes source delivery")
    for event in (selected["anchor"], selected["native"], selected["continuity"], selected["aggregate"], selected["capture"]["capture_plan_event"]):
        if parse_rfc3339(event.recorded_at, "selected source clock") > cutoff:
            raise ValueError("review cutoff excludes a selected source event")
    effective_raw = _blob(blobs, request.effective_date_request_evidence)
    effective = EffectiveDateReconciliationRequest.from_bytes(effective_raw)
    if (effective.dataset_evidence != selected["capture"]["plan"].dataset_evidence
            or effective.native_continuity_export_evidence != selected["continuity_reference"]):
        raise ValueError("effective-date request must select the exact original native dataset and intake")
    if parse_rfc3339(effective.data_cutoff_at, "effective cutoff") > cutoff or parse_rfc3339(effective.recorded_at, "effective clock") > cutoff:
        raise ValueError("review cutoff excludes effective-date source review")
    effective_material = reconcile_effective_dates(effective, blobs)
    if _blob(blobs, packet.context_evidence) != context.to_bytes():
        raise ValueError("applicability packet must bind the exact regenerated native source context")
    if parse_rfc3339(packet.recorded_at, "packet clock") > cutoff or parse_rfc3339(packet.data_cutoff_at, "packet cutoff") > cutoff:
        raise ValueError("review cutoff excludes applicability source packet")
    applicability = assess_historical_applicability(packet, context, blobs)
    previous = [event for event in events if event.event_type == REVIEW_TYPE and event.payload["request"]["anchor_review_event_id"] == request.anchor_review_event_id]
    if any(parse_rfc3339(event.recorded_at, "prior clock") > parse_rfc3339(request.recorded_at, "review clock") for event in previous):
        raise ValueError("same-anchor review cannot backdate preceding history")
    if request.supersedes_event_id is not None:
        prior = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if prior is None or any(event.payload["request"]["supersedes_event_id"] == prior.event_id for event in previous):
            raise ValueError("supersession requires an unsuperseded same-anchor review")
        if parse_rfc3339(prior.payload["request"]["data_cutoff_at"], "prior cutoff") > cutoff:
            raise ValueError("supersession cannot move cutoff backwards")
    evidence = {"independent-evidence/request.v1.json": request.to_bytes(),
        "independent-evidence/effective-date-request.v1.json": effective_raw,
        "independent-evidence/applicability-packet.v1.json": packet_raw,
        "independent-evidence/source-context.v1.json": context.to_bytes()}
    merge(evidence, effective_material["evidence"])
    merge(evidence, applicability["evidence"])
    merge(evidence, context_material["evidence"])
    snapshot = selected["snapshot"]["result"]
    result = validate_result({"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION,
        "review_id": request.review_id, "status": "DESCRIPTIVE_EVIDENCE_RECONCILIATION_ONLY",
        "anchor_review_event_id": selected["anchor"].event_id,
        "anchor_event_sha256": sha256_bytes(selected["anchor"].to_bytes()),
        "selected_qualification_event_id": selected["native"].event_id,
        "native_qualification_snapshot": snapshot,
        "native_qualification_result_sha256": sha256_bytes(canonical_json_bytes(snapshot)),
        "native_reason_codes": sorted(set(snapshot["reason_codes"])),
        "source_context": context.to_dict(), "effective_date_reconciliation": effective_material["result"],
        "historical_feed_cost_applicability": applicability["result"],
        "native_coverage_proposal": effective_material["result"]["coverage_proposal"],
        "cost_assumptions_proposal": None, "native_coverage_proposal_applied": False,
        "native_qualification_recomputed": False, "native_gate_override": False,
        "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "source_applicability_verified": False, "opening_execution_capacity_verified": False,
        "uncertainty_computed": False, "economic_hypothesis_supported": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "limitations": list(LIMITATIONS), "auto_trading_enabled": False, "authority": AUTHORITY})
    merge(evidence, implementation_evidence())
    # Already retained quote bodies are not duplicated in this compact event.
    existing_hashes = {ref["sha256"] for event in events for ref in event.evidence}
    retained_new = {path: raw for path, raw in evidence.items()
        if sha256_bytes(raw) not in existing_hashes or path.startswith("independent-evidence/")}
    return {"request": request, "result": result, "evidence": retained_new,
        "parent": context_material["parent"], "links": context_material["links"],
        "prior_review_event_ids": sorted(event.event_id for event in previous)}
