"""Pure qualification of frozen trading evidence, separate from simulation.

This design gate does not alter v15/v16 gates, evaluate returns, consume legacy
Galactica rules, or implement the declared future statistical protocol.
"""
from decimal import Context, Decimal, ROUND_FLOOR, localcontext
from pathlib import Path

from .contracts.trading_evidence_qualification import (
    TradingEvidenceQualificationPolicy, TradingTrainingAssumptions,
    TradingEvidenceQualificationRequest, POLICY_TYPE, ASSESSMENT_TYPE,
    POLICY_VERSION, CONTINUITY_POLICY, COST_POLICY,
)
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.trading_research import TradingResearchPlan
from .contracts.mission_request import parse_rfc3339
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, registered_context, validate_research_event
from .trading_shadow_review_journal import validate_reviewed_event

CODE_PATHS = ("contracts/trading_evidence_qualification.py", "trading_evidence_qualification.py",
              "trading_continuity_qualification.py", "trading_training_calibration.py", "trading_evidence_qualification_journal.py")
AUTHORITY = {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"qualification/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def merge(target, material):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw):
            raise ValueError("qualification evidence paths must bind unambiguous bytes")
        target[path] = raw
    if len(target) > 512 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("qualification exceeds retained evidence bounds")


def event_by_id(events, identity, types):
    matches = [event for event in events if event.event_id == identity and event.domain == "TRADING" and event.event_type in types]
    if len(matches) != 1: raise ValueError("qualification requires unique preceding TRADING source records")
    return matches[0]


def _prefix(document, events, event_type, id_field):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events): raise ValueError("ambiguous qualification history")
    matches = [event for event in events if event.event_type == event_type and event.source[id_field] == getattr(document, id_field)]
    if len(matches) > 1: raise ValueError("ambiguous qualification identity")
    if matches:
        field = "policy" if event_type == POLICY_TYPE else "request"
        if matches[0].payload[field] != document.to_dict(): raise ValueError("qualification identity is immutable")
        events = events[:events.index(matches[0])]
    return events


def prepare_policy(events, blobs, *, policy_id, recorded_at, base_plan_event_id,
                   supporting_evidence, reviewer_id, review_notes, continuity_event_id=None,
                   cost_event_id=None, risk_review_event_id=None, training_quote_chains=None,
                   training_cost_assumptions_evidence=None, uncertainty_protocol=None,
                   status="PROPOSED", supersedes_policy_event_id=None):
    base = event_by_id(events, base_plan_event_id, {"TRADING_RESEARCH_PLAN_REGISTERED"})
    plan = TradingResearchPlan.from_mapping(base.payload["plan"])
    reference = next((ref for ref in base.evidence if ref["sha256"] == base.source["source_sha256"]), None)
    if reference is None or plan.schema_version != "blackpod.trading_research_plan.v2": raise ValueError("qualification requires a frozen governed v2 plan")
    if training_quote_chains is None:
        training_quote_chains = []
        if cost_event_id is not None:
            from .contracts.trading_cost_intake import CostIntakeRequest
            old = event_by_id(events, cost_event_id, {"TRADING_COST_INTAKE_RECORDED"})
            native = CostIntakeRequest.from_mapping(old.payload["request"])
            # Retain the explicit existing sample even when it is outside TRAIN.
            # The new calibrator defers; preparation never relabels sessions.
            training_quote_chains = [{"fold_id": fold["fold_id"], "pages": native.quote_pages} for fold in plan.protocol["folds"]]
    evidence_scope = "RETAINED_HISTORY_RESEARCH"
    if continuity_event_id is not None:
        source = event_by_id(events, continuity_event_id, {"TRADING_CONTINUITY_INTAKE_RECORDED"})
        evidence_scope = source.payload["request"]["evidence_scope"]
    elif risk_review_event_id is not None:
        evidence_scope = event_by_id(events, risk_review_event_id, {"TRADING_SHADOW_RISK_REVIEW_RECORDED"}).payload["review"]["evidence_scope"]
    return TradingEvidenceQualificationPolicy.from_mapping({
        "schema_version": POLICY_VERSION, "policy_id": policy_id, "recorded_at": recorded_at,
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_EVIDENCE_QUALIFICATION_ONLY", "status": status,
        "base_plan_event_id": base.event_id, "base_plan_evidence": reference, "dataset_evidence": plan.dataset_evidence,
        "hypothesis_evidence": plan.frozen_hypothesis_evidence, "continuity_event_id": continuity_event_id,
        "cost_event_id": cost_event_id, "risk_review_event_id": risk_review_event_id, "training_quote_chains": training_quote_chains,
        "training_cost_assumptions_evidence": training_cost_assumptions_evidence, "evidence_scope": evidence_scope,
        "continuity_policy": CONTINUITY_POLICY, "cost_policy": COST_POLICY, "uncertainty_protocol": uncertainty_protocol,
        "supporting_evidence": supporting_evidence, "reviewer_id": reviewer_id, "review_notes": review_notes,
        "supersedes_policy_event_id": supersedes_policy_event_id, "auto_trading_enabled": False, "authority": AUTHORITY})


def policy_context(policy, events, blobs):
    policy = policy if isinstance(policy, TradingEvidenceQualificationPolicy) else TradingEvidenceQualificationPolicy.from_mapping(policy)
    events = _prefix(policy, events, POLICY_TYPE, "policy_id")
    base = event_by_id(events, policy.base_plan_event_id, {"TRADING_RESEARCH_PLAN_REGISTERED"})
    validate_research_event(base, events[:events.index(base)], blobs)
    plan, data, _, _ = registered_context(base.payload["plan"], events, blobs)
    if (plan.schema_version != "blackpod.trading_research_plan.v2" or policy.base_plan_evidence not in base.evidence
            or _blob(blobs, policy.base_plan_evidence) != plan.to_bytes() or policy.dataset_evidence != plan.dataset_evidence
            or policy.hypothesis_evidence != plan.frozen_hypothesis_evidence):
        raise ValueError("qualification must bind the exact original plan/dataset/hypothesis")
    hypothesis = TradingHypothesis.from_bytes(_blob(blobs, policy.hypothesis_evidence))
    parent = event_by_id(events, base.payload["hypothesis_event_id"], {"TRADING_HYPOTHESIS_CATALOG_RECORDED"})
    from .trading_research_intake_journal import validate_intake_event
    validate_intake_event(parent, events[:events.index(parent)], blobs)
    sources = [base, parent]; selected = {}
    for field, kind in (("continuity_event_id", "TRADING_CONTINUITY_INTAKE_RECORDED"), ("cost_event_id", "TRADING_COST_INTAKE_RECORDED"), ("risk_review_event_id", "TRADING_SHADOW_RISK_REVIEW_RECORDED")):
        identity = getattr(policy, field)
        if identity is None: selected[field] = None; continue
        event = event_by_id(events, identity, {kind})
        validate_reviewed_event(event, events[:events.index(event)], blobs)
        source_doc = event.payload["review" if field == "risk_review_event_id" else "request"]
        if source_doc["evidence_scope"] != policy.evidence_scope: raise ValueError("qualification evidence scope mismatch")
        if field != "risk_review_event_id" and source_doc["dataset_evidence"] != policy.dataset_evidence: raise ValueError("qualification source dataset mismatch")
        if field == "risk_review_event_id" and _blob(blobs, source_doc["base_plan_evidence"]) != plan.to_bytes(): raise ValueError("qualification risk source plan mismatch")
        selected[field] = event; sources.append(event)
    if any(parse_rfc3339(event.recorded_at, "source clock") > parse_rfc3339(policy.recorded_at, "policy freeze") for event in sources):
        raise ValueError("qualification policy cannot precede source records")
    if policy.evidence_scope == "SYNTHETIC_FIXTURE_ONLY" and not all(symbol.startswith("SYNTH") for symbol in data.universe):
        raise ValueError("fictional evidence scope requires fictional symbols")
    evidence = {}
    for event in sources:
        merge(evidence, {ref["path"]: _blob(blobs, ref) for ref in event.evidence})
    external = list(policy.supporting_evidence)
    external += [ref for chain in policy.training_quote_chains for page in chain["pages"] for ref in page.values()]
    from .contracts.trading_evidence_capture import CaptureReceipt
    for chain in policy.training_quote_chains:
        if chain["fold_id"] not in {fold["fold_id"] for fold in plan.protocol["folds"]}: raise ValueError("training quote chain names an unknown original fold")
        for page in chain["pages"]:
            receipt = CaptureReceipt.from_bytes(_blob(blobs, page["receipt_evidence"]))
            if receipt.url != "https://data.alpaca.markets/v2/stocks/quotes" or receipt.body_sha256 != page["body_evidence"]["sha256"] or receipt.size_bytes != page["body_evidence"]["size_bytes"]:
                raise ValueError("training receipt must bind exact native quote bytes")
            if not parse_rfc3339(data.recorded_at, "dataset clock") <= parse_rfc3339(receipt.captured_at, "capture clock") <= parse_rfc3339(policy.recorded_at, "policy freeze"):
                raise ValueError("training capture must follow source dataset and precede policy freeze")
    if policy.training_cost_assumptions_evidence is not None:
        reference = policy.training_cost_assumptions_evidence
        assumptions = TradingTrainingAssumptions.from_bytes(_blob(blobs, reference))
        if (assumptions.base_plan_evidence != policy.base_plan_evidence or assumptions.dataset_evidence != policy.dataset_evidence
                or assumptions.evidence_scope != policy.evidence_scope or parse_rfc3339(assumptions.recorded_at, "assumption clock") > parse_rfc3339(policy.recorded_at, "policy freeze")):
            raise ValueError("training assumptions must bind original source/scope and precede policy freeze")
        forbidden = {reference["sha256"], policy.base_plan_evidence["sha256"], policy.dataset_evidence["sha256"]}
        if any(ref["sha256"] in forbidden for ref in assumptions.origin_evidence): raise ValueError("training assumptions require separate retained support")
        external += [reference, *assumptions.origin_evidence]
    merge(evidence, {ref["path"]: _blob(blobs, ref) for ref in external})
    merge(evidence, implementation_evidence())
    merge(evidence, {"qualification/policy.v1.json": policy.to_bytes()})
    peers = [event for event in events if event.event_type == POLICY_TYPE and event.payload["policy"]["base_plan_event_id"] == base.event_id]
    if any(parse_rfc3339(event.recorded_at, "prior policy clock") > parse_rfc3339(policy.recorded_at, "policy freeze") for event in peers):
        raise ValueError("policy freeze clock cannot predate its preceding same-plan designs")
    if policy.supersedes_policy_event_id is not None:
        previous = next((event for event in peers if event.event_id == policy.supersedes_policy_event_id), None)
        if previous is None or any(event.payload["policy"]["supersedes_policy_event_id"] == previous.event_id for event in peers):
            raise ValueError("policy supersession requires an unsuperseded same-plan policy")
        if parse_rfc3339(previous.recorded_at, "prior policy") > parse_rfc3339(policy.recorded_at, "policy freeze"):
            raise ValueError("policy supersession cannot move backwards")
    return {"policy": policy, "events": events, "base": base, "parent": parent, "plan": plan,
        "dataset": data, "hypothesis": hypothesis, "sources": selected, "evidence": evidence,
        "links": {"base_plan_event_id": base.event_id, "hypothesis_event_id": parent.event_id, "intake_event_id": base.payload["intake_event_id"]}}


def _protocol(policy, plan, risk):
    protocol = policy.uncertainty_protocol
    reasons = []
    if protocol is None: return "MISSING", ["UNCERTAINTY_STABILITY_PROTOCOL_MISSING"]
    if protocol["minimum_development_folds"] > len(plan.protocol["folds"]): reasons.append("DECLARED_STABILITY_FOLD_COUNT_INFEASIBLE")
    feasible = 0
    for fold in plan.protocol["folds"]:
        count = len({row["source_session_id"] for row in risk["capacity_checks"] if row["fold_id"] == fold["fold_id"] and row["joint_eligible"]})
        if max(protocol["minimum_evaluation_sessions"], protocol["block_length_sessions"]) > count:
            reasons.append("DECLARED_UNCERTAINTY_QUALIFIED_SAMPLE_INFEASIBLE")
        else: feasible += 1
    if feasible < protocol["minimum_development_folds"]: reasons.append("DECLARED_STABILITY_QUALIFIED_FOLD_COUNT_INFEASIBLE")
    return ("INFEASIBLE" if reasons else "FROZEN_NOT_EVALUATED"), reasons


def _risk(material, calibration, continuity, blobs):
    from .trading_shadow_risk_review import assess_shadow_risk_review
    from .contracts.trading_shadow_risk_review import TradingShadowRiskReview
    event = material["sources"]["risk_review_event_id"]
    if event is None: return {"eligible": False, "reason_codes": ["SIMULATION_RISK_REVIEW_MISSING"], "native_assessment": None, "capacity_checks": []}
    review = TradingShadowRiskReview.from_mapping(event.payload["review"])
    native = assess_shadow_risk_review(review, material["plan"], material["dataset"], blobs, material["policy"].recorded_at)
    reasons = list(native["reason_codes"]); checks = []
    if not native["eligible"]: reasons.append("EXPLICIT_SIMULATION_RISK_REVIEW_UNQUALIFIED")
    # Daily participation is a declared research proxy, not opening liquidity.
    by_fold = {fold["fold_id"]: fold for fold in calibration["folds"]}
    continuity_windows = {(row["fold_id"], row["symbol"], row["source_session_id"]): row for row in continuity["opportunities"]}
    with localcontext(Context(prec=256)):
        for opportunity in native["opportunities"]:
            fold = by_fold.get(opportunity["fold_id"], {})
            proxies = fold.get("capacity_proxy") or []
            proxy = next((item for item in proxies if item["symbol"] == opportunity["symbol"]), None)
            bound = None if proxy is None else proxy.get("daily_quantity_research_proxy")
            okay = bound is not None and Decimal(opportunity["whole_quantity"]) <= Decimal(bound)
            key = (opportunity["fold_id"], opportunity["symbol"], opportunity["source_session_id"])
            comparable = continuity_windows.get(key, {}).get("combined_eligible") is True
            known_close_feasible = opportunity["status"] == "FEASIBLE_AT_KNOWN_CLOSE_ONLY" and Decimal(opportunity["whole_quantity"]) > 0
            checks.append({"fold_id": opportunity["fold_id"], "symbol": opportunity["symbol"], "source_session_id": opportunity["source_session_id"], "whole_quantity": opportunity["whole_quantity"], "maximum_daily_proxy_quantity": bound, "within_daily_proxy": okay,
                "known_close_feasible": known_close_feasible, "continuity_comparable": comparable, "joint_eligible": okay and known_close_feasible and comparable,
                "native_reason_codes": opportunity["reason_codes"], "opening_fill_capacity_verified": False})
    if not any(row["joint_eligible"] for row in checks): reasons.append("NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS")
    return {"eligible": not reasons, "reason_codes": sorted(set(reasons)), "native_assessment": native, "capacity_checks": checks}


def qualify_evidence(request, events, blobs):
    request = request if isinstance(request, TradingEvidenceQualificationRequest) else TradingEvidenceQualificationRequest.from_mapping(request)
    events = _prefix(request, events, ASSESSMENT_TYPE, "qualification_id")
    policy_event = event_by_id(events, request.policy_event_id, {POLICY_TYPE})
    before = events[:events.index(policy_event)]
    material = policy_context(policy_event.payload["policy"], before, blobs)
    if policy_event.payload["links"] != material["links"] or policy_event.payload["implementation_evidence"] != refs(implementation_evidence()): raise ValueError("frozen qualification policy links or installed method changed")
    policy = material["policy"]
    if parse_rfc3339(policy.recorded_at, "policy freeze") > parse_rfc3339(request.data_cutoff_at, "cutoff"):
        raise ValueError("qualification cutoff must include frozen policy evidence")
    from .trading_continuity_intake import verify_continuity_intake
    from .trading_continuity_qualification import qualify_continuity_windows
    from .trading_training_calibration import calibrate_training_evidence
    continuity_source = material["sources"]["continuity_event_id"]
    native = None if continuity_source is None else verify_continuity_intake(continuity_source.payload["export"], blobs)
    continuity = qualify_continuity_windows(policy, material["plan"], material["dataset"], material["hypothesis"], native)
    calibration_material = calibrate_training_evidence(policy, material["plan"], material["dataset"], blobs)
    calibration = calibration_material["assessment"]
    risk = _risk(material, calibration, continuity, blobs)
    protocol_status, protocol_reasons = _protocol(policy, material["plan"], risk)
    reasons = list(continuity["reason_codes"]) + list(calibration["reason_codes"]) + list(risk["reason_codes"]) + protocol_reasons
    if policy.status != "REVIEWED_FOR_SHADOW_QUALIFICATION": reasons.append("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW")
    if continuity["counts"]["combined_eligible"] == 0: reasons.append("NO_COMPARABLE_CONTINUITY_WINDOWS")
    previous = [event for event in events if event.event_type == ASSESSMENT_TYPE and event.payload["policy_event_id"] == policy_event.event_id]
    if any(parse_rfc3339(event.recorded_at, "prior clock") > parse_rfc3339(request.recorded_at, "clock") for event in previous): raise ValueError("qualification cannot backdate prior assessment history")
    if request.supersedes_event_id is not None:
        prior = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if prior is None or any(event.payload["request"]["supersedes_event_id"] == prior.event_id for event in previous): raise ValueError("qualification supersession requires an unsuperseded same-policy assessment")
        if parse_rfc3339(prior.payload["request"]["data_cutoff_at"], "prior cutoff") > parse_rfc3339(request.data_cutoff_at, "cutoff"): raise ValueError("qualification supersession cutoff cannot move backwards")
    reasons = sorted(set(reasons))
    result = {"schema_version": "blackpod.trading_evidence_qualification.v1", "method_version": "blackpod.trading_real_evidence_qualification.v1",
        "qualification_id": request.qualification_id, "policy_id": policy.policy_id,
        "status": "DEFER_EVIDENCE_QUALIFICATION" if reasons else "READY_FOR_QUALIFIED_STUDY_DESIGN", "eligible_for_study_design": not reasons,
        "reason_codes": reasons, "continuity": continuity, "training_calibration": calibration, "risk": risk,
        "uncertainty_protocol": policy.uncertainty_protocol, "uncertainty_status": protocol_status,
        "uncertainty_computed": False, "economic_hypothesis_supported": False, "existing_gate_override": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "limitations": ["QUALIFIED_DESIGN_NOT_SIMULATION_EXECUTION_OR_STRATEGY_PROMOTION", "DAILY_VOLUME_PROXY_NOT_OPENING_LIQUIDITY_OR_FILL_CAPACITY", "UNCERTAINTY_PROTOCOL_FROZEN_NOT_IMPLEMENTED_OR_STATISTICALLY_VALIDATED", "RETROSPECTIVE_BOUNDARY_CENSORING_NOT_PROSPECTIVE_ACTION_AVAILABILITY", "CURRENT_V15_V16_GATE_DISPOSITIONS_PRESERVED", "FINAL_HOLDOUT_UNSCORED_NOT_ACCESS_SEALED"],
        "provenance": {"links": material["links"], "hypothesis_sha256": policy.hypothesis_evidence["sha256"], "policy_sha256": sha256_bytes(policy.to_bytes()),
            "provider_authenticity_verified": False, "historical_point_in_time_verified": False, "reviewer_identity_authenticated": False,
            "design_freeze_semantics": "DESIGN_FROZEN_BEFORE_THIS_CALIBRATION_ONLY", "native_cost_bound_used_for_calibration": False,
            "native_continuity_review_status": continuity["native_continuity_review_status"]},
        "auto_trading_enabled": False, "authority": AUTHORITY}
    evidence = dict(material["evidence"]); merge(evidence, calibration_material["evidence"])
    merge(evidence, {"qualification/request.v1.json": request.to_bytes()})
    return {"result": result, "evidence": evidence, "parent": material["parent"], "prior_qualification_event_ids": sorted(event.event_id for event in previous)}
