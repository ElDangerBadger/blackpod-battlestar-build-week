"""Append-only v20 segmented qualification, with unchanged v18/v19 replay."""
from .contracts.decision_journal import JournalEvent
from .contracts.segmented_evidence_qualification import (
    JOURNAL_VERSION, BINDING_TYPE, ASSESSMENT_TYPE,
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_research_journal import identity
from .segmented_evidence_qualification import (
    binding_context, qualify_segmented_evidence, refs, merge, implementation_evidence,
)


def binding_material(binding, events, blobs):
    material = binding_context(binding, events, blobs)
    binding = material["binding"]
    event = JournalEvent.from_mapping({
        "schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {
            "decision_id": material["parent"].decision_id,
            "event_type": BINDING_TYPE, "binding_id": binding.binding_id}),
        "decision_id": material["parent"].decision_id,
        "event_type": BINDING_TYPE, "recorded_at": binding.recorded_at,
        "source": {"kind": "SEGMENTED_TRAIN_EVIDENCE_BINDING",
            "binding_id": binding.binding_id,
            "source_sha256": sha256_bytes(binding.to_bytes())},
        "evidence": refs(material["evidence"]),
        "payload": {"binding": binding.to_dict(), "links": material["links"],
            "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "evidence": material["evidence"]}


def qualification_material(request, events, blobs):
    request = (request if isinstance(request, SegmentedEvidenceQualificationRequest)
        else SegmentedEvidenceQualificationRequest.from_mapping(request))
    material = qualify_segmented_evidence(request, events, blobs)
    evidence = dict(material["evidence"])
    merge(evidence, {"segmented-qualification/result.v1.json":
        canonical_json_bytes(material["result"])})
    event = JournalEvent.from_mapping({
        "schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {
            "decision_id": material["parent"].decision_id,
            "event_type": ASSESSMENT_TYPE,
            "qualification_id": request.qualification_id}),
        "decision_id": material["parent"].decision_id,
        "event_type": ASSESSMENT_TYPE, "recorded_at": request.recorded_at,
        "source": {"kind": "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION",
            "qualification_id": request.qualification_id,
            "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence),
        "payload": {"request": request.to_dict(), "result": material["result"],
            "binding_event_id": request.binding_event_id,
            "aggregate_export_event_id": request.aggregate_export_event_id,
            "prior_qualification_event_ids": material["prior_qualification_event_ids"],
            "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "evidence": evidence, "result": material["result"]}


def build_binding_event(binding, events, blobs):
    return binding_material(binding, events, blobs)["event"]


def evidence_for_binding(binding, events, blobs):
    return binding_material(binding, events, blobs)["evidence"]


def build_qualification_event(request, events, blobs):
    return qualification_material(request, events, blobs)["event"]


def evidence_for_qualification(request, events, blobs):
    return qualification_material(request, events, blobs)["evidence"]


def validate_segmented_qualification_event(event, previous, blobs):
    if event.event_type == BINDING_TYPE:
        expected = build_binding_event(event.payload["binding"], previous, blobs)
    elif event.event_type == ASSESSMENT_TYPE:
        expected = build_qualification_event(event.payload["request"], previous, blobs)
    else:
        raise ValueError("unsupported segmented qualification event")
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("segmented qualification differs from exact retained-input replay")
