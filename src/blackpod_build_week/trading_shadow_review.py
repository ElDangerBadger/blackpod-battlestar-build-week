"""Additive governed evidence/risk boundary around frozen shadow calculations."""
from .contracts.trading_shadow_review import ReviewedShadowStudy
from .contracts.trading_shadow_research import TradingShadowStudy
from .contracts.trading_shadow_risk_review import TradingShadowRiskReview
from .contracts.trading_research import TradingResearchPlan
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_research_journal import _blob, registered_context, evidence_for_research
from .trading_shadow_risk_review import shadow_risk_review_material, project_reviewed_base_plan
from .trading_continuity_intake import verify_continuity_intake
from .trading_cost_intake import verify_cost_intake
from .trading_shadow_gates import shadow_gate_material
from .trading_shadow_intents import produce_shadow_intents
from .trading_shadow_evaluation import evaluate_shadow_study

METHOD_VERSION = "blackpod.governed_shadow_review.v1"


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def mapping(value):
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def merge_evidence(target, incoming):
    for path, raw in incoming.items():
        if path in target and target[path] != raw:
            raise ValueError("reviewed shadow source paths bind conflicting bytes")
        target[path] = raw
    if len(target) > 512 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("reviewed shadow evidence exceeds file or combined-byte bound")


def _export(reference, blobs, verify):
    if reference is None:
        return None
    from .contracts.mission_request import parse_strict_json_object_bytes
    return verify(parse_strict_json_object_bytes(_blob(blobs, reference)), blobs)


def reviewed_study_material(study, events, blobs):
    study = study if isinstance(study, ReviewedShadowStudy) else ReviewedShadowStudy.from_mapping(study)
    base = TradingResearchPlan.from_bytes(_blob(blobs, study.base_plan_evidence))
    if base.schema_version != "blackpod.trading_research_plan.v2":
        raise ValueError("reviewed study requires original registered quality plan v2")
    base, dataset, _, original = registered_context(base, events, blobs)
    if parse_rfc3339(study.registered_at, "study clock") < parse_rfc3339(original.recorded_at, "base clock"):
        raise ValueError("reviewed study cannot predate original plan registration")
    risk_review = TradingShadowRiskReview.from_bytes(_blob(blobs, study.risk_review_evidence))
    if study.sizing != risk_review.sizing or study.evidence_scope != risk_review.evidence_scope:
        raise ValueError("reviewed study sizing/scope must equal its explicit risk review")
    risk_material = shadow_risk_review_material(risk_review, base, dataset, blobs, study.registered_at)
    hypothesis = TradingHypothesis.from_bytes(_blob(blobs, base.frozen_hypothesis_evidence))
    continuity = _export(study.continuity_intake_evidence, blobs, verify_continuity_intake)
    costs = _export(study.cost_intake_evidence, blobs, verify_cost_intake)
    reasons = list(risk_material["assessment"]["reason_codes"])
    evidence = evidence_for_research(base, blobs)
    merge_evidence(evidence, {study.base_plan_evidence["path"]: _blob(blobs, study.base_plan_evidence),
        study.risk_review_evidence["path"]: _blob(blobs, study.risk_review_evidence)})
    merge_evidence(evidence, risk_material["evidence"])
    for material, reference, kind in ((continuity, study.continuity_intake_evidence, "CONTINUITY"),
                                      (costs, study.cost_intake_evidence, "COST")):
        if material is None:
            reasons.append(kind + "_INTAKE_MISSING")
            continue
        if material["request"].dataset_evidence != base.dataset_evidence or material["request"].evidence_scope != study.evidence_scope:
            raise ValueError("reviewed adapter dataset or evidence scope differs from original study")
        if parse_rfc3339(material["request"].recorded_at, "adapter clock") > parse_rfc3339(study.registered_at, "study clock"):
            raise ValueError("reviewed study cannot predate its adapter intake")
        merge_evidence(evidence, material["evidence"])
        merge_evidence(evidence, {reference["path"]: _blob(blobs, reference)})
    if continuity is not None and continuity["review"].status != "CONTINUITY_SUPPORTED":
        reasons.append("CONTINUITY_ADAPTER_UNRESOLVED")
        if continuity["source"].events:
            reasons.append("PRICE_CONTINUITY_DISCONTINUITY_PRESENT")
        if not mapping(continuity["export"])["coverage_review_supported"]:
            reasons.append("EX_DATE_COVERAGE_UNVERIFIED")
    if costs is not None and not costs["assessment"]["eligible"]:
        reasons.extend(costs["assessment"]["reason_codes"])
        reasons.append("COST_ADAPTER_UNRESOLVED")
    projected = project_reviewed_base_plan(risk_review, base) if risk_material["assessment"]["eligible"] else base
    projected_path = "reviewed-shadow/internal-risk-plan.v2.json"
    projected_ref = ref(projected_path, projected.to_bytes())
    internal = study.to_dict()
    for key in ("continuity_intake_evidence", "cost_intake_evidence", "risk_review_evidence"):
        internal.pop(key)
    internal["schema_version"] = "blackpod.trading_shadow_study.v1"
    internal["base_plan_evidence"] = projected_ref
    internal["price_continuity_evidence"] = None if continuity is None else mapping(continuity["export"])["price_continuity_review_evidence"]
    internal["cost_evidence"] = None if costs is None else mapping(costs["export"])["review_evidence"]
    internal = TradingShadowStudy.from_mapping(internal)
    merge_evidence(evidence, {projected_path: projected.to_bytes(), "reviewed-shadow/internal-study.v1.json": internal.to_bytes()})
    combined = dict(blobs); combined.update({sha256_bytes(raw): raw for raw in evidence.values()})
    old_assessment = None
    if (continuity is not None and costs is not None and costs["source"] is not None
            and continuity["review"].status == "CONTINUITY_SUPPORTED" and costs["review"].status == "SUPPORTED"):
        checked = shadow_gate_material(internal, projected, dataset, combined)
        old_assessment = checked["assessment"]
        reasons.extend(old_assessment["reason_codes"])
        merge_evidence(evidence, checked["evidence"])
    reasons = sorted(set(reasons))
    gate = {"eligible": not reasons, "reason_codes": reasons,
        "cost_model": old_assessment["cost_model"] if not reasons and old_assessment is not None else None,
        "provenance": {"method_version": METHOD_VERSION, "risk_review_status": risk_review.status,
            "risk_review_evidence": study.risk_review_evidence,
            "continuity_intake_status": None if continuity is None else mapping(continuity["export"])["status"],
            "cost_intake_status": None if costs is None else costs["assessment"]["status"],
            "evidence_scope": study.evidence_scope, "provider_authenticity_verified": False,
            "historical_point_in_time_verified": False, "human_execution_approval_verified": False,
            "legacy_gates": old_assessment}}
    if gate["eligible"] and gate["cost_model"] is None:
        raise ValueError("reviewed eligibility requires complete independently gated costs")
    links = {"base_plan_event_id": original.event_id, "hypothesis_event_id": original.payload["hypothesis_event_id"],
        "intake_event_id": original.payload["intake_event_id"]}
    return {"study": study, "base_plan": base, "dataset": dataset, "hypothesis": hypothesis,
        "risk_review": risk_review, "risk_assessment": risk_material["assessment"], "continuity": continuity, "costs": costs,
        "projected_plan": projected, "internal_study": internal, "gate_assessment": gate,
        "evidence": evidence, "blobs": combined, "links": links}


def assess_reviewed_material(material):
    m = material
    production = produce_shadow_intents(m["internal_study"], m["projected_plan"], m["dataset"], m["hypothesis"], m["gate_assessment"])
    calculation = evaluate_shadow_study(m["internal_study"], m["projected_plan"], m["dataset"], m["hypothesis"], production, m["gate_assessment"])
    result = {"schema_version": "blackpod.trading_shadow_reviewed_evaluation.v1", "method_version": METHOD_VERSION,
        "study_id": m["study"].study_id, "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
        "status": calculation["status"], "evidence_scope": m["study"].evidence_scope,
        "gate_assessment": m["gate_assessment"], "risk_assessment": m["risk_assessment"],
        "original_plan_evidence": m["study"].base_plan_evidence, "original_simulation_risk": m["base_plan"].risk,
        "reviewed_simulation_risk": m["risk_review"].simulation_risk,
        "internal_risk_projection_prepared": m["risk_assessment"]["eligible"],
        "internal_risk_projection_semantics": "EPHEMERAL_SIMULATION_ONLY_ORIGINAL_PLAN_UNMODIFIED",
        "calculation_result": calculation, "final_holdout": calculation["final_holdout"],
        "realized_trade_pnl": None, "auto_trading_enabled": False, "authority": m["study"].authority}
    return {"production": production, "result": result}
