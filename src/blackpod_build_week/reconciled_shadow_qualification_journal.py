"""Exact retained-source projection; publication verifies the complete history.

An exact v23 intake supplies additional research vetoes. This module never
replaces a native result, establishes a trusted verification cache, or grants
study, policy, capital or execution authority.
"""
from pathlib import Path

from .contracts.decision_journal import JournalEvent
from .contracts.reconciled_action_journal import POLICY_TYPE, INTAKE_TYPE
from .contracts.reconciled_shadow_qualification_journal import (
    JOURNAL_VERSION, TYPE, KIND, validate_links, validate_source_snapshot,
)
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import identity, _blob
from .evidence_reconciliation import refs, merge
from .reconciled_action_journal import (
    CODE_PATHS as INTAKE_CODE_PATHS, POLICY_PATH, RESULT_PATH as INTAKE_RESULT_PATH,
    _history, _event, _leaf, source_context as native_source_context,
    validate_reconciled_action_event,
)

REQUEST_PATH = "reconciled-shadow-qualification/request.v1.json"
RESULT_PATH = "reconciled-shadow-qualification/result.v1.json"
CODE_PATHS = tuple(dict.fromkeys((
    "contracts/reconciled_shadow_qualification_journal.py", "reconciled_shadow_qualification_journal.py",
    "contracts/reconciled_shadow_qualification.py", "reconciled_shadow_qualification.py",
    "contracts/segmented_evidence_qualification.py", "contracts/trading_research.py",
    *INTAKE_CODE_PATHS,
)))


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"reconciled-shadow-qualification/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def source_context(intake_event_id, events, blobs):
    """Bind exact source leaves; no full-history verification is claimed here."""
    from .contracts.reconciled_action_intake import ReconciledActionIntakePolicy
    events = _history(events)
    intake = _event(events, intake_event_id, INTAKE_TYPE)
    earlier = events[:events.index(intake)]
    policy_event = _event(earlier, intake.payload["links"]["policy_event_id"], POLICY_TYPE)
    before_policy = earlier[:earlier.index(policy_event)]
    for source in (policy_event, intake):
        for reference in source.evidence:
            _blob(blobs, reference)
    validate_reconciled_action_event(policy_event, before_policy, blobs)
    validate_reconciled_action_event(intake, earlier, blobs)
    policy_ref, policy_raw = _leaf(policy_event, POLICY_PATH, blobs)
    policy = ReconciledActionIntakePolicy.from_bytes(policy_raw)
    intake_ref, intake_raw = _leaf(intake, INTAKE_RESULT_PATH, blobs)
    if intake_raw != canonical_json_bytes(intake.payload["result"]):
        raise ValueError("selected intake differs from its original retained result")
    native_context = native_source_context(policy.anchor_review_event_id, before_policy, blobs)
    native, anchor = native_context["native"], native_context["anchor"]
    snapshot = intake.payload["anchor_snapshot"]["native_qualification_snapshot"]
    if (snapshot != native.payload["result"] or intake.decision_id != native.decision_id
            or intake.decision_id != policy_event.decision_id
            or intake.payload["result"]["policy_evidence"] != policy_ref):
        raise ValueError("selected intake has different native or policy lineage")
    native_ref, native_raw = _leaf(native, "segmented-qualification/result.v1.json", blobs)
    if native_raw != canonical_json_bytes(snapshot):
        raise ValueError("selected native result differs from its retained leaf")
    links = validate_links({"intake_event_id": intake.event_id, "policy_event_id": policy_event.event_id,
        **native_context["links"]})
    source_snapshot = validate_source_snapshot({"intake_event_sha256": sha256_bytes(intake.to_bytes()),
        "intake_result_sha256": sha256_bytes(intake_raw), "policy_event_sha256": sha256_bytes(policy_event.to_bytes()),
        "native_qualification_event_sha256": sha256_bytes(native.to_bytes()),
        "anchor_review_event_sha256": sha256_bytes(anchor.to_bytes())})
    return {"intake": intake, "policy_event": policy_event, "policy": policy,
        "native": native, "anchor": anchor, "continuity": native_context["continuity"],
        "links": links, "source_snapshot": source_snapshot, "intake_result_ref": intake_ref,
        "intake_result": intake.payload["result"], "native_snapshot": snapshot,
        "native_result_ref": native_ref, "dataset_evidence": policy.dataset_evidence,
        "evidence_scope": policy.evidence_scope}


def _prefix(request, events):
    events = _history(events)
    prior = [event for event in events if event.event_type == TYPE and event.source["qualification_id"] == request.qualification_id]
    if len(prior) > 1:
        raise ValueError("shadow qualification identity is ambiguous")
    if prior:
        if prior[0].payload["request"] != request.to_dict():
            raise ValueError("shadow qualification identity is immutable")
        events = events[:events.index(prior[0])]
    return events


def qualification_material(request, events, blobs):
    from .contracts.reconciled_shadow_qualification import ReconciledShadowQualificationRequest
    from .reconciled_shadow_qualification import qualify_reconciled_overlay
    request = request if isinstance(request, ReconciledShadowQualificationRequest) else ReconciledShadowQualificationRequest.from_mapping(request)
    events = _prefix(request, events)
    context = source_context(request.intake_event_id, events, blobs)
    if request.intake_result_evidence != context["intake_result_ref"]:
        raise ValueError("shadow qualification must select the exact recorded intake result leaf")
    cutoff = parse_rfc3339(request.data_cutoff_at, "shadow qualification cutoff")
    if any(parse_rfc3339(context[key].recorded_at, "selected source clock") > cutoff
            for key in ("intake", "policy_event", "native", "anchor", "continuity")):
        raise ValueError("shadow qualification cutoff excludes a selected source event")
    previous = [event for event in events if event.event_type == TYPE
        and event.payload["links"]["anchor_review_event_id"] == context["anchor"].event_id]
    if any(parse_rfc3339(event.recorded_at, "prior qualification clock") > parse_rfc3339(request.recorded_at, "qualification clock") for event in previous):
        raise ValueError("shadow qualification cannot backdate same-anchor history")
    if request.supersedes_event_id is not None:
        old = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if old is None or any(event.payload["request"]["supersedes_event_id"] == old.event_id for event in previous):
            raise ValueError("shadow qualification supersession requires an unsuperseded same-anchor record")
        if parse_rfc3339(old.payload["request"]["data_cutoff_at"], "prior cutoff") > cutoff:
            raise ValueError("shadow qualification supersession cannot retreat its cutoff")
    material = qualify_reconciled_overlay(request, context["intake_result"], context["native_snapshot"], blobs)
    evidence = dict(material["evidence"])
    merge(evidence, {REQUEST_PATH: request.to_bytes(), RESULT_PATH: canonical_json_bytes(material["result"])})
    implementation = implementation_evidence()
    merge(evidence, implementation)
    retained = {ref["sha256"] for event in events for ref in event.evidence}
    evidence = {path: raw for path, raw in evidence.items()
        if sha256_bytes(raw) not in retained or path.startswith("reconciled-shadow-qualification/")}
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": context["intake"].decision_id,
            "event_type": TYPE, "qualification_id": request.qualification_id}),
        "decision_id": context["intake"].decision_id, "event_type": TYPE, "recorded_at": request.recorded_at,
        "source": {"kind": KIND, "qualification_id": request.qualification_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence), "payload": {"request": request.to_dict(), "result": material["result"],
            "links": context["links"], "source_snapshot": context["source_snapshot"],
            "prior_qualification_event_ids": sorted(event.event_id for event in previous),
            "implementation_evidence": refs(implementation)}})
    return {"event": event, "result": material["result"], "evidence": evidence}


def validate_reconciled_shadow_qualification_event(event, previous, blobs):
    expected = qualification_material(event.payload["request"], previous, blobs)["event"]
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("shadow qualification differs from exact retained-source replay")
