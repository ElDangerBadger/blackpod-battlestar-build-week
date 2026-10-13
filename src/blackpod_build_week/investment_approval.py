"""Pure declared-human review of exact, non-executable SHADOW proposals.

Approval grants research status only. Identity strings are not authentication.
Every check is reproduced against the history that preceded the original event;
later revocation or expiry cannot change the bytes of an idempotent retry.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.investment_governance import (
    ApprovalInput, ProposalInput, SHADOW_APPROVAL_SCOPE, validate_approval_decision,
)
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes

APPROVAL_EVENT_TYPE = "INVESTMENT_SHADOW_APPROVAL_RECORDED"
PROPOSAL_EVENT_TYPE = "INVESTMENT_DECISION_PROPOSAL_RECORDED"


class ApprovalEvidenceError(ValueError):
    """A declared approval is not bound to a currently reviewable proposal."""


def _time(value: str):
    return parse_rfc3339(value, "approval timestamp")


def _identity(prefix: str, value: object) -> str:
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _event_id(approval: ApprovalInput, proposal_event: JournalEvent) -> str:
    return _identity("journal-event", {"decision_id": proposal_event.decision_id,
        "event_type": APPROVAL_EVENT_TYPE, "approval_id": approval.approval_id})


def _indexed(events: Sequence[JournalEvent]) -> dict[str, JournalEvent]:
    result = {}
    for event in events:
        if event.event_id in result:
            raise ApprovalEvidenceError("journal contains ambiguous event identities")
        result[event.event_id] = event
    return result


def _parent(approval: ApprovalInput, events: Sequence[JournalEvent], blobs: Mapping[str, bytes]):
    # Imports are deliberately local: importing the journal never starts a
    # provider, model, live stage workflow, or executor.
    from .investment_governance import proposal_context, validate_proposal_event

    index = _indexed(events)
    parent = index.get(approval.proposal_event_id)
    if parent is None or parent.schema_version != "blackpod.decision_journal_event.v4" or parent.event_type != PROPOSAL_EVENT_TYPE:
        raise ApprovalEvidenceError("approval requires an existing v4 investment proposal")
    proposal = ProposalInput.from_mapping(parent.payload["proposal"])
    if proposal.proposal_id != approval.proposal_id or parent.source["source_sha256"] != approval.proposal_sha256:
        raise ApprovalEvidenceError("approval proposal identity or canonical input hash mismatch")
    position = next(i for i, event in enumerate(events) if event.event_id == parent.event_id)
    try:
        validate_proposal_event(parent, events[:position], blobs)
        context = proposal_context(proposal, events[:position], blobs)
    except ValueError as exc:
        raise ApprovalEvidenceError(str(exc)) from exc
    if blobs.get(approval.proposal_sha256) != proposal.to_bytes():
        raise ApprovalEvidenceError("approval requires retained canonical proposal bytes")
    report = parent.payload["report"]
    exact_hashes = {
        "risk_policy_sha256": report["risk_policy_sha256"],
        "risk_context_sha256": report["risk_context_sha256"],
        "report_sha256": sha256_bytes(canonical_json_bytes(report)),
    }
    for field, expected in exact_hashes.items():
        if getattr(approval, field) != expected:
            raise ApprovalEvidenceError("approval " + field + " does not bind the exact proposal report")
    # Existing retries use precisely their original prefix. A changed input
    # with that identity still builds different bytes and conflicts at storage.
    retry_id = _event_id(approval, parent)
    retry = next((i for i, event in enumerate(events) if event.event_id == retry_id), None)
    if retry is not None:
        return _parent(approval, events[:retry], blobs)
    return parent, proposal, context, tuple(events)


def _active_reviews(events: Sequence[JournalEvent], hypothesis_event_id: str, cutoff: str):
    eligible = [event for event in events if event.event_type in {
        "INVESTMENT_CHALLENGE_RECORDED", "INVESTMENT_OUTCOME_EVALUATION_RECORDED"}
        and _time(event.recorded_at) <= _time(cutoff)]
    relevant = []
    for event in eligible:
        key = "challenge" if event.event_type == "INVESTMENT_CHALLENGE_RECORDED" else "evaluation"
        if event.payload[key]["hypothesis_event_id"] == hypothesis_event_id:
            relevant.append(event)
    superseded = {event.payload["challenge" if event.event_type == "INVESTMENT_CHALLENGE_RECORDED" else "evaluation"]["supersedes_event_id"]
                  for event in relevant}
    return tuple(event for event in relevant if event.event_id not in superseded)


def _fresh_packet(approval: ApprovalInput, parent: JournalEvent, proposal: ProposalInput,
                  context: Mapping[str, Any], events: Sequence[JournalEvent],
                  blobs: Mapping[str, bytes]) -> None:
    now = _time(approval.recorded_at)
    policy = proposal.risk_policy
    if now > _time(proposal.valid_until):
        raise ApprovalEvidenceError("proposal is expired at approval recorded_at")
    if (now - _time(proposal.risk_context["as_of"])).total_seconds() > policy["max_context_age_seconds"]:
        raise ApprovalEvidenceError("risk context is stale at approval recorded_at")
    if now >= _time(context["hypothesis"].horizon["end_at"]):
        raise ApprovalEvidenceError("hypothesis horizon has ended")
    expiry = _time(approval.expires_at)
    if expiry > _time(proposal.valid_until) or (expiry - now).total_seconds() > policy["max_approval_lifetime_seconds"]:
        raise ApprovalEvidenceError("approval expiry exceeds proposal validity or policy lifetime")
    active = _active_reviews(events, proposal.hypothesis_event_id, approval.recorded_at)
    active_ids = {event.event_id for event in active}
    if proposal.challenge_event_id not in active_ids or (proposal.evaluation_event_id is not None and proposal.evaluation_event_id not in active_ids):
        raise ApprovalEvidenceError("selected challenge or evaluation has been superseded")
    for event in active:
        if event.event_type == "INVESTMENT_CHALLENGE_RECORDED":
            challenge = event.payload["challenge"]
            if (challenge["disposition"] != "REVIEW_SUPPORTS" or challenge["unresolved_questions"] or
                    any(item["status"] != "SUPPORTED" for item in challenge["assumption_reviews"])):
                raise ApprovalEvidenceError("active challenge does not provide unqualified support")
        else:
            result = event.payload["result"]
            if result["comparison_summary"] == "INVALIDATION_TRIGGERED":
                raise ApprovalEvidenceError("known active evaluation triggers hypothesis invalidation")
            if (result["comparison_summary"] == "EXPECTATIONS_NOT_MET" or
                    any(check["status"] == "NOT_MET" for check in result["check_results"])):
                raise ApprovalEvidenceError("known active evaluation has unmet expectations")
    for event in events:
        if event.event_type != PROPOSAL_EVENT_TYPE or _time(event.recorded_at) > now:
            continue
        other = event.payload["proposal"]
        if other["supersedes_event_id"] == parent.event_id:
            raise ApprovalEvidenceError("proposal has been superseded")
        packet = other["risk_context"]
        if (packet["portfolio_scope_id"] == proposal.risk_context["portfolio_scope_id"]
                and _time(packet["as_of"]) > _time(proposal.risk_context["as_of"])):
            raise ApprovalEvidenceError("a newer known portfolio context requires a new proposal")
    # Reuse the policy's complete deterministic gate at approval time, without
    # changing or retaining a modified proposal. This also verifies newly known
    # source-bound challenge and evaluation records.
    from .investment_governance import assess_proposal
    current = proposal.to_dict()
    current.update(recorded_at=approval.recorded_at, evidence_cutoff_at=approval.recorded_at)
    try:
        report = assess_proposal(ProposalInput.from_mapping(current), events, blobs)
    except ValueError as exc:
        raise ApprovalEvidenceError(str(exc)) from exc
    if report["gate"] != "REVIEW_READY":
        raise ApprovalEvidenceError("proposal risk gate changed since its recorded evidence snapshot")


def assess_approval(approval: ApprovalInput, events: Sequence[JournalEvent],
                    blobs: Mapping[str, bytes]) -> dict[str, Any]:
    """Validate exact binding, role separation, lifecycle, and positive gate."""
    approval = ApprovalInput.from_mapping(approval.to_dict())
    parent, proposal, context, history = _parent(approval, events, blobs)
    if _time(approval.recorded_at) < _time(proposal.recorded_at):
        raise ApprovalEvidenceError("approval cannot predate its proposal")
    policy = proposal.risk_policy
    if approval.approver_id not in policy["authorized_approver_ids"] or approval.approver_role != policy["required_approver_role"]:
        raise ApprovalEvidenceError("approver ID and role must match the exact bound risk policy")
    actors = {proposal.submitted_by, context["hypothesis"].author_id,
              context["challenge_event"].payload["challenge"]["reviewer_id"]}
    if context["evaluation_event"] is not None:
        actors.add(context["evaluation_event"].payload["evaluation"]["evaluator_id"])
    if approval.approver_id in actors:
        raise ApprovalEvidenceError("approver must differ from submitter, author, challenger, and evaluator")
    prior = [event for event in history if event.event_type == APPROVAL_EVENT_TYPE
             and event.payload["approval"]["proposal_event_id"] == parent.event_id]
    if approval.action == "REVOKE":
        target = next((event for event in prior if event.event_id == approval.revokes_approval_event_id), None)
        if target is None or target.payload["approval"]["action"] != "APPROVE":
            raise ApprovalEvidenceError("revocation requires the earlier APPROVE for this exact proposal")
        if any(event.payload["approval"]["action"] == "REVOKE" for event in prior):
            raise ApprovalEvidenceError("an approval can be revoked only once")
        if _time(approval.recorded_at) < _time(target.recorded_at):
            raise ApprovalEvidenceError("revocation cannot predate the approval")
    elif prior:
        raise ApprovalEvidenceError("proposal already has a review action; create a new proposal to reconsider")
    if approval.action == "APPROVE":
        if parent.payload["report"]["gate"] != "REVIEW_READY":
            raise ApprovalEvidenceError("APPROVE cannot bypass REJECT or DEFER risk gates")
        if not set(parent.payload["report"]["residual_risks"]) <= set(approval.acknowledged_residual_risks):
            raise ApprovalEvidenceError("approval must acknowledge every recorded residual risk")
        _fresh_packet(approval, parent, proposal, context, history, blobs)
    result = {"REJECT": "REJECTED", "DEFER": "DEFERRED", "REVOKE": "REVOKED"}.get(approval.action)
    if approval.action == "APPROVE":
        result = "SIMULATED_SHADOW_APPROVED" if approval.origin == "SIMULATED_TEST" else "SHADOW_RESEARCH_APPROVED"
    return validate_approval_decision({
        "action": approval.action, "result": result, "origin": approval.origin,
        "scope": approval.scope, "expires_at": approval.expires_at,
        "approver_identity_authenticated": False, "operational_authority_granted": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "authority": approval.authority,
    }, approval)


def evidence_for_approval(approval: ApprovalInput, events: Sequence[JournalEvent],
                          blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    """Retain canonical input and the exact reviewed packet, without reads."""
    assess_approval(approval, events, blobs)
    parent, proposal, _, _ = _parent(approval, events, blobs)
    evidence = {reference["path"]: blobs[reference["sha256"]] for reference in parent.evidence}
    evidence[f"proposals/{proposal.proposal_id}/proposal_event.json"] = parent.to_bytes()
    evidence[f"approvals/{approval.approval_id}/approval.json"] = approval.to_bytes()
    return evidence


def build_approval_event(approval: ApprovalInput, events: Sequence[JournalEvent],
                         blobs: Mapping[str, bytes]) -> JournalEvent:
    decision = assess_approval(approval, events, blobs)
    parent, _, _, _ = _parent(approval, events, blobs)
    evidence = evidence_for_approval(approval, events, blobs)
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v4",
        "event_id": _event_id(approval, parent), "decision_id": parent.decision_id,
        "domain": "INVESTMENT", "event_type": APPROVAL_EVENT_TYPE, "recorded_at": approval.recorded_at,
        "source": {"kind": "INVESTMENT_SHADOW_APPROVAL", "approval_id": approval.approval_id,
                   "source_sha256": sha256_bytes(approval.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
                     for path, raw in sorted(evidence.items())],
        "payload": {"approval": approval.to_dict(), "decision": decision},
    })


def validate_approval_event(event: JournalEvent, previous: Sequence[JournalEvent],
                            blobs: Mapping[str, bytes]) -> None:
    if event.schema_version != "blackpod.decision_journal_event.v4" or event.event_type != APPROVAL_EVENT_TYPE:
        raise ApprovalEvidenceError("shadow approval requires the v4 approval event type")
    approval = ApprovalInput.from_mapping(event.payload["approval"])
    if blobs.get(event.source["source_sha256"]) != approval.to_bytes():
        raise ApprovalEvidenceError("retained approval input differs from canonical payload")
    expected = build_approval_event(approval, previous, blobs)
    if event.to_bytes() != expected.to_bytes():
        raise ApprovalEvidenceError("approval event differs from its reproducible source projection")


def approval_state(proposal_event: JournalEvent, events: Sequence[JournalEvent], as_of: str) -> dict[str, Any]:
    """Explicit-time research status, never operational or financial permission."""
    now = _time(as_of)
    if proposal_event.event_type != PROPOSAL_EVENT_TYPE:
        raise ApprovalEvidenceError("state requires an investment proposal event")
    if _time(proposal_event.recorded_at) > now:
        raise ApprovalEvidenceError("proposal did not exist at as_of")
    actions = [event for event in events if event.event_type == APPROVAL_EVENT_TYPE
               and event.payload["approval"]["proposal_event_id"] == proposal_event.event_id
               and _time(event.recorded_at) <= now]
    state, approval_id, expiry = "UNREVIEWED", None, None
    for event in actions:
        state = event.payload["decision"]["result"]
        approval_id = event.event_id
        expiry = event.payload["approval"]["expires_at"]
    if state in {"SHADOW_RESEARCH_APPROVED", "SIMULATED_SHADOW_APPROVED"} and now >= _time(expiry):
        state = "EXPIRED"
    return {"proposal_event_id": proposal_event.event_id, "as_of": as_of, "state": state,
            "approval_event_id": approval_id, "expires_at": expiry, "scope": SHADOW_APPROVAL_SCOPE,
            "approver_identity_authenticated": False, "operational_authority_granted": False,
            "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
            "authority": proposal_event.payload["proposal"]["authority"]}
