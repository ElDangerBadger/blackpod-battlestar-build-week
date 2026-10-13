"""Pure shadow simulations and predeclared, entry-notional matched controls.

Candidate inputs are independently generated research observations. Fractional
control quantities are arithmetic counterfactuals, never broker order sizes.
The comparator matches admitted entry purchase notional and holding duration;
it does not claim equal day-by-day exposure, beta, or realized execution costs.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext

from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.trading_research import (
    TradingResearchDataset, TradingResearchIntents, TradingResearchPlan,
    validate_research_inputs,
)
from .contracts.trading_shadow_research import TradingShadowStudy, validate_shadow_cost_model
from .trading_hypotheses import hypothesis_research_strategy
from . import trading_research_evaluation as generic

METHOD_VERSION = "blackpod.matched_entry_shadow_evaluation.v1"
CONTROL_KIND = "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"
SIGN_QUANTUM = Decimal("0.000000000000000000000001")
LIMITATIONS = (
    "RESEARCH_SIMULATION_NOT_REALIZED_TRADE_PNL",
    "RETROSPECTIVE_AVAILABILITY_ASSUMPTION_NOT_POINT_IN_TIME_PROOF",
    "RETAINED_SOURCE_REVIEW_NOT_PROVIDER_OR_REVIEWER_AUTHENTICATION",
    "FRACTIONAL_COUNTERFACTUAL_QUANTITIES_NOT_EXECUTABLE_ORDERS",
    "MATCHED_ENTRY_PURCHASE_NOTIONAL_AND_DURATION_NOT_DAILY_EXPOSURE_OR_BETA",
    "CONTROL_ADMISSION_CONDITIONAL_ON_CANDIDATE_ACCEPTED_ENTRY",
    "PRIOR_COMPLETED_VOLUME_NOT_OPENING_LIQUIDITY",
    "DECLARED_COST_STRESS_NOT_OBSERVED_EXECUTION_COST",
    "CASH_BASELINE_NO_INTEREST_ASSUMED",
    "FOLDS_RESET_CASH_NO_AGGREGATED_PORTFOLIO_RETURN",
    "UNSELECTED_UNIVERSE_AND_FAILED_CONTROLS_RETAINED_NO_WINNER_PROMOTION",
    "FINAL_HOLDOUT_WITHHELD_NOT_ACCESS_SEALED",
    "NO_ALPHA_SIGNIFICANCE_OR_EXECUTION_AUTHORITY",
)


def _mapping(value, document):
    return (document.from_bytes(value.to_bytes()) if isinstance(value, document)
            else document.from_mapping(value)).to_mapping()


def _text(value):
    return generic._text(value)


def _number(value):
    return Decimal(value)


def _projection(plan, dataset, intents, study, costs):
    """Use the unchanged generic arithmetic engine through ephemeral v1 inputs.

    No original plan/dataset bytes are mutated or reclassified in storage. The
    outer result retains their genuine retrospective availability semantics.
    """
    projected_plan, projected_data = deepcopy(plan), deepcopy(dataset)
    projected_plan.pop("frozen_hypothesis_evidence", None)
    projected_plan.pop("evaluation_purpose", None)
    projected_plan["schema_version"] = "blackpod.trading_research_plan.v1"
    projected_plan["plan_id"] = study["study_id"] + "-candidate"
    projected_plan["experiment_id"] = study["experiment_id"]
    projected_plan["trial_registry"] = deepcopy(study["trial_registry"])
    projected_plan["cost_model"] = costs
    projected_data["schema_version"] = "blackpod.trading_research_dataset.v1"
    projected_data["provenance"] = {
        "source_kind": "RETAINED_MARKET_CAPTURE",
        "source_evidence": deepcopy(dataset["provenance"]["source_evidence"]),
        "timestamp_policy": "RETAINED_RECEIPT_AVAILABILITY",
        "historical_point_in_time_verified": False,
    }
    return generic.evaluate_research(projected_plan, projected_data, intents)


def _validate_inputs(study, base_plan, dataset, hypothesis, production, gates):
    study = _mapping(study, TradingShadowStudy)
    plan = _mapping(base_plan, TradingResearchPlan)
    data = _mapping(dataset, TradingResearchDataset)
    hypothesis = _mapping(hypothesis, TradingHypothesis)
    if plan["schema_version"] != "blackpod.trading_research_plan.v2" or data["schema_version"] != "blackpod.trading_research_dataset.v2":
        raise ContractValidationError("shadow studies require immutable v2 hypothesis/data-quality sources")
    described = hypothesis_research_strategy(hypothesis)
    if plan["strategy"] != described["strategy"] or plan["horizon"] != described["horizon"]:
        raise ContractValidationError("shadow study must bind the original hypothesis strategy and horizon")
    empty = {"schema_version": "blackpod.trading_research_intents.v1", "intent_set_id": "shadow-source-validation",
             "plan_id": plan["plan_id"], "created_at": plan["registered_at"],
             "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [], "authority": study["authority"]}
    validate_research_inputs(plan, data, empty)
    if not isinstance(production, dict) or production.get("study_id") != study["study_id"] or production.get("hypothesis_id") != hypothesis["hypothesis_id"]:
        raise ContractValidationError("shadow production must bind this study and hypothesis")
    if production.get("auto_trading_enabled") is not False or production.get("authority") != study["authority"]:
        raise ContractValidationError("shadow production must retain disabled authority")
    intents = _mapping(production.get("intents"), TradingResearchIntents)
    if intents["plan_id"] != study["study_id"] + "-candidate":
        raise ContractValidationError("produced intent identity must bind the shadow candidate projection")
    if not isinstance(gates, dict) or set(gates) != {"eligible", "reason_codes", "cost_model", "provenance"}:
        raise ContractValidationError("shadow evaluation requires explicit evidence gate assessment")
    if type(gates["eligible"]) is not bool or not isinstance(gates["reason_codes"], list) or any(not isinstance(item, str) for item in gates["reason_codes"]) or not isinstance(gates["provenance"], dict):
        raise ContractValidationError("shadow evidence gate assessment is malformed")
    if gates["eligible"]:
        if gates["reason_codes"] or gates["cost_model"] is None:
            raise ContractValidationError("eligible shadow gates require reviewed costs and no unresolved reasons")
        validate_shadow_cost_model(gates["cost_model"])
    elif intents["decisions"] or production.get("episodes"):
        raise ContractValidationError("deferred gates cannot produce shadow exposure")
    _validate_episodes(production.get("episodes"), intents, plan, data, hypothesis)
    from .trading_shadow_intents import produce_shadow_intents
    if production != produce_shadow_intents(study, plan, data, hypothesis, gates):
        raise ContractValidationError("shadow production must exactly replay the frozen independent producer")
    return study, plan, data, hypothesis, intents


def _validate_episodes(episodes, intents, plan, data, hypothesis):
    if not isinstance(episodes, list) or len(episodes) > 10000:
        raise ContractValidationError("shadow episodes must be a bounded list")
    decisions = {row["decision_id"]: row for row in intents["decisions"]}
    folds = {row["fold_id"]: row for row in plan["protocol"]["folds"]}
    identities, bound = set(), set()
    for episode in episodes:
        if not isinstance(episode, dict):
            raise ContractValidationError("shadow episode must be a mapping")
        identity = episode.get("episode_id")
        if not isinstance(identity, str) or identity in identities:
            raise ContractValidationError("shadow episode identities must be distinct strings")
        identities.add(identity)
        fold = folds.get(episode.get("fold_id"))
        if fold is None or episode.get("symbol") not in plan["universe"]:
            raise ContractValidationError("shadow episode must bind a retained fold and symbol")
        entry_index, exit_index = episode.get("entry_session_index"), episode.get("exit_session_index")
        if type(entry_index) is not int or type(exit_index) is not int or exit_index - entry_index != hypothesis["horizon"]["holding_sessions"] or episode.get("holding_sessions") != exit_index - entry_index:
            raise ContractValidationError("shadow episode must preserve the hypothesis holding duration")
        if not fold["test"]["start_index"] <= entry_index < exit_index <= fold["test"]["end_index"]:
            raise ContractValidationError("shadow episodes cannot leave development TEST partitions")
        for role, action, index in (("entry", "BUY", entry_index), ("exit", "SELL", exit_index)):
            decision_id = episode.get(role + "_decision_id")
            if decision_id is None and role == "exit":
                continue
            decision = decisions.get(decision_id)
            if decision is None or decision_id in bound or decision["action"] != action or decision["fold_id"] != episode["fold_id"] or decision["symbol"] != episode["symbol"] or decision["qty"] != episode.get("qty") or decision["source_session_id"] != data["sessions"][index - 1]["session_id"]:
                raise ContractValidationError("shadow episode must bind its exact entry/exit intent, quantity and clock")
            bound.add(decision_id)
    if bound != set(decisions):
        raise ContractValidationError("every produced shadow decision must belong to one retained episode")


def _control_point(index, session, cash, cohorts, bars, role):
    positions = {}
    for cohort in cohorts:
        if cohort["status"] != "OPEN":
            continue
        for leg in cohort["legs"]:
            positions[leg["symbol"]] = positions.get(leg["symbol"], Decimal(0)) + _number(leg["qty"])
    values = [{"symbol": symbol, "qty": _text(qty),
               "market_value": _text(qty * _number(bars[symbol]["open" if role == "OPEN" else "close"]))}
              for symbol, qty in sorted(positions.items())]
    gross = sum((_number(row["market_value"]) for row in values), Decimal(0))
    return {"session_index": index, "session_id": session["session_id"], "mark_role": role,
            "cash": _text(cash), "equity": _text(cash + gross), "gross_exposure": _text(gross), "positions": values}


def _control_breaches(point, risk):
    equity, gross = _number(point["equity"]), _number(point["gross_exposure"])
    reasons = []
    if equity <= 0:
        reasons.append("CONTROL_NONPOSITIVE_EQUITY")
    if gross > equity * _number(risk["max_gross_exposure_fraction"]):
        reasons.append("CONTROL_GROSS_EXPOSURE_DRIFT")
    for position in point["positions"]:
        if _number(position["market_value"]) > equity * _number(risk["max_position_fraction"]):
            reasons.append("CONTROL_POSITION_EXPOSURE_DRIFT:" + position["symbol"])
    return [{"session_index": point["session_index"], "mark_role": point["mark_role"], "reason_code": reason} for reason in reasons]


def _matched_control(fold, plan, data, episodes, costs):
    """Admit whole equal-weight cohorts using one independent fold cash ledger."""
    fills = {row["decision_id"]: row for row in fold["fills"]}
    sessions, universe, risk = data["sessions"], plan["universe"], plan["risk"]
    cash, used_volume, cohorts, entry_schedule = _number(risk["initial_cash"]), {}, [], {}
    adverse = (_number(costs["spread_bps"]) / Decimal(2) + _number(costs["slippage_bps"])) / generic.BPS
    for episode in episodes:
        entry = fills.get(episode["entry_decision_id"])
        if entry is None:
            continue
        exit_fill = fills.get(episode.get("exit_decision_id"))
        matches = [] if exit_fill is None else [row for row in fold["matched_lots"] if row["exit_fill_id"] == exit_fill["fill_id"]]
        fifo_lineage = bool(matches) and all(row["entry_fill_id"] == entry["fill_id"] for row in matches) and sum((_number(row["qty"]) for row in matches), Decimal(0)) == _number(entry["qty"])
        cohort = {"cohort_id": episode["episode_id"] + "-control", "episode_id": episode["episode_id"],
                  "candidate_entry_fill_id": entry["fill_id"],
                  "candidate_exit_fill_id": None if exit_fill is None else exit_fill["fill_id"],
                  "candidate_fifo_lineage_matched": fifo_lineage,
                  "entry_session_index": episode["entry_session_index"], "exit_session_index": episode["exit_session_index"],
                  "holding_sessions": episode["holding_sessions"], "target_entry_purchase_notional": entry["notional"],
                  "status": "PENDING", "reason_codes": [], "legs": [], "simulated_net_pnl": None,
                  "candidate_simulated_net_pnl": None if exit_fill is None else exit_fill["simulated_realized_net_pnl"]}
        cohorts.append(cohort)
        entry_schedule.setdefault(episode["entry_session_index"], []).append(cohort)
    opening_curve, closing_curve, breaches = [], [], []
    declared_fold = next(row for row in plan["protocol"]["folds"] if row["fold_id"] == fold["fold_id"])
    for index in range(declared_fold["test"]["start_index"], declared_fold["test"]["end_index"] + 1):
        session = sessions[index]
        bars = {row["symbol"]: row for row in session["bars"]}
        known = {row["symbol"]: row for row in sessions[index - 1]["bars"]}
        # Exit before entry is a frozen arithmetic ordering, not provider fill
        # sequencing. Whole cohort admission preserves equal weighting.
        for cohort in sorted(cohorts, key=lambda row: row["cohort_id"]):
            if cohort["status"] != "OPEN" or cohort["exit_session_index"] != index:
                continue
            exits, reasons = [], []
            for leg in cohort["legs"]:
                symbol, qty = leg["symbol"], _number(leg["qty"])
                reference = _number(bars[symbol]["open"])
                price, notional = reference * (Decimal(1) - adverse), qty * reference * (Decimal(1) - adverse)
                fee = _number(costs["fee_per_fill"]) + notional * _number(costs["fee_bps"]) / generic.BPS
                volume = _number(known[symbol]["volume"])
                if volume == 0 or qty + used_volume.get((index, symbol), Decimal(0)) > volume * _number(risk["max_volume_participation_fraction"]):
                    reasons.append("CONTROL_EXIT_KNOWN_VOLUME_INSUFFICIENT:" + symbol)
                if notional > _number(risk["max_order_notional"]):
                    reasons.append("CONTROL_EXIT_MAX_ORDER_NOTIONAL:" + symbol)
                exits.append((leg, price, notional, fee, qty * (reference - price)))
            if cash + sum((item[2] - item[3] for item in exits), Decimal(0)) < 0:
                reasons.append("CONTROL_EXIT_INSUFFICIENT_CASH_FOR_FEES")
            if reasons:
                cohort["reason_codes"].extend(reasons)
                continue
            pnl = Decimal(0)
            for leg, price, notional, fee, adverse_cost in exits:
                gross = notional - _number(leg["entry_notional"])
                net = gross - _number(leg["entry_fee"]) - fee
                leg.update({"exit_reference_open_price": bars[leg["symbol"]]["open"], "exit_price": _text(price),
                            "exit_notional": _text(notional), "exit_fee": _text(fee),
                            "exit_adverse_price_cost": _text(adverse_cost), "simulated_gross_pnl": _text(gross), "simulated_net_pnl": _text(net)})
                cash += notional - fee
                used_volume[(index, leg["symbol"])] = used_volume.get((index, leg["symbol"]), Decimal(0)) + _number(leg["qty"])
                pnl += net
            cohort["status"], cohort["simulated_net_pnl"] = "CLOSED", _text(pnl)
        for cohort in sorted(entry_schedule.get(index, []), key=lambda row: row["cohort_id"]):
            target = _number(cohort["target_entry_purchase_notional"])
            # The final leg receives the exact Decimal residual: totals are
            # equal even for universes whose count does not divide the target.
            per_leg = target / Decimal(len(universe))
            legs, reasons, total_fees = [], [], Decimal(0)
            for offset, symbol in enumerate(universe):
                with localcontext(generic._context()) as allocation_context:
                    # Allocate finite 256-digit divisions with wider exact
                    # subtraction; sequential 256-digit subtraction can itself
                    # introduce a residual into the purported matching ledger.
                    allocation_context.prec = 512
                    notional = target - per_leg * Decimal(len(universe) - 1) if offset == len(universe) - 1 else per_leg
                reference, price = _number(bars[symbol]["open"]), _number(bars[symbol]["open"]) * (Decimal(1) + adverse)
                qty = notional / price
                fee = _number(costs["fee_per_fill"]) + notional * _number(costs["fee_bps"]) / generic.BPS
                total_fees += fee
                volume = _number(known[symbol]["volume"])
                if volume == 0 or qty + used_volume.get((index, symbol), Decimal(0)) > volume * _number(risk["max_volume_participation_fraction"]):
                    reasons.append("CONTROL_ENTRY_KNOWN_VOLUME_INSUFFICIENT:" + symbol)
                if notional > _number(risk["max_order_notional"]):
                    reasons.append("CONTROL_ENTRY_MAX_ORDER_NOTIONAL:" + symbol)
                legs.append({"symbol": symbol, "qty": _text(qty), "entry_reference_open_price": _text(reference),
                             "exact_quantity_ratio": {"numerator": _text(notional), "denominator": _text(price)},
                             "entry_price": _text(price), "entry_notional": _text(notional), "entry_fee": _text(fee),
                             "entry_adverse_price_cost": _text(qty * (price - reference)), "arithmetic_quantity_only": True})
            if cash < target + total_fees:
                reasons.append("CONTROL_INSUFFICIENT_CASH")
            mark = _control_point(index, session, cash, cohorts, bars, "OPEN")
            post_equity = _number(mark["equity"]) - total_fees - sum((_number(leg["entry_adverse_price_cost"]) for leg in legs), Decimal(0))
            post_gross = _number(mark["gross_exposure"]) + sum((_number(leg["qty"]) * _number(leg["entry_reference_open_price"]) for leg in legs), Decimal(0))
            if post_equity <= 0:
                reasons.append("CONTROL_NONPOSITIVE_POST_FILL_EQUITY")
            elif post_gross > post_equity * _number(risk["max_gross_exposure_fraction"]):
                reasons.append("CONTROL_MAX_GROSS_EXPOSURE")
            previous_positions = {row["symbol"]: _number(row["market_value"]) for row in mark["positions"]}
            for leg in legs:
                exposure = previous_positions.get(leg["symbol"], Decimal(0)) + _number(leg["qty"]) * _number(leg["entry_reference_open_price"])
                if exposure > post_equity * _number(risk["max_position_fraction"]):
                    reasons.append("CONTROL_MAX_POSITION_EXPOSURE:" + leg["symbol"])
            cohort["legs"] = legs
            with localcontext(generic._context()) as allocation_context:
                allocation_context.prec = 512
                cohort["entry_purchase_notional"] = _text(sum((_number(leg["entry_notional"]) for leg in legs), Decimal(0)))
            cohort["exact_entry_purchase_notional_match"] = cohort["entry_purchase_notional"] == cohort["target_entry_purchase_notional"]
            if reasons:
                cohort["status"], cohort["reason_codes"] = "REJECTED_ENTRY", sorted(set(reasons))
                continue
            cash -= target + total_fees
            cohort["status"] = "OPEN"
            for leg in legs:
                used_volume[(index, leg["symbol"])] = used_volume.get((index, leg["symbol"]), Decimal(0)) + _number(leg["qty"])
        opening_curve.append(_control_point(index, session, cash, cohorts, bars, "OPEN"))
        closing_curve.append(_control_point(index, session, cash, cohorts, bars, "CLOSE"))
        breaches.extend(_control_breaches(opening_curve[-1], risk))
        breaches.extend(_control_breaches(closing_curve[-1], risk))
    for cohort in cohorts:
        if cohort["status"] == "OPEN":
            cohort["reason_codes"].append("CONTROL_EXIT_NOT_COMPLETED")
    return {"kind": CONTROL_KIND, "initial_cash": risk["initial_cash"], "cohorts": cohorts,
            "closed_cohort_count": sum(row["status"] == "CLOSED" for row in cohorts),
            "candidate_admitted_entry_count": len(cohorts), "opening_equity_curve": opening_curve,
            "equity_curve": closing_curve, "risk_breaches": breaches,
            "exact_entry_gross_matching": True, "daily_path_exposure_matching": False,
            "event_ordering": "EXIT_BEFORE_ENTRY_THEN_COHORT_ID", "fractional_arithmetic_only": True}


def _comparison(fold, control):
    reasons = []
    if fold["status"] != "SIMULATED":
        reasons.append("CANDIDATE_FOLD_NOT_SIMULATED")
    if not control["cohorts"]:
        reasons.append("NO_ACCEPTED_CANDIDATE_ENTRY")
    if fold["open_lots"]:
        reasons.append("CANDIDATE_OPEN_LOTS_NOT_COMPARABLE")
    if fold["risk_breaches"] or fold["holding_breaches"]:
        reasons.append("CANDIDATE_OBSERVED_RISK_BREACH")
    if control["risk_breaches"]:
        reasons.append("CONTROL_OBSERVED_RISK_BREACH")
    for cohort in control["cohorts"]:
        if cohort["candidate_exit_fill_id"] is None:
            reasons.append("CANDIDATE_EPISODE_EXIT_NOT_FILLED")
        if not cohort["candidate_fifo_lineage_matched"]:
            reasons.append("CANDIDATE_EPISODE_FIFO_LINEAGE_NOT_MATCHED")
        if cohort["status"] != "CLOSED":
            reasons.append("CONTROL_COHORT_NOT_CLOSED")
        if not cohort.get("exact_entry_purchase_notional_match", False):
            reasons.append("CONTROL_ENTRY_NOTIONAL_NOT_MATCHED")
    if reasons:
        return {"status": "INCONCLUSIVE", "reason_codes": sorted(set(reasons)), "candidate_net_pnl": None,
                "control_net_pnl": None, "net_excess_vs_cash": None, "net_excess_vs_control": None,
                "positive_vs_cash": None, "positive_vs_control": None,
                "falsification_status": "INCONCLUSIVE_MISSING_OR_NONCOMPARABLE_EVIDENCE"}
    candidate = sum((_number(row["candidate_simulated_net_pnl"]) for row in control["cohorts"]), Decimal(0))
    benchmark = sum((_number(row["simulated_net_pnl"]) for row in control["cohorts"]), Decimal(0))
    if candidate != _number(fold["metrics"]["simulated_realized_net_pnl"]):
        raise ContractValidationError("episode realized research P&L must conserve candidate FIFO accounting")
    excess = candidate - benchmark
    # Fractional Decimal ratios can leave a final arithmetic residual around
    # zero. Preserve full ledger values; never call such residuals an edge.
    cash_sign, control_sign = candidate.quantize(SIGN_QUANTUM), excess.quantize(SIGN_QUANTUM)
    return {"status": "COMPLETE_DESCRIPTIVE_COMPARISON", "reason_codes": [], "candidate_net_pnl": _text(candidate),
            "control_net_pnl": _text(benchmark), "net_excess_vs_cash": _text(candidate),
            "net_excess_vs_control": _text(excess), "positive_vs_cash": cash_sign > 0,
            "positive_vs_control": control_sign > 0,
            "sign_comparison_values": {"net_excess_vs_cash": _text(cash_sign), "net_excess_vs_control": _text(control_sign)},
            "falsification_status": "NONPOSITIVE_REQUIRED_COMPARISON" if cash_sign <= 0 or control_sign <= 0 else "POSITIVE_DESCRIPTIVE_SIGN_ONLY_NOT_VALIDATED_EDGE"}


def evaluate_shadow_study(study, base_plan, dataset, hypothesis, production, gates):
    """Replay deterministic admitted research fills and fixed cost sensitivities.

    Gates are produced by the retained-source verifier. This pure layer checks
    their explicit structure; source reconstruction and journal history remain
    the caller's evidence boundary, never an authentication claim here.
    """
    with localcontext(generic._context()):
        study, plan, data, hypothesis, intents = _validate_inputs(study, base_plan, dataset, hypothesis, production, gates)
        result = {"schema_version": "blackpod.trading_shadow_evaluation.v1", "study_id": study["study_id"],
                  "experiment_id": study["experiment_id"], "trial_id": study["trial_registry"]["trial_id"],
                  "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
                  "evidence_scope": study["evidence_scope"],
                  "method_version": METHOD_VERSION, "producer_method_version": production.get("method_version"),
                  "producer_status": production.get("status"), "hypothesis_id": hypothesis["hypothesis_id"],
                  "precision_policy": deepcopy(generic.PRECISION_POLICY), "gate_assessment": deepcopy(gates),
                  "comparison_precision_policy": {"net_pnl_sign_scale": 24, "rounding": "ROUND_HALF_EVEN", "full_ledger_values_retained": True},
                  "availability_semantics": {"historical_point_in_time_verified": False,
                      "classification": "RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF",
                      "source_provenance": deepcopy(data["provenance"]),
                      "internal_generic_v1_projection": "EPHEMERAL_ARITHMETIC_ONLY_ORIGINAL_SOURCES_UNCHANGED"},
                  "cost_stress_runs": [], "cost_stress_consistency": [],
                  "final_holdout": {**deepcopy(plan["protocol"]["final_holdout"]), "scoring_status": "WITHHELD", "access_sealed": False},
                  "aggregate": None, "realized_trade_pnl": None, "auto_trading_enabled": False,
                  "authority": deepcopy(study["authority"]), "limitations": list(LIMITATIONS)}
        if not gates["eligible"]:
            result["status"], result["reason_codes"] = "DEFER_EVIDENCE_GATES", list(gates["reason_codes"])
            return result
        result["status"], result["reason_codes"] = "SHADOW_SIMULATED", []
        for multiplier in study["cost_stress_multipliers"]:
            costs = {key: _text(_number(value) * _number(multiplier)) for key, value in gates["cost_model"].items()}
            if any(_number(costs[field]) > 1000 for field in ("spread_bps", "slippage_bps", "fee_bps")):
                result["cost_stress_runs"].append({"multiplier": multiplier, "cost_model": costs,
                    "status": "DEFER_COST_STRESS_EXCEEDS_GENERIC_SUPPORTED_BOUND", "candidate": None, "folds": []})
                continue
            candidate = _projection(plan, data, intents, study, costs)
            rows = []
            for fold in candidate["folds"]:
                episodes = [row for row in production["episodes"] if row["fold_id"] == fold["fold_id"]]
                control = _matched_control(fold, plan, data, episodes, costs)
                rows.append({"fold_id": fold["fold_id"], "control": control, "comparison": _comparison(fold, control),
                             "cash_benchmark": {"kind": "CASH", "simulated_net_pnl": "0", "interest_assumed": False}})
            result["cost_stress_runs"].append({"multiplier": multiplier, "cost_model": costs,
                "status": "SIMULATED", "candidate": candidate, "folds": rows})
        for fold in plan["protocol"]["folds"]:
            comparisons = [next((row["comparison"] for row in run["folds"] if row["fold_id"] == fold["fold_id"]), None)
                           for run in result["cost_stress_runs"]]
            if any(row is None or row["status"] != "COMPLETE_DESCRIPTIVE_COMPARISON" for row in comparisons):
                status = "INCONCLUSIVE"
            elif all(row["positive_vs_cash"] and row["positive_vs_control"] for row in comparisons):
                status = "POSITIVE_DESCRIPTIVE_SIGNS_AT_ALL_DECLARED_COST_STRESSES"
            else:
                status = "NONPOSITIVE_REQUIRED_COMPARISON_AT_DECLARED_COST_STRESS"
            result["cost_stress_consistency"].append({"fold_id": fold["fold_id"], "status": status,
                "statistical_significance": "NOT_ASSESSED", "winner_selected": False, "promotion_enabled": False})
        return result
