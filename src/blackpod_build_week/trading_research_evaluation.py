"""Pure, strategy-neutral offline trading research evaluation.

Externally supplied decisions are simulated observations, not executable orders.
This module does not import any strategy, broker, provider, inference runtime or
Galactica/Battlestar analytical definitions. Monetary calculations use an
isolated Decimal context; simulated results confer no execution authority.
"""
from __future__ import annotations

from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext

from .hashing import canonical_json_bytes, sha256_bytes
from .contracts.mission_request import parse_rfc3339

ZERO = Decimal("0")
ONE = Decimal("1")
BPS = Decimal("10000")
RATIO_QUANTUM = Decimal("0.000000000000000000000001")
FEE_QUANTUM = Decimal("0." + "0" * 79 + "1")
PRECISION_POLICY = {
    "calculation_precision": 256,
    "ratio_scale": 24,
    "fee_allocation_scale": 80,
    "rounding": "ROUND_HALF_EVEN",
    "fee_residual": "LAST_MATCH_REMAINDER",
}
METHOD_VERSION = "blackpod.next_open_research_evaluation.v1"
HISTORICAL_DATA_QUALITY_METHOD_VERSION = "blackpod.historical_data_quality_evaluation.v1"
RESEARCH_MAX_PROJECTED_ROWS = 20000
LIMITATIONS = (
    "EXTERNAL_INTENTS_NOT_A_FITTED_OR_VERIFIED_STRATEGY",
    "DECLARED_SOURCE_PROVENANCE_AND_AVAILABILITY_NOT_AUTHENTICATED",
    "FINAL_HOLDOUT_SCORING_WITHHELD_NOT_ACCESS_SEALED",
    "DECLARED_LABEL_HORIZON_NOT_PROOF_OF_MODEL_TRAINING",
    "DAILY_NEXT_OPEN_WHOLE_FILL_MODEL_NOT_EXECUTION_CAPACITY",
    "PRIOR_COMPLETED_BAR_VOLUME_NOT_OPENING_LIQUIDITY",
    "FIXED_COST_ASSUMPTIONS_NOT_OBSERVED_SPREADS_OR_FEES",
    "CLOSE_ONLY_DRAWDOWN_NOT_INTRADAY_RISK",
    "CASH_BASELINE_NOT_RISK_MATCHED_ALPHA_BENCHMARK",
    "FOLDS_RESET_CASH_NO_AGGREGATED_PORTFOLIO_RETURN",
    "NO_CORPORATE_ACTIONS_FINANCING_SHORTS_LEVERAGE_OR_PARTIAL_FILLS",
    "NO_ANNUALIZED_OR_SELECTION_BIAS_STATISTICS",
    "NO_STRATEGY_PROMOTION_OR_EXECUTION_AUTHORITY",
)
HISTORICAL_LIMITATIONS = (
    "RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF",
    "RETURNED_HISTORICAL_VALUES_MAY_INCLUDE_REVISIONS",
    "SESSION_END_PLUS_DELAY_IS_MODELED_NOT_AUTHENTICATED_PUBLICATION",
    "FROZEN_HYPOTHESIS_IS_NOT_HISTORICAL_PREREGISTRATION",
    "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER_OR_PERFORMANCE_ASSESSMENT",
    "SELECTED_UNIVERSE_NOT_SURVIVORSHIP_FREE",
)


class TradingResearchEvaluationError(ValueError):
    """A supplied research relationship cannot be evaluated faithfully."""


def _context():
    return Context(prec=256, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   flags=[], traps=[DivisionByZero, InvalidOperation, Overflow])


def _number(value):
    return Decimal(value)


def _time(value):
    return parse_rfc3339(value, "research timestamp")


def _text(value):
    if value == 0:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return _text((numerator / denominator).quantize(RATIO_QUANTUM))


def _allocate_fee(total, slice_qty, remaining_qty):
    """Keep a lot's exact remaining fee; a final close consumes the remainder."""
    if slice_qty == remaining_qty:
        return total
    amount = (total * slice_qty / remaining_qty).quantize(FEE_QUANTUM)
    return max(ZERO, min(total, amount))


def _match_fifo(lots, quantity, sell_price, exit_fee, fill_id):
    """Consume only the requested long quantity and retain exact fee attribution."""
    remaining, exit_fee_remaining, matches = quantity, exit_fee, []
    for lot in lots:
        if remaining == 0:
            break
        if lot["remaining_qty"] == 0:
            continue
        take = min(remaining, lot["remaining_qty"])
        entry_fee = _allocate_fee(lot["remaining_entry_fee"], take, lot["remaining_qty"])
        allocated_exit = _allocate_fee(exit_fee_remaining, take, remaining)
        gross = take * (sell_price - lot["entry_price"])
        matches.append({
            "entry_fill_id": lot["entry_fill_id"], "exit_fill_id": fill_id,
            "symbol": lot["symbol"], "qty": _text(take),
            "buy_price": _text(lot["entry_price"]), "sell_price": _text(sell_price),
            "allocated_entry_fee": _text(entry_fee), "allocated_exit_fee": _text(allocated_exit),
            "simulated_gross_pnl": _text(gross),
            "simulated_net_pnl": _text(gross - entry_fee - allocated_exit),
        })
        lot["remaining_qty"] -= take
        lot["remaining_entry_fee"] -= entry_fee
        remaining -= take
        exit_fee_remaining -= allocated_exit
    if remaining != 0 or exit_fee_remaining != 0:
        raise TradingResearchEvaluationError("FIFO cannot cover a requested simulated sell")
    return matches


def _metrics(initial_cash, equity_curve, fills, matched_lots):
    """Define bounded unannualized sample metrics without implying significance."""
    end_equity = _number(equity_curve[-1]["equity"]) if equity_curve else initial_cash
    high_water, maximum_drawdown, maximum_duration, duration = initial_cash, ZERO, 0, 0
    returns, prior = [], initial_cash
    for point in equity_curve:
        current = _number(point["equity"])
        if current < high_water:
            duration += 1
            maximum_duration = max(maximum_duration, duration)
            maximum_drawdown = max(maximum_drawdown, (high_water - current) / high_water)
        else:
            high_water, duration = current, 0
        returns.append((current - prior) / prior if prior else ZERO)
        prior = current
    sell_pnls = [_number(fill["simulated_realized_net_pnl"]) for fill in fills if fill["side"] == "SELL"]
    wins = sum((value for value in sell_pnls if value > 0), ZERO)
    losses = sum((-value for value in sell_pnls if value < 0), ZERO)
    turnover = sum((_number(fill["notional"]) for fill in fills), ZERO)
    all_fees = sum((_number(fill["fee"]) for fill in fills), ZERO)
    price_cost = sum((_number(fill["adverse_price_cost"]) for fill in fills), ZERO)
    return {
        "initial_cash": _text(initial_cash), "ending_equity": _text(end_equity),
        "simulated_total_pnl": _text(end_equity - initial_cash),
        "net_return": _ratio(end_equity - initial_cash, initial_cash),
        "maximum_close_drawdown": _ratio(maximum_drawdown, ONE),
        "maximum_drawdown_duration_sessions": maximum_duration,
        "equity_observation_count": len(equity_curve), "fill_count": len(fills),
        "matched_lot_count": len(matched_lots), "sell_fill_count": len(sell_pnls),
        "profitable_sell_fill_count": sum(value > 0 for value in sell_pnls),
        "losing_sell_fill_count": sum(value < 0 for value in sell_pnls),
        "sell_fill_win_rate": _ratio(Decimal(sum(value > 0 for value in sell_pnls)), Decimal(len(sell_pnls))),
        "simulated_net_expectancy_per_sell_fill": _ratio(sum(sell_pnls, ZERO), Decimal(len(sell_pnls))),
        "sell_fill_profit_factor": _ratio(wins, losses),
        "turnover_notional": _text(turnover), "turnover_to_initial_cash": _ratio(turnover, initial_cash),
        "fees": _text(all_fees), "adverse_price_cost": _text(price_cost),
        "modeled_total_cost": _text(all_fees + price_cost),
        "worst_close_to_close_return": _ratio(min(returns), ONE) if returns else None,
        "sharpe_ratio": None, "sortino_ratio": None, "annualized_return": None,
        "statistical_significance": "NOT_ASSESSED",
        "maximum_close_gross_exposure_fraction": _text(max(
            (_number(point["gross_exposure_fraction"]) for point in equity_curve), default=ZERO)),
    }


def _documents(plan, dataset, intents):
    from .contracts.trading_research import (
        TradingResearchPlan, TradingResearchDataset, TradingResearchIntents,
        validate_research_inputs,
    )
    typed = []
    for value, document in ((plan, TradingResearchPlan), (dataset, TradingResearchDataset),
                            (intents, TradingResearchIntents)):
        typed.append(value if isinstance(value, document) else document.from_mapping(value))
    validate_research_inputs(*typed)
    return tuple(value.to_mapping() for value in typed)


def _split_projection(plan, dataset):
    sessions, projected, quality = dataset["sessions"], [], []
    horizon = plan["horizon"]["label_horizon_sessions"]
    for fold in plan["protocol"]["folds"]:
        train, validation = fold["train"], fold["validation"]
        cutoff = _time(sessions[train["end_index"]]["available_at"])
        validation_open = _time(sessions[validation["start_index"]]["open_at"])
        eligible, purged = [], []
        for index in range(train["start_index"], train["end_index"] + 1):
            source, target_index = sessions[index], index + horizon
            reasons = []
            if _time(source["available_at"]) > cutoff:
                reasons.append("FEATURE_NOT_AVAILABLE_BY_TRAIN_CUTOFF")
            if _time(source["available_at"]) > validation_open:
                reasons.append("FEATURE_AVAILABLE_AFTER_VALIDATION_START")
                quality.append({"fold_id": fold["fold_id"], "session_id": source["session_id"],
                                "reason_code": "FEATURE_AVAILABLE_AFTER_VALIDATION_START"})
            target = sessions[target_index] if target_index < len(sessions) else None
            if target_index > train["end_index"]:
                reasons.append("LABEL_TARGET_OUTSIDE_TRAIN")
            elif target is not None and _time(target["available_at"]) > cutoff:
                reasons.append("LABEL_NOT_AVAILABLE_BY_TRAIN_CUTOFF")
            if target is not None and _time(target["available_at"]) > validation_open:
                reasons.append("LABEL_AVAILABLE_AFTER_VALIDATION_START")
                if target_index <= train["end_index"]:
                    quality.append({"fold_id": fold["fold_id"], "session_id": source["session_id"],
                                    "reason_code": "LABEL_AVAILABLE_AFTER_VALIDATION_START"})
            row = {"source_index": index, "source_session_id": source["session_id"],
                   "feature_available_at": source["available_at"], "target_index": target_index,
                   "target_session_id": target["session_id"] if target else None,
                   "target_available_at": target["available_at"] if target else None}
            if reasons:
                purged.append({**row, "reason_codes": reasons})
            else:
                eligible.append(row)
        projected.append({
            "fold_id": fold["fold_id"], "train": train, "validation": validation,
            "test": fold["test"], "train_cutoff_at": sessions[train["end_index"]]["available_at"],
            "validation_open_at": sessions[validation["start_index"]]["open_at"],
            "train_to_validation_gap_sessions": validation["start_index"] - train["end_index"] - 1,
            "validation_to_test_gap_sessions": fold["test"]["start_index"] - validation["end_index"] - 1,
            "eligible_training_label_samples": eligible, "purged_training_label_samples": purged,
            "model_training_verified": False,
        })
    return {"folds": projected, "availability_failures": quality,
            "label_horizon_sessions": horizon, "embargo_sessions": plan["protocol"]["embargo_sessions"],
            "final_holdout": {**plan["protocol"]["final_holdout"], "scoring_status": "WITHHELD",
                              "access_sealed": False}}


def _check_projection_bound(plan):
    projected = sum(fold["train"]["end_index"] - fold["train"]["start_index"] + 1
                    + 2 * (fold["test"]["end_index"] - fold["test"]["start_index"] + 1)
                    for fold in plan["protocol"]["folds"])
    if projected > RESEARCH_MAX_PROJECTED_ROWS:
        raise TradingResearchEvaluationError("research projection exceeds 20000 combined training/open/close rows")


def plan_chronological_splits(plan, dataset):
    """Project declared chronological labels and purges; never fit or score models."""
    from .contracts.trading_research import TradingResearchPlan, TradingResearchDataset
    typed_plan = plan if isinstance(plan, TradingResearchPlan) else TradingResearchPlan.from_mapping(plan)
    typed_data = dataset if isinstance(dataset, TradingResearchDataset) else TradingResearchDataset.from_mapping(dataset)
    # The same cross-document checks apply without manufacturing any decisions.
    from .contracts.trading_research import TradingResearchIntents
    mapping = typed_plan.to_mapping()
    empty = {"schema_version": "blackpod.trading_research_intents.v1",
             "intent_set_id": "split-projection-empty", "plan_id": mapping["plan_id"],
             "created_at": mapping["registered_at"], "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY",
             "decisions": [], "authority": mapping["authority"]}
    # Validation of evidence references belongs to the retained-source journal
    # wrapper, not this pure projection.
    _, data, _ = _documents(typed_plan, typed_data, TradingResearchIntents.from_mapping(empty))
    _check_projection_bound(mapping)
    return _split_projection(mapping, data)


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _position_qty(lots, symbol):
    return sum((lot["remaining_qty"] for lot in lots if lot["symbol"] == symbol), ZERO)


def _mark(cash, lots, prices):
    by_symbol = {}
    for lot in lots:
        if lot["remaining_qty"]:
            by_symbol[lot["symbol"]] = by_symbol.get(lot["symbol"], ZERO) + lot["remaining_qty"]
    exposure = sum((qty * prices[symbol] for symbol, qty in by_symbol.items()), ZERO)
    return cash + exposure, exposure, by_symbol


def _point(session, index, cash, lots, prices, role):
    equity, exposure, positions = _mark(cash, lots, prices)
    if equity <= 0:
        raise TradingResearchEvaluationError("simulated equity is nonpositive")
    return {"session_id": session["session_id"], "session_index": index,
            "marked_at": session["open_at"] if role == "OPEN" else session["close_at"],
            "mark_role": role, "cash": _text(cash), "equity": _text(equity),
            "gross_exposure": _text(exposure), "gross_exposure_fraction": _ratio(exposure, equity),
            "positions": [{"symbol": symbol, "qty": _text(qty), "mark_price": _text(prices[symbol]),
                           "market_value": _text(qty * prices[symbol])}
                          for symbol, qty in sorted(positions.items())]}


def _observed_risk_breaches(point, risk):
    """Annotate price-driven breaches; never invent an exit or claim readiness."""
    equity = _number(point["equity"])
    common = {"session_id": point["session_id"], "mark_role": point["mark_role"],
              "marked_at": point["marked_at"], "forced_exit": False}
    findings = []
    gross = _number(point["gross_exposure"])
    if gross > equity * _number(risk["max_gross_exposure_fraction"]):
        findings.append({**common, "symbol": None, "reason_code": "MAX_GROSS_EXPOSURE_FRACTION_OBSERVED",
                         "observed_fraction": _ratio(gross, equity),
                         "declared_limit": risk["max_gross_exposure_fraction"]})
    for position in point["positions"]:
        value = _number(position["market_value"])
        if value > equity * _number(risk["max_position_fraction"]):
            findings.append({**common, "symbol": position["symbol"], "reason_code": "MAX_POSITION_FRACTION_OBSERVED",
                             "observed_fraction": _ratio(value, equity),
                             "declared_limit": risk["max_position_fraction"]})
    return findings


def _intent_timing(decision, fold, sessions, indices, risk, holdout):
    source_index = indices[decision["source_session_id"]]
    next_index = source_index + 1
    if next_index >= len(sessions):
        return next_index, "NO_NEXT_SESSION"
    if holdout["start_index"] <= next_index <= holdout["end_index"]:
        return next_index, "FINAL_HOLDOUT_WITHHELD"
    if not fold["test"]["start_index"] <= next_index <= fold["test"]["end_index"]:
        return next_index, "UNSCORED_PARTITION"
    source, next_session = sessions[source_index], sessions[next_index]
    when = _time(decision["decision_at"])
    available = _time(source["available_at"])
    if available > when:
        return next_index, "SOURCE_NOT_YET_AVAILABLE"
    if when >= _time(next_session["open_at"]):
        return next_index, "NEXT_OPEN_NOT_AFTER_DECISION"
    elapsed = when - available
    age_seconds = Decimal(elapsed.days * 86400 + elapsed.seconds) + Decimal(elapsed.microseconds) / Decimal("1000000")
    if age_seconds > Decimal(str(risk["max_staleness_seconds"])):
        return next_index, "STALE_SOURCE_OBSERVATION"
    execution_elapsed = _time(next_session["open_at"]) - available
    execution_age_seconds = Decimal(execution_elapsed.days * 86400 + execution_elapsed.seconds) + Decimal(execution_elapsed.microseconds) / Decimal("1000000")
    if execution_age_seconds > Decimal(str(risk["max_staleness_seconds"])):
        return next_index, "SOURCE_STALE_AT_NEXT_OPEN"
    return next_index, None


def _simulate_fold(plan, dataset, decisions, fold, split):
    sessions, indices = dataset["sessions"], {row["session_id"]: index for index, row in enumerate(dataset["sessions"])}
    risk, costs, initial = plan["risk"], plan["cost_model"], _number(plan["risk"]["initial_cash"])
    cash, lots, fills, matched, dispositions, scheduled = initial, [], [], [], [], {}
    used_volume = {}
    for decision in sorted(decisions, key=lambda item: (_time(item["decision_at"]), item["decision_id"])):
        index, reason = _intent_timing(decision, fold, sessions, indices, risk, plan["protocol"]["final_holdout"])
        if reason is not None:
            dispositions.append({"decision_id": decision["decision_id"], "disposition": "REJECTED",
                                 "reason_code": reason, "execution_session_index": index})
        else:
            scheduled.setdefault(index, []).append(decision)
    equity_curve, opening_curve, holding_breaches, risk_breaches = [], [], [], []
    spread_half = _number(costs["spread_bps"]) / Decimal("2")
    adverse_fraction = (spread_half + _number(costs["slippage_bps"])) / BPS
    for index in range(fold["test"]["start_index"], fold["test"]["end_index"] + 1):
        session = sessions[index]
        bars = {bar["symbol"]: bar for bar in session["bars"]}
        opening = {symbol: _number(bar["open"]) for symbol, bar in bars.items()}
        closing = {symbol: _number(bar["close"]) for symbol, bar in bars.items()}
        # A simultaneous opening batch has a published deterministic order;
        # input file list order cannot alter cash/risk admission.
        for decision in sorted(scheduled.get(index, []), key=lambda item: item["decision_id"]):
            base = {"decision_id": decision["decision_id"], "execution_session_index": index}
            if decision["action"] == "HOLD":
                dispositions.append({**base, "disposition": "HOLD", "reason_code": "HOLD_NO_FILL"})
                continue
            symbol, side, qty = decision["symbol"], decision["action"], _number(decision["qty"])
            source_bar = next(bar for bar in sessions[indices[decision["source_session_id"]]]["bars"] if bar["symbol"] == symbol)
            reference_price = opening[symbol]
            price = reference_price * (ONE + adverse_fraction if side == "BUY" else ONE - adverse_fraction)
            notional = qty * price
            fee = _number(costs["fee_per_fill"]) + notional * _number(costs["fee_bps"]) / BPS
            known_volume = _number(source_bar["volume"])
            reason = None
            if known_volume == 0:
                reason = "ZERO_KNOWN_VOLUME"
            elif qty + used_volume.get((index, symbol), ZERO) > known_volume * _number(risk["max_volume_participation_fraction"]):
                reason = "KNOWN_VOLUME_PARTICIPATION_EXCEEDED"
            elif notional > _number(risk["max_order_notional"]):
                reason = "MAX_ORDER_NOTIONAL_EXCEEDED"
            elif side == "SELL" and qty > _position_qty(lots, symbol):
                reason = "INSUFFICIENT_LONG_POSITION"
            next_cash = cash - notional - fee if side == "BUY" else cash + notional - fee
            if reason is None and next_cash < 0:
                reason = "INSUFFICIENT_CASH"
            equity, exposure, positions = _mark(cash, lots, opening)
            if reason is None and side == "BUY":
                post_equity = next_cash + exposure + qty * reference_price
                post_gross = exposure + qty * reference_price
                post_position = (positions.get(symbol, ZERO) + qty) * reference_price
                if post_equity <= 0:
                    reason = "NONPOSITIVE_POST_FILL_EQUITY"
                elif post_position > post_equity * _number(risk["max_position_fraction"]):
                    reason = "MAX_POSITION_FRACTION_EXCEEDED"
                elif post_gross > post_equity * _number(risk["max_gross_exposure_fraction"]):
                    reason = "MAX_GROSS_EXPOSURE_FRACTION_EXCEEDED"
            if reason is not None:
                dispositions.append({**base, "disposition": "REJECTED", "reason_code": reason})
                continue
            fill_id = _identity("simulated-fill", {"trial_id": plan["trial_registry"]["trial_id"],
                                "fold_id": fold["fold_id"], "decision_id": decision["decision_id"]})
            adverse_cost = qty * (price - reference_price if side == "BUY" else reference_price - price)
            fill_matches = []
            if side == "BUY":
                lots.append({"symbol": symbol, "entry_fill_id": fill_id, "entry_session_index": index,
                             "entry_price": price, "remaining_qty": qty, "remaining_entry_fee": fee})
            else:
                selected = [lot for lot in lots if lot["symbol"] == symbol]
                fill_matches = _match_fifo(selected, qty, price, fee, fill_id)
                matched.extend(fill_matches)
            cash = next_cash
            used_volume[(index, symbol)] = used_volume.get((index, symbol), ZERO) + qty
            fills.append({"fill_id": fill_id, "decision_id": decision["decision_id"],
                          "symbol": symbol, "side": side, "qty": _text(qty),
                          "execution_session_id": session["session_id"], "execution_at": session["open_at"],
                          "known_volume_session_id": decision["source_session_id"],
                          "known_volume": source_bar["volume"], "reference_open_price": _text(reference_price),
                          "price": _text(price), "notional": _text(notional), "fee": _text(fee),
                          "adverse_price_cost": _text(adverse_cost),
                          "simulated_realized_net_pnl": _text(sum((_number(row["simulated_net_pnl"]) for row in fill_matches), ZERO)) if side == "SELL" else None})
            dispositions.append({**base, "disposition": "FILLED", "reason_code": "SIMULATED_NEXT_OPEN_FILL", "fill_id": fill_id})
        opening_curve.append(_point(session, index, cash, lots, opening, "OPEN"))
        equity_curve.append(_point(session, index, cash, lots, closing, "CLOSE"))
        risk_breaches.extend(_observed_risk_breaches(opening_curve[-1], risk))
        risk_breaches.extend(_observed_risk_breaches(equity_curve[-1], risk))
        for lot in lots:
            age = index - lot["entry_session_index"]
            if lot["remaining_qty"] and age > plan["horizon"]["max_holding_sessions"]:
                holding_breaches.append({"entry_fill_id": lot["entry_fill_id"], "symbol": lot["symbol"],
                                        "session_id": session["session_id"], "holding_sessions": age,
                                        "reason_code": "MAX_HOLDING_SESSIONS_EXCEEDED", "forced_exit": False})
    terminal = sessions[fold["test"]["end_index"]]
    last_prices = {bar["symbol"]: _number(bar["close"]) for bar in terminal["bars"]}
    open_lots = [{"entry_fill_id": lot["entry_fill_id"], "symbol": lot["symbol"],
                  "remaining_qty": _text(lot["remaining_qty"]), "entry_price": _text(lot["entry_price"]),
                  "remaining_entry_fee": _text(lot["remaining_entry_fee"]),
                  "terminal_mark_price": _text(last_prices[lot["symbol"]]),
                  "simulated_unrealized_net_pnl": _text(lot["remaining_qty"] * (last_prices[lot["symbol"]] - lot["entry_price"]) - lot["remaining_entry_fee"])}
                 for lot in lots if lot["remaining_qty"]]
    metrics = _metrics(initial, equity_curve, fills, matched)
    metrics["simulated_realized_net_pnl"] = _text(sum((_number(row["simulated_net_pnl"]) for row in matched), ZERO))
    metrics["simulated_unrealized_net_pnl"] = _text(sum((_number(row["simulated_unrealized_net_pnl"]) for row in open_lots), ZERO))
    metrics["observed_simulation_risk_breach_count"] = len(risk_breaches) + len(holding_breaches)
    if _number(metrics["simulated_total_pnl"]) != _number(metrics["simulated_realized_net_pnl"]) + _number(metrics["simulated_unrealized_net_pnl"]):
        raise TradingResearchEvaluationError("simulated realized/unrealized P&L does not conserve equity")
    ordered = sorted(dispositions, key=lambda row: row["decision_id"])
    return {"fold_id": fold["fold_id"], "status": "SIMULATED", "split": split,
            "decisions": ordered, "rejections": [row for row in ordered if row["disposition"] == "REJECTED"],
            "fills": fills, "matched_lots": matched, "open_lots": open_lots,
            "equity_curve": equity_curve, "opening_equity_curve": opening_curve,
            "holding_breaches": holding_breaches, "risk_breaches": risk_breaches, "metrics": metrics,
            "benchmark": {"kind": "CASH", "initial_equity": _text(initial), "ending_equity": _text(initial),
                          "net_return": "0", "maximum_close_drawdown": "0", "modeled_total_cost": "0"}}


def _historical_data_quality_result(plan, dataset, splits):
    """Project evidence eligibility, never manufacture hypothesis decisions."""
    folds = []
    for fold, projection in zip(plan["protocol"]["folds"], splits["folds"]):
        failures = [row for row in splits["availability_failures"] if row["fold_id"] == fold["fold_id"]]
        status = "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER"
        if failures or not projection["eligible_training_label_samples"]:
            status = "DEFER_SPLIT_AVAILABILITY_INVALID"
        if plan["horizon"]["kind"] == "DAY":
            status = "DEFER_UNSUPPORTED_DAY_HORIZON"
        folds.append({"fold_id": fold["fold_id"], "status": status,
                      "split": projection, "decisions": [], "rejections": [], "fills": [],
                      "matched_lots": [], "open_lots": [], "equity_curve": [],
                      "opening_equity_curve": [], "holding_breaches": [], "risk_breaches": [],
                      "metrics": None, "benchmark": None, "unscored_decision_ids": []})
    provenance = dataset["provenance"]
    return {"schema_version": "blackpod.trading_research_evaluation.v2",
            "plan_id": plan["plan_id"], "experiment_id": plan["experiment_id"],
            "trial_id": plan["trial_registry"]["trial_id"], "domain": "TRADING",
            "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
            "method_version": HISTORICAL_DATA_QUALITY_METHOD_VERSION,
            "precision_policy": dict(PRECISION_POLICY), "evaluation_purpose": "DATA_QUALITY_ONLY",
            "hypothesis_status": "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION",
            "frozen_hypothesis_evidence": dict(plan["frozen_hypothesis_evidence"]),
            "source_artifact_binding": dict(provenance["governed_intake"]),
            "availability_semantics": {
                "classification": "RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF",
                "actual_receipt_availability": "RETAINED_SOURCE_RECEIPTS_ONLY_NOT_PAST_PUBLICATION",
                "modeled_historical_availability": provenance["timestamp_policy"],
                "availability_assumption": dict(provenance["availability_assumption"]),
                "historical_point_in_time_verified": False,
            },
            "protocol": splits, "folds": folds, "final_holdout": splits["final_holdout"],
            "aggregate": None, "data_quality": {"availability_failures": splits["availability_failures"],
                "source_provenance_authenticated": False, "model_training_verified": False,
                "strategy_producer_present": False, "historical_source_reconstructed_by_pure_evaluator": False},
            "realized_trade_pnl": None, "auto_trading_enabled": False,
            "authority": dict(plan["authority"]), "limitations": [*LIMITATIONS, *HISTORICAL_LIMITATIONS]}


def evaluate_research(plan, dataset, intents):
    """Evaluate supplied TEST intents, never infer, train, select, or authorize."""
    with localcontext(_context()):
        plan, dataset, intents = _documents(plan, dataset, intents)
        _check_projection_bound(plan)
        splits = _split_projection(plan, dataset)
        if plan["schema_version"] == "blackpod.trading_research_plan.v2":
            return _historical_data_quality_result(plan, dataset, splits)
        folds = []
        for fold, projection in zip(plan["protocol"]["folds"], splits["folds"]):
            decisions = [row for row in intents["decisions"] if row["fold_id"] == fold["fold_id"]]
            availability_failures = [row for row in splits["availability_failures"] if row["fold_id"] == fold["fold_id"]]
            deferred = "DEFER_SPLIT_AVAILABILITY_INVALID" if availability_failures or not projection["eligible_training_label_samples"] else None
            if plan["horizon"]["kind"] == "DAY":
                deferred = "DEFER_UNSUPPORTED_DAY_HORIZON"
            if deferred is not None:
                folds.append({"fold_id": fold["fold_id"], "status": deferred,
                              "split": projection, "decisions": [], "rejections": [], "fills": [],
                              "matched_lots": [], "open_lots": [], "equity_curve": [],
                              "opening_equity_curve": [], "holding_breaches": [], "risk_breaches": [],
                              "metrics": None, "benchmark": None,
                              "unscored_decision_ids": sorted(row["decision_id"] for row in decisions)})
            else:
                folds.append(_simulate_fold(plan, dataset, decisions, fold, projection))
        return {"schema_version": "blackpod.trading_research_evaluation.v1",
                "plan_id": plan["plan_id"], "experiment_id": plan["experiment_id"],
                "trial_id": plan["trial_registry"]["trial_id"], "domain": "TRADING",
                "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
                "method_version": METHOD_VERSION, "precision_policy": dict(PRECISION_POLICY),
                "protocol": splits, "folds": folds, "final_holdout": splits["final_holdout"],
                "aggregate": None, "data_quality": {"availability_failures": splits["availability_failures"],
                    "source_provenance_authenticated": False, "model_training_verified": False},
                "realized_trade_pnl": None, "auto_trading_enabled": False,
                "authority": plan["authority"], "limitations": list(LIMITATIONS)}
