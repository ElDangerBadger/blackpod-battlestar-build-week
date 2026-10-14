"""Candidate projection and append-only lineage; storage verifies full history.

Projection can prepare an untrusted candidate from retained, hash-bound inputs.
Only the existing journal verifier establishes the complete history's validity
before publication. No source snapshot is a trusted verification cache.
"""
from pathlib import Path

from .contracts.decision_journal import JournalEvent
from .contracts.evidence_reconciliation import REVIEW_TYPE as ANCHOR_TYPE
from .contracts.reconciled_action_journal import (
    JOURNAL_VERSION, POLICY_TYPE, INTAKE_TYPE, POLICY_KIND, INTAKE_KIND, validate_links,
)
from .contracts.mission_request import parse_rfc3339
from .evidence_reconciliation import CODE_PATHS as PRIOR_CODE_PATHS, refs, merge
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, identity

POLICY_PATH = "reconciled-actions/policy.v1.json"
REQUEST_PATH = "reconciled-actions/request.v1.json"
RESULT_PATH = "reconciled-actions/result.v1.json"
MASKS_PATH = "reconciled-actions/original-native-masks.v1.json"
CODE_PATHS = tuple(dict.fromkeys((
    "contracts/reconciled_action_journal.py", "reconciled_action_journal.py",
    "contracts/reconciled_action_intake.py", "reconciled_action_intake.py",
    "contracts/qqq_distribution_inventory.py", "qqq_distribution_inventory.py",
    *PRIOR_CODE_PATHS,
)))


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"reconciled-actions/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _event(events, event_id, event_type):
    found = [event for event in events if event.event_id == event_id and event.event_type == event_type and event.domain == "TRADING"]
    if len(found) != 1:
        raise ValueError("reconciled intake requires one exact preceding TRADING source")
    return found[0]


def _leaf(event, path, blobs):
    found = [ref for ref in event.evidence if ref["path"] == path]
    if len(found) != 1:
        raise ValueError("reconciled intake requires the original retained source leaf")
    return found[0], _blob(blobs, found[0])


def _history(events):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("reconciled action history has duplicate identities")
    return events


def _prefix(document, events, event_type, field):
    events = _history(events)
    found = [event for event in events if event.event_type == event_type and event.source[field] == getattr(document, field)]
    if len(found) > 1:
        raise ValueError("reconciled action identity is ambiguous")
    if found:
        key = "policy" if event_type == POLICY_TYPE else "request"
        if found[0].payload[key] != document.to_dict():
            raise ValueError("reconciled action identity is immutable")
        events = events[:events.index(found[0])]
    return events


def source_context(anchor_review_event_id, events, blobs):
    """Bind an exact v22 report; no full-history verification is claimed here."""
    events = _history(events)
    anchor = _event(events, anchor_review_event_id, ANCHOR_TYPE)
    earlier = events[:events.index(anchor)]
    _, raw = _leaf(anchor, "independent-evidence/result.v1.json", blobs)
    if raw != canonical_json_bytes(anchor.payload["result"]):
        raise ValueError("v22 anchor result differs from original retained bytes")
    report = anchor.payload["result"]
    native = _event(earlier, report["selected_qualification_event_id"], "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_RECORDED")
    snapshot = report["native_qualification_snapshot"]
    if native.decision_id != anchor.decision_id or native.payload["result"] != snapshot:
        raise ValueError("v22 anchor no longer binds its exact original qualification")
    native_hash = sha256_bytes(canonical_json_bytes(snapshot))
    if native_hash != report["native_qualification_result_sha256"]:
        raise ValueError("original native qualification hash differs")
    _, native_raw = _leaf(native, "segmented-qualification/result.v1.json", blobs)
    if native_raw != canonical_json_bytes(snapshot):
        raise ValueError("original native result leaf differs")
    continuity = _event(earlier, anchor.payload["links"]["continuity_event_id"], "TRADING_CONTINUITY_INTAKE_RECORDED")
    native_ref, export_raw = _leaf(continuity, "continuity-intake/export.v1.json", blobs)
    effective = report["effective_date_reconciliation"]
    if (native_ref != effective["native_continuity_export_evidence"]
            or export_raw != canonical_json_bytes(continuity.payload["export"])):
        raise ValueError("reconciled intake must preserve the exact original native export")
    dataset_ref = report["source_context"]["dataset_evidence"]
    if dataset_ref != effective["dataset_evidence"] or continuity.payload["export"]["dataset_evidence"] != dataset_ref:
        raise ValueError("original native dataset binding differs")
    _blob(blobs, dataset_ref)
    masks = snapshot["continuity"]
    if not isinstance(masks, dict) or "native_action_audit" not in masks:
        raise ValueError("v22 anchor has no retained native mask assessment to preserve")
    masks_raw = canonical_json_bytes(masks)
    if masks["native_action_audit"] != continuity.payload["export"]["native_actions"]:
        raise ValueError("original mask snapshot has a different native action audit")
    for event in (anchor, native, continuity):
        for ref in event.evidence:
            _blob(blobs, ref)
    links = validate_links({"anchor_review_event_id": anchor.event_id,
        "continuity_event_id": continuity.event_id, "selected_qualification_event_id": native.event_id})
    return {"anchor": anchor, "native": native, "continuity": continuity, "links": links,
        "dataset_evidence": dataset_ref, "native_continuity_export_evidence": native_ref,
        "original_native_masks_evidence": _reference(MASKS_PATH, masks_raw), "masks_raw": masks_raw,
        "evidence_scope": continuity.payload["export"]["evidence_scope"],
        "independent_inventories": [item["manifest_evidence"] for item in effective["source_inventory"]],
        "anchor_snapshot": {"anchor_event_sha256": sha256_bytes(anchor.to_bytes()),
            "anchor_result_sha256": sha256_bytes(raw), "native_qualification_snapshot": snapshot,
            "native_qualification_result_sha256": native_hash}}


def _check_policy(policy, events, blobs):
    context = source_context(policy.anchor_review_event_id, events, blobs)
    for key in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence", "evidence_scope"):
        if getattr(policy, key) != context[key]:
            raise ValueError("policy changes its original v22 " + key)
    if any(ref not in policy.independent_inventories for ref in context["independent_inventories"]):
        raise ValueError("frozen policy cannot drop an original v22 independent inventory")
    if _blob(blobs, policy.original_native_masks_evidence) != context["masks_raw"]:
        raise ValueError("frozen policy rewrites original native masks")
    if parse_rfc3339(context["anchor"].recorded_at, "anchor clock") > parse_rfc3339(policy.recorded_at, "policy clock"):
        raise ValueError("frozen policy predates its original v22 review")
    return context


def prepare_policy(anchor_review_event_id, policy_id, recorded_at, independent_inventories, events, blobs):
    from .contracts.reconciled_action_intake import ReconciledActionIntakePolicy, POLICY_CONSTANTS, AUTHORITY
    context = source_context(anchor_review_event_id, events, blobs)
    value = {**POLICY_CONSTANTS, "policy_id": policy_id, "recorded_at": recorded_at,
        "anchor_review_event_id": anchor_review_event_id, "independent_inventories": independent_inventories,
        **{key: context[key] for key in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence", "evidence_scope")},
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)}
    policy = ReconciledActionIntakePolicy.from_mapping(value)
    candidate_blobs = {**blobs, sha256_bytes(context["masks_raw"]): context["masks_raw"]}
    material = policy_material(policy, events, candidate_blobs)
    return {**material, "policy": policy}


def _new_evidence(evidence, events):
    existing = {ref["sha256"] for event in events for ref in event.evidence}
    return {path: raw for path, raw in evidence.items() if sha256_bytes(raw) not in existing or path.startswith("reconciled-actions/")}


def policy_material(policy, events, blobs):
    from .contracts.reconciled_action_intake import ReconciledActionIntakePolicy
    from .reconciled_action_intake import inspect_policy_sources
    policy = policy if isinstance(policy, ReconciledActionIntakePolicy) else ReconciledActionIntakePolicy.from_mapping(policy)
    events = _prefix(policy, events, POLICY_TYPE, "policy_id")
    context = _check_policy(policy, events, blobs)
    inspected = inspect_policy_sources(policy, blobs)
    evidence = dict(inspected["evidence"])
    merge(evidence, {POLICY_PATH: policy.to_bytes(), MASKS_PATH: context["masks_raw"]})
    merge(evidence, implementation_evidence())
    evidence = _new_evidence(evidence, events)
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": context["anchor"].decision_id, "event_type": POLICY_TYPE, "policy_id": policy.policy_id}),
        "decision_id": context["anchor"].decision_id, "event_type": POLICY_TYPE, "recorded_at": policy.recorded_at,
        "source": {"kind": POLICY_KIND, "policy_id": policy.policy_id, "source_sha256": sha256_bytes(policy.to_bytes())},
        "evidence": refs(evidence), "payload": {"policy": policy.to_dict(), "links": context["links"],
            "anchor_snapshot": context["anchor_snapshot"], "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "policy": policy, "evidence": evidence}


def intake_material(request, events, blobs):
    from .contracts.reconciled_action_intake import ReconciledActionIntakePolicy, ReconciledActionIntakeRequest
    from .reconciled_action_intake import build_reconciled_action_intake
    request = request if isinstance(request, ReconciledActionIntakeRequest) else ReconciledActionIntakeRequest.from_mapping(request)
    events = _prefix(request, events, INTAKE_TYPE, "intake_id")
    policy_event = _event(events, request.policy_event_id, POLICY_TYPE)
    policy = ReconciledActionIntakePolicy.from_bytes(_blob(blobs, request.policy_evidence))
    if policy.to_dict() != policy_event.payload["policy"]:
        raise ValueError("intake selects a different frozen policy")
    policy_ref, policy_raw = _leaf(policy_event, POLICY_PATH, blobs)
    if policy_ref != request.policy_evidence or policy_raw != policy.to_bytes():
        raise ValueError("intake must select the exact recorded policy leaf")
    context = _check_policy(policy, events[:events.index(policy_event)], blobs)
    if policy_event.decision_id != context["anchor"].decision_id:
        raise ValueError("intake policy belongs to a different research decision")
    previous = [event for event in events if event.event_type == INTAKE_TYPE
        and event.payload["links"]["anchor_review_event_id"] == policy.anchor_review_event_id]
    cutoff = parse_rfc3339(request.data_cutoff_at, "intake cutoff")
    if any(parse_rfc3339(event.recorded_at, "prior intake clock") > parse_rfc3339(request.recorded_at, "intake clock") for event in previous):
        raise ValueError("intake cannot backdate same-anchor history")
    if request.supersedes_event_id is not None:
        prior = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if prior is None or any(event.payload["request"]["supersedes_event_id"] == prior.event_id for event in previous):
            raise ValueError("intake supersession requires an unsuperseded same-anchor record")
        if parse_rfc3339(prior.payload["request"]["data_cutoff_at"], "prior cutoff") > cutoff:
            raise ValueError("intake supersession cannot retreat its cutoff")
    material = build_reconciled_action_intake(policy, request, blobs)
    evidence = dict(material["evidence"])
    merge(evidence, {REQUEST_PATH: request.to_bytes(), RESULT_PATH: canonical_json_bytes(material["result"])})
    merge(evidence, implementation_evidence())
    evidence = _new_evidence(evidence, events)
    links = validate_links({**context["links"], "policy_event_id": policy_event.event_id}, intake=True)
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION, "domain": "TRADING",
        "event_id": identity("journal-event", {"decision_id": context["anchor"].decision_id, "event_type": INTAKE_TYPE, "intake_id": request.intake_id}),
        "decision_id": context["anchor"].decision_id, "event_type": INTAKE_TYPE, "recorded_at": request.recorded_at,
        "source": {"kind": INTAKE_KIND, "intake_id": request.intake_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": refs(evidence), "payload": {"request": request.to_dict(), "result": material["result"], "links": links,
            "anchor_snapshot": context["anchor_snapshot"], "prior_intake_event_ids": sorted(event.event_id for event in previous),
            "implementation_evidence": refs(implementation_evidence())}})
    return {"event": event, "result": material["result"], "evidence": evidence}


def validate_reconciled_action_event(event, previous, blobs):
    if event.event_type == POLICY_TYPE:
        expected = policy_material(event.payload["policy"], previous, blobs)["event"]
    elif event.event_type == INTAKE_TYPE:
        expected = intake_material(event.payload["request"], previous, blobs)["event"]
    else:
        raise ValueError("unsupported reconciled action event")
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("reconciled action event differs from exact retained-source replay")
