"""Pure evidence gates; local reviews never authenticate a provider or policy.

All claimed coverage, event rows and cost bounds are checked against retained
bytes. Origin evidence is retained verbatim for human audit, not executed or
replaced by a review status. Missing optional evidence defers research.
"""
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from .contracts.mission_request import parse_rfc3339
from .contracts.trading_shadow_research import (
    TradingShadowStudy, PriceContinuityEvidence, TradingCostEvidence,
    PriceContinuitySource, TradingCostSource, validate_shadow_cost_model,
)
from .contracts.trading_research import TradingResearchPlan, TradingResearchDataset
from .contracts.historical_intake import HistoricalIntakeRequest
from .hashing import sha256_bytes

METHOD_VERSION = "blackpod.trading_shadow_evidence_gates.v1"


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ValueError("shadow gate evidence differs in hash or size")
    return raw


def _retain(retained, ref, blobs):
    raw = _blob(blobs, ref)
    if ref["path"] in retained and retained[ref["path"]] != raw:
        raise ValueError("shadow gate source paths bind conflicting bytes")
    if ref["path"] not in retained and (len(retained) >= 256 or sum(map(len, retained.values())) + len(raw) > 64 * 1024 * 1024):
        raise ValueError("shadow gate evidence exceeds retained-file or combined-byte limits")
    retained[ref["path"]] = raw
    return raw


def shadow_gate_material(study, base_plan, dataset, blobs):
    study = TradingShadowStudy.from_mapping(study.to_dict() if isinstance(study, TradingShadowStudy) else study)
    base_plan = base_plan if isinstance(base_plan, TradingResearchPlan) else TradingResearchPlan.from_mapping(base_plan)
    dataset = dataset if isinstance(dataset, TradingResearchDataset) else TradingResearchDataset.from_mapping(dataset)
    if base_plan.schema_version != "blackpod.trading_research_plan.v2" or dataset.schema_version != "blackpod.trading_research_dataset.v2":
        raise ValueError("shadow gates require original quality plan v2 and governed dataset v2")
    if _blob(blobs, study.base_plan_evidence) != base_plan.to_bytes() or _blob(blobs, base_plan.dataset_evidence) != dataset.to_bytes():
        raise ValueError("shadow gate context differs from its exact source evidence")
    request = HistoricalIntakeRequest.from_bytes(_blob(blobs, dataset.provenance["governed_intake"]["request_evidence"]))
    reasons, retained, reviews, sources = [], {}, {}, {}
    ids = [session["session_id"] for session in dataset.sessions]
    dataset_clock = parse_rfc3339(dataset.recorded_at, "dataset clock")
    freeze_clock = parse_rfc3339(study.registered_at, "study clock")
    fixture = study.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
    if fixture and (not all(symbol.startswith("SYNTH") for symbol in dataset.universe)
                    or request.availability_assumption["declared_by"] != "synthetic-fixture-author"):
        reasons.append("SYNTHETIC_SCOPE_REQUIRES_EXPLICIT_CONTROLLED_FIXTURE")
    cost_model = None
    for kind, ref, review_cls, source_cls in (
        ("PRICE_CONTINUITY", study.price_continuity_evidence, PriceContinuityEvidence, PriceContinuitySource),
        ("COST", study.cost_evidence, TradingCostEvidence, TradingCostSource),
    ):
        if ref is None:
            reasons.append(kind + "_EVIDENCE_MISSING")
            continue
        review = review_cls.from_bytes(_retain(retained, ref, blobs))
        expected_basis = "SYNTHETIC_FIXTURE" if fixture else ("RETAINED_COST_REVIEW" if kind == "COST" else "RETAINED_CORPORATE_ACTION_REVIEW")
        if review.basis != expected_basis:
            reasons.append(kind + "_EVIDENCE_SCOPE_MISMATCH")
        if review.dataset_evidence != base_plan.dataset_evidence or review.universe != dataset.universe:
            raise ValueError("gate review dataset or universe differs from original research")
        if (review.coverage_start_session_id, review.coverage_end_session_id) != (ids[0], ids[-1]):
            reasons.append(kind + "_REVIEW_COVERAGE_INCOMPLETE")
        review_clock = parse_rfc3339(review.recorded_at, "review clock")
        if not dataset_clock <= review_clock <= freeze_clock:
            raise ValueError("gate review cannot predate capture or follow study freeze")
        if review.status != ("SUPPORTED" if kind == "COST" else "CONTINUITY_SUPPORTED"):
            reasons.append(kind + "_REVIEW_UNRESOLVED")
        rows = []
        for source_ref in review.source_evidence:
            source = source_cls.from_bytes(_retain(retained, source_ref, blobs))
            if source.dataset_evidence != base_plan.dataset_evidence or source.universe != dataset.universe:
                raise ValueError("gate source dataset or universe differs from reviewed research")
            if source.basis != ("SYNTHETIC_FIXTURE" if fixture else "RETAINED_REVIEW_SOURCE"):
                reasons.append(kind + "_SOURCE_SCOPE_MISMATCH")
            if ((source.coverage_start_session_id, source.coverage_end_session_id) != (ids[0], ids[-1])
                    or not source.coverage_complete):
                reasons.append(kind + "_SOURCE_COVERAGE_INCOMPLETE")
            if not dataset_clock <= parse_rfc3339(source.recorded_at, "source clock") <= review_clock:
                raise ValueError("gate source declaration clock is outside capture/review bounds")
            for origin_ref in source.origin_evidence:
                if origin_ref["path"] in {ref["path"], source_ref["path"], base_plan.dataset_evidence["path"]}:
                    raise ValueError("gate origin evidence cannot be its own review, source or dataset")
                _retain(retained, origin_ref, blobs)
            if kind == "PRICE_CONTINUITY":
                if any(event["effective_session_id"] not in ids for event in source.events):
                    raise ValueError("corporate action references an unknown dataset session")
                if source.events:
                    reasons.append("PRICE_CONTINUITY_DISCONTINUITY_PRESENT")
            else:
                if review.cost_model is not None:
                    for observation in source.observations:
                        if any(Decimal(review.cost_model[field]) < Decimal(observation[field])
                               for field in ("spread_bps", "slippage_bps", "fee_bps", "fee_per_fill")):
                            reasons.append("COST_MODEL_BELOW_RETAINED_REVIEW_BOUND")
            rows.append({"evidence": source_ref, "source": source.to_dict()})
        reviews[kind] = {"evidence": ref, "review": review.to_dict()}
        sources[kind] = rows
        if kind == "COST":
            cost_model = review.cost_model
            if cost_model is None:
                reasons.append("COST_MODEL_MISSING")
            else:
                with localcontext(Context(prec=256, rounding=ROUND_HALF_EVEN)):
                    if Decimal(cost_model["spread_bps"]) + Decimal(cost_model["slippage_bps"]) <= 0:
                        reasons.append("COST_ZERO_FRICTION_NOT_SUPPORTED")
                    try:
                        for multiplier in study.cost_stress_multipliers:
                            validate_shadow_cost_model({field: format(Decimal(value) * Decimal(multiplier), "f")
                                                        for field, value in cost_model.items()})
                    except ValueError:
                        reasons.append("COST_STRESS_BOUND_EXCEEDS_SUPPORTED_RANGE")
    reasons = sorted(set(reasons))
    assessment = {"eligible": not reasons,
        "reason_codes": reasons, "cost_model": cost_model if not reasons else None,
        "provenance": {"gate_method_version": METHOD_VERSION, "evidence_scope": study.evidence_scope, "reviews": reviews, "sources": sources,
            "provider_authenticity_verified": False, "historical_point_in_time_verified": False,
            "origin_evidence_semantics": "RETAINED_LOCAL_REVIEW_MATERIAL_NOT_PROVIDER_ATTESTATION",
            "costs_semantics": "DECLARED_REVIEW_BOUNDS_NOT_OBSERVED_EXECUTION_COSTS",
            "continuity_policy": "DEFER_ENTIRE_DATASET_IF_ANY_DECLARED_DISCONTINUITY_OR_INCOMPLETE_COVERAGE"}}
    return {"assessment": assessment, "evidence": retained}


def assess_shadow_gates(study, base_plan, dataset, blobs):
    return shadow_gate_material(study, base_plan, dataset, blobs)["assessment"]
