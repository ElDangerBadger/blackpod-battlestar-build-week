"""Research-only acceptance over existing source-bound investment reviews.

An exact deadline comparison and an economically supported investment thesis
are different claims. This adapter replays the former without claiming that
generic retained JSON, reviewer labels, or a positive price move prove the
latter. It does not acquire data, adjudicate narratives, or change authority.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy

from .contracts.decision_journal import JournalEvent
from .contracts.investment_hypothesis import InvestmentHypothesis
from .contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .investment_hypothesis import validate_hypothesis_event
from .investment_review import assess_challenge, evaluate_outcome, validate_review_event

METHOD_VERSION = "blackpod.investment_research_acceptance.v1"
HYPOTHESIS_TYPE = "INVESTMENT_HYPOTHESIS_RECORDED"
CHALLENGE_TYPE = "INVESTMENT_CHALLENGE_RECORDED"
OUTCOME_TYPE = "INVESTMENT_OUTCOME_EVALUATION_RECORDED"

LIMITATIONS = (
    "RESEARCH_CLASSIFICATION_NOT_INVESTMENT_RECOMMENDATION_OR_AUTHORIZATION",
    "RETAINED_HASHES_NOT_SOURCE_AUTHENTICATION_OR_PUBLICATION_TIME_ATTESTATION",
    "SOURCE_UNITS_METRIC_MEANING_AND_FUNDAMENTAL_ROLES_ARE_SUPPLIED_CLAIMS",
    "DISTINCT_ARTIFACTS_AND_REVIEWER_IDS_DO_NOT_PROVE_EVIDENCE_INDEPENDENCE",
    "DEADLINE_POINT_COMPARISONS_NOT_WHOLE_HORIZON_MONITORING",
    "CAUSAL_MECHANISM_AND_ECONOMIC_TRUTH_NOT_ADJUDICATED",
    "BUSINESS_QUALITY_NOT_INVESTMENT_ATTRACTIVENESS_AT_EVALUATED_PRICE",
    "VALUATION_AND_PRICE_DEPENDENT_EXPECTED_RETURN_NOT_ESTABLISHED",
    "SHADOW_RESEARCH_HAS_NO_REALIZED_TRADE_PNL",
)
NEXT_EVIDENCE = (
    "Retain comparable business fundamentals with source definitions, units, observation periods and release-time evidence.",
    "Evaluate the original causal mechanism and competing explanations using independently justified fundamental and statistical evidence.",
    "Provide a source-bound valuation and evaluated price, or explicitly justify why valuation is not applicable to this thesis.",
    "Retain original deadline measurements and a separately declared monitoring cadence before drawing whole-horizon conclusions.",
)


def _time(value):
    return parse_rfc3339(value, "investment assessment timestamp")


def _event(identity, events, types):
    selected = [event for event in events if event.event_id == identity]
    if len(selected) != 1 or selected[0].domain != "INVESTMENT" or selected[0].event_type not in types:
        raise ValueError("investment acceptance requires a unique retained source event of the requested type")
    return selected[0]


def _prefix(event, events):
    return events[:next(index for index, item in enumerate(events) if item.event_id == event.event_id)]


def _blob(ref, blobs):
    raw = blobs.get(ref["sha256"])
    if (not isinstance(raw, bytes) or sha256_bytes(raw) != ref["sha256"]
            or len(raw) != ref["size_bytes"]):
        raise ValueError("investment acceptance evidence is absent, changed or incorrectly sized")
    return raw


def _retain(evidence, event, blobs):
    for ref in event.evidence:
        raw = _blob(ref, blobs)
        # Source-qualified aliases preserve different artifacts with identical
        # relative paths without relying on an arbitrary latest source.
        alias = "research-acceptance/investment/" + event.event_id + "/" + ref["path"]
        if alias in evidence and evidence[alias] != raw:
            raise ValueError("investment acceptance evidence alias contains conflicting source bytes")
        evidence[alias] = raw
    if len(evidence) > 512 or sum(map(len, evidence.values())) > 64 * 1024 * 1024:
        raise ValueError("investment acceptance exceeds its retained evidence bound")


def _context(request, events, blobs):
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("investment acceptance source journal has ambiguous event identities")
    source = _event(request["hypothesis"]["source_event_id"], events, {HYPOTHESIS_TYPE})
    validate_hypothesis_event(source, _prefix(source, events), blobs)
    hypothesis = InvestmentHypothesis.from_mapping(source.payload)
    ref = request["hypothesis"]["evidence"]
    if (hypothesis.hypothesis_id != request["hypothesis"]["hypothesis_id"]
            or hypothesis.schema_version != request["hypothesis"]["document_schema_version"]
            or ref not in source.evidence or _blob(ref, blobs) != hypothesis.to_bytes()):
        raise ValueError("investment acceptance hypothesis differs from its original canonical source")
    research = _event(request["research_event_id"], events, {HYPOTHESIS_TYPE, CHALLENGE_TYPE})
    selected = [source]
    challenge_event, challenge, challenge_report = None, None, None
    if research.event_type == HYPOTHESIS_TYPE:
        if research.event_id != source.event_id:
            raise ValueError("investment acceptance research must bind the selected original hypothesis")
    else:
        if (research.payload["challenge"]["hypothesis_event_id"] != source.event_id
                or research.decision_id != source.decision_id):
            raise ValueError("investment acceptance challenge belongs to another hypothesis")
        validate_review_event(research, _prefix(research, events), blobs)
        challenge_event = research
        challenge = ChallengeInput.from_mapping(research.payload["challenge"])
        challenge_report = assess_challenge(challenge, _prefix(research, events), blobs)
        selected.append(research)
    evaluation, result = None, None
    if request["evaluation_event_id"] is not None:
        evaluation = _event(request["evaluation_event_id"], events, {OUTCOME_TYPE})
        if (evaluation.payload["evaluation"]["hypothesis_event_id"] != source.event_id
                or evaluation.decision_id != source.decision_id):
            raise ValueError("investment acceptance outcome belongs to another hypothesis")
        before = _prefix(evaluation, events)
        if research.event_id not in {event.event_id for event in before}:
            raise ValueError("investment acceptance outcome must follow its original research source")
        validate_review_event(evaluation, before, blobs)
        outcome = OutcomeEvaluationInput.from_mapping(evaluation.payload["evaluation"])
        if challenge_event is not None and outcome.challenge_event_id != challenge_event.event_id:
            raise ValueError("investment acceptance outcome does not use the selected exact challenge")
        if challenge_event is None:
            challenge_event = _event(outcome.challenge_event_id, before, {CHALLENGE_TYPE})
            challenge = ChallengeInput.from_mapping(challenge_event.payload["challenge"])
            challenge_report = assess_challenge(challenge, _prefix(challenge_event, events), blobs)
            selected.append(challenge_event)
        result = evaluate_outcome(outcome, before, blobs)
        if result != evaluation.payload["result"]:
            raise ValueError("investment acceptance original outcome differs from exact historical replay")
        selected.append(evaluation)
    cutoff = _time(request["data_cutoff_at"])
    if cutoff > _time(request["recorded_at"]) or any(_time(event.recorded_at) > cutoff for event in selected):
        raise ValueError("investment acceptance cutoff must cover selected source records and precede assessment")
    if any(_time(event.payload[key]["evidence_cutoff_at"]) > cutoff
           for event in selected for key in ("challenge", "evaluation") if key in event.payload):
        raise ValueError("investment acceptance cannot use review evidence after its declared data cutoff")
    evidence = {}
    for event in selected:
        _retain(evidence, event, blobs)
    evidence[ref["path"]] = _blob(ref, blobs)
    return source, hypothesis, research, challenge_event, challenge, challenge_report, evaluation, result, evidence


def assess_investment_acceptance(request, events: Sequence[JournalEvent], blobs: Mapping[str, bytes]):
    """Assess an exact historical research revision with no writes or inference.

    Invalid native history raises rather than being accepted as a new trusted
    source. A separately supplied, untrusted candidate result can be retained
    and classified INVALID when it disagrees with the frozen native replay.
    """
    from .contracts.research_assessment import ResearchAssessmentRequest
    value = request.to_dict() if hasattr(request, "to_dict") else dict(request)
    request = ResearchAssessmentRequest.from_mapping(deepcopy(value)).to_dict()
    if request["domain"] != "INVESTMENT" or request["methodology_version"] != METHOD_VERSION:
        raise ValueError("investment acceptance requires its exact desk and methodology")
    events = tuple(events)
    (source, hypothesis, research, challenge_event, challenge, challenge_report,
     evaluation, result, evidence) = _context(request, events, blobs)
    findings = []

    def finding(criterion, effect, statement, *, event=source, pointer=None, observed=None):
        findings.append({"finding_id": "investment-finding-%04d" % (len(findings) + 1),
            "criterion": criterion, "effect": effect,
            "evidence_event_id": None if event is None else event.event_id,
            "value_pointer": pointer, "observed": observed, "statement": statement})

    finding("THESIS_SPECIFICATION", "SUPPORTS",
        "The immutable thesis has a stated mechanism, assumptions, alternatives, horizon, fixed expectations and invalidation predicates; form is not economic proof.",
        pointer="/payload/status", observed=hypothesis.status)
    finding("REPRODUCIBILITY", "SUPPORTS",
        "The selected original hypothesis and every selected challenge/outcome replay from their exact earlier journal prefixes.")
    for index, observation in enumerate(hypothesis.observations):
        finding("SOURCE_VALUE_BINDING", "SUPPORTS",
            "The recorded scalar and timestamp match retained source bytes; economic metric meaning and units remain supplied annotations.",
            pointer="/payload/observations/%d/value" % index, observed=observation["value"])
    limitations = list(LIMITATIONS)
    questions = [
        "Does independently justified evidence identify the original causal mechanism rather than a competing explanation?",
        "Are the business fundamentals sufficiently specified and economically comparable?",
        "Would this be an attractive investment at the evaluated price, as distinct from a plausible business thesis?",
    ]
    next_evidence = list(NEXT_EVIDENCE)
    native = [{"source_event_id": source.event_id, "native_status": hypothesis.status,
        "mapped_classification": "EVALUABLE", "reason": "A validated shadow specification is an unproven research proposition, never an investment approval."}]
    if hypothesis.research_mode == "RETROSPECTIVE":
        limitations.append("RETROSPECTIVE_HYPOTHESIS_NOT_PROSPECTIVE_PREREGISTRATION")
    for item in hypothesis.observations:
        raw = parse_strict_json_object_bytes(blobs[item["artifact_sha256"]], document_name="hypothesis source")
        if raw.get("source_kind") == "SYNTHETIC_FIXTURE":
            limitations.append("SYNTHETIC_FIXTURE_NOT_REAL_INVESTMENT_EVIDENCE")
            break
    if _time(request["data_cutoff_at"]) < _time(hypothesis.horizon["end_at"]):
        finding("HORIZON_MATURITY", "UNKNOWN", "The original investment horizon has not elapsed at this assessment's supplied data cutoff; success or failure is unresolved.",
            pointer="/payload/horizon/end_at", observed=hypothesis.horizon["end_at"])
        limitations.append("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED")
        next_evidence.append("Wait for the original horizon and retain its required measurements; do not infer thesis success from interim price appreciation.")
    else:
        finding("HORIZON_MATURITY", "SUPPORTS", "The supplied cutoff reaches the original horizon; this supplied clock does not authenticate an actual observed outcome.",
            pointer="/payload/horizon/end_at", observed=hypothesis.horizon["end_at"])
    classification = "EVALUABLE"
    if challenge is None:
        finding("INDEPENDENT_CHALLENGE", "PREREQUISITE", "No source-bound independent declared challenge is selected; alternative claims in the draft are not independent corroboration.")
        next_evidence.append("Record an independently declared, source-bound challenge covering the original assumptions and alternatives.")
    else:
        native.append({"source_event_id": challenge_event.event_id, "native_status": challenge.disposition,
            "mapped_classification": "EVALUABLE" if challenge.disposition == "REVIEW_SUPPORTS" else "INCONCLUSIVE",
            "reason": "A reviewer disposition is a supplied opinion; it never establishes economic support or changes the original thesis."})
        for index, item in enumerate(challenge.assumption_reviews):
            finding("ASSUMPTION_REVIEW", "LIMITATION" if item["status"] != "SUPPORTED" else "SUPPORTS",
                "The original assumption review records a declared opinion, not independently established economic support; its original explanation remains retained.", event=challenge_event,
                pointer="/payload/challenge/assumption_reviews/%d/status" % index, observed=item["status"])
        for index, role in enumerate(challenge_report["missing_evidence_roles"]):
            finding("FUNDAMENTAL_AND_STATISTICAL_EVIDENCE", "PREREQUISITE", "The selected challenge has no declared " + role + " evidence role; labels alone would not verify independence.",
                event=challenge_event, pointer="/payload/assessment/missing_evidence_roles/%d" % index, observed=role)
        finding("SOURCE_INDEPENDENCE", "UNKNOWN", "Source relationship replay establishes retained overlap and role labels, never independently justified economic evidence.",
            event=challenge_event, pointer="/payload/assessment/source_independence_verified", observed=False)
        for item in challenge.counter_hypotheses:
            finding("ALTERNATIVE_EXPLANATIONS", "LIMITATION", "A recorded competing explanation requires its original discriminating test; the counterhypothesis and test remain unchanged retained evidence.", event=challenge_event)
        for question in challenge.unresolved_questions:
            questions.append(question)
        for note in challenge.risk_notes:
            finding("IMPORTANT_RISKS", "LIMITATION", "A declared risk note remains unresolved in this descriptive review; its complete original text is retained.", event=challenge_event,
                pointer="/payload/challenge/risk_notes/%d" % list(challenge.risk_notes).index(note), observed=note)
    finding("VALUATION_APPLICABILITY", "PREREQUISITE", "The current hypothesis contract does not establish evaluated-price valuation or a source-bound justification for treating valuation as inapplicable.")
    finding("FUNDAMENTAL_METRIC_SEMANTICS", "PREREQUISITE", "Generic mission scalar bindings do not independently establish business-performance definitions, observation periods or economic comparability.")
    finding("ECONOMIC_CAUSALITY", "UNKNOWN", "Neither a plausible causal narrative nor an interim price gain validates the long-horizon economic mechanism.")
    if result is not None:
        summary = result["comparison_summary"]
        classification = "INCONCLUSIVE"
        if request["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES":
            classification = ("SUPPORTED" if summary == "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION"
                              else "CONTRADICTED" if summary in {"INVALIDATION_TRIGGERED", "EXPECTATIONS_NOT_MET"}
                              else "INCONCLUSIVE")
        native.append({"source_event_id": evaluation.event_id, "native_status": summary,
            "mapped_classification": classification,
            "reason": "Classification concerns recorded fixed-deadline predicates only; missing/not-due measurements do not contradict the thesis and passing points do not establish causal truth."})
        for index, item in enumerate(result["check_results"]):
            effect = ("CONTRADICTS" if item["status"] in {"NOT_MET", "TRIGGERED"}
                      else "SUPPORTS" if item["status"] in {"MET", "NOT_TRIGGERED"} else "UNKNOWN")
            finding("DECLARED_DEADLINE_COMPARISON", effect,
                "Original %s %s has status %s at its recorded deadline; the comparison does not monitor the entire investment horizon." % (item["check_type"], item["check_id"], item["status"]),
                event=evaluation, pointer="/payload/result/check_results/%d/observed_value" % index, observed=item["observed_value"])
        limitations.append("SOURCE_BOUND_DEADLINE_RESULT_NOT_REALIZED_INVESTMENT_PERFORMANCE")
        if request["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES":
            limitations.append("SUPPORT_OR_CONTRADICTION_RESTRICTED_TO_EXACT_RECORDED_PREDICATES")
        if summary in {"PENDING", "INCONCLUSIVE"}:
            next_evidence.append("Retain usable observations for every original due_at/check_by predicate without changing deadlines, thresholds or metric definitions.")
    elif request["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES":
        classification = "NOT_EVALUABLE"
        finding("DEADLINE_MEASUREMENTS", "PREREQUISITE", "No recorded fixed-deadline outcome evaluation was selected; absent measurements cannot support or contradict an original predicate.")
    if request["assessment_scope"] == "ECONOMIC_VALIDATION":
        classification = "NOT_EVALUABLE"
        finding("ECONOMIC_VALIDATION", "PREREQUISITE", "Independent fundamental semantics, causal discrimination and valuation applicability remain unestablished; this descriptive method cannot evaluate economic investment support.")
    candidate_ref = request["candidate_result_evidence"]
    if candidate_ref is not None:
        if result is None:
            raise ValueError("investment acceptance candidate requires an existing outcome evaluation")
        raw = _blob(candidate_ref, blobs)
        if candidate_ref["path"] in evidence and evidence[candidate_ref["path"]] != raw:
            raise ValueError("investment acceptance candidate evidence path conflicts with its immutable sources")
        evidence[candidate_ref["path"]] = raw
        try:
            candidate = parse_strict_json_object_bytes(raw, document_name="untrusted investment candidate result")
            agrees = canonical_json_bytes(candidate) == canonical_json_bytes(result)
        except (ValueError, RecursionError):
            agrees = False
        if not agrees:
            classification = "INVALID"
            finding("RESULT_REPLAY_CONSISTENCY", "INVALID", "The separately retained candidate result disagrees with the exact frozen native outcome replay; original measurements and journal records remain unchanged.",
                event=evaluation)
        else:
            finding("RESULT_REPLAY_CONSISTENCY", "SUPPORTS", "The supplied candidate matches the deterministic native result; matching software output is not economic proof.", event=evaluation)
    fields = {
        "classification": classification, "evaluation_performed": result is not None,
        "native_status_mapping": native, "findings": findings,
        "limitations": list(dict.fromkeys(limitations)), "unresolved_questions": list(dict.fromkeys(questions)),
        "next_evidence_requirements": list(dict.fromkeys(next_evidence)),
        "economic_hypothesis_supported": False, "source_authentication_verified": False,
        "historical_point_in_time_verified": False,
        "claim_scope": "DECLARED_DEADLINE_PREDICATES_ONLY" if request["assessment_scope"] == "DECLARED_DEADLINE_PREDICATES" else "INVESTMENT_THESIS_EVIDENTIARY_STRENGTH",
        "maturity": "DESCRIPTIVE_ONLY",
    }
    if len(evidence) > 512 or sum(map(len, evidence.values())) > 64 * 1024 * 1024:
        raise ValueError("investment acceptance exceeds its retained evidence bound")
    return {"assessment_fields": fields, "evidence": evidence}
