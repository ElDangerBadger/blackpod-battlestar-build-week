"""Pure, causal producers for the two frozen independent research hypotheses.

The output is an offline simulation input. It is never an order, an allocation,
a recommendation to trade, or a claim of demonstrated edge. Retained evidence
and the continuity/cost gates are verified by the journal boundary before this
function is called. No prices after a decision are used to select or size it.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext

from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.trading_research import (
    RESEARCH_MAX_DECISIONS, TRADING_RESEARCH_PLAN_V2_VERSION,
    TradingResearchDataset, TradingResearchIntents, TradingResearchPlan, validate_research_inputs,
)
from .contracts.trading_shadow_research import TradingShadowStudy, validate_shadow_cost_model
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_hypotheses import hypothesis_research_strategy

METHOD_VERSION = "blackpod.independent_shadow_intents.v1"
PRODUCTION_VERSION = "blackpod.trading_shadow_production.v1"
MAX_OPPORTUNITIES = RESEARCH_MAX_DECISIONS
_MAX_QUANTITY = Decimal("99999999999999999999")
_RATIO_QUANTUM = Decimal("0.000000000000000000000001")


class TradingShadowIntentError(ValueError):
    """A shadow relationship cannot be projected without changing its meaning."""


def _context():
    return Context(prec=256, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   flags=[], traps=[DivisionByZero, InvalidOperation, Overflow])


def _document(value, document):
    return document.from_mapping(value.to_mapping() if isinstance(value, document) else value)


def _time(value):
    return parse_rfc3339(value, "shadow decision timestamp")


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _text(value):
    if value == 0:
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _bind(reference, document, name):
    body = document.to_bytes()
    if reference["sha256"] != sha256_bytes(body) or reference["size_bytes"] != len(body):
        raise TradingShadowIntentError(name + " does not bind the exact supplied document")


def _documents(study, base_plan, dataset, hypothesis):
    study = _document(study, TradingShadowStudy)
    plan = _document(base_plan, TradingResearchPlan)
    data = _document(dataset, TradingResearchDataset)
    hypothesis = _document(hypothesis, TradingHypothesis)
    if plan.schema_version != TRADING_RESEARCH_PLAN_V2_VERSION:
        raise TradingShadowIntentError("independent shadow production requires a frozen v2 data-quality plan")
    _bind(study.base_plan_evidence, plan, "base plan evidence")
    _bind(plan.dataset_evidence, data, "dataset evidence")
    _bind(plan.frozen_hypothesis_evidence, hypothesis, "frozen hypothesis evidence")
    projected = hypothesis_research_strategy(hypothesis)
    if plan.strategy != projected["strategy"] or plan.horizon != projected["horizon"]:
        raise TradingShadowIntentError("base plan strategy and horizon must match the exact frozen hypothesis")
    empty = TradingResearchIntents.from_mapping({
        "schema_version": "blackpod.trading_research_intents.v1", "intent_set_id": "shadow-input-validation",
        "plan_id": plan.plan_id, "created_at": study.registered_at,
        "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [], "authority": study.authority,
    })
    validate_research_inputs(plan, data, empty)
    registered = _time(study.registered_at)
    if any(_time(clock) > registered for clock in (plan.registered_at, data.recorded_at, hypothesis.recorded_at)):
        raise TradingShadowIntentError("shadow registration cannot precede its frozen input declarations")
    count = sum(fold["test"]["end_index"] - fold["test"]["start_index"] + 1
                for fold in plan.protocol["folds"]) * len(plan.universe)
    if count > MAX_OPPORTUNITIES:
        raise TradingShadowIntentError("shadow opportunities exceed the supported 10000-row bound")
    return study.to_mapping(), plan.to_mapping(), data.to_mapping(), hypothesis.to_mapping()


def _gate_reasons(gates):
    """Fail closed for absent, contradictory, or truthy-but-not-boolean gates."""
    if not isinstance(gates, Mapping):
        return ["GATE_EVIDENCE_NOT_ELIGIBLE", "GATE_INPUT_UNVERIFIED"]
    if set(gates) != {"eligible", "reason_codes", "cost_model", "provenance"} or not isinstance(gates["provenance"], Mapping):
        return ["GATE_EVIDENCE_NOT_ELIGIBLE", "GATE_INPUT_UNVERIFIED"]
    supplied = gates.get("reason_codes")
    if not isinstance(supplied, list) or any(not isinstance(value, str) or not value for value in supplied):
        return ["GATE_EVIDENCE_NOT_ELIGIBLE", "GATE_REASON_CODES_UNVERIFIED"]
    reasons = set(supplied)
    if gates.get("eligible") is not True:
        reasons.add("GATE_EVIDENCE_NOT_ELIGIBLE")
    try:
        validate_shadow_cost_model(gates.get("cost_model"))
    except (ContractValidationError, TypeError, ValueError):
        reasons.add("GATE_COST_MODEL_UNVERIFIED")
    return sorted(reasons)


def _next_open_reason(source_index, sessions, risk):
    """Only the returned calendar clock is inspected after the source session."""
    if source_index + 1 >= len(sessions):
        return "NO_NEXT_SESSION"
    available = _time(sessions[source_index]["available_at"])
    decision_at = available + timedelta(microseconds=1)
    next_open = _time(sessions[source_index + 1]["open_at"])
    if decision_at >= next_open:
        return "NEXT_OPEN_NOT_AFTER_DECISION"
    age = next_open - available
    seconds = Decimal(age.days * 86400 + age.seconds) + Decimal(age.microseconds) / Decimal("1000000")
    if seconds > Decimal(risk["max_staleness_seconds"]):
        return "SOURCE_STALE_AT_NEXT_OPEN"
    return None


def _decision(study, fold, source_index, session, symbol, action, qty):
    identity = {"study_id": study["study_id"], "fold_id": fold["fold_id"],
                "source_session_id": session["session_id"], "symbol": symbol, "action": action}
    return {"decision_id": _identity("shadow-decision", identity), "fold_id": fold["fold_id"],
            "source_session_id": session["session_id"],
            "decision_at": _stamp(_time(session["available_at"]) + timedelta(microseconds=1)),
            "action": action, "symbol": symbol, "qty": qty}


def _opportunity(study, fold, source_index, session, symbol, status, reasons, **detail):
    identity = {"study_id": study["study_id"], "fold_id": fold["fold_id"],
                "source_session_id": session["session_id"], "symbol": symbol}
    return {"opportunity_id": _identity("shadow-opportunity", identity), "fold_id": fold["fold_id"],
            "source_session_index": source_index, "source_session_id": session["session_id"],
            "symbol": symbol, "status": status, "reason_codes": sorted(reasons), **detail}


def produce_shadow_intents(study, base_plan, dataset, hypothesis, gates):
    """Produce TEST-only whole-quantity intents and retain every opportunity.

    Each symbol has a deterministic planned holding schedule. Rejected entries
    remain scheduled research inputs; a later simulator records their rejected
    exits as well. Planned exposure must never be described as an accepted fill.
    The next calendar opening can be checked, but its price/volume is never used
    for candidate selection or sizing. Later exit-clock failures preserve the
    earlier entry and explicitly leave comparison eligibility unresolved.
    """
    with localcontext(_context()):
        study, plan, data, hypothesis = _documents(study, base_plan, dataset, hypothesis)
        reasons = _gate_reasons(gates)
        decisions, episodes, opportunities = [], [], []
        result = {"schema_version": PRODUCTION_VERSION, "method_version": METHOD_VERSION,
                  "study_id": study["study_id"], "hypothesis_id": hypothesis["hypothesis_id"],
                  "evidence_scope": study["evidence_scope"],
                  "status": "DEFER_GATE_EVIDENCE" if reasons else "PRODUCED_SHADOW_RESEARCH_ONLY",
                  "reason_codes": reasons, "episodes": episodes, "opportunities": opportunities,
                  "auto_trading_enabled": False, "authority": dict(study["authority"])}
        if not reasons:
            sessions = data["sessions"]
            lookback = hypothesis["signal"]["lookback_sessions"]
            holding = hypothesis["horizon"]["holding_sessions"]
            budget = Decimal(study["sizing"]["per_symbol_notional"])
            for fold in plan["protocol"]["folds"]:
                active = {}
                first, last = fold["test"]["start_index"] - 1, fold["test"]["end_index"] - 1
                for source_index in range(first, last + 1):
                    session = sessions[source_index]
                    for symbol in plan["universe"]:
                        episode = active.get(symbol)
                        if episode is not None:
                            exit_source = episode["exit_session_index"] - 1
                            if source_index == exit_source:
                                reason = _next_open_reason(source_index, sessions, plan["risk"])
                                if reason is None:
                                    exit_decision = _decision(study, fold, source_index, session, symbol, "SELL", episode["qty"])
                                    decisions.append(exit_decision)
                                    episode["exit_decision_id"] = exit_decision["decision_id"]
                                    episode["status"] = "SCHEDULED_SHADOW"
                                    del active[symbol]
                                    status, row_reasons = "SCHEDULED_EXIT", ["DECLARED_HOLDING_INTERVAL_COMPLETE"]
                                else:
                                    episode["status"] = "DEFER_EXIT_CLOCK_UNAVAILABLE"
                                    episode["reason_codes"] = [reason]
                                    status, row_reasons = "DEFER", [reason]
                            else:
                                status, row_reasons = "NO_CANDIDATE", ["PLANNED_POSITION_ALREADY_OPEN"]
                            opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                               status, row_reasons, episode_id=episode["episode_id"]))
                            continue
                        if source_index < lookback:
                            opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                               "DEFER", ["INSUFFICIENT_COMPLETED_LOOKBACK"]))
                            continue
                        when = _time(session["available_at"]) + timedelta(microseconds=1)
                        input_indices = range(source_index - lookback, source_index + 1)
                        unavailable = [index for index in input_indices if _time(sessions[index]["available_at"]) > when]
                        if unavailable:
                            opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                               "DEFER", ["LOOKBACK_INPUT_NOT_YET_AVAILABLE"],
                                                               unavailable_input_indices=unavailable))
                            continue
                        known = [{"session_index": index, "session_id": sessions[index]["session_id"],
                                  "available_at": sessions[index]["available_at"],
                                  "close": next(bar["close"] for bar in sessions[index]["bars"] if bar["symbol"] == symbol)}
                                 for index in input_indices]
                        close = Decimal(known[-1]["close"])
                        signal = close / Decimal(known[0]["close"]) - Decimal("1")
                        matched = (signal < 0 if hypothesis["signal"]["candidate_condition"] == "RETURN_LT_ZERO" else signal > 0)
                        detail = {"decision_at": _stamp(when), "known_inputs": known,
                                  "observed_return": _text(signal.quantize(_RATIO_QUANTUM)),
                                  "observed_return_sign": "NEGATIVE" if signal < 0 else "POSITIVE" if signal > 0 else "ZERO",
                                  "observed_return_precision": "24_DECIMAL_DISPLAY_ONLY_SIGN_USES_UNROUNDED_DECIMAL"}
                        if not matched:
                            code = "ZERO_RETURN_NO_CANDIDATE" if signal == 0 else "CONDITION_NOT_SATISFIED"
                            opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                               "NO_CANDIDATE", [code], **detail))
                            continue
                        entry_index, exit_index = source_index + 1, source_index + 1 + holding
                        reason = "DECLARED_EXIT_OUTSIDE_TEST" if exit_index > fold["test"]["end_index"] else None
                        if reason is None:
                            reason = _next_open_reason(source_index, sessions, plan["risk"])
                        quantity = (budget / close).to_integral_value(rounding=ROUND_FLOOR)
                        if reason is None and quantity == 0:
                            reason = "KNOWN_CLOSE_BUDGET_BELOW_ONE_WHOLE_SHARE"
                        if reason is None and quantity > _MAX_QUANTITY:
                            reason = "WHOLE_SHARE_QUANTITY_OUTSIDE_CONTRACT_BOUND"
                        if reason is not None:
                            opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                               "DEFER", [reason], **detail))
                            continue
                        entry = _decision(study, fold, source_index, session, symbol, "BUY", _text(quantity))
                        episode = {"episode_id": _identity("shadow-episode", {"entry_decision_id": entry["decision_id"]}),
                                   "fold_id": fold["fold_id"], "symbol": symbol,
                                   "entry_decision_id": entry["decision_id"], "exit_decision_id": None,
                                   "entry_session_index": entry_index, "exit_session_index": exit_index,
                                   "holding_sessions": holding, "source_session_index": source_index,
                                   "known_inputs": known, "decision_at": entry["decision_at"], "qty": entry["qty"],
                                   "sizing_reference_close": known[-1]["close"],
                                   "status": "PLANNED_SHADOW_EXIT", "reason_codes": []}
                        episodes.append(episode)
                        active[symbol] = episode
                        decisions.append(entry)
                        opportunities.append(_opportunity(study, fold, source_index, session, symbol,
                                                           "SCHEDULED_ENTRY", ["FROZEN_CONDITION_SATISFIED"],
                                                           episode_id=episode["episode_id"], qty=entry["qty"], **detail))
        decisions.sort(key=lambda row: (_time(row["decision_at"]), row["decision_id"]))
        result["intents"] = TradingResearchIntents.from_mapping({
            "schema_version": "blackpod.trading_research_intents.v1",
            "intent_set_id": study["study_id"] + "-candidate-intents", "plan_id": study["study_id"] + "-candidate",
            "created_at": study["registered_at"], "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY",
            "decisions": decisions, "authority": dict(study["authority"]),
        }).to_mapping()
        return result
