"""Strict strategy-neutral contracts for development-only offline research.

These declarations cannot authorize an order, activate a desk budget, select a
production strategy or attest historical point-in-time availability. A supplied
BUY/SELL quantity is a simulation input, never an executable broker order.
No legacy strategy, forecast preset, prompt or sizing rule is imported here.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_decimal, accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference

TRADING_RESEARCH_PLAN_VERSION = "blackpod.trading_research_plan.v1"
TRADING_RESEARCH_DATASET_VERSION = "blackpod.trading_research_dataset.v1"
TRADING_RESEARCH_PLAN_V2_VERSION = "blackpod.trading_research_plan.v2"
TRADING_RESEARCH_DATASET_V2_VERSION = "blackpod.trading_research_dataset.v2"
GOVERNED_HISTORY_METHOD_VERSION = "blackpod.alpaca_daily_history_projection.v1"
TRADING_RESEARCH_INTENTS_VERSION = "blackpod.trading_research_intents.v1"
TRADING_RESEARCH_SCOPE = "DEVELOPMENT_EVALUATION_ONLY"
TRADING_RESEARCH_MODE = "OFFLINE_SIMULATION"
RESEARCH_MAX_SESSIONS = 10000
RESEARCH_MAX_DECISIONS = 10000
_EQUITY_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,31}$")
_WHOLE_QUANTITY = re.compile(r"^[1-9][0-9]{0,19}$")


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def research_symbol(value):
    """Independently validate a bounded equity symbol without legacy imports."""
    if not isinstance(value, str) or not _EQUITY_SYMBOL.fullmatch(value) or ".." in value:
        raise ContractValidationError("symbol must be an explicit path-safe uppercase equity symbol")
    return value


def _universe(value):
    result = [research_symbol(item) for item in _list(value, "universe")]
    if not 1 <= len(result) <= 8 or result != sorted(set(result)):
        raise ContractValidationError("universe must be sorted, unique and contain one through eight symbols")
    return result


def _integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractValidationError(name + " must be a bounded integer from " + str(minimum) + " through " + str(maximum))
    return value


def _range(value, name):
    result = _object(value, {"start_index", "end_index"}, name)
    for field in result:
        result[field] = _integer(result[field], name + "." + field, 0, RESEARCH_MAX_SESSIONS - 1)
    if result["start_index"] > result["end_index"]:
        raise ContractValidationError(name + " must be a nonempty inclusive index range")
    return result


def _decimal(value, name, *, positive=False, maximum=None):
    result = accounting_decimal(value, name, positive=positive, nonnegative=not positive)
    if maximum is not None and Decimal(result) > maximum:
        raise ContractValidationError(name + " exceeds its declared permitted range")
    return result


def _plan_v1(value):
    result = _object(value, {
        "schema_version", "plan_id", "experiment_id", "registered_at", "domain", "mode", "scope",
        "strategy", "universe", "horizon", "dataset_evidence", "intents_evidence", "protocol", "cost_model",
        "risk", "benchmark", "trial_registry", "auto_trading_enabled", "authority",
    }, "trading research plan")
    for field, expected in (("schema_version", TRADING_RESEARCH_PLAN_VERSION), ("domain", "TRADING"),
                            ("mode", TRADING_RESEARCH_MODE), ("scope", TRADING_RESEARCH_SCOPE)):
        _constant(result, field, expected)
    for field in ("plan_id", "experiment_id"):
        result[field] = _identifier(result[field], field)
    result["registered_at"] = accounting_timestamp(result["registered_at"], "registered_at")
    strategy = _object(result["strategy"], {
        "strategy_id", "version", "hypothesis", "expected_edge", "falsification_conditions", "ancestry", "implementation_status",
    }, "strategy")
    strategy["strategy_id"] = _identifier(strategy["strategy_id"], "strategy_id")
    strategy["version"] = _string(strategy["version"], "strategy.version", 128)
    for field in ("hypothesis", "expected_edge"):
        strategy[field] = _string(strategy[field], "strategy." + field, 10000)
    conditions = [_string(item, "falsification_condition", 10000)
                  for item in _list(strategy["falsification_conditions"], "falsification_conditions")]
    if not 1 <= len(conditions) <= 32 or len(set(conditions)) != len(conditions):
        raise ContractValidationError("falsification conditions must be nonempty, unique and bounded")
    strategy["falsification_conditions"] = conditions
    _constant(strategy, "ancestry", "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")
    _constant(strategy, "implementation_status", "EXTERNAL_INTENTS_ONLY")
    result["strategy"] = strategy
    result["universe"] = _universe(result["universe"])
    horizon = _object(result["horizon"], {"kind", "max_holding_sessions", "label_horizon_sessions"}, "horizon")
    horizon["kind"] = _enum(horizon["kind"], {"DAY", "SWING"}, "horizon.kind")
    for field in ("max_holding_sessions", "label_horizon_sessions"):
        horizon[field] = _integer(horizon[field], "horizon." + field, 1, 20)
    result["horizon"] = horizon
    for field in ("dataset_evidence", "intents_evidence"):
        result[field] = evidence_reference(result[field], field)
    if result["dataset_evidence"]["path"] == result["intents_evidence"]["path"]:
        raise ContractValidationError("dataset and intent evidence must have distinct paths")
    protocol = _object(result["protocol"], {"folds", "embargo_sessions", "final_holdout"}, "protocol")
    embargo = _integer(protocol["embargo_sessions"], "embargo_sessions", 0, 100)
    holdout = _range(protocol["final_holdout"], "final_holdout")
    folds, seen, last_test_end = [], set(), -1
    for item in _list(protocol["folds"], "folds"):
        row = _object(item, {"fold_id", "train", "validation", "test"}, "fold")
        row["fold_id"] = _identifier(row["fold_id"], "fold_id")
        if row["fold_id"] in seen:
            raise ContractValidationError("fold identities must be unique")
        seen.add(row["fold_id"])
        for field in ("train", "validation", "test"):
            row[field] = _range(row[field], "fold." + field)
        for left, right in (("train", "validation"), ("validation", "test")):
            gap = row[right]["start_index"] - row[left]["end_index"] - 1
            if gap < embargo:
                raise ContractValidationError("fold train, validation and test must be chronological with the declared embargo")
        if row["test"]["start_index"] <= last_test_end:
            raise ContractValidationError("fold test ranges must be disjoint and chronologically ordered")
        if holdout["start_index"] <= row["test"]["end_index"]:
            raise ContractValidationError("final holdout must follow every development test range")
        last_test_end = row["test"]["end_index"]
        folds.append(row)
    if not 1 <= len(folds) <= 32:
        raise ContractValidationError("protocol must contain one through thirty-two folds")
    protocol["folds"], protocol["final_holdout"] = folds, holdout
    result["protocol"] = protocol
    cost = _object(result["cost_model"], {"spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"}, "cost_model")
    for field in ("spread_bps", "slippage_bps", "fee_bps"):
        cost[field] = _decimal(cost[field], "cost_model." + field, maximum=Decimal("1000"))
    cost["fee_per_fill"] = _decimal(cost["fee_per_fill"], "fee_per_fill")
    result["cost_model"] = cost
    risk = _object(result["risk"], {
        "initial_cash", "max_order_notional", "max_position_fraction", "max_gross_exposure_fraction",
        "max_volume_participation_fraction", "max_staleness_seconds",
    }, "risk")
    for field in ("initial_cash", "max_order_notional"):
        risk[field] = _decimal(risk[field], "risk." + field, positive=True)
    for field in ("max_position_fraction", "max_gross_exposure_fraction", "max_volume_participation_fraction"):
        risk[field] = _decimal(risk[field], "risk." + field, positive=True, maximum=Decimal("1"))
    risk["max_staleness_seconds"] = _integer(risk["max_staleness_seconds"], "max_staleness_seconds", 1, 366 * 86400)
    result["risk"] = risk
    benchmark = _object(result["benchmark"], {"kind"}, "benchmark")
    _constant(benchmark, "kind", "CASH")
    result["benchmark"] = benchmark
    registry = _object(result["trial_registry"], {"trial_id", "prior_trial_ids"}, "trial_registry")
    registry["trial_id"] = _identifier(registry["trial_id"], "trial_id")
    prior = [_identifier(item, "prior_trial_id") for item in _list(registry["prior_trial_ids"], "prior_trial_ids")]
    if len(prior) > 10000 or len(set(prior)) != len(prior) or registry["trial_id"] in prior:
        raise ContractValidationError("prior trial identities must be distinct, bounded and exclude the current trial")
    registry["prior_trial_ids"] = prior
    result["trial_registry"] = registry
    _fixed_boolean(result, "auto_trading_enabled", False)
    result["authority"] = disabled_authority(result["authority"])
    return result


def _plan(value):
    """Add explicit hypothesis/data-quality semantics without changing v1."""
    if not isinstance(value, Mapping) or value.get("schema_version") != TRADING_RESEARCH_PLAN_V2_VERSION:
        return _plan_v1(value)
    extra = {"frozen_hypothesis_evidence", "evaluation_purpose"}
    fields = {
        "schema_version", "plan_id", "experiment_id", "registered_at", "domain", "mode", "scope",
        "strategy", "universe", "horizon", "dataset_evidence", "intents_evidence", "protocol", "cost_model",
        "risk", "benchmark", "trial_registry", "auto_trading_enabled", "authority",
    }
    supplied = _object(value, fields | extra, "trading research plan v2")
    base = {key: item for key, item in supplied.items() if key not in extra}
    base["schema_version"] = TRADING_RESEARCH_PLAN_VERSION
    result = _plan_v1(base)
    result["schema_version"] = TRADING_RESEARCH_PLAN_V2_VERSION
    result["frozen_hypothesis_evidence"] = evidence_reference(supplied["frozen_hypothesis_evidence"], "frozen hypothesis evidence")
    _constant(supplied, "evaluation_purpose", "DATA_QUALITY_ONLY")
    result["evaluation_purpose"] = supplied["evaluation_purpose"]
    paths = [result[field]["path"] for field in ("dataset_evidence", "intents_evidence", "frozen_hypothesis_evidence")]
    if len(set(paths)) != len(paths):
        raise ContractValidationError("dataset, intent and frozen hypothesis evidence must have distinct paths")
    return result


def _dataset_v1(value):
    result = _object(value, {
        "schema_version", "dataset_id", "recorded_at", "universe", "provenance", "sessions", "authority",
    }, "trading research dataset")
    _constant(result, "schema_version", TRADING_RESEARCH_DATASET_VERSION)
    result["dataset_id"] = _identifier(result["dataset_id"], "dataset_id")
    result["recorded_at"] = accounting_timestamp(result["recorded_at"], "recorded_at")
    recorded = parse_rfc3339(result["recorded_at"], "recorded_at")
    result["universe"] = _universe(result["universe"])
    provenance = _object(result["provenance"], {
        "source_kind", "source_evidence", "timestamp_policy", "historical_point_in_time_verified",
    }, "dataset provenance")
    provenance["source_kind"] = _enum(provenance["source_kind"], {"SYNTHETIC_FIXTURE", "RETAINED_MARKET_CAPTURE"}, "source_kind")
    expected_policy = "SYNTHETIC_DECLARED" if provenance["source_kind"] == "SYNTHETIC_FIXTURE" else "RETAINED_RECEIPT_AVAILABILITY"
    _constant(provenance, "timestamp_policy", expected_policy)
    _fixed_boolean(provenance, "historical_point_in_time_verified", False)
    references = [evidence_reference(item, "dataset source evidence")
                  for item in _list(provenance["source_evidence"], "source_evidence")]
    if not 1 <= len(references) <= 128 or len({row["path"] for row in references}) != len(references):
        raise ContractValidationError("dataset source evidence must be nonempty, distinct and bounded")
    provenance["source_evidence"] = references
    result["provenance"] = provenance
    sessions, seen, last_close = [], set(), None
    for item in _list(result["sessions"], "sessions"):
        row = _object(item, {"session_id", "open_at", "close_at", "available_at", "bars"}, "session")
        row["session_id"] = _identifier(row["session_id"], "session_id")
        if row["session_id"] in seen:
            raise ContractValidationError("session identities must be unique")
        seen.add(row["session_id"])
        for field in ("open_at", "close_at", "available_at"):
            row[field] = accounting_timestamp(row[field], "session." + field)
        opening, closing, available = (parse_rfc3339(row[field], field) for field in ("open_at", "close_at", "available_at"))
        if not opening < closing <= available <= recorded:
            raise ContractValidationError("completed session clocks must satisfy open < close <= available <= recorded")
        if last_close is not None and opening <= last_close:
            raise ContractValidationError("sessions must be strictly ordered and nonoverlapping")
        last_close = closing
        bars, symbols = [], []
        for item in _list(row["bars"], "bars"):
            bar = _object(item, {"symbol", "open", "high", "low", "close", "volume"}, "bar")
            bar["symbol"] = research_symbol(bar["symbol"])
            symbols.append(bar["symbol"])
            for field in ("open", "high", "low", "close"):
                bar[field] = _decimal(bar[field], "bar." + field, positive=True)
            bar["volume"] = _decimal(bar["volume"], "bar.volume")
            lower, upper = Decimal(bar["low"]), Decimal(bar["high"])
            if lower > upper or any(not lower <= Decimal(bar[field]) <= upper for field in ("open", "close")):
                raise ContractValidationError("bar OHLC must be internally consistent")
            bars.append(bar)
        if symbols != result["universe"]:
            raise ContractValidationError("every session must contain exactly the sorted dataset universe")
        row["bars"] = bars
        sessions.append(row)
    if not 1 <= len(sessions) <= RESEARCH_MAX_SESSIONS:
        raise ContractValidationError("dataset session count must be nonempty and bounded")
    result["sessions"] = sessions
    result["authority"] = disabled_authority(result["authority"])
    return result


def _dataset(value):
    """Validate declared retrospective times without claiming PIT evidence."""
    if not isinstance(value, Mapping) or value.get("schema_version") != TRADING_RESEARCH_DATASET_V2_VERSION:
        return _dataset_v1(value)
    supplied = _object(value, {
        "schema_version", "dataset_id", "recorded_at", "universe", "provenance", "sessions", "authority",
    }, "trading research dataset v2")
    provenance = _object(supplied["provenance"], {
        "source_kind", "source_evidence", "timestamp_policy", "historical_point_in_time_verified",
        "governed_intake", "availability_assumption",
    }, "historical dataset provenance")
    _constant(provenance, "source_kind", "GOVERNED_HISTORICAL_INTAKE")
    _constant(provenance, "timestamp_policy", "DECLARED_RETROSPECTIVE_SESSION_END_PLUS_LAG")
    _fixed_boolean(provenance, "historical_point_in_time_verified", False)
    references = [evidence_reference(item, "historical source evidence")
                  for item in _list(provenance["source_evidence"], "source_evidence")]
    if len(references) != 5 or len({row["path"] for row in references}) != 5:
        raise ContractValidationError("historical source evidence must contain the request and four distinct source references")
    provenance["source_evidence"] = references
    intake = _object(provenance["governed_intake"], {"intake_id", "request_evidence", "method_version"}, "governed intake")
    intake["intake_id"] = _identifier(intake["intake_id"], "intake_id")
    intake["request_evidence"] = evidence_reference(intake["request_evidence"], "request_evidence")
    _constant(intake, "method_version", GOVERNED_HISTORY_METHOD_VERSION)
    if intake["request_evidence"] not in references:
        raise ContractValidationError("governed intake request must bind a retained dataset source reference")
    provenance["governed_intake"] = intake
    assumption = _object(provenance["availability_assumption"], {
        "mode", "delay_seconds", "declared_by", "rationale", "assumption_verified",
    }, "availability assumption")
    _constant(assumption, "mode", "RETURNED_SESSION_END_PLUS_DECLARED_DELAY")
    assumption["delay_seconds"] = _integer(assumption["delay_seconds"], "delay_seconds", 0, 604800)
    assumption["declared_by"] = _identifier(assumption["declared_by"], "declared_by")
    assumption["rationale"] = _string(assumption["rationale"], "availability rationale", 10000)
    _fixed_boolean(assumption, "assumption_verified", False)
    provenance["availability_assumption"] = assumption
    # Reuse strict OHLC and session validation; the temporary v1 declaration is
    # local only. Actual returned bytes are authenticated separately by journal
    # reconstruction. Neither schema attests historical publication timing.
    base = dict(supplied)
    base["schema_version"] = TRADING_RESEARCH_DATASET_VERSION
    base["provenance"] = {
        "source_kind": "RETAINED_MARKET_CAPTURE", "source_evidence": references,
        "timestamp_policy": "RETAINED_RECEIPT_AVAILABILITY", "historical_point_in_time_verified": False,
    }
    result = _dataset_v1(base)
    result["schema_version"] = TRADING_RESEARCH_DATASET_V2_VERSION
    result["provenance"] = provenance
    return result


def _intents(value):
    result = _object(value, {
        "schema_version", "intent_set_id", "plan_id", "created_at", "origin", "decisions", "authority",
    }, "trading research intents")
    _constant(result, "schema_version", TRADING_RESEARCH_INTENTS_VERSION)
    _constant(result, "origin", "EXTERNALLY_AUTHORED_RESEARCH_ONLY")
    for field in ("intent_set_id", "plan_id"):
        result[field] = _identifier(result[field], field)
    result["created_at"] = accounting_timestamp(result["created_at"], "created_at")
    decisions, seen = [], set()
    for item in _list(result["decisions"], "decisions"):
        row = _object(item, {"decision_id", "fold_id", "source_session_id", "decision_at", "action", "symbol", "qty"}, "research decision")
        for field in ("decision_id", "fold_id", "source_session_id"):
            row[field] = _identifier(row[field], field)
        if row["decision_id"] in seen:
            raise ContractValidationError("research decision identities must be unique")
        seen.add(row["decision_id"])
        row["decision_at"] = accounting_timestamp(row["decision_at"], "decision_at")
        row["action"] = _enum(row["action"], {"BUY", "SELL", "HOLD"}, "research action")
        row["symbol"] = research_symbol(row["symbol"])
        if row["action"] == "HOLD":
            _constant(row, "qty", "0")
        elif not isinstance(row["qty"], str) or not _WHOLE_QUANTITY.fullmatch(row["qty"]):
            raise ContractValidationError("BUY and SELL require bounded positive whole-share quantity strings")
        decisions.append(row)
    if len(decisions) > RESEARCH_MAX_DECISIONS:
        raise ContractValidationError("research decision count exceeds the supported bound")
    result["decisions"] = decisions
    result["authority"] = disabled_authority(result["authority"])
    return result


class TradingResearchPlan(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_plan)


class TradingResearchDataset(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_dataset)


class TradingResearchIntents(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_intents)


def validate_research_inputs(plan, dataset, intents):
    """Bind structural references; economic/availability failures are recorded.

    Exact retained byte hashes and receipt clocks are checked by the evidence
    boundary. This function does not turn backdated or oversized decisions into
    parser failures: the evaluator retains their explicit rejection reasons.
    """
    if not isinstance(plan, TradingResearchPlan):
        plan = TradingResearchPlan.from_mapping(plan)
    if not isinstance(dataset, TradingResearchDataset):
        dataset = TradingResearchDataset.from_mapping(dataset)
    if not isinstance(intents, TradingResearchIntents):
        intents = TradingResearchIntents.from_mapping(intents)
    if intents.plan_id != plan.plan_id:
        raise ContractValidationError("intent set must bind the exact research plan identity")
    if dataset.universe != plan.universe:
        raise ContractValidationError("research plan and dataset universes must match exactly")
    v2_plan = plan.schema_version == TRADING_RESEARCH_PLAN_V2_VERSION
    v2_dataset = dataset.schema_version == TRADING_RESEARCH_DATASET_V2_VERSION
    if v2_plan != v2_dataset:
        raise ContractValidationError("governed historical datasets require an explicit v2 research plan and vice versa")
    if v2_plan and intents.decisions:
        raise ContractValidationError("v2 DATA_QUALITY_ONLY research requires empty intents until a separate strategy producer exists")
    count = len(dataset.sessions)
    ranges = [plan.protocol["final_holdout"]]
    for fold in plan.protocol["folds"]:
        ranges.extend(fold[field] for field in ("train", "validation", "test"))
    if any(row["end_index"] >= count for row in ranges):
        raise ContractValidationError("every declared partition must bind retained session indices")
    folds = {row["fold_id"] for row in plan.protocol["folds"]}
    sources = {row["session_id"] for row in dataset.sessions}
    universe = set(plan.universe)
    for row in intents.decisions:
        if row["fold_id"] not in folds or row["source_session_id"] not in sources or row["symbol"] not in universe:
            raise ContractValidationError("research decisions must bind retained folds, source sessions and universe symbols")
    return plan, dataset, intents
