"""Pure review of simulation declarations using completed source-session data.

This assesses sizing feasibility, not strategy profitability or a broker's
buying power. It does not select optimal allocations, tune a risk rule, inspect
future prices, authenticate review identities, or grant either desk authority.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext

from .contracts.mission_request import parse_rfc3339
from .contracts.trading_research import (
    TRADING_RESEARCH_PLAN_V2_VERSION, TradingResearchDataset, TradingResearchPlan,
)
from .contracts.trading_shadow_risk_review import TradingShadowRiskReview
from .hashing import sha256_bytes

METHOD_VERSION = "blackpod.trading_shadow_sizing_risk_review.v1"
ASSESSMENT_VERSION = "blackpod.trading_shadow_risk_assessment.v1"
MAX_OPPORTUNITIES = 10000
_MAX_QUANTITY = Decimal("99999999999999999999")


class TradingShadowRiskReviewError(ValueError):
    """A retained review cannot be interpreted under its original source plan."""


def _context():
    return Context(prec=256, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   flags=[], traps=[DivisionByZero, InvalidOperation, Overflow])


def _document(value, cls):
    return cls.from_mapping(value.to_mapping() if isinstance(value, cls) else value)


def _time(value):
    return parse_rfc3339(value, "shadow risk review clock")


def _text(value):
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _bind(reference, document, name):
    body = document.to_bytes()
    if reference["sha256"] != sha256_bytes(body) or reference["size_bytes"] != len(body):
        raise TradingShadowRiskReviewError(name + " does not bind the exact supplied document")


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise TradingShadowRiskReviewError("risk review source evidence differs in hash or size")
    return raw


def _inputs(review, base_plan, dataset=None, study_registered_at=None):
    review, plan = _document(review, TradingShadowRiskReview), _document(base_plan, TradingResearchPlan)
    if plan.schema_version != TRADING_RESEARCH_PLAN_V2_VERSION:
        raise TradingShadowRiskReviewError("shadow risk review requires an original frozen data-quality plan v2")
    _bind(review.base_plan_evidence, plan, "base plan evidence")
    when = _time(review.recorded_at)
    if _time(plan.registered_at) > when:
        raise TradingShadowRiskReviewError("risk review cannot predate the original plan freeze")
    if study_registered_at is not None and when > _time(study_registered_at):
        raise TradingShadowRiskReviewError("risk review cannot follow the new shadow study freeze")
    if dataset is None:
        return review, plan, None
    data = _document(dataset, TradingResearchDataset)
    _bind(plan.dataset_evidence, data, "dataset evidence")
    if plan.universe != data.universe:
        raise TradingShadowRiskReviewError("risk review dataset and plan universes must match")
    if _time(data.recorded_at) > when:
        raise TradingShadowRiskReviewError("risk review cannot predate the retained dataset capture")
    count = 0
    for fold in plan.protocol["folds"]:
        test = fold["test"]
        if test["start_index"] < 1 or test["end_index"] >= len(data.sessions):
            raise TradingShadowRiskReviewError("TEST sizing opportunities require a completed previous session and returned session range")
        count += (test["end_index"] - test["start_index"] + 1) * len(plan.universe)
    if count > MAX_OPPORTUNITIES:
        raise TradingShadowRiskReviewError("risk sizing opportunities exceed the supported 10000-row bound")
    return review, plan, data


def project_reviewed_base_plan(review, base_plan):
    """Return an ephemeral simulation projection, preserving original identities.

    The result must never replace or register as the source plan. A caller must
    retain the original review/plan and explicitly bind this changed hash in its
    internal projection wrapper. Only the six simulation-risk fields change.
    """
    review, plan, _ = _inputs(review, base_plan)
    row = plan.to_mapping()
    row["risk"] = review.simulation_risk
    return TradingResearchPlan.from_mapping(row)


def shadow_risk_review_material(review, base_plan, dataset, blobs=None, study_registered_at=None):
    """Retain exact support bytes and report every causal TEST sizing opportunity."""
    with localcontext(_context()):
        review, plan, data = _inputs(review, base_plan, dataset, study_registered_at)
        retained, reasons = {}, []
        if review.status != "APPROVED_FOR_SHADOW":
            reasons.append("RISK_REVIEW_NOT_APPROVED_FOR_SHADOW")
        if blobs is None:
            reasons.append("RISK_REVIEW_SOURCE_EVIDENCE_UNVERIFIED")
        else:
            if _blob(blobs, review.base_plan_evidence) != plan.to_bytes() or _blob(blobs, plan.dataset_evidence) != data.to_bytes():
                raise TradingShadowRiskReviewError("risk review context differs from retained original plan or dataset bytes")
            for ref in review.source_evidence:
                if ref["path"] in {review.base_plan_evidence["path"], plan.dataset_evidence["path"], plan.intents_evidence["path"], plan.frozen_hypothesis_evidence["path"]}:
                    raise TradingShadowRiskReviewError("risk review support paths must be distinct from original research inputs")
                raw = _blob(blobs, ref)
                if sum(map(len, retained.values())) + len(raw) > 64 * 1024 * 1024:
                    raise TradingShadowRiskReviewError("risk review source evidence exceeds the retained-byte limit")
                retained[ref["path"]] = raw
        fixture = review.evidence_scope == "SYNTHETIC_FIXTURE_ONLY"
        if fixture and not all(symbol.startswith("SYNTH") for symbol in plan.universe):
            reasons.append("RISK_REVIEW_SYNTHETIC_SCOPE_REQUIRES_CONTROLLED_FIXTURE")
        if not fixture and any(symbol.startswith("SYNTH") for symbol in plan.universe):
            reasons.append("RISK_REVIEW_RETAINED_SCOPE_REJECTS_SYNTHETIC_SYMBOLS")
        risk, sizing = review.simulation_risk, review.sizing
        cash, budget = Decimal(risk["initial_cash"]), Decimal(sizing["per_symbol_notional"])
        position_cap, gross_cap = cash * Decimal(risk["max_position_fraction"]), cash * Decimal(risk["max_gross_exposure_fraction"])
        combined = budget * Decimal(len(plan.universe))
        if combined > gross_cap:
            reasons.append("FULL_UNIVERSE_DECLARED_NOTIONAL_EXCEEDS_GROSS_CAP")
        if combined > cash:
            reasons.append("FULL_UNIVERSE_DECLARED_NOTIONAL_EXCEEDS_CASH_CAP")
        minimum = min(cash / Decimal(len(plan.universe)), gross_cap / Decimal(len(plan.universe)),
                      position_cap, Decimal(risk["max_order_notional"]))
        bounds = {
            "simulation_initial_cash": risk["initial_cash"], "universe_count": len(plan.universe),
            "per_symbol_declared_notional": sizing["per_symbol_notional"], "full_universe_declared_notional": _text(combined),
            "maximum_order_notional": risk["max_order_notional"], "maximum_position_notional_at_initial_cash": _text(position_cap),
            "maximum_gross_notional_at_initial_cash": _text(gross_cap), "maximum_equal_symbol_notional_at_initial_cash": _text(minimum),
            "declaration_cap_semantics": "INITIAL_CASH_BOUNDS_NOT_LIVE_EQUITY_OR_GUARANTEED_FILL",
            "cost_reserve_semantics": "COSTS_AND_PRICE_GAPS_REQUIRE_SEPARATE_GATE_AND_RUNTIME_REJECTION",
        }
        rows, counts = [], {"total": 0, "feasible_known_close": 0, "deferred": 0}
        sessions = data.sessions
        for fold in plan.protocol["folds"]:
            for source_index in range(fold["test"]["start_index"] - 1, fold["test"]["end_index"]):
                session = sessions[source_index]
                decision_at = _time(session["available_at"]) + timedelta(microseconds=1)
                for bar in session["bars"]:
                    close, volume = Decimal(bar["close"]), Decimal(bar["volume"])
                    quantity = (budget / close).to_integral_value(rounding=ROUND_FLOOR)
                    row_reasons = []
                    if quantity == 0:
                        row_reasons.append("KNOWN_CLOSE_BUDGET_BELOW_ONE_WHOLE_SHARE")
                    elif quantity > _MAX_QUANTITY:
                        row_reasons.append("WHOLE_SHARE_QUANTITY_OUTSIDE_CONTRACT_BOUND")
                    volume_cap = volume * Decimal(risk["max_volume_participation_fraction"])
                    if quantity > volume_cap:
                        row_reasons.append("KNOWN_VOLUME_PARTICIPATION_CAP_EXCEEDED")
                    counts["total"] += 1
                    counts["deferred" if row_reasons else "feasible_known_close"] += 1
                    rows.append({
                        "fold_id": fold["fold_id"], "source_session_index": source_index, "source_session_id": session["session_id"],
                        "symbol": bar["symbol"], "decision_at": _stamp(decision_at), "source_available_at": session["available_at"],
                        "known_close": bar["close"], "known_volume": bar["volume"], "whole_quantity": _text(quantity),
                        "known_close_notional": _text(quantity * close), "unallocated_symbol_budget": _text(budget - quantity * close),
                        "maximum_quantity_from_known_volume": _text(volume_cap),
                        "status": "DEFER" if row_reasons else "FEASIBLE_AT_KNOWN_CLOSE_ONLY", "reason_codes": sorted(row_reasons),
                        "execution_or_fill_authorized": False,
                    })
        if not counts["feasible_known_close"]:
            reasons.append("ALL_TEST_SIZING_OPPORTUNITIES_INFEASIBLE")
        reasons = sorted(set(reasons))
        result = {
            "schema_version": ASSESSMENT_VERSION, "method_version": METHOD_VERSION,
            "risk_review_id": review.risk_review_id, "base_plan_id": plan.plan_id,
            "status": "DEFER_SHADOW_SIZING" if reasons else "READY_FOR_SHADOW_SIZING", "eligible": not reasons,
            "reason_codes": reasons, "evidence_scope": review.evidence_scope,
            "simulation_risk": risk, "sizing": sizing, "budget_bounds": bounds,
            "opportunity_counts": counts, "opportunities": rows,
            "provenance": {
                "base_plan_evidence": review.base_plan_evidence, "source_evidence": review.source_evidence,
                "source_evidence_hash_verified": blobs is not None, "reviewer_id": review.reviewer_id,
                "review_notes": review.review_notes,
                "review_status": review.status, "reviewer_identity_authenticated": False,
                "human_execution_approval_verified": False, "desk_budget_activated": False,
                "source_time_semantics": "SOURCE_CAPTURE_CLOCK_VALIDATION_BELONGS_TO_GOVERNED_ADAPTER",
                "sizing_inputs": "COMPLETED_SOURCE_SESSION_CLOSE_AND_VOLUME_ONLY_NO_FUTURE_PRICES_OR_RETURNS",
                "strategy_selection_or_tuning_performed": False, "limitations": review.limitations,
            },
            "auto_trading_enabled": False, "authority": review.authority,
        }
        return {"assessment": result, "evidence": retained}


def assess_shadow_risk_review(review, base_plan, dataset, blobs=None, study_registered_at=None):
    return shadow_risk_review_material(review, base_plan, dataset, blobs, study_registered_at)["assessment"]
