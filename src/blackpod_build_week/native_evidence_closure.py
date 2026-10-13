"""Pure descriptive evidence-closure review of immutable native qualifications.

The exact v20 method replays each selected original record. Supplemental review
claims are retained alongside it and are never applied to its prerequisites.
"""
from pathlib import Path

from .contracts.native_evidence_closure import (
    NativeEvidenceClosureReviewRequest, NativeEvidenceSupplementalReview,
    CATEGORIES, REQUEST_VERSION, RESULT_VERSION, METHOD_VERSION, REVIEW_TYPE,
    LIMITATIONS, validate_result, validate_links,
)
from .contracts.segmented_evidence_qualification import ASSESSMENT_TYPE
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, identity
from .segmented_evidence_qualification import (
    qualify_segmented_evidence, implementation_evidence as native_implementation,
    refs as native_refs, CODE_PATHS as NATIVE_CODE,
)
from .native_quote_diagnostics import diagnose_segmented_quotes

AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
CODE_PATHS = tuple(dict.fromkeys((
    "contracts/native_evidence_closure.py", "native_evidence_closure.py", "native_quote_diagnostics.py", "native_evidence_closure_journal.py",
    *NATIVE_CODE, "contracts/mission_request.py", "contracts/investment_review.py", "contracts/trading_accounting.py", "contracts/trading_reconciliation.py",
)))


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"native-closure/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def merge(target, material):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw):
            raise ValueError("native closure evidence has conflicting source paths")
        target[path] = raw
    if len(target) > 512 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("native closure evidence exceeds compact bounds")


def _document(value, kind):
    return kind.from_mapping(value.to_dict() if hasattr(value, "to_dict") else value)


def _event(events, event_id, event_type):
    selected = [event for event in events if event.event_id == event_id and event.domain == "TRADING" and event.event_type == event_type]
    if len(selected) != 1: raise ValueError("native closure requires a unique preceding TRADING source")
    return selected[0]


def _prefix(request, events):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("native closure history contains ambiguous identities")
    existing = [event for event in events if event.event_type == REVIEW_TYPE and event.source["review_id"] == request.review_id]
    if len(existing) > 1: raise ValueError("native closure review identity is ambiguous")
    if existing:
        if existing[0].payload["request"] != request.to_dict():
            raise ValueError("native closure review identity is immutable")
        events = events[:events.index(existing[0])]
    return events


def _verify_retained_leaves(events, blobs, verified):
    """Require source leaves themselves, not only reproducible payload values."""
    for event in events:
        for reference in event.evidence:
            identity = (reference["sha256"], reference["size_bytes"])
            if identity not in verified:
                _blob(blobs, reference)
                verified.add(identity)


def _native_record(event, events, blobs, verified):
    """Replay once and check the complete v20 wrapper without recalculating it twice."""
    _verify_retained_leaves((event,), blobs, verified)
    previous = events[:events.index(event)]
    material = qualify_segmented_evidence(event.payload["request"], previous, blobs)
    expected_evidence = dict(material["evidence"])
    merge(expected_evidence, {"segmented-qualification/result.v1.json": canonical_json_bytes(material["result"])})
    request = material["request"]
    expected_id = identity("journal-event", {"decision_id": material["parent"].decision_id, "event_type": ASSESSMENT_TYPE, "qualification_id": request.qualification_id})
    if (event.event_id != expected_id or event.decision_id != material["parent"].decision_id
            or event.payload["result"] != material["result"]
            or event.payload["binding_event_id"] != request.binding_event_id
            or event.payload["aggregate_export_event_id"] != request.aggregate_export_event_id
            or event.payload["prior_qualification_event_ids"] != material["prior_qualification_event_ids"]
            or event.payload["implementation_evidence"] != native_refs(native_implementation())
            or event.evidence != refs(expected_evidence)):
        raise ValueError("native closure source qualification differs from exact frozen-method replay")
    policy = material["policy_material"]["policy"]
    snapshot = {"qualification_event_id": event.event_id, "recorded_at": event.recorded_at,
        "result_sha256": sha256_bytes(canonical_json_bytes(material["result"])),
        "binding_event_id": request.binding_event_id,
        "qualification_policy_event_id": material["policy_event"].event_id,
        "capture_plan_event_id": material["capture_plan_event"].event_id,
        "aggregate_export_event_id": material["aggregate_export_event"].event_id,
        "policy_status": policy.status, "continuity_event_id": policy.continuity_event_id,
        "cost_event_id": policy.cost_event_id, "risk_review_event_id": policy.risk_review_event_id,
        "training_cost_assumptions_evidence": policy.training_cost_assumptions_evidence,
        "result": material["result"]}
    related = {event.event_id, material["binding_event"].event_id, material["policy_event"].event_id,
        material["capture_plan_event"].event_id, material["aggregate_export_event"].event_id,
        material["parent"].event_id, material["policy_material"]["base"].event_id,
        material["links"]["intake_event_id"],
        *material["result"]["provenance"]["segment_event_ids"]}
    related.update(source.event_id for source in material["policy_material"]["sources"].values() if source is not None)
    _verify_retained_leaves((source for source in events if source.event_id in related), blobs, verified)
    return material, snapshot, related


def _same_scope(anchor, candidate):
    if (anchor["capture_plan_event"].event_id != candidate["capture_plan_event"].event_id
            or anchor["plan"].to_bytes() != candidate["plan"].to_bytes()
            or anchor["dataset"].to_bytes() != candidate["dataset"].to_bytes()
            or anchor["hypothesis"].to_bytes() != candidate["hypothesis"].to_bytes()
            or anchor["policy_material"]["policy"].evidence_scope != candidate["policy_material"]["policy"].evidence_scope
            or anchor["parent"].decision_id != candidate["parent"].decision_id):
        raise ValueError("closure candidate must preserve exact original plan, dataset, hypothesis and frozen capture scope")


def _source_findings(material, snapshot):
    native, policy = snapshot["result"], material["policy_material"]["policy"]
    sections = ("continuity", "training_calibration", "risk", "uncertainty_protocol", "training_calibration")
    source_ids = (
        [snapshot["qualification_policy_event_id"], policy.continuity_event_id],
        [snapshot["qualification_policy_event_id"], snapshot["aggregate_export_event_id"], policy.cost_event_id],
        [snapshot["qualification_policy_event_id"], policy.risk_review_event_id],
        [snapshot["qualification_policy_event_id"]],
        [snapshot["qualification_policy_event_id"], snapshot["aggregate_export_event_id"]],
    )
    statuses = (native["continuity"]["status"], native["training_calibration"]["status"],
        None if native["risk"]["native_assessment"] is None else native["risk"]["native_assessment"]["status"],
        native["uncertainty_status"], native["training_calibration"]["status"])
    reasons = (native["continuity"]["reason_codes"], native["training_calibration"]["reason_codes"], native["risk"]["reason_codes"],
        [reason for reason in native["reason_codes"] if "UNCERTAINTY" in reason or "STABILITY" in reason],
        [reason for reason in native["training_calibration"]["reason_codes"] if "COST" in reason or "SPREAD" in reason])
    statements = (
        "Original native continuity coverage and uncensored-window results are retained; supplemental source review does not replace independent effective-date coverage.",
        "Exact TRAIN spread extrema, declared fee/slippage assumptions and daily-volume proxy are retained; quotes do not prove cost applicability or opening fill capacity.",
        "Original shadow-only sizing review and joint continuity/capacity checks are retained; a review status cannot authorize orders or activate capital.",
        "The original declared uncertainty protocol and feasibility status are retained; no bootstrap, intervals, strategy support or holdout evaluation is performed.",
        "Every retained raw quote is accounted for by the original admission rule; wide spread witnesses and component exceedances are descriptive and never clipped or excluded.",
    )
    return [{"category": category, "source_qualification_event_id": snapshot["qualification_event_id"],
        "source_event_ids": sorted({snapshot["qualification_event_id"], *(value for value in source_ids[index] if value is not None)}),
        "native_value_pointer": "/payload/result/" + sections[index],
        "native_value_sha256": sha256_bytes(canonical_json_bytes(native[sections[index]])),
        "native_status": statuses[index], "native_reason_codes": sorted(set(reasons[index])), "statement": statements[index]}
        for index, category in enumerate(CATEGORIES)]


def review_native_evidence_closure(request, events, blobs):
    request = _document(request, NativeEvidenceClosureReviewRequest)
    events = _prefix(request, events)
    anchor_event = _event(events, request.anchor_qualification_event_id, ASSESSMENT_TYPE)
    verified = set()
    anchor, anchor_snapshot, related = _native_record(anchor_event, events, blobs, verified)
    candidate_event, candidate, candidate_snapshot = None, None, None
    if request.candidate_qualification_event_id is not None:
        candidate_event = _event(events, request.candidate_qualification_event_id, ASSESSMENT_TYPE)
        if events.index(candidate_event) <= events.index(anchor_event) or parse_rfc3339(candidate_event.recorded_at, "candidate clock") < parse_rfc3339(anchor_event.recorded_at, "anchor clock"):
            raise ValueError("closure candidate must be a distinct later immutable qualification")
        candidate, candidate_snapshot, candidate_related = _native_record(candidate_event, events, blobs, verified)
        _same_scope(anchor, candidate)
        related.update(candidate_related)
    selected, selected_snapshot = (candidate or anchor), (candidate_snapshot or anchor_snapshot)
    cutoff = parse_rfc3339(request.data_cutoff_at, "review cutoff")
    if any(parse_rfc3339(event.recorded_at, "selected source clock") > cutoff for event in events if event.event_id in related):
        raise ValueError("closure cutoff excludes a selected native source record")
    previous = [event for event in events if event.event_type == REVIEW_TYPE and event.payload["request"]["anchor_qualification_event_id"] == request.anchor_qualification_event_id]
    if any(parse_rfc3339(event.recorded_at, "prior review clock") > parse_rfc3339(request.recorded_at, "review clock") for event in previous):
        raise ValueError("closure review cannot backdate preceding same-anchor history")
    if request.supersedes_event_id is not None:
        superseded = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if superseded is None or any(event.payload["request"]["supersedes_event_id"] == superseded.event_id for event in previous):
            raise ValueError("closure supersession requires an unsuperseded same-anchor review")
        prior = superseded.payload["request"]
        if parse_rfc3339(prior["data_cutoff_at"], "prior cutoff") > cutoff:
            raise ValueError("closure supersession cannot move its cutoff backwards")
        prior_candidate = prior["candidate_qualification_event_id"]
        if prior_candidate is not None and (candidate_event is None or events.index(candidate_event) < next(index for index, event in enumerate(events) if event.event_id == prior_candidate)):
            raise ValueError("closure supersession cannot retreat its selected native candidate")
    evidence = {"native-closure/request.v1.json": request.to_bytes()}
    supplemental = None
    if request.supplemental_review_evidence is not None:
        reference = request.supplemental_review_evidence
        original_supplemental_bytes = _blob(blobs, reference)
        supplemental = NativeEvidenceSupplementalReview.from_bytes(original_supplemental_bytes)
        if supplemental.anchor_qualification_event_id != anchor_event.event_id or supplemental.candidate_qualification_event_id != request.candidate_qualification_event_id:
            raise ValueError("supplemental review must bind the exact anchor and candidate")
        supplemental_clock = parse_rfc3339(supplemental.recorded_at, "supplemental review clock")
        if supplemental_clock > cutoff or supplemental_clock < parse_rfc3339(selected_snapshot["recorded_at"], "selected qualification clock"):
            raise ValueError("supplemental review must follow selected qualification and precede cutoff")
        existing_hashes = {ref["sha256"] for event in events for ref in event.evidence}
        merge(evidence, {"native-closure/supplemental-review.v1.json": original_supplemental_bytes})
        for item in supplemental.categories:
            if not set(item["source_event_ids"]) <= related:
                raise ValueError("supplemental source event must belong to the exact selected native closure")
            for document in item["source_documents"]:
                raw = _blob(blobs, document["evidence"])
                if document["evidence"]["sha256"] == reference["sha256"]:
                    raise ValueError("supplemental review cannot cite itself as source evidence")
                if document["evidence"]["sha256"] not in existing_hashes:
                    merge(evidence, {"native-closure/support/" + document["evidence"]["sha256"] + ".raw": raw})
    anchor_diagnostics = diagnose_segmented_quotes(anchor["aggregate_export_event"], events, blobs)
    candidate_diagnostics = None if candidate is None else diagnose_segmented_quotes(candidate["aggregate_export_event"], events, blobs)
    old_reasons, new_reasons = set(anchor_snapshot["result"]["reason_codes"]), set(selected_snapshot["result"]["reason_codes"])
    result = validate_result({"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION, "review_id": request.review_id,
        "status": "DESCRIPTIVE_REVIEW_ONLY", "selected_qualification_event_id": selected_snapshot["qualification_event_id"],
        "anchor_qualification": anchor_snapshot, "candidate_qualification": candidate_snapshot,
        "reason_comparison": {"resolved_reason_codes": sorted(old_reasons - new_reasons), "persisting_reason_codes": sorted(old_reasons & new_reasons), "new_reason_codes": sorted(new_reasons - old_reasons)},
        "missing_prerequisites": sorted(new_reasons), "source_findings": _source_findings(selected, selected_snapshot),
        "supplemental_review": None if supplemental is None else supplemental.to_dict(),
        "anchor_diagnostics": anchor_diagnostics, "candidate_diagnostics": candidate_diagnostics,
        "native_gate_override": False, "supplemental_review_applied_to_native_gates": False,
        "reviewer_identity_authenticated": False, "source_applicability_verified": False,
        "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "uncertainty_computed": False, "economic_hypothesis_supported": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "limitations": sorted(LIMITATIONS), "auto_trading_enabled": False, "authority": AUTHORITY})
    links = validate_links({"anchor_qualification_event_id": anchor_event.event_id,
        "candidate_qualification_event_id": None if candidate_event is None else candidate_event.event_id,
        "selected_qualification_event_id": selected_snapshot["qualification_event_id"],
        "base_plan_event_id": selected["links"]["base_plan_event_id"], "hypothesis_event_id": selected["links"]["hypothesis_event_id"],
        "capture_plan_event_id": selected["capture_plan_event"].event_id,
        "selected_qualification_policy_event_id": selected["policy_event"].event_id,
        "selected_aggregate_export_event_id": selected["aggregate_export_event"].event_id})
    merge(evidence, implementation_evidence())
    return {"request": request, "result": result, "evidence": evidence, "parent": selected["parent"], "decision_id": selected["parent"].decision_id,
        "links": links, "prior_review_event_ids": sorted(event.event_id for event in previous)}
