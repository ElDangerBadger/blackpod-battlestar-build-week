"""Pure independent candidate specification export, with no strategy execution.

The candidate names describe falsifiable proposals, not demonstrated effects.
No Galactica implementation, indicator preset, Brigade recommendation, broker,
provider, strategy optimizer, or supplied intent set is consumed here.
"""
from __future__ import annotations

from .contracts.trading_hypothesis import (
    EXPECTED_TESTS, FAILURE_RULES, HYPOTHESIS_FAMILIES, REQUIRED_METRICS,
    TRADING_HYPOTHESIS_CATALOG_SCHEMA_VERSION, TRADING_HYPOTHESIS_MODE,
    TRADING_HYPOTHESIS_SCHEMA_VERSION, TRADING_HYPOTHESIS_SCOPE,
    TradingHypothesis, TradingHypothesisCatalog,
)


def _authority():
    return {field: False for field in (
        "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
    )}


_PROPOSALS = {
    "PREVIOUS_SESSION_REVERSAL": {
        "name": "Previous-session negative-return reversal",
        "statement": "After a negative completed-session return, a one-session long research exposure may outperform cash and a matched exposure control after declared costs.",
        "mechanism": "Temporary selling pressure could move prices below a subsequent clearing level; this explanation is an untested alternative to lasting adverse information.",
        "assumptions": [
            "Completed close prices are comparable across the lookback and holding interval.",
            "Any temporary selling pressure unwinds within the declared holding interval.",
            "An apparent gross effect may be eliminated by spreads, slippage and fees.",
        ],
        "alternatives": [
            {"alternative_id": "persistent-adverse-information", "statement": "A negative return reflects information that continues to lower subsequent prices.",
             "distinguishing_test": "Compare subsequent net return after negative returns with the preregistered exposure control in each chronological development fold."},
            {"alternative_id": "data-or-fill-artifact", "statement": "An apparent reversal comes from adjusted price discontinuities, stale bars or optimistic assumed fills.",
             "distinguishing_test": "Defer unverified price continuity and repeat the declared comparison at all frozen cost stress multipliers."},
        ],
        "falsification": [
            "Net excess return is nonpositive relative to cash or the required matched exposure control across the declared development evaluation.",
            "The positive excess return sign fails at a predeclared cost stress multiplier.",
            "The observed behavior is confined to an undeclared post hoc subset of symbols or sessions.",
        ],
    },
    "FIVE_SESSION_CONTINUATION": {
        "name": "Five-session positive-return continuation",
        "statement": "After a positive five-session completed-close return, a three-session long research exposure may outperform cash and a matched exposure control after declared costs.",
        "mechanism": "Gradual information incorporation or persistent demand could continue beyond the observation interval; this explanation is an untested alternative to temporary overreaction.",
        "assumptions": [
            "Completed close prices are comparable across the lookback and holding interval.",
            "A proposed continuation lasts beyond the declared five-session observation interval.",
            "An apparent gross effect may be eliminated by spreads, slippage and fees.",
        ],
        "alternatives": [
            {"alternative_id": "temporary-overreaction", "statement": "The positive return reflects temporary pressure that reverses rather than continues.",
             "distinguishing_test": "Compare subsequent net return after positive five-session returns with the preregistered exposure control in each chronological development fold."},
            {"alternative_id": "passive-market-exposure", "statement": "Any positive result is explained by general market exposure rather than the return condition.",
             "distinguishing_test": "Require the matched equal-gross-exposure control and retain its comparison separately from the cash comparison."},
        ],
        "falsification": [
            "Net excess return is nonpositive relative to cash or the required matched exposure control across the declared development evaluation.",
            "The positive excess return sign fails at a predeclared cost stress multiplier.",
            "The observed behavior is confined to an undeclared post hoc subset of symbols or sessions.",
        ],
    },
}


def _hypothesis_mapping(family, *, recorded_at, author_id):
    specification, proposal = HYPOTHESIS_FAMILIES[family], _PROPOSALS[family]
    return {
        "schema_version": TRADING_HYPOTHESIS_SCHEMA_VERSION,
        "hypothesis_id": specification["hypothesis_id"], "specification_version": "1",
        "recorded_at": recorded_at, "author_id": author_id, "domain": "TRADING",
        "mode": TRADING_HYPOTHESIS_MODE, "scope": TRADING_HYPOTHESIS_SCOPE,
        "status": "PROPOSED_SPECIFICATION", "ancestry": "INDEPENDENT_NEW_RESEARCH_SPECIFICATION",
        "implementation_status": "SPECIFICATION_ONLY_NO_INTENTS",
        "preregistration_claim": "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION",
        "name": proposal["name"],
        "mechanism": {"statement": proposal["statement"], "proposed_causal_mechanism": proposal["mechanism"],
                      "assumptions": list(proposal["assumptions"]), "evidence_status": "UNTESTED_PROPOSAL"},
        "alternatives": [dict(value) for value in proposal["alternatives"]],
        "signal": {
            "family": family, "formula": specification["formula"],
            "lookback_sessions": specification["lookback_sessions"],
            "candidate_condition": specification["candidate_condition"], "zero_return_behavior": "NO_CANDIDATE",
            "input_field": "COMPLETED_SESSION_CLOSE", "known_at_requirement": "ALL_LOOKBACK_INPUTS_AVAILABLE_BEFORE_DECISION",
            "missing_input_behavior": "DEFER_NO_IMPUTATION", "parameter_selection": "PREDECLARED_PROPOSED_NOT_TUNED",
        },
        "horizon": {
            "kind": "SWING", "holding_sessions": specification["holding_sessions"],
            "label_horizon_sessions": specification["holding_sessions"],
            "entry_clock": "NEXT_SESSION_OPEN_AFTER_INPUT_AVAILABILITY",
            "exit_clock": "SESSION_OPEN_AFTER_DECLARED_HOLDING_SESSIONS",
            "overlap_policy": "NO_OVERLAPPING_POSITIONS_OR_REENTRY_WHILE_OPEN",
        },
        "data_requirements": {
            "bar_frequency": "COMPLETED_DAILY_REGULAR_SESSIONS",
            "universe_selection": "FIXED_SOURCE_BOUND_UNIVERSE_BEFORE_DECISION_GENERATION",
            "corporate_actions": "DEFER_IF_PRICE_RETURN_CONTINUITY_UNVERIFIED",
            "availability": "EXPLICIT_RETAINED_AVAILABILITY_NO_BACKDATING",
            "missing_sessions": "DEFER_NO_FORWARD_FILL",
            "survivorship": "DECLARED_SELECTED_UNIVERSE_NO_MARKET_WIDE_GENERALIZATION",
        },
        "exposure_policy": {
            "kind": "LONG_ONLY_UNLEVERED_RESEARCH", "size_source": "REQUIRES_SEPARATE_PREDECLARED_RESEARCH_PLAN",
            "capital_status": "NO_DESK_BUDGET_OR_OWNERSHIP_ACTIVATION", "leverage": "DISABLED", "shorts": "DISABLED",
        },
        "test_protocol": {
            "partition_policy": "CHRONOLOGICAL_DEVELOPMENT_FOLDS_WITH_PURGING_AND_EMBARGO",
            "final_holdout": "SEALED_NOT_SCORED_BY_THIS_BURST",
            "benchmarks": [
                {"kind": "CASH", "status": "AVAILABLE_IN_OFFLINE_FOUNDATION",
                 "definition": "Uninvested simulated cash under the separately declared research plan; no interest yield is invented."},
                {"kind": "MATCHED_EQUAL_GROSS_EXPOSURE_CONTROL", "status": "DECLARED_NOT_IMPLEMENTED",
                 "definition": "Future unconditional equal-weight exposure to the fixed research universe, matched to the candidate exposure budget and holding schedule, without selecting symbols by this hypothesis; implementation and pre-outcome rules must be frozen separately."},
            ],
            "cost_policy": "SOURCE_BOUND_SPREAD_SLIPPAGE_AND_FEES_BEFORE_DECISION_GENERATION",
            "cost_stress_multipliers": ["1", "2", "4"], "required_metrics": list(REQUIRED_METRICS),
            "missing_evidence_policy": "INCONCLUSIVE", "performance_status": "NOT_EVALUATED",
            "selection_policy": "NO_AUTOMATIC_SELECTION_OR_PROMOTION", "failure_rules": list(FAILURE_RULES),
        },
        "expected_tests": list(EXPECTED_TESTS), "falsification_conditions": list(proposal["falsification"]),
        "auto_trading_enabled": False, "authority": _authority(),
    }


def catalog_hypotheses(recorded_at, author_id, *, catalog_id="independent-trading-hypotheses-v1"):
    """Return the two frozen proposals without reading data or producing trades.

    Fixed lookbacks/holds are design proposals, not calibrated optimal values.
    Cost stress levels are declared sensitivities, not observed trading costs.
    Matching exposures and checking the proposed expected tests are future
    evaluation work; this export produces no measured performance or winner.
    """
    hypotheses = [_hypothesis_mapping(family, recorded_at=recorded_at, author_id=author_id)
                  for family in HYPOTHESIS_FAMILIES]
    hypotheses.sort(key=lambda value: value["hypothesis_id"])
    return TradingHypothesisCatalog.from_mapping({
        "schema_version": TRADING_HYPOTHESIS_CATALOG_SCHEMA_VERSION, "catalog_id": catalog_id,
        "recorded_at": recorded_at, "author_id": author_id, "domain": "TRADING", "mode": TRADING_HYPOTHESIS_MODE,
        "scope": TRADING_HYPOTHESIS_SCOPE, "status": "PROPOSED_SPECIFICATION",
        "selection_policy": "NO_WINNER_SELECTED_NO_INTENTS_GENERATED", "hypotheses": hypotheses,
        "auto_trading_enabled": False, "authority": _authority(),
    })


def hypothesis_catalog(recorded_at, author_id, *, catalog_id="independent-trading-hypotheses-v1"):
    """Named alias for CLI/export callers; no hidden clock or mutable state."""
    return catalog_hypotheses(recorded_at, author_id, catalog_id=catalog_id)


def validate_hypothesis_catalog(value):
    """Validate an imported catalog; never infer author authenticity or results."""
    if isinstance(value, TradingHypothesisCatalog):
        return TradingHypothesisCatalog.from_bytes(value.to_bytes())
    return TradingHypothesisCatalog.from_mapping(value)


def catalog_documents(catalog):
    """Return separate immutable hypothesis documents for evidence retention."""
    catalog = validate_hypothesis_catalog(catalog)
    return tuple(TradingHypothesis.from_mapping(value) for value in catalog.hypotheses)


def hypothesis_research_strategy(hypothesis):
    """Project descriptive fields into the existing offline plan shape.

    EXTERNAL_INTENTS_ONLY is the plan's existing boundary, not a claim that
    these specifications generate them. The caller supplies an empty intent
    set for a data-quality-only study; no signal or performance is computed.
    """
    if isinstance(hypothesis, TradingHypothesis):
        hypothesis = TradingHypothesis.from_bytes(hypothesis.to_bytes())
    else:
        hypothesis = TradingHypothesis.from_mapping(hypothesis)
    return {
        "strategy": {
            "strategy_id": hypothesis.hypothesis_id,
            "version": hypothesis.specification_version,
            "hypothesis": hypothesis.mechanism["statement"],
            "expected_edge": "Untested proposal: net excess return over cash and the declared matched exposure control; no edge has been measured.",
            "falsification_conditions": hypothesis.falsification_conditions,
            "ancestry": hypothesis.ancestry,
            "implementation_status": "EXTERNAL_INTENTS_ONLY",
        },
        "horizon": {
            "kind": "SWING", "max_holding_sessions": hypothesis.horizon["holding_sessions"],
            "label_horizon_sessions": hypothesis.horizon["label_horizon_sessions"],
        },
    }
