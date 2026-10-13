"""Additive research classifications over unchanged, frozen trading calculations.

The adapter verifies original journal relationships and replays the existing
method. Descriptive simulation signs are never evidence of an authorized or
statistically established trading edge. No data, hypothesis, cost assumption,
holding period, or sealed scoring partition is changed by this assessment.
"""
from __future__ import annotations

from copy import deepcopy

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_hypothesis import TradingHypothesis, TradingHypothesisCatalog
from .contracts.trading_research import TradingResearchPlan
from .hashing import canonical_json_bytes
from .trading_research_journal import _blob, registered_context, assess_registered_research, validate_research_event
from .trading_research_intake_journal import CATALOG_TYPE, validate_intake_event
from .trading_shadow_journal import (
    STUDY_TYPE as SHADOW_STUDY, EVALUATION_TYPE as SHADOW_EVALUATION,
    registered_shadow_context, assess_registered_shadow, validate_shadow_event,
)
from .trading_shadow_review_journal import (
    STUDY_TYPE as REVIEWED_STUDY, EVALUATION_TYPE as REVIEWED_EVALUATION,
    _registered, assess_registered_reviewed_study, validate_reviewed_event,
)

METHOD_VERSION = "blackpod.trading_research_acceptance.v1"
PLAN_TYPE = "TRADING_RESEARCH_PLAN_REGISTERED"
PLAN_EVALUATION = "TRADING_RESEARCH_EVALUATION_RECORDED"

LIMITATIONS = (
    "RESEARCH_CLASSIFICATION_NOT_AUTHORIZATION_OR_STRATEGY_PROMOTION",
    "POSITIVE_SIMULATION_RETURN_IS_NOT_VALIDATED_ECONOMIC_SUPPORT",
    "RETROSPECTIVE_AVAILABILITY_ASSUMPTION_NOT_HISTORICAL_POINT_IN_TIME_PROOF",
    "RETAINED_HASHES_NOT_PROVIDER_OR_REVIEWER_AUTHENTICATION",
    "MATCHED_ENTRY_PURCHASE_NOTIONAL_AND_DURATION_NOT_DAILY_EXPOSURE_OR_BETA",
    "DECLARED_COST_BOUNDS_AND_STRESSES_NOT_OBSERVED_EXECUTION_COSTS",
    "SELECTED_FIXED_UNIVERSE_SURVIVORSHIP_NOT_CONTROLLED",
    "GLOBAL_TRIAL_COMPLETENESS_AND_PROSPECTIVE_PREREGISTRATION_NOT_VERIFIED",
    "STATISTICAL_UNCERTAINTY_AND_EFFECT_STABILITY_NOT_ESTABLISHED",
    "FINAL_HOLDOUT_WITHHELD_AND_NOT_ACCESS_SEALED",
    "FOLD_CASH_RESETS_NO_AGGREGATE_PORTFOLIO_PERFORMANCE",
)
NEXT_EVIDENCE = (
    "Retain governed continuity treatment or complete evidence of comparable prices across every tested interval.",
    "Retain predeclared training-only cost and capacity evidence, including fee/slippage assumptions and their applicability.",
    "Specify and freeze an uncertainty and across-period stability methodology before independent economic evaluation.",
    "Document selection, trial completeness, publication-time availability, and market-direction/concentration alternatives.",
)

_METRICS = (
    "simulated_total_pnl", "simulated_realized_net_pnl", "net_return",
    "modeled_total_cost", "fees", "adverse_price_cost", "turnover_notional",
    "turnover_to_initial_cash", "maximum_close_drawdown",
    "maximum_drawdown_duration_sessions", "maximum_close_gross_exposure_fraction",
    "sell_fill_count", "profitable_sell_fill_count", "losing_sell_fill_count",
    "sell_fill_win_rate", "simulated_net_expectancy_per_sell_fill", "sell_fill_profit_factor",
    "sharpe_ratio", "sortino_ratio", "annualized_return", "statistical_significance",
)


def _mapping(value):
    return deepcopy(value.to_dict() if hasattr(value, "to_dict") else dict(value))


def _event(identity, events, *, types=None):
    matches = [event for event in events if event.event_id == identity]
    if len(matches) != 1 or matches[0].domain != "TRADING":
        raise ValueError("trading acceptance requires a unique retained TRADING source event")
    event = matches[0]
    if types is not None and event.event_type not in types:
        raise ValueError("trading acceptance source event type is unsupported")
    return event


def _prefix(event, events):
    return tuple(events)[:tuple(events).index(event)]


def _retain(evidence, event, blobs):
    for ref in event.evidence:
        raw = _blob(blobs, ref)
        if ref["path"] in evidence and evidence[ref["path"]] != raw:
            raise ValueError("trading acceptance evidence path binds conflicting source bytes")
        evidence[ref["path"]] = raw
    if len(evidence) > 512 or sum(map(len, evidence.values())) > 64 * 1024 * 1024:
        raise ValueError("trading acceptance exceeds its retained evidence bound")


def _context(request, events, blobs):
    hypothesis_source = _event(request["hypothesis"]["source_event_id"], events, types={CATALOG_TYPE})
    validate_intake_event(hypothesis_source, _prefix(hypothesis_source, events), blobs)
    catalog = TradingHypothesisCatalog.from_mapping(hypothesis_source.payload["catalog"])
    ref = request["hypothesis"]["evidence"]
    hypothesis = TradingHypothesis.from_bytes(_blob(blobs, ref))
    if (hypothesis.hypothesis_id != request["hypothesis"]["hypothesis_id"]
            or hypothesis.schema_version != request["hypothesis"]["document_schema_version"]
            or hypothesis.to_dict() not in catalog.hypotheses or ref not in hypothesis_source.evidence):
        raise ValueError("trading acceptance hypothesis differs from its exact frozen catalog member")
    research = _event(request["research_event_id"], events, types={PLAN_TYPE, SHADOW_STUDY, REVIEWED_STUDY})
    if research.event_type == PLAN_TYPE:
        validate_research_event(research, _prefix(research, events), blobs)
        plan = TradingResearchPlan.from_mapping(research.payload["plan"])
        if plan.schema_version != "blackpod.trading_research_plan.v2":
            raise ValueError("trading acceptance requires independently frozen hypothesis plan v2")
        plan, data, _, _ = registered_context(plan, events, blobs)
        material = {"base_plan": plan, "dataset": data, "hypothesis": hypothesis,
                    "gate_assessment": {"eligible": False, "reason_codes": ["DATA_QUALITY_PLAN_HAS_NO_STRATEGY_EVALUATION"]}}
        evaluation_type, validator = PLAN_EVALUATION, validate_research_event
    elif research.event_type == SHADOW_STUDY:
        validate_shadow_event(research, _prefix(research, events), blobs)
        material, _ = registered_shadow_context(research.payload["study"], events, blobs)
        evaluation_type, validator = SHADOW_EVALUATION, validate_shadow_event
    else:
        validate_reviewed_event(research, _prefix(research, events), blobs)
        material, _ = _registered(research.payload["study"], events, blobs)
        evaluation_type, validator = REVIEWED_EVALUATION, validate_reviewed_event
    if (research.payload["hypothesis_event_id"] != hypothesis_source.event_id
            or material["base_plan"].frozen_hypothesis_evidence != ref
            or material["hypothesis"].to_dict() != hypothesis.to_dict()):
        raise ValueError("trading acceptance research does not bind this original hypothesis")
    evaluation, result = None, None
    if request["evaluation_event_id"] is not None:
        evaluation = _event(request["evaluation_event_id"], events, types={evaluation_type})
        link = "plan_event_id" if research.event_type == PLAN_TYPE else "study_event_id"
        if (evaluation.payload[link] != research.event_id
                or tuple(events).index(evaluation) <= tuple(events).index(research)):
            raise ValueError("trading acceptance evaluation must follow and link its original research registration")
        before = _prefix(evaluation, events)
        validator(evaluation, before, blobs)
        if research.event_type == PLAN_TYPE:
            result = assess_registered_research(research.payload["plan"], before, blobs)
        elif research.event_type == SHADOW_STUDY:
            result = assess_registered_shadow(research.payload["study"], before, blobs)["result"]
        else:
            result = assess_registered_reviewed_study(research.payload["study"], before, blobs)["result"]
        if result != evaluation.payload["result"]:
            raise ValueError("trading acceptance original result differs from exact frozen evaluation replay")
    selected = [hypothesis_source, research] + ([] if evaluation is None else [evaluation])
    cutoff = parse_rfc3339(request["data_cutoff_at"], "data cutoff")
    recorded = parse_rfc3339(request["recorded_at"], "assessment clock")
    if any(parse_rfc3339(event.recorded_at, "source event clock") > cutoff for event in selected) or cutoff > recorded:
        raise ValueError("trading acceptance cutoff must cover selected retained source records and precede assessment")
    evidence = {}
    for event in selected:
        _retain(evidence, event, blobs)
    return hypothesis_source, hypothesis, research, evaluation, material, result, evidence


def assess_trading_acceptance(request, events, blobs):
    """Return a deterministic mapping without writing, scoring new data or tuning.

    A separate candidate result is untrusted evidence. Its discrepancy becomes
    INVALID; corrupt native history or relationships raise and never acquire
    credibility by being imported into the authoritative journal.
    """
    from .contracts.research_assessment import ResearchAssessmentRequest
    request = _mapping(ResearchAssessmentRequest.from_mapping(_mapping(request)))
    if request["domain"] != "TRADING" or request["methodology_version"] != METHOD_VERSION:
        raise ValueError("trading acceptance requires its exact desk and methodology")
    events = tuple(events)
    source, hypothesis, research, evaluation, material, result, evidence = _context(request, events, blobs)
    findings = []

    def finding(criterion, effect, statement, *, event=research, pointer=None, observed=None):
        findings.append({"finding_id": "trading-finding-%04d" % (len(findings) + 1),
            "criterion": criterion, "effect": effect, "evidence_event_id": None if event is None else event.event_id,
            "value_pointer": pointer, "observed": observed, "statement": statement})

    finding("STRATEGY_SPECIFICATION", "SUPPORTS", "The original entry condition, exit schedule, holding horizon and fixed universe remain source-bound; they are untested specifications.",
        event=source, pointer="/payload/catalog/status", observed="PROPOSED_SPECIFICATION")
    finding("REPRODUCIBILITY", "SUPPORTS", "Original source relationships and installed frozen calculations replay without changing historical bytes.")
    gates = material["gate_assessment"]
    for reason in gates["reason_codes"]:
        finding("EVALUATION_PREREQUISITES", "PREREQUISITE", reason, observed=reason)
    limitations = list(LIMITATIONS)
    questions = [
        "Would the observed effect survive source selection, independent uncertainty analysis and market-direction/concentration alternatives?",
        "Can the historical availability and execution-cost applicability be independently established?",
    ]
    native = [{"source_event_id": source.event_id, "native_status": "PROPOSED_SPECIFICATION",
               "mapped_classification": "EVALUABLE" if gates["eligible"] else "NOT_EVALUABLE",
               "reason": "A frozen specification is not a measured outcome or authorization."}]
    classification = "EVALUABLE" if gates["eligible"] else "NOT_EVALUABLE"
    performed = False
    if request["assessment_scope"] == "ECONOMIC_VALIDATION" and result is None:
        classification = "NOT_EVALUABLE"
        finding("ECONOMIC_VALIDITY", "PREREQUISITE", "Economic validation needs publication-time, applicable calibrated costs and frozen uncertainty evidence absent from the present descriptive method.")
    if result is not None:
        calculation = result.get("calculation_result", result)
        status = calculation.get("status", "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER")
        native_result_status = result.get("status", result.get("evaluation_purpose", "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER"))
        performed = status == "SHADOW_SIMULATED"
        if status != "SHADOW_SIMULATED":
            classification = "NOT_EVALUABLE"
            finding("EVALUATION_PREREQUISITES", "PREREQUISITE", "No hypothesis-return evaluation occurred; source gates or a data-quality-only method withheld strategy scoring.",
                    event=evaluation, pointer="/payload/result/status" if "status" in result else "/payload/result/evaluation_purpose",
                    observed=native_result_status if "status" in result else result["evaluation_purpose"])
        else:
            classification = "INCONCLUSIVE"
            stem = "/payload/result" + ("/calculation_result" if "calculation_result" in result else "")
            runs = calculation["cost_stress_runs"]
            comparisons, baseline_positive = [], False
            for run_index, run in enumerate(runs):
                runstem = stem + "/cost_stress_runs/%d" % run_index
                finding("COST_SENSITIVITY", "SUPPORTS" if run["status"] == "SIMULATED" else "LIMITATION",
                    "The frozen cost stress is retained without clipping, extrapolation or post hoc repair.", event=evaluation,
                    pointer=runstem + "/status", observed=run["status"])
                for fold_index, fold in enumerate(run["folds"]):
                    comparison = fold["comparison"]
                    comparisons.append(comparison)
                    prefix = runstem + "/folds/%d/comparison" % fold_index
                    complete = comparison["status"] == "COMPLETE_DESCRIPTIVE_COMPARISON"
                    if not complete:
                        finding("BENCHMARK_COMPARISON", "LIMITATION", "An incomplete or noncomparable required control cannot support or contradict the return expectation.",
                            event=evaluation, pointer=prefix + "/status", observed=comparison["status"])
                    for key in ("net_excess_vs_cash", "net_excess_vs_control"):
                        signkey = "positive_vs_cash" if key.endswith("cash") else "positive_vs_control"
                        finding("BENCHMARK_COMPARISON", "SUPPORTS" if complete and comparison[signkey] else ("CONTRADICTS" if complete else "UNKNOWN"),
                            "Descriptive signed excess at cost multiplier %s in fold %s; this is not a confidence interval or validated edge." % (run["multiplier"], fold["fold_id"]),
                            event=evaluation, pointer=prefix + "/" + key, observed=comparison[key])
                    if run["multiplier"] == "1" and complete and comparison["positive_vs_cash"]:
                        baseline_positive = True
                if run["multiplier"] == "1" and run["candidate"] is not None:
                    for fold_index, fold in enumerate(run["candidate"]["folds"]):
                        for key in _METRICS:
                            value = fold["metrics"].get(key)
                            finding("ECONOMIC_MEASUREMENTS", "UNKNOWN" if value is None or value == "NOT_ASSESSED" else "SUPPORTS",
                                "Native descriptive measurement %s in fold %s; missing values are not substituted." % (key, fold["fold_id"]),
                                event=evaluation, pointer=runstem + "/candidate/folds/%d/metrics/%s" % (fold_index, key) if key in fold["metrics"] else None,
                                observed=value)
                        finding("TRADE_DISTRIBUTION", "LIMITATION", "Sell-fill counts, win rate and expectancy are descriptive sample statistics; independent trade distribution uncertainty is not assessed.", event=evaluation)
                        finding("GROSS_PERFORMANCE", "LIMITATION", "Matched-lot gross P&L uses adversely adjusted modeled fill prices before fees; no frictionless gross-performance proxy is substituted.", event=evaluation)
            if (comparisons and all(item["status"] == "COMPLETE_DESCRIPTIVE_COMPARISON" for item in comparisons)
                    and all(not item["positive_vs_cash"] or not item["positive_vs_control"] for item in comparisons)
                    and not baseline_positive and request["assessment_scope"] == "EXPLORATORY_RESEARCH"):
                classification = "CONTRADICTED"
                finding("DECLARED_EXPECTATION", "CONTRADICTS", "Every complete declared fold/stress fails at least one required positive comparison; contradiction is restricted to these descriptive retained intervals, not the general economic mechanism.", event=evaluation)
            if baseline_positive:
                finding("ECONOMIC_ROBUSTNESS", "LIMITATION", "An apparently positive base-cost result does not establish robustness, uncertainty, selection independence or a generalizable economic edge.", event=evaluation)
            finding("HOLDOUT_BOUNDARY", "SUPPORTS", "The final holdout remains withheld; this assessment does not score it.",
                event=evaluation, pointer=stem + "/final_holdout/scoring_status", observed=calculation["final_holdout"]["scoring_status"])
            finding("STATISTICAL_UNCERTAINTY", "LIMITATION", "No uncertainty estimate, effective independent sample size or post-selection adjustment exists in the frozen method.", event=evaluation)
        native.append({"source_event_id": evaluation.event_id, "native_status": native_result_status,
                       "mapped_classification": classification,
                       "reason": "Existing method status maps to research acceptance without replacing the source status."})
    native.insert(1, {"source_event_id": research.event_id,
        "native_status": research.event_type,
        "mapped_classification": "EVALUABLE" if gates["eligible"] else "NOT_EVALUABLE",
        "reason": "Registration describes evaluation prerequisites independently of any later outcome."})
    candidate_ref = request["candidate_result_evidence"]
    if candidate_ref is not None:
        if result is None:
            raise ValueError("candidate-result assessment requires an existing original evaluation")
        raw = _blob(blobs, candidate_ref)
        if candidate_ref["path"] in evidence and evidence[candidate_ref["path"]] != raw:
            raise ValueError("candidate result path collides with source evidence")
        evidence[candidate_ref["path"]] = raw
        if len(evidence) > 512 or sum(map(len, evidence.values())) > 64 * 1024 * 1024:
            raise ValueError("trading acceptance exceeds its retained evidence bound")
        try:
            candidate = parse_strict_json_object_bytes(raw)
            agrees = canonical_json_bytes(candidate) == canonical_json_bytes(result)
        except (ValueError, TypeError, RecursionError):
            agrees = False
        if not agrees:
            classification = "INVALID"
            finding("REPRODUCIBILITY", "INVALID", "The separately retained, untrusted candidate result disagrees with the exact frozen original replay or is malformed. The authoritative original evaluation remains unchanged.",
                event=evaluation, observed=False)
        else:
            finding("REPRODUCIBILITY", "SUPPORTS", "The separately retained candidate result exactly matches the original frozen replay.", event=evaluation, observed=True)
    if material.get("study") is not None and material["study"].evidence_scope == "SYNTHETIC_FIXTURE_ONLY":
        limitations.append("AUTHORED_FIXTURE_ESTABLISHES_SOFTWARE_BEHAVIOR_NOT_REAL_SECURITY_EFFECTIVENESS")
    claim_scope = ("Declared descriptive hypothesis expectations on retained development intervals only; economic validation and market-wide generalization are unresolved."
                   if request["assessment_scope"] == "EXPLORATORY_RESEARCH" else
                   "Economic validation requested; the current frozen method establishes descriptive simulation only and cannot establish an investment-quality trading edge.")
    fields = {"classification": classification, "evaluation_performed": performed,
        "native_status_mapping": native, "findings": findings,
        "limitations": limitations, "unresolved_questions": questions,
        "next_evidence_requirements": list(NEXT_EVIDENCE), "economic_hypothesis_supported": False,
        "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "claim_scope": claim_scope, "maturity": "DESCRIPTIVE_ONLY"}
    return {"assessment_fields": fields, "evidence": evidence}
