"""Immutable v22 projection; source findings do not change native decisions."""
from .contracts.decision_journal import JournalEvent
from .contracts.evidence_reconciliation import EvidenceReconciliationRequest, JOURNAL_VERSION, REVIEW_TYPE, SOURCE_KIND
from .evidence_reconciliation import assess_evidence_reconciliation, implementation_evidence, refs, merge
from .trading_research_journal import identity
from .hashing import canonical_json_bytes, sha256_bytes


def review_material(request, events, blobs):
    request = request if isinstance(request, EvidenceReconciliationRequest) else EvidenceReconciliationRequest.from_mapping(request)
    material = assess_evidence_reconciliation(request, events, blobs)
    evidence = dict(material["evidence"])
    merge(evidence, {"independent-evidence/result.v1.json": canonical_json_bytes(material["result"])})
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": material["parent"].decision_id,
            "event_type": REVIEW_TYPE, "review_id": request.review_id}),
        "decision_id": material["parent"].decision_id, "event_type": REVIEW_TYPE,
        "recorded_at": request.recorded_at,
        "source": {"kind": SOURCE_KIND, "review_id": request.review_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence), "payload": {"request": request.to_dict(), "result": material["result"],
            "links": material["links"], "prior_review_event_ids": material["prior_review_event_ids"],
            "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "result": material["result"], "evidence": evidence}


def build_review_event(request, events, blobs):
    return review_material(request, events, blobs)["event"]


def evidence_for_review(request, events, blobs):
    return review_material(request, events, blobs)["evidence"]


def validate_evidence_reconciliation_event(event, previous, blobs):
    if event.event_type != REVIEW_TYPE:
        raise ValueError("unsupported independent evidence event")
    expected = build_review_event(event.payload["request"], previous, blobs)
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("independent reconciliation differs from exact retained-source replay")
