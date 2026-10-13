"""Versioned, independently authored trading research specifications.

These documents freeze proposed experiments. They do not implement signals,
select a strategy, produce simulation intents, establish an economic edge, or
authorize execution. A recorded specification is not a claim that already
observed historical prices were unknown when it was written.
"""
from __future__ import annotations

from types import MappingProxyType

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument

TRADING_HYPOTHESIS_SCHEMA_VERSION = "blackpod.trading_hypothesis.v1"
TRADING_HYPOTHESIS_CATALOG_SCHEMA_VERSION = "blackpod.trading_hypothesis_catalog.v1"
TRADING_HYPOTHESIS_SCOPE = "RESEARCH_ONLY"
TRADING_HYPOTHESIS_MODE = "OFFLINE_RESEARCH"

# Closed specifications rather than user-selected/tuned presets. Changing a
# formula or parameter requires a successor contract and a new research trial.
HYPOTHESIS_FAMILIES = MappingProxyType({
    "PREVIOUS_SESSION_REVERSAL": MappingProxyType({
        "hypothesis_id": "previous-session-reversal-v1",
        "lookback_sessions": 1,
        "formula": "close[t] / close[t-1] - 1",
        "candidate_condition": "RETURN_LT_ZERO",
        "holding_sessions": 1,
    }),
    "FIVE_SESSION_CONTINUATION": MappingProxyType({
        "hypothesis_id": "five-session-continuation-v1",
        "lookback_sessions": 5,
        "formula": "close[t] / close[t-5] - 1",
        "candidate_condition": "RETURN_GT_ZERO",
        "holding_sessions": 3,
    }),
})
HYPOTHESIS_IDS = frozenset(row["hypothesis_id"] for row in HYPOTHESIS_FAMILIES.values())
EXPECTED_TESTS = (
    "NET_RETURN_EXCEEDS_CASH",
    "NET_RETURN_EXCEEDS_MATCHED_EQUAL_GROSS_EXPOSURE_CONTROL",
    "EXCESS_RETURN_SIGN_PERSISTS_AT_PREDECLARED_COST_STRESS_LEVELS",
)
REQUIRED_METRICS = (
    "NET_RETURN", "NET_EXPECTANCY_PER_CLOSED_TRADE", "MAX_DRAWDOWN",
    "TURNOVER", "EXPOSURE", "CLOSED_TRADE_COUNT", "REJECTION_COUNT",
    "NET_EXCESS_RETURN_OVER_CASH", "NET_EXCESS_RETURN_OVER_MATCHED_CONTROL",
)
FAILURE_RULES = (
    "NONPOSITIVE_NET_EXCESS_RETURN_OVER_EITHER_REQUIRED_BENCHMARK_IS_NOT_SUPPORT",
    "COST_STRESS_SIGN_FAILURE_IS_NOT_SUPPORT",
    "MISSING_AVAILABILITY_COSTS_OR_REQUIRED_CONTROL_IS_INCONCLUSIVE",
    "INCOMPLETE_TRIAL_REGISTRY_OR_UNDECLARED_PARAMETER_CHANGE_IS_INCONCLUSIVE",
    "UNSCORED_FINAL_HOLDOUT_CANNOT_ESTABLISH_VALIDATED_PERFORMANCE",
)


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def _texts(value, name, *, minimum=1, maximum=16):
    rows = [_string(row, name, 10000) for row in _list(value, name)]
    if not minimum <= len(rows) <= maximum or len(set(rows)) != len(rows):
        raise ContractValidationError(name + " must contain bounded, distinct explicit text")
    return rows


def _research_boundary(row):
    for field, expected in {
        "domain": "TRADING", "mode": TRADING_HYPOTHESIS_MODE,
        "scope": TRADING_HYPOTHESIS_SCOPE, "status": "PROPOSED_SPECIFICATION",
    }.items():
        _constant(row, field, expected)
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])


def _hypothesis(value):
    row = _object(value, {
        "schema_version", "hypothesis_id", "specification_version", "recorded_at", "author_id",
        "domain", "mode", "scope", "status", "ancestry", "implementation_status",
        "preregistration_claim", "name", "mechanism", "alternatives", "signal", "horizon",
        "data_requirements", "exposure_policy", "test_protocol", "expected_tests",
        "falsification_conditions", "auto_trading_enabled", "authority",
    }, "trading hypothesis")
    _constant(row, "schema_version", TRADING_HYPOTHESIS_SCHEMA_VERSION)
    _constant(row, "specification_version", "1")
    _research_boundary(row)
    _constant(row, "ancestry", "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")
    _constant(row, "implementation_status", "SPECIFICATION_ONLY_NO_INTENTS")
    _constant(row, "preregistration_claim", "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION")
    row["hypothesis_id"] = _identifier(row["hypothesis_id"], "hypothesis_id")
    row["author_id"] = _identifier(row["author_id"], "author_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["name"] = _string(row["name"], "name", 256)
    mechanism = _object(row["mechanism"], {"statement", "proposed_causal_mechanism", "assumptions", "evidence_status"}, "mechanism")
    for field in ("statement", "proposed_causal_mechanism"):
        mechanism[field] = _string(mechanism[field], "mechanism." + field, 10000)
    mechanism["assumptions"] = _texts(mechanism["assumptions"], "mechanism.assumptions")
    _constant(mechanism, "evidence_status", "UNTESTED_PROPOSAL")
    row["mechanism"] = mechanism
    alternatives = []
    identities = set()
    for value in _list(row["alternatives"], "alternatives"):
        alternative = _object(value, {"alternative_id", "statement", "distinguishing_test"}, "alternative")
        alternative["alternative_id"] = _identifier(alternative["alternative_id"], "alternative_id")
        if alternative["alternative_id"] in identities:
            raise ContractValidationError("alternative identities must be distinct")
        identities.add(alternative["alternative_id"])
        for field in ("statement", "distinguishing_test"):
            alternative[field] = _string(alternative[field], "alternative." + field, 10000)
        alternatives.append(alternative)
    if not 1 <= len(alternatives) <= 16:
        raise ContractValidationError("alternatives must be nonempty and bounded")
    row["alternatives"] = alternatives
    signal = _object(row["signal"], {
        "family", "formula", "lookback_sessions", "candidate_condition", "zero_return_behavior",
        "input_field", "known_at_requirement", "missing_input_behavior", "parameter_selection",
    }, "signal")
    family = _enum(signal["family"], set(HYPOTHESIS_FAMILIES), "signal.family")
    specification = HYPOTHESIS_FAMILIES[family]
    for field in ("formula", "lookback_sessions", "candidate_condition"):
        _constant(signal, field, specification[field])
    for field, expected in {
        "zero_return_behavior": "NO_CANDIDATE", "input_field": "COMPLETED_SESSION_CLOSE",
        "known_at_requirement": "ALL_LOOKBACK_INPUTS_AVAILABLE_BEFORE_DECISION",
        "missing_input_behavior": "DEFER_NO_IMPUTATION", "parameter_selection": "PREDECLARED_PROPOSED_NOT_TUNED",
    }.items():
        _constant(signal, field, expected)
    _constant(row, "hypothesis_id", specification["hypothesis_id"])
    row["signal"] = signal
    horizon = _object(row["horizon"], {
        "kind", "holding_sessions", "label_horizon_sessions", "entry_clock", "exit_clock", "overlap_policy",
    }, "horizon")
    for field, expected in {
        "kind": "SWING", "holding_sessions": specification["holding_sessions"],
        "label_horizon_sessions": specification["holding_sessions"],
        "entry_clock": "NEXT_SESSION_OPEN_AFTER_INPUT_AVAILABILITY",
        "exit_clock": "SESSION_OPEN_AFTER_DECLARED_HOLDING_SESSIONS",
        "overlap_policy": "NO_OVERLAPPING_POSITIONS_OR_REENTRY_WHILE_OPEN",
    }.items():
        _constant(horizon, field, expected)
    row["horizon"] = horizon
    requirements = _object(row["data_requirements"], {
        "bar_frequency", "universe_selection", "corporate_actions", "availability", "missing_sessions", "survivorship",
    }, "data_requirements")
    for field, expected in {
        "bar_frequency": "COMPLETED_DAILY_REGULAR_SESSIONS",
        "universe_selection": "FIXED_SOURCE_BOUND_UNIVERSE_BEFORE_DECISION_GENERATION",
        "corporate_actions": "DEFER_IF_PRICE_RETURN_CONTINUITY_UNVERIFIED",
        "availability": "EXPLICIT_RETAINED_AVAILABILITY_NO_BACKDATING",
        "missing_sessions": "DEFER_NO_FORWARD_FILL",
        "survivorship": "DECLARED_SELECTED_UNIVERSE_NO_MARKET_WIDE_GENERALIZATION",
    }.items():
        _constant(requirements, field, expected)
    row["data_requirements"] = requirements
    exposure = _object(row["exposure_policy"], {"kind", "size_source", "capital_status", "leverage", "shorts"}, "exposure_policy")
    for field, expected in {
        "kind": "LONG_ONLY_UNLEVERED_RESEARCH", "size_source": "REQUIRES_SEPARATE_PREDECLARED_RESEARCH_PLAN",
        "capital_status": "NO_DESK_BUDGET_OR_OWNERSHIP_ACTIVATION", "leverage": "DISABLED", "shorts": "DISABLED",
    }.items():
        _constant(exposure, field, expected)
    row["exposure_policy"] = exposure
    protocol = _object(row["test_protocol"], {
        "partition_policy", "final_holdout", "benchmarks", "cost_policy", "cost_stress_multipliers",
        "required_metrics", "missing_evidence_policy", "performance_status", "selection_policy", "failure_rules",
    }, "test_protocol")
    for field, expected in {
        "partition_policy": "CHRONOLOGICAL_DEVELOPMENT_FOLDS_WITH_PURGING_AND_EMBARGO",
        "final_holdout": "SEALED_NOT_SCORED_BY_THIS_BURST",
        "cost_policy": "SOURCE_BOUND_SPREAD_SLIPPAGE_AND_FEES_BEFORE_DECISION_GENERATION",
        "missing_evidence_policy": "INCONCLUSIVE", "performance_status": "NOT_EVALUATED",
        "selection_policy": "NO_AUTOMATIC_SELECTION_OR_PROMOTION",
    }.items():
        _constant(protocol, field, expected)
    _constant(protocol, "cost_stress_multipliers", ["1", "2", "4"])
    _constant(protocol, "required_metrics", list(REQUIRED_METRICS))
    _constant(protocol, "failure_rules", list(FAILURE_RULES))
    benchmarks = []
    for value in _list(protocol["benchmarks"], "benchmarks"):
        benchmark = _object(value, {"kind", "status", "definition"}, "benchmark")
        benchmark["definition"] = _string(benchmark["definition"], "benchmark.definition", 10000)
        benchmarks.append(benchmark)
    if len(benchmarks) != 2:
        raise ContractValidationError("both cash and a matched equal-gross-exposure control must be declared")
    for benchmark, kind, status in zip(benchmarks,
            ("CASH", "MATCHED_EQUAL_GROSS_EXPOSURE_CONTROL"),
            ("AVAILABLE_IN_OFFLINE_FOUNDATION", "DECLARED_NOT_IMPLEMENTED")):
        _constant(benchmark, "kind", kind)
        _constant(benchmark, "status", status)
    protocol["benchmarks"] = benchmarks
    row["test_protocol"] = protocol
    _constant(row, "expected_tests", list(EXPECTED_TESTS))
    row["falsification_conditions"] = _texts(row["falsification_conditions"], "falsification_conditions")
    return row


def _catalog(value):
    row = _object(value, {
        "schema_version", "catalog_id", "recorded_at", "author_id", "domain", "mode", "scope", "status",
        "selection_policy", "hypotheses", "auto_trading_enabled", "authority",
    }, "trading hypothesis catalog")
    _constant(row, "schema_version", TRADING_HYPOTHESIS_CATALOG_SCHEMA_VERSION)
    _research_boundary(row)
    _constant(row, "selection_policy", "NO_WINNER_SELECTED_NO_INTENTS_GENERATED")
    row["catalog_id"] = _identifier(row["catalog_id"], "catalog_id")
    row["author_id"] = _identifier(row["author_id"], "author_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    hypotheses = [_hypothesis(value) for value in _list(row["hypotheses"], "hypotheses")]
    identities = [hypothesis["hypothesis_id"] for hypothesis in hypotheses]
    if identities != sorted(HYPOTHESIS_IDS):
        raise ContractValidationError("catalog must contain exactly the two ordered independent hypothesis specifications")
    for hypothesis in hypotheses:
        if hypothesis["recorded_at"] != row["recorded_at"] or hypothesis["author_id"] != row["author_id"]:
            raise ContractValidationError("catalog and hypothesis authors and recording clocks must match")
    row["hypotheses"] = hypotheses
    return row


class TradingHypothesis(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_hypothesis)


class TradingHypothesisCatalog(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_catalog)
