"""Additive v18 frozen qualification policy and linked assessment records."""
from .contracts.decision_journal import JournalEvent
from .contracts.trading_evidence_qualification import JOURNAL_VERSION, POLICY_TYPE, ASSESSMENT_TYPE
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_research_journal import identity
from .trading_evidence_qualification import policy_context, qualify_evidence, refs, merge, implementation_evidence


def policy_material(policy, events, blobs):
    material = policy_context(policy, events, blobs); policy = material["policy"]
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": material["parent"].decision_id, "event_type": POLICY_TYPE, "policy_id": policy.policy_id}),
        "decision_id": material["parent"].decision_id, "event_type": POLICY_TYPE, "recorded_at": policy.recorded_at,
        "source": {"kind": "TRADING_EVIDENCE_QUALIFICATION_POLICY", "policy_id": policy.policy_id, "source_sha256": sha256_bytes(policy.to_bytes())},
        "evidence": refs(material["evidence"]), "payload": {"policy": policy.to_dict(), "links": material["links"], "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "evidence": material["evidence"]}


def qualification_material(request, events, blobs):
    material = qualify_evidence(request, events, blobs)
    from .contracts.trading_evidence_qualification import TradingEvidenceQualificationRequest
    request = TradingEvidenceQualificationRequest.from_mapping(request.to_dict() if hasattr(request, "to_dict") else request)
    evidence = dict(material["evidence"]); merge(evidence, {"qualification/result.v1.json": canonical_json_bytes(material["result"])})
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": material["parent"].decision_id, "event_type": ASSESSMENT_TYPE, "qualification_id": request.qualification_id}),
        "decision_id": material["parent"].decision_id, "event_type": ASSESSMENT_TYPE, "recorded_at": request.recorded_at,
        "source": {"kind": "TRADING_EVIDENCE_QUALIFICATION", "qualification_id": request.qualification_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence), "payload": {"request": request.to_dict(), "result": material["result"], "policy_event_id": request.policy_event_id,
            "prior_qualification_event_ids": material["prior_qualification_event_ids"], "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "evidence": evidence, "result": material["result"]}


def build_policy_event(policy, events, blobs): return policy_material(policy, events, blobs)["event"]
def evidence_for_policy(policy, events, blobs): return policy_material(policy, events, blobs)["evidence"]
def build_qualification_event(request, events, blobs): return qualification_material(request, events, blobs)["event"]
def evidence_for_qualification(request, events, blobs): return qualification_material(request, events, blobs)["evidence"]


def validate_qualification_event(event, previous, blobs):
    expected = (build_policy_event(event.payload["policy"], previous, blobs) if event.event_type == POLICY_TYPE
                else build_qualification_event(event.payload["request"], previous, blobs))
    if expected.to_bytes() != event.to_bytes(): raise ValueError("qualification differs from frozen retained-input replay")
