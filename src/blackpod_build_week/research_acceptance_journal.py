"""Append-only v17 assessments on original hypothesis decision histories."""
from .contracts.decision_journal import JournalEvent
from .contracts.research_assessment import EVENT_TYPE, EVENT_VERSION
from .research_acceptance import assess_research, assessment_context, merge_evidence, refs
from .trading_research_journal import identity
from .hashing import sha256_bytes


def assessment_material(request, events, blobs):
    request, previous, source, _ = assessment_context(request, events)
    material = assess_research(request, previous, blobs)
    evidence = dict(material["evidence"])
    merge_evidence(evidence, {"research-acceptance/assessment.v1.json": material["assessment"].to_bytes()})
    event = JournalEvent.from_mapping({"schema_version": EVENT_VERSION,
        "event_id": identity("journal-event", {"decision_id": source.decision_id, "event_type": EVENT_TYPE, "assessment_id": request.assessment_id}),
        "decision_id": source.decision_id, "domain": request.domain, "event_type": EVENT_TYPE,
        "recorded_at": request.recorded_at,
        "source": {"kind": "RESEARCH_ASSESSMENT", "assessment_id": request.assessment_id, "hypothesis_id": request.hypothesis["hypothesis_id"], "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence), "payload": {"request": request.to_dict(), "assessment": material["assessment"].to_dict(), "prior_assessment_event_ids": material["prior_assessment_event_ids"]}})
    return {"event": event, "evidence": evidence, "assessment": material["assessment"]}


def build_assessment_event(request, events, blobs):
    return assessment_material(request, events, blobs)["event"]


def evidence_for_assessment(request, events, blobs):
    return assessment_material(request, events, blobs)["evidence"]


def validate_assessment_event(event, previous_events, blobs):
    expected = build_assessment_event(event.payload["request"], previous_events, blobs)
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("research assessment differs from exact frozen evidence and methodology replay")
