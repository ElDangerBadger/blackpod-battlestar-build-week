"""Append-only native evidence review, preserving original qualification gates."""
from .contracts.decision_journal import JournalEvent
from .contracts.native_evidence_closure import (
    JOURNAL_VERSION, REVIEW_TYPE, NativeEvidenceClosureReviewRequest,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_research_journal import identity
from .native_evidence_closure import (
    review_native_evidence_closure, implementation_evidence, refs, merge,
)


def review_material(request, events, blobs):
    request = (request if isinstance(request, NativeEvidenceClosureReviewRequest)
        else NativeEvidenceClosureReviewRequest.from_mapping(request))
    material = review_native_evidence_closure(request, events, blobs)
    evidence = dict(material["evidence"])
    merge(evidence, {"native-closure/result.v1.json": canonical_json_bytes(material["result"])})
    event = JournalEvent.from_mapping({
        "schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {
            "decision_id": material["parent"].decision_id,
            "event_type": REVIEW_TYPE, "review_id": request.review_id}),
        "decision_id": material["parent"].decision_id,
        "event_type": REVIEW_TYPE, "recorded_at": request.recorded_at,
        "source": {"kind": "TRADING_NATIVE_EVIDENCE_CLOSURE_REVIEW",
            "review_id": request.review_id,
            "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence),
        "payload": {"request": request.to_dict(), "result": material["result"],
            "links": material["links"],
            "prior_review_event_ids": material["prior_review_event_ids"],
            "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "evidence": evidence, "result": material["result"]}


def build_review_event(request, events, blobs):
    return review_material(request, events, blobs)["event"]


def evidence_for_review(request, events, blobs):
    return review_material(request, events, blobs)["evidence"]


def validate_native_closure_event(event, previous, blobs):
    if event.event_type != REVIEW_TYPE:
        raise ValueError("unsupported native evidence-closure event")
    expected = build_review_event(event.payload["request"], previous, blobs)
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("native evidence closure differs from exact retained-source replay")
