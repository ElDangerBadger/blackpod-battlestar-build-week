"""Pure, retained-source SHADOW portfolio proposal assessment.

Weights are declared long-only fractions of account equity. No money, share
quantities, orders, capital transfers, live policy, or truth judgments derive
from these inputs. Decimal comparisons preserve the supplied budget; the
initial capital proposal is deliberately not a rebalancing instruction.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from itertools import combinations
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.investment_governance import (
    ProposalInput, RiskContextInput, ShadowRiskPolicy, RISK_METHOD_VERSION,
    SHADOW_APPROVAL_SCOPE, validate_proposal_report,
)
from .contracts.investment_hypothesis import InvestmentHypothesis
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .investment_hypothesis import validate_hypothesis_event
from .investment_review import validate_review_event

PROPOSAL_EVENT_TYPE = "INVESTMENT_DECISION_PROPOSAL_RECORDED"
CHALLENGE_EVENT_TYPE = "INVESTMENT_CHALLENGE_RECORDED"
EVALUATION_EVENT_TYPE = "INVESTMENT_OUTCOME_EVALUATION_RECORDED"
RESIDUAL_RISKS = (
    "DECLARED_IDENTITIES_UNAUTHENTICATED", "SOURCE_INDEPENDENCE_NOT_ESTABLISHED",
    "METRIC_UNITS_NOT_INDEPENDENTLY_VERIFIED", "RISK_CONTEXT_MANUALLY_DECLARED",
    "SHADOW_POLICY_NOT_LIVE_OR_CALIBRATED", "WHOLE_HORIZON_INVALIDATION_NOT_ESTABLISHED",
    "CAPITAL_POLICY_NOT_ACTIVATED", "DECLARED_TIMESTAMPS_NOT_ATTESTED",
)


class GovernanceEvidenceError(ValueError):
    """Proposal lineage or retained evidence cannot be reproduced."""


def _time(value: str):
    return parse_rfc3339(value, "governance timestamp")


def _decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


def _number(value: Decimal) -> int | float:
    # Only serialization uses floats. Every comparison and sum used Decimal.
    return int(value) if value == value.to_integral_value() else float(value)


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))}"


def _indexed(events: Sequence[JournalEvent]) -> dict[str, JournalEvent]:
    indexed = {}
    for event in events:
        if event.event_id in indexed:
            raise GovernanceEvidenceError("source history contains ambiguous event identities")
        indexed[event.event_id] = event
    return indexed


def _validate_source(event: JournalEvent, events: Sequence[JournalEvent], blobs: Mapping[str, bytes]) -> None:
    index = next(index for index, item in enumerate(events) if item.event_id == event.event_id)
    try:
        if event.event_type == "INVESTMENT_HYPOTHESIS_RECORDED":
            validate_hypothesis_event(event, events[:index], blobs)
        else:
            validate_review_event(event, events[:index], blobs)
    except ValueError as exc:
        raise GovernanceEvidenceError(str(exc)) from exc


def _active_reviews(events: Sequence[JournalEvent], hypothesis_event_id: str,
                    cutoff: str, event_type: str) -> list[JournalEvent]:
    key = "challenge" if event_type == CHALLENGE_EVENT_TYPE else "evaluation"
    known = [event for event in events if event.event_type == event_type
             and event.payload[key]["hypothesis_event_id"] == hypothesis_event_id
             and _time(event.recorded_at) <= _time(cutoff)]
    superseded = {event.payload[key]["supersedes_event_id"] for event in known}
    return [event for event in known if event.event_id not in superseded]


def proposal_context(proposal: ProposalInput, events: Sequence[JournalEvent],
                     blobs: Mapping[str, bytes]) -> dict[str, Any]:
    """Resolve exact earlier links; integrity failures raise, insufficiency defers.

    Later events are not used to rewrite an older projection. An approval must
    separately check the active history at its own recording time.
    """
    proposal = ProposalInput.from_mapping(proposal.to_dict())
    indexed = _indexed(events)
    hypothesis_event = indexed.get(proposal.hypothesis_event_id)
    if hypothesis_event is None or hypothesis_event.schema_version != "blackpod.decision_journal_event.v2" or hypothesis_event.event_type != "INVESTMENT_HYPOTHESIS_RECORDED":
        raise GovernanceEvidenceError("proposal requires an existing v2 investment hypothesis")
    hypothesis = InvestmentHypothesis.from_mapping(hypothesis_event.payload)
    if hypothesis.hypothesis_id != proposal.hypothesis_id or hypothesis_event.source["source_sha256"] != proposal.hypothesis_sha256:
        raise GovernanceEvidenceError("proposal hypothesis identity or hash differs from the original")
    _validate_source(hypothesis_event, events, blobs)
    challenge_event = indexed.get(proposal.challenge_event_id)
    if challenge_event is None or challenge_event.schema_version != "blackpod.decision_journal_event.v3" or challenge_event.event_type != CHALLENGE_EVENT_TYPE:
        raise GovernanceEvidenceError("proposal requires an existing v3 challenge")
    linked = [hypothesis_event, challenge_event]
    evaluation_event = None
    if proposal.evaluation_event_id is not None:
        evaluation_event = indexed.get(proposal.evaluation_event_id)
        if evaluation_event is None or evaluation_event.schema_version != "blackpod.decision_journal_event.v3" or evaluation_event.event_type != EVALUATION_EVENT_TYPE:
            raise GovernanceEvidenceError("proposal requires an existing v3 outcome evaluation")
        if evaluation_event.payload["evaluation"]["challenge_event_id"] != challenge_event.event_id:
            raise GovernanceEvidenceError("selected outcome evaluation must bind the selected challenge")
        linked.append(evaluation_event)
    for event in linked[1:]:
        key = "challenge" if event.event_type == CHALLENGE_EVENT_TYPE else "evaluation"
        value = event.payload[key]
        if event.decision_id != hypothesis_event.decision_id or value["hypothesis_event_id"] != hypothesis_event.event_id:
            raise GovernanceEvidenceError("proposal source links cannot cross hypotheses or decisions")
        _validate_source(event, events, blobs)
    if any(_time(event.recorded_at) > _time(proposal.evidence_cutoff_at) for event in linked):
        raise GovernanceEvidenceError("proposal cutoff must not precede linked source records")
    policy = ShadowRiskPolicy.from_mapping(proposal.risk_policy)
    context = RiskContextInput.from_mapping(proposal.risk_context)
    if _time(policy.recorded_at) > _time(proposal.evidence_cutoff_at) or _time(context.as_of) > _time(proposal.evidence_cutoff_at):
        raise GovernanceEvidenceError("risk policy and context must exist by the proposal evidence cutoff")
    for event in events:
        if event.event_type != PROPOSAL_EVENT_TYPE:
            continue
        prior = ProposalInput.from_mapping(event.payload["proposal"])
        old_policy = ShadowRiskPolicy.from_mapping(prior.risk_policy)
        old_context = RiskContextInput.from_mapping(prior.risk_context)
        if (old_policy.policy_id, old_policy.policy_version) == (policy.policy_id, policy.policy_version) and old_policy.to_bytes() != policy.to_bytes():
            raise GovernanceEvidenceError("same policy identity/version has conflicting retained content")
        if old_context.context_id == context.context_id and old_context.to_bytes() != context.to_bytes():
            raise GovernanceEvidenceError("same risk context identity has conflicting retained content")
    if proposal.supersedes_event_id is not None:
        prior = indexed.get(proposal.supersedes_event_id)
        if prior is None or prior.event_type != PROPOSAL_EVENT_TYPE:
            raise GovernanceEvidenceError("supersedes_event_id requires an earlier proposal")
        prior_index = next(index for index, event in enumerate(events) if event.event_id == prior.event_id)
        validate_proposal_event(prior, events[:prior_index], blobs)
        previous = ProposalInput.from_mapping(prior.payload["proposal"])
        if previous.hypothesis_event_id != hypothesis_event.event_id or previous.proposal_id == proposal.proposal_id:
            raise GovernanceEvidenceError("superseding proposal requires the same hypothesis and a new proposal_id")
        if _time(proposal.recorded_at) < _time(previous.recorded_at) or _time(proposal.evidence_cutoff_at) < _time(previous.evidence_cutoff_at):
            raise GovernanceEvidenceError("superseding proposal cannot retreat recording time or evidence cutoff")
    active_challenges = _active_reviews(events, hypothesis_event.event_id, proposal.evidence_cutoff_at, CHALLENGE_EVENT_TYPE)
    active_evaluations = _active_reviews(events, hypothesis_event.event_id, proposal.evidence_cutoff_at, EVALUATION_EVENT_TYPE)
    for event in [*active_challenges, *active_evaluations]:
        _validate_source(event, events, blobs)
    return {"proposal": proposal, "hypothesis_event": hypothesis_event, "hypothesis": hypothesis,
            "challenge_event": challenge_event, "evaluation_event": evaluation_event,
            "risk_policy": policy, "risk_context": context,
            "active_challenges": active_challenges, "active_evaluations": active_evaluations}


def assess_proposal(proposal: ProposalInput, events: Sequence[JournalEvent],
                    blobs: Mapping[str, bytes]) -> dict[str, Any]:
    """Check declared exposure and known research; never grant authority."""
    context = proposal_context(proposal, events, blobs)
    proposal, hypothesis = context["proposal"], context["hypothesis"]
    policy, risk = context["risk_policy"], context["risk_context"]
    limits = policy.limits
    checks = []

    def check(identity, status, observed, limit, reason):
        checks.append({"check_id": identity, "status": status, "observed": observed,
                       "limit": limit, "reason_code": reason})

    def required(identity, passed, observed, reason):
        check(identity, "PASS" if passed else "UNKNOWN", observed, True, "SATISFIED" if passed else reason)

    def upper(identity, actual, maximum):
        passed = actual <= _decimal(maximum)
        check(identity, "PASS" if passed else "FAIL", _number(actual), maximum,
              "WITHIN_LIMIT" if passed else "LIMIT_EXCEEDED")

    def lower(identity, actual, minimum):
        passed = actual >= _decimal(minimum)
        check(identity, "PASS" if passed else "FAIL", _number(actual), minimum,
              "WITHIN_LIMIT" if passed else "MINIMUM_NOT_MET")

    required("PROSPECTIVE_HYPOTHESIS", hypothesis.research_mode == "PROSPECTIVE", hypothesis.research_mode,
             "RETROSPECTIVE_RESEARCH_NOT_AUTHORIZATION_BASIS")
    active_horizon = _time(hypothesis.horizon["start_at"]) <= _time(proposal.recorded_at) <= _time(hypothesis.horizon["end_at"])
    required("ACTIVE_HYPOTHESIS_HORIZON", active_horizon, active_horizon, "HYPOTHESIS_HORIZON_EXPIRED")
    required("PROPOSAL_VALIDITY", _time(proposal.recorded_at) < _time(proposal.valid_until), proposal.valid_until, "PROPOSAL_EXPIRED")
    total = sum((_decimal(item["weight"]) for item in risk.positions), Decimal(0)) + sum((_decimal(value) for value in risk.cash_by_desk.values()), Decimal(0))
    required("EXACT_CONTEXT_TOTAL", total == Decimal(1), _number(total), "DECLARED_WEIGHTS_DO_NOT_EXACTLY_SUM_TO_ONE")
    required("COMPLETE_CONTEXT", risk.is_complete, risk.is_complete, "INCOMPLETE_ACCOUNT_CONTEXT")
    age = Decimal(str((_time(proposal.recorded_at) - _time(risk.as_of)).total_seconds()))
    fresh = age <= Decimal(policy.max_context_age_seconds)
    check("CONTEXT_FRESHNESS", "PASS" if fresh else "UNKNOWN", _number(age), policy.max_context_age_seconds,
          "CONTEXT_CURRENT" if fresh else "STALE_ACCOUNT_CONTEXT")
    challenges, evaluations = context["active_challenges"], context["active_evaluations"]
    required("SELECTED_CHALLENGE_ACTIVE", any(item.event_id == proposal.challenge_event_id for item in challenges),
             proposal.challenge_event_id, "SELECTED_CHALLENGE_SUPERSEDED")
    if context["evaluation_event"] is not None:
        required("SELECTED_EVALUATION_ACTIVE", any(item.event_id == proposal.evaluation_event_id for item in evaluations),
                 proposal.evaluation_event_id, "SELECTED_EVALUATION_SUPERSEDED")
    dissent = any(item.payload["challenge"]["disposition"] != "REVIEW_SUPPORTS"
                  or item.payload["challenge"]["unresolved_questions"]
                  or any(assumption["status"] != "SUPPORTED" for assumption in item.payload["challenge"]["assumption_reviews"])
                  for item in challenges)
    required("NO_ACTIVE_DISSENT", not dissent, not dissent, "ACTIVE_DISSENT_OR_UNTESTED_ASSUMPTIONS")
    selected_challenge = context["challenge_event"].payload["challenge"]
    artifacts = {role: {item["artifact_sha256"] for item in selected_challenge["observations"] if item["evidence_role"] == role}
                 for role in ("FUNDAMENTAL", "STATISTICAL")}
    role_coverage = all(artifacts.values())
    required("DECLARED_EVIDENCE_ROLE_COVERAGE", role_coverage, role_coverage, "MISSING_FUNDAMENTAL_OR_STATISTICAL_ROLE")
    distinct = role_coverage and any(first != second for first in artifacts["FUNDAMENTAL"] for second in artifacts["STATISTICAL"])
    required("DISTINCT_ROLE_ARTIFACTS", distinct, distinct, "ROLE_EVIDENCE_SHARES_RETAINED_ARTIFACT")
    invalidated = any(item.payload["result"]["comparison_summary"] == "INVALIDATION_TRIGGERED" for item in evaluations)
    check("NO_KNOWN_INVALIDATION", "FAIL" if invalidated else "PASS", invalidated, False,
          "KNOWN_ACTIVE_INVALIDATION" if invalidated else "NO_RECORDED_ACTIVE_INVALIDATION")
    unmet = any(item.payload["result"]["comparison_summary"] == "EXPECTATIONS_NOT_MET"
                or any(result["status"] == "NOT_MET" for result in item.payload["result"]["check_results"])
                for item in evaluations)
    required("NO_KNOWN_UNMET_EXPECTATIONS", not unmet, not unmet, "KNOWN_EXPECTATIONS_NOT_MET")
    final = context["evaluation_event"]
    final_complete = bool(final and final.payload["evaluation"]["evaluation_stage"] == "FINAL"
                          and final.payload["result"]["comparison_summary"] == "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION"
                          and final in evaluations)
    if policy.require_final_evaluation:
        required("FINAL_EVALUATION", final_complete, final_complete, "MATURE_COMPLETE_FINAL_EVALUATION_REQUIRED")

    # The existing investment budget is preserved. No initial 50/50 reset.
    investment_positions = {item["symbol"]: _decimal(item["weight"]) for item in risk.positions if item["desk"] == "INVESTMENT"}
    budget = sum(investment_positions.values(), Decimal(0)) + _decimal(risk.cash_by_desk["INVESTMENT"])
    targets = {item["symbol"]: _decimal(item["weight"]) for item in proposal.targets}
    missing_targets = set(investment_positions) - set(targets)
    required("FULL_INVESTMENT_TARGETS", not missing_targets, ",".join(sorted(missing_targets)) or None,
             "EXISTING_INVESTMENT_SYMBOL_OMITTED")
    gross = sum(targets.values(), Decimal(0))
    upper("INVESTMENT_DESK_BUDGET", gross, _number(budget))
    upper("INVESTMENT_GROSS", gross, limits["max_investment_gross"])
    consolidated = dict(targets)
    for item in risk.positions:
        if item["desk"] == "TRADING":
            consolidated[item["symbol"]] = consolidated.get(item["symbol"], Decimal(0)) + _decimal(item["weight"])
    held = {symbol: weight for symbol, weight in consolidated.items() if weight > 0}
    consolidated_gross = sum(consolidated.values(), Decimal(0))
    cash = _decimal(risk.cash_by_desk["TRADING"]) + budget - gross
    upper("CONSOLIDATED_GROSS", consolidated_gross, limits["max_consolidated_gross"])
    lower("CASH_RESERVE", cash, limits["min_cash_weight"])
    instruments = {item["symbol"]: item for item in risk.instruments}
    sectors: dict[str, Decimal] = {}
    stress = Decimal(0)
    stress_complete = True
    for index, (symbol, weight) in enumerate(sorted(held.items())):
        upper(f"POSITION_WEIGHT_{index}", weight, limits["max_position_weight"])
        instrument = instruments.get(symbol)
        required(f"INSTRUMENT_METADATA_{index}", instrument is not None, symbol, "MISSING_HELD_INSTRUMENT_METADATA")
        if instrument is None:
            stress_complete = False
            continue
        sectors[instrument["sector"]] = sectors.get(instrument["sector"], Decimal(0)) + weight
        if instrument["liquidity_score"] is None:
            check(f"LIQUIDITY_{index}", "UNKNOWN", None, limits["min_liquidity_score"], "MISSING_LIQUIDITY_SCORE")
        else:
            lower(f"LIQUIDITY_{index}", _decimal(instrument["liquidity_score"]), limits["min_liquidity_score"])
        if instrument["stress_loss_fraction"] is None:
            stress_complete = False
            check(f"STRESS_INPUT_{index}", "UNKNOWN", None, None, "MISSING_STRESS_LOSS_FRACTION")
        else:
            stress += weight * _decimal(instrument["stress_loss_fraction"])
    for index, (sector, weight) in enumerate(sorted(sectors.items())):
        upper(f"SECTOR_WEIGHT_{index}", weight, limits["max_sector_weight"])
    if stress_complete:
        upper("CONSOLIDATED_STRESS_LOSS", stress, limits["max_stress_loss_weight"])
    else:
        check("CONSOLIDATED_STRESS_LOSS", "UNKNOWN", None, limits["max_stress_loss_weight"], "INCOMPLETE_STRESS_INPUTS")
    correlations = {tuple(sorted((item["symbol_a"], item["symbol_b"]))): item["correlation"] for item in risk.correlations}
    for index, pair in enumerate(combinations(sorted(held), 2)):
        correlation = correlations.get(pair)
        if correlation is None:
            check(f"CORRELATED_PAIR_{index}", "UNKNOWN", None, limits["max_correlated_pair_weight"], "MISSING_HELD_PAIR_CORRELATION")
        elif abs(_decimal(correlation)) >= _decimal(limits["high_correlation_threshold"]):
            upper(f"CORRELATED_PAIR_{index}", held[pair[0]] + held[pair[1]], limits["max_correlated_pair_weight"])
        else:
            check(f"CORRELATED_PAIR_{index}", "PASS", correlation, limits["high_correlation_threshold"], "BELOW_HIGH_CORRELATION_THRESHOLD")
    gate = "REJECT" if any(item["status"] == "FAIL" for item in checks) else "DEFER" if any(item["status"] == "UNKNOWN" for item in checks) else "REVIEW_READY"
    residual = [*RESIDUAL_RISKS, *([] if final_complete else ["NO_FINAL_OUTCOME_EVALUATION"])]
    return validate_proposal_report({
        "risk_method_version": RISK_METHOD_VERSION, "gate": gate, "checks": checks,
        "metrics": {"investment_budget_weight": _number(budget), "proposed_investment_gross": _number(gross),
                    "projected_consolidated_gross": _number(consolidated_gross), "projected_cash_weight": _number(cash),
                    "projected_stress_loss_weight": _number(stress) if stress_complete else None,
                    "projected_symbol_weights": [{"symbol": symbol, "weight": _number(weight)} for symbol, weight in sorted(consolidated.items())],
                    "projected_sector_weights": [{"sector": sector, "weight": _number(weight)} for sector, weight in sorted(sectors.items())]},
        "risk_policy_sha256": sha256_bytes(policy.to_bytes()), "risk_context_sha256": sha256_bytes(risk.to_bytes()),
        "residual_risks": residual, "proposal_ready_for_human_review": gate == "REVIEW_READY",
        "approval_scope": SHADOW_APPROVAL_SCOPE, "economic_truth_evaluated": False,
        "operational_authority_granted": False, "authority": proposal.authority,
    }, proposal)


def evidence_for_proposal(proposal: ProposalInput, events: Sequence[JournalEvent],
                          blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    """Retain immutable input plus exact linked and active-review evidence."""
    context = proposal_context(proposal, events, blobs)
    proposal = context["proposal"]
    evidence = {f"investment_proposals/{proposal.proposal_id}/proposal.json": proposal.to_bytes(),
                f"risk_policies/{context['risk_policy'].policy_id}/v{context['risk_policy'].policy_version}.json": context["risk_policy"].to_bytes(),
                f"risk_contexts/{context['risk_context'].context_id}/context.json": context["risk_context"].to_bytes()}
    sources = {event.event_id: event for event in [context["hypothesis_event"], context["challenge_event"],
               *([] if context["evaluation_event"] is None else [context["evaluation_event"]]),
               *context["active_challenges"], *context["active_evaluations"]]}
    for event in sources.values():
        evidence[f"source_events/{event.event_id}/event.json"] = event.to_bytes()
        for reference in event.evidence:
            raw = blobs.get(reference["sha256"])
            if raw is None or sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
                raise GovernanceEvidenceError("proposal source evidence blob missing or hash/size mismatch")
            evidence[f"source_evidence/{reference['sha256']}.blob"] = raw
    return evidence


def build_proposal_event(proposal: ProposalInput, events: Sequence[JournalEvent],
                         blobs: Mapping[str, bytes]) -> JournalEvent:
    report = assess_proposal(proposal, events, blobs)
    evidence = evidence_for_proposal(proposal, events, blobs)
    decision_id = _identity("journal-decision", {"kind": "INVESTMENT_DECISION_PROPOSAL", "proposal_id": proposal.proposal_id})
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v4",
        "event_id": _identity("journal-event", {"decision_id": decision_id, "event_type": PROPOSAL_EVENT_TYPE}),
        "decision_id": decision_id, "domain": "INVESTMENT", "event_type": PROPOSAL_EVENT_TYPE,
        "recorded_at": proposal.recorded_at,
        "source": {"kind": "INVESTMENT_DECISION_PROPOSAL", "proposal_id": proposal.proposal_id,
                   "source_sha256": sha256_bytes(proposal.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"proposal": proposal.to_dict(), "report": report},
    })


def validate_proposal_event(event: JournalEvent, previous_events: Sequence[JournalEvent],
                            blobs: Mapping[str, bytes]) -> None:
    """Rebuild every computed field against the original chain prefix."""
    if event.schema_version != "blackpod.decision_journal_event.v4" or event.event_type != PROPOSAL_EVENT_TYPE:
        raise GovernanceEvidenceError("proposal validation requires a v4 proposal event")
    proposal = ProposalInput.from_mapping(event.payload["proposal"])
    expected = build_proposal_event(proposal, previous_events, blobs)
    if expected.to_bytes() != event.to_bytes():
        raise GovernanceEvidenceError("proposal event differs from its retained source projection")
    if blobs.get(event.source["source_sha256"]) != proposal.to_bytes():
        raise GovernanceEvidenceError("retained proposal input differs from its canonical payload")
