"""Pure source-bound SHADOW challenge and fixed-deadline outcome review.

The supplied review is research, never authority. Different retained artifacts
do not establish economically independent evidence. Outcome comparisons use
only the original plan's recorded deadline points: they do not aggregate a
window, establish whole-horizon absence of invalidation, or prove causality.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.investment_hypothesis import InvestmentHypothesis
from .contracts.investment_review import (
    OBSERVATION_FIELDS, REQUIRED_EVIDENCE_ROLES, ChallengeInput, OutcomeEvaluationInput,
    validate_challenge_assessment, validate_outcome_result,
)
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .investment_hypothesis import (
    HypothesisEvidenceError,
    bind_journal_observations,
    validate_hypothesis_event,
)


class ReviewEvidenceError(ValueError):
    """A review cannot be reproduced from its exact earlier journal evidence."""


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))}"


def _indexed(events: Sequence[JournalEvent]) -> dict[str, JournalEvent]:
    result: dict[str, JournalEvent] = {}
    for event in events:
        if event.event_id in result:
            raise ReviewEvidenceError("source journal contains ambiguous event identities")
        result[event.event_id] = event
    return result


def _time(value: str):
    return parse_rfc3339(value, "review timestamp")


def _parent(
    value: Mapping[str, Any], events: Sequence[JournalEvent], blobs: Mapping[str, bytes],
) -> tuple[JournalEvent, InvestmentHypothesis]:
    parent = _indexed(events).get(value["hypothesis_event_id"])
    if parent is None or parent.schema_version != "blackpod.decision_journal_event.v2" or parent.event_type != "INVESTMENT_HYPOTHESIS_RECORDED":
        raise ReviewEvidenceError("review requires an existing v2 investment hypothesis event")
    hypothesis = InvestmentHypothesis.from_mapping(parent.payload)
    if hypothesis.hypothesis_id != value["hypothesis_id"] or parent.source["source_sha256"] != value["hypothesis_sha256"]:
        raise ReviewEvidenceError("review hypothesis identity or canonical hash does not match its parent")
    if blobs.get(value["hypothesis_sha256"]) != hypothesis.to_bytes():
        raise ReviewEvidenceError("review requires the retained canonical original hypothesis")
    parent_index = next(index for index, event in enumerate(events) if event.event_id == parent.event_id)
    try:
        validate_hypothesis_event(parent, events[:parent_index], blobs)
    except HypothesisEvidenceError as exc:
        raise ReviewEvidenceError(str(exc)) from exc
    if _time(value["recorded_at"]) < _time(hypothesis.recorded_at) or _time(value["evidence_cutoff_at"]) < _time(hypothesis.recorded_at):
        raise ReviewEvidenceError("review recorded_at and evidence cutoff must not precede the hypothesis")
    return parent, hypothesis


def _supersedes(value: Mapping[str, Any], parent: JournalEvent, event_type: str,
                events: Sequence[JournalEvent]) -> None:
    previous_id = value["supersedes_event_id"]
    if previous_id is None:
        return
    previous = _indexed(events).get(previous_id)
    if previous is None or previous.schema_version != "blackpod.decision_journal_event.v3" or previous.event_type != event_type:
        raise ReviewEvidenceError("supersedes_event_id requires an earlier review of the same event type")
    input_key = "challenge" if event_type == "INVESTMENT_CHALLENGE_RECORDED" else "evaluation"
    prior_input = previous.payload[input_key]
    if previous.decision_id != parent.decision_id or prior_input["hypothesis_event_id"] != parent.event_id:
        raise ReviewEvidenceError("supersession cannot cross hypotheses or decisions")
    if _time(value["recorded_at"]) < _time(previous.recorded_at):
        raise ReviewEvidenceError("superseding review cannot be recorded before the earlier review")
    if _time(value["evidence_cutoff_at"]) < _time(prior_input["evidence_cutoff_at"]):
        raise ReviewEvidenceError("superseding review cannot retreat to an earlier evidence cutoff")
    if event_type == "INVESTMENT_OUTCOME_EVALUATION_RECORDED" and prior_input["evaluation_stage"] == "FINAL" and value["evaluation_stage"] != "FINAL":
        raise ReviewEvidenceError("a FINAL outcome evaluation cannot be superseded by an INTERIM review")


def _bind(observations: Sequence[Mapping[str, Any]], cutoff: str,
          events: Sequence[JournalEvent], blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    try:
        return bind_journal_observations(observations, cutoff, events, blobs)
    except HypothesisEvidenceError as exc:
        raise ReviewEvidenceError(str(exc)) from exc


def _challenge_context(challenge: ChallengeInput, events: Sequence[JournalEvent],
                       blobs: Mapping[str, bytes]):
    challenge = ChallengeInput.from_mapping(challenge.to_dict())
    value = challenge.to_dict()
    parent, hypothesis = _parent(value, events, blobs)
    if value["reviewer_id"] == hypothesis.author_id:
        raise ReviewEvidenceError("challenge reviewer_id must differ from the hypothesis author_id")
    indices = {item["assumption_index"] for item in value["assumption_reviews"]}
    if indices != set(range(len(hypothesis.hypothesis["assumptions"]))):
        raise ReviewEvidenceError("assumption reviews must cover every original assumption index exactly once")
    _supersedes(value, parent, "INVESTMENT_CHALLENGE_RECORDED", events)
    observations = [{key: observation[key] for key in OBSERVATION_FIELDS}
                    for observation in value["observations"]]
    evidence = _bind(observations, value["evidence_cutoff_at"], events, blobs)
    return challenge, parent, hypothesis, evidence


def assess_challenge(challenge: ChallengeInput, events: Sequence[JournalEvent],
                     blobs: Mapping[str, bytes]) -> dict[str, Any]:
    """Describe retained-source overlap, without claiming independent support."""
    challenge, _, hypothesis, _ = _challenge_context(challenge, events, blobs)
    original_values = {(item["artifact_sha256"], item["value_pointer"])
                       for item in hypothesis.observations}
    original_artifacts = {item["artifact_sha256"] for item in hypothesis.observations}
    relationships = []
    for observation in challenge.observations:
        digest = observation["artifact_sha256"]
        relationship = ("SAME_VALUE_BINDING" if (digest, observation["value_pointer"]) in original_values
                        else "SHARED_ARTIFACT" if digest in original_artifacts
                        else "DISTINCT_RETAINED_ARTIFACT")
        relationships.append({
            "observation_id": observation["observation_id"], "relationship": relationship,
            "independence_verified": False, "evidence_role": observation["evidence_role"],
            "provenance_group": observation["provenance_group"],
        })
    roles = {item["evidence_role"] for item in challenge.observations}
    return validate_challenge_assessment({
        "assessment_method_version": "blackpod.source_relationship_assessment.v1",
        "reviewer_distinct": True, "reviewer_identity_authenticated": False,
        "source_relationships": relationships, "declared_evidence_roles": sorted(roles),
        "missing_evidence_roles": sorted(REQUIRED_EVIDENCE_ROLES - roles),
        "source_independence_verified": False, "economic_truth_evaluated": False,
        "execution_status": "NOT_EXECUTED", "authority": challenge.authority,
    }, challenge)


def _outcome_context(evaluation: OutcomeEvaluationInput, events: Sequence[JournalEvent],
                     blobs: Mapping[str, bytes]):
    evaluation = OutcomeEvaluationInput.from_mapping(evaluation.to_dict())
    value = evaluation.to_dict()
    parent, hypothesis = _parent(value, events, blobs)
    if value["evaluator_id"] == hypothesis.author_id:
        raise ReviewEvidenceError("outcome evaluator_id must differ from the hypothesis author_id")
    if value["evaluator_role"] != hypothesis.evaluation_plan["evaluator_role"]:
        raise ReviewEvidenceError("evaluator_role must match the fixed original evaluation plan")
    challenge_event = _indexed(events).get(value["challenge_event_id"])
    if challenge_event is None or challenge_event.schema_version != "blackpod.decision_journal_event.v3" or challenge_event.event_type != "INVESTMENT_CHALLENGE_RECORDED":
        raise ReviewEvidenceError("outcome evaluation requires an existing v3 challenge event")
    if challenge_event.decision_id != parent.decision_id or challenge_event.payload["challenge"]["hypothesis_event_id"] != parent.event_id:
        raise ReviewEvidenceError("outcome challenge must link to the same hypothesis and decision")
    challenge_index = next(index for index, event in enumerate(events) if event.event_id == challenge_event.event_id)
    validate_review_event(challenge_event, events[:challenge_index], blobs)
    if _time(value["evidence_cutoff_at"]) < _time(challenge_event.recorded_at):
        raise ReviewEvidenceError("outcome evidence cutoff must not precede its challenge")
    if value["evaluation_stage"] == "FINAL" and _time(value["evidence_cutoff_at"]) < _time(hypothesis.evaluation_plan["evaluate_at"]):
        raise ReviewEvidenceError("FINAL evaluation requires reaching the original evaluate_at")
    _supersedes(value, parent, "INVESTMENT_OUTCOME_EVALUATION_RECORDED", events)
    rules = {("OUTCOME", item["outcome_id"]): item for item in hypothesis.expected_outcomes}
    rules.update({("INVALIDATION", item["condition_id"]): item for item in hypothesis.invalidation_conditions})
    observations = {}
    for measurement in value["measurements"]:
        key = measurement["check_type"], measurement["check_id"]
        rule = rules.get(key)
        if rule is None:
            raise ReviewEvidenceError("measurement references an unknown original check")
        if any(measurement[field] != rule[field] for field in ("metric", "unit")):
            raise ReviewEvidenceError("measurement metric and unit must match the original check exactly")
        deadline = rule["due_at"] if key[0] == "OUTCOME" else rule["check_by"]
        if _time(deadline) > _time(value["evidence_cutoff_at"]):
            raise ReviewEvidenceError("measurement cannot be supplied before its original deadline")
        observation = measurement["observation"]
        if observation["as_of"] != deadline:
            raise ReviewEvidenceError("measurement as_of must equal the exact original deadline point")
        identity = observation["observation_id"]
        if identity in observations and observations[identity] != observation:
            raise ReviewEvidenceError("reused observation_id has a conflicting source binding")
        observations[identity] = observation
    evidence = _bind(list(observations.values()), value["evidence_cutoff_at"], events, blobs)
    return evaluation, parent, hypothesis, challenge_event, evidence


def _predicate(operator: str, actual: object, threshold: object) -> bool | None:
    # bool is never treated as a number. Null and type mismatches remain
    # inconclusive even for NE; absence cannot establish a counterexample.
    numeric = type(actual) in (int, float) and type(threshold) in (int, float)
    textual = type(actual) is str and type(threshold) is str and operator in {"EQ", "NE"}
    if not (numeric or textual):
        return None
    if operator == "GT":
        return actual > threshold
    if operator == "GTE":
        return actual >= threshold
    if operator == "LT":
        return actual < threshold
    if operator == "LTE":
        return actual <= threshold
    if operator == "EQ":
        return actual == threshold
    if operator == "NE":
        return actual != threshold
    raise ReviewEvidenceError("unsupported original check operator")


def evaluate_outcome(evaluation: OutcomeEvaluationInput, events: Sequence[JournalEvent],
                     blobs: Mapping[str, bytes]) -> dict[str, Any]:
    """Apply supplied observations to exact precommitted deadline predicates."""
    evaluation, _, hypothesis, _, _ = _outcome_context(evaluation, events, blobs)
    measured = {(item["check_type"], item["check_id"]): item for item in evaluation.measurements}
    checks = []
    for check_type, rules, identity, date_field in (
        ("OUTCOME", hypothesis.expected_outcomes, "outcome_id", "due_at"),
        ("INVALIDATION", hypothesis.invalidation_conditions, "condition_id", "check_by"),
    ):
        for rule in rules:
            item = {"check_type": check_type, "check_id": rule[identity], "metric": rule["metric"],
                    "unit": rule["unit"], "due_at": rule[date_field],
                    "observed_value": None, "observation_id": None}
            measurement = measured.get((check_type, rule[identity]))
            if _time(rule[date_field]) > _time(evaluation.evidence_cutoff_at):
                item["status"] = "NOT_DUE"
            elif measurement is None:
                item["status"] = "MISSING"
            else:
                actual = measurement["observation"]["value"]
                item.update(observed_value=actual, observation_id=measurement["observation"]["observation_id"])
                result = _predicate(rule["operator"], actual, rule["threshold"])
                item["status"] = ("INCONCLUSIVE" if result is None
                                  else ("MET" if result else "NOT_MET") if check_type == "OUTCOME"
                                  else ("TRIGGERED" if result else "NOT_TRIGGERED"))
            checks.append(item)
    statuses = {item["status"] for item in checks}
    summary = ("INVALIDATION_TRIGGERED" if "TRIGGERED" in statuses
               else "PENDING" if "NOT_DUE" in statuses
               else "INCONCLUSIVE" if statuses & {"MISSING", "INCONCLUSIVE"}
               else "EXPECTATIONS_NOT_MET" if "NOT_MET" in statuses
               else "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
    return validate_outcome_result({
        "comparison_method_version": "blackpod.deadline_point_comparison.v1",
        "plan_id": hypothesis.evaluation_plan["plan_id"], "evaluation_stage": evaluation.evaluation_stage,
        "comparison_summary": summary, "check_results": checks,
        "measurement_basis": "RECORDED_DEADLINE_POINTS_ONLY",
        "whole_horizon_invalidation_established": False, "manual_review_required": True,
        "hypothesis_research_mode": hypothesis.research_mode, "economic_truth_evaluated": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "authority": evaluation.authority,
    }, evaluation)


def evidence_for_challenge(challenge: ChallengeInput, events: Sequence[JournalEvent],
                           blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    """Retain exact original hypothesis, supplied review, and bound sources."""
    challenge, _, hypothesis, evidence = _challenge_context(challenge, events, blobs)
    evidence[f"hypotheses/{hypothesis.hypothesis_id}/hypothesis.json"] = hypothesis.to_bytes()
    evidence[f"challenges/{challenge.challenge_id}/challenge.json"] = challenge.to_bytes()
    return evidence


def evidence_for_outcome(evaluation: OutcomeEvaluationInput, events: Sequence[JournalEvent],
                         blobs: Mapping[str, bytes]) -> dict[str, bytes]:
    """Retain the fixed plan, original challenge and normalized evaluation."""
    evaluation, _, hypothesis, challenge_event, evidence = _outcome_context(evaluation, events, blobs)
    challenge = ChallengeInput.from_mapping(challenge_event.payload["challenge"])
    evidence[f"hypotheses/{hypothesis.hypothesis_id}/hypothesis.json"] = hypothesis.to_bytes()
    evidence[f"challenges/{challenge.challenge_id}/challenge.json"] = challenge.to_bytes()
    evidence[f"outcome_evaluations/{evaluation.evaluation_id}/evaluation.json"] = evaluation.to_bytes()
    return evidence


def _event(review, parent: JournalEvent, evidence: Mapping[str, bytes], report: dict[str, Any],
           *, challenge: bool) -> JournalEvent:
    event_type = "INVESTMENT_CHALLENGE_RECORDED" if challenge else "INVESTMENT_OUTCOME_EVALUATION_RECORDED"
    identity_field = "challenge_id" if challenge else "evaluation_id"
    document_key, report_key = ("challenge", "assessment") if challenge else ("evaluation", "result")
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v3",
        "event_id": _identity("journal-event", {"decision_id": parent.decision_id,
                                               "event_type": event_type, identity_field: getattr(review, identity_field)}),
        "decision_id": parent.decision_id, "domain": "INVESTMENT", "event_type": event_type,
        "recorded_at": review.recorded_at,
        "source": {"kind": "INVESTMENT_CHALLENGE" if challenge else "INVESTMENT_OUTCOME_EVALUATION",
                   identity_field: getattr(review, identity_field), "source_sha256": sha256_bytes(review.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
                     for path, raw in sorted(evidence.items())],
        "payload": {document_key: review.to_dict(), report_key: report},
    })


def build_challenge_event(challenge: ChallengeInput, events: Sequence[JournalEvent],
                          blobs: Mapping[str, bytes]) -> JournalEvent:
    assessment = assess_challenge(challenge, events, blobs)
    parent, _ = _parent(challenge.to_dict(), events, blobs)
    return _event(challenge, parent, evidence_for_challenge(challenge, events, blobs), assessment, challenge=True)


def build_outcome_event(evaluation: OutcomeEvaluationInput, events: Sequence[JournalEvent],
                        blobs: Mapping[str, bytes]) -> JournalEvent:
    result = evaluate_outcome(evaluation, events, blobs)
    parent, _ = _parent(evaluation.to_dict(), events, blobs)
    return _event(evaluation, parent, evidence_for_outcome(evaluation, events, blobs), result, challenge=False)


def validate_review_event(event: JournalEvent, previous_events: Sequence[JournalEvent],
                          blobs: Mapping[str, bytes]) -> None:
    """Rebuild all computed fields and identities on every retained-history scan."""
    if event.schema_version != "blackpod.decision_journal_event.v3":
        raise ReviewEvidenceError("investment review requires a v3 journal event")
    if event.event_type == "INVESTMENT_CHALLENGE_RECORDED":
        document = ChallengeInput.from_mapping(event.payload["challenge"])
        expected = build_challenge_event(document, previous_events, blobs)
    elif event.event_type == "INVESTMENT_OUTCOME_EVALUATION_RECORDED":
        document = OutcomeEvaluationInput.from_mapping(event.payload["evaluation"])
        expected = build_outcome_event(document, previous_events, blobs)
    else:
        raise ReviewEvidenceError("unsupported investment review event type")
    if expected.to_bytes() != event.to_bytes():
        raise ReviewEvidenceError("review event differs from its retained source projection")
    if blobs.get(event.source["source_sha256"]) != document.to_bytes():
        raise ReviewEvidenceError("retained review input differs from its canonical payload")
