"""Source-bound, inactive two-desk research and bounded PAPER test proposals.

Imported evidence and proposed parameters are descriptive claims. This contract
never installs ownership, activates budgets, enables automation, or authorizes an
order. Scenario stop distance is not a guarantee of maximum loss.
"""
from __future__ import annotations

from decimal import Context, Decimal, localcontext

from .decision_journal import _enum, _hash, _identifier, _object, _string
from .investment_review import _event_id, _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError, normalize_rfc3339, parse_rfc3339
from .trading_accounting import accounting_decimal, accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference, symbol_text

DESK_REVIEW_SCHEMA_VERSION = "blackpod.shadow_two_desk_review.v1"
DESK_REVIEW_SCOPE = "SHADOW_TWO_DESK_REVIEW_ONLY"
DESK_REVIEW_METHOD_VERSION = "blackpod.deterministic_two_desk_review.v1"
DESK_REVIEW_LIMITATIONS = (
    "PRICE_DERIVED_NATIVE_EVIDENCE_NOT_INDEPENDENT", "IEX_VOLUME_NOT_CONSOLIDATED_LIQUIDITY",
    "HISTORICAL_PRICES_NOT_EXPECTED_RETURNS", "ISSUER_MANDATE_NOT_FUNDAMENTAL_ALPHA",
    "PROPOSED_PARAMETERS_NOT_LIVE_POLICY", "STOP_SCENARIO_NOT_MAXIMUM_LOSS",
    "MARKET_AND_ACCOUNT_SNAPSHOTS_NOT_ATOMIC", "CORPORATE_ACTION_ACCOUNTING_UNSUPPORTED",
    "PROVIDER_IDENTITY_NOT_ATTESTED", "NO_EXECUTION_AUTHORITY",
)
METRIC_FIELDS = frozenset({"last", "bid", "ask", "spread_pct", "atr14", "sma20", "sma50", "return20_pct",
                           "return60_pct", "range_pct", "iex_average_dollar_volume20"})


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def _positive_fraction(value, name):
    value = accounting_decimal(value, name, positive=True)
    if Decimal(value) > 1:
        raise ContractValidationError(name + " must not exceed one")
    return value


def _bounded_integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ContractValidationError(name + " must be an integer in the supported range")
    return value


def _review(value):
    result = _object(value, {"schema_version", "review_id", "recorded_at", "mode", "account_id", "scope",
                             "budget", "sources", "policy", "authority"}, "shadow two-desk review")
    _constant(result, "schema_version", DESK_REVIEW_SCHEMA_VERSION)
    _constant(result, "mode", "PAPER")
    _constant(result, "scope", DESK_REVIEW_SCOPE)
    for field in ("review_id", "account_id"):
        result[field] = _identifier(result[field], field)
    result["recorded_at"] = accounting_timestamp(result["recorded_at"], "recorded_at")
    result["authority"] = disabled_authority(result["authority"])
    budget = _object(result["budget"], {"proposal_evidence", "source_snapshot_event_id", "source_snapshot_sha256"}, "budget")
    budget["proposal_evidence"] = evidence_reference(budget["proposal_evidence"], "budget.proposal_evidence")
    budget["source_snapshot_event_id"] = _event_id(budget["source_snapshot_event_id"], "budget.source_snapshot_event_id")
    budget["source_snapshot_sha256"] = _hash(budget["source_snapshot_sha256"], "budget.source_snapshot_sha256")
    result["budget"] = budget
    sources = _object(result["sources"], {"market_evidence", "analysis_evidence", "issuer_evidence"}, "sources")
    for field in sources:
        sources[field] = evidence_reference(sources[field], "sources." + field)
    references = [budget["proposal_evidence"], *sources.values()]
    if len({reference["path"] for reference in references}) != len(references):
        raise ContractValidationError("review evidence references must have distinct paths")
    result["sources"] = sources
    policy = _object(result["policy"], {"status", "max_entry_fraction", "scenario_risk_fraction", "atr_multiple", "price_buffer_fraction",
        "investment_candidate_fraction", "max_active_entries", "max_completed_cycles", "expires_at", "investment_horizon_days", "benchmark_symbol"}, "policy")
    _constant(policy, "status", "PROPOSED_SHADOW_ONLY")
    for field in ("max_entry_fraction", "scenario_risk_fraction", "investment_candidate_fraction"):
        policy[field] = _positive_fraction(policy[field], "policy." + field)
    policy["atr_multiple"] = accounting_decimal(policy["atr_multiple"], "policy.atr_multiple", positive=True)
    if Decimal(policy["atr_multiple"]) > 100:
        raise ContractValidationError("policy.atr_multiple exceeds the supported scenario range")
    policy["price_buffer_fraction"] = accounting_decimal(policy["price_buffer_fraction"], "policy.price_buffer_fraction", nonnegative=True)
    if Decimal(policy["price_buffer_fraction"]) > 1:
        raise ContractValidationError("policy.price_buffer_fraction must not exceed one")
    for field in ("max_active_entries", "max_completed_cycles"):
        if type(policy[field]) is not int or policy[field] != 1:
            raise ContractValidationError("policy." + field + " must be exactly one in this bounded proposal")
    policy["investment_horizon_days"] = _bounded_integer(policy["investment_horizon_days"], "policy.investment_horizon_days", 1, 3650)
    policy["benchmark_symbol"] = symbol_text(policy["benchmark_symbol"], "policy.benchmark_symbol")
    policy["expires_at"] = accounting_timestamp(policy["expires_at"], "policy.expires_at")
    if parse_rfc3339(policy["expires_at"], "expires_at") <= parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("proposed plan expiry must be after recorded_at")
    result["policy"] = policy
    return result


class DeskReviewInput(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_review)


ReviewInput = DeskReviewInput


def _texts(value, name, *, symbols=False):
    validator = symbol_text if symbols else _string
    entries = [validator(entry, name) for entry in _list(value, name)]
    if len(entries) > 256 or len(set(entries)) != len(entries):
        raise ContractValidationError(name + " must contain unique bounded entries")
    return entries


def _money(result, fields, *, nullable=()):
    for field in fields:
        if result[field] is None and field in nullable:
            continue
        result[field] = accounting_decimal(result[field], field, nonnegative=True, output=True)


def _counts(value, name):
    if not isinstance(value, dict) or len(value) > 16:
        raise ContractValidationError(name + " must be a bounded count object")
    result = {}
    for key, count in value.items():
        key = _identifier(key, name + " key")
        result[key] = _bounded_integer(count, name + "." + key, 0, 256)
    return result


def validate_review_result(value, review: DeskReviewInput):
    """Validate passive report shape; retained source replay verifies calculations."""
    result = _object(value, {"method_version", "status", "account_id", "budget_source_snapshot_event_id", "budgets_usd", "market_as_of",
        "native_summary", "candidates", "trading_plan", "investment_plan", "ownership_proposal", "readiness",
        "auto_trading_enabled", "realized_trade_pnl", "authority", "reason_codes", "limitations"}, "two-desk review result")
    _constant(result, "status", "SHADOW_REVIEW_ONLY")
    _constant(result, "method_version", DESK_REVIEW_METHOD_VERSION)
    _constant(result, "account_id", review.account_id)
    _constant(result, "budget_source_snapshot_event_id", review.budget["source_snapshot_event_id"])
    result["market_as_of"] = accounting_timestamp(result["market_as_of"], "market_as_of")
    if parse_rfc3339(result["market_as_of"], "market_as_of") > parse_rfc3339(review.recorded_at, "recorded_at"):
        raise ContractValidationError("market_as_of cannot be after recorded_at")
    budgets = _object(result["budgets_usd"], {"TRADING", "INVESTMENT"}, "budgets_usd")
    _money(budgets, budgets)
    result["budgets_usd"] = budgets
    native = _object(result["native_summary"], {"oracle_state", "candidate_counts", "senate_counts", "independent_evidence"}, "native_summary")
    if native["oracle_state"] is not None:
        native["oracle_state"] = _string(native["oracle_state"], "oracle_state")
    for field in ("candidate_counts", "senate_counts"):
        native[field] = _counts(native[field], field)
    _fixed_boolean(native, "independent_evidence", False)
    result["native_summary"] = native
    candidates, symbols, ranks = [], set(), set()
    for entry in _list(result["candidates"], "candidates"):
        row = _object(entry, {"symbol", "category", "rank", "metrics", "native", "reason_codes"}, "candidate")
        row["symbol"] = symbol_text(row["symbol"])
        if row["symbol"] in symbols:
            raise ContractValidationError("candidates must have unique symbols")
        symbols.add(row["symbol"])
        row["category"] = _enum(row["category"], {"TRADING_PILOT", "INVESTMENT_RESEARCH", "DEFER", "EXCLUDE"}, "candidate.category")
        if row["rank"] is not None:
            row["rank"] = _bounded_integer(row["rank"], "candidate.rank", 1, 256)
            rank_key = (row["category"], row["rank"])
            if rank_key in ranks:
                raise ContractValidationError("candidate ranks must be unique within each category")
            ranks.add(rank_key)
        metrics = _object(row["metrics"], METRIC_FIELDS, "candidate.metrics")
        for field in metrics:
            if metrics[field] is not None:
                metrics[field] = accounting_decimal(metrics[field], "metrics." + field, output=True,
                    nonnegative=field not in {"return20_pct", "return60_pct"})
        row["metrics"] = metrics
        contribution = _object(row["native"], {"candidate_state", "senate_disposition", "confidence_label"}, "candidate.native")
        if contribution["candidate_state"] is not None:
            contribution["candidate_state"] = _enum(contribution["candidate_state"], {"REVIEW", "WATCH", "OBSERVE", "REJECT"}, "candidate_state")
        for field in ("senate_disposition", "confidence_label"):
            if contribution[field] is not None:
                contribution[field] = _string(contribution[field], field)
        row["native"] = contribution
        row["reason_codes"] = _texts(row["reason_codes"], "candidate.reason_codes")
        candidates.append(row)
    if len(candidates) > 256:
        raise ContractValidationError("candidates exceeds the supported count")
    result["candidates"] = candidates
    plan = _object(result["trading_plan"], {"status", "symbol", "qty", "max_entry_notional_usd", "buffered_price_usd",
        "estimated_notional_usd", "stop_distance_usd", "scenario_loss_usd", "total_round_trip_notional_usd", "maximum_completed_cycles",
        "max_active_entries", "time_exit_minutes", "expiry", "authorization_required", "purpose", "return_expectation"}, "trading_plan")
    plan["status"] = _enum(plan["status"], {"CONDITIONAL_FUNCTIONAL_PILOT", "DEFER"}, "trading_plan.status")
    if plan["symbol"] is not None:
        plan["symbol"] = symbol_text(plan["symbol"])
        if plan["symbol"] not in symbols:
            raise ContractValidationError("trading plan symbol must be a retained candidate")
    plan["qty"] = _bounded_integer(plan["qty"], "trading_plan.qty", 0, 1000000000)
    _money(plan, ("max_entry_notional_usd", "buffered_price_usd", "estimated_notional_usd", "stop_distance_usd",
                  "scenario_loss_usd", "total_round_trip_notional_usd"), nullable=("buffered_price_usd", "stop_distance_usd", "scenario_loss_usd"))
    if plan["symbol"] is None and plan["qty"] != 0:
        raise ContractValidationError("a symbol-free trading proposal cannot have positive quantity")
    for field, expected in (("maximum_completed_cycles", 1), ("max_active_entries", 1), ("time_exit_minutes", 30)):
        if type(plan[field]) is not int or plan[field] != expected:
            raise ContractValidationError("trading_plan." + field + " must be " + str(expected))
    plan["expiry"] = accounting_timestamp(plan["expiry"], "trading_plan.expiry")
    _constant(plan, "expiry", review.policy["expires_at"])
    _fixed_boolean(plan, "authorization_required", True)
    _constant(plan, "purpose", "EXECUTION_AND_ACCOUNTING_TEST")
    _constant(plan, "return_expectation", None)
    if Decimal(plan["estimated_notional_usd"]) > Decimal(plan["max_entry_notional_usd"]) or Decimal(plan["max_entry_notional_usd"]) > Decimal(budgets["TRADING"]):
        raise ContractValidationError("trading proposal must remain within its declared entry and desk budgets")
    result["trading_plan"] = plan
    investment = _object(result["investment_plan"], {"status", "horizon_days", "candidates", "total_notional_usd", "cash_reserve_usd", "allocation_authorized"}, "investment_plan")
    _constant(investment, "status", "RESEARCH_ONLY")
    if type(investment["horizon_days"]) is not int or investment["horizon_days"] != review.policy["investment_horizon_days"]:
        raise ContractValidationError("investment_plan.horizon_days must match the proposed review policy")
    research, research_symbols = [], set()
    for entry in _list(investment["candidates"], "investment_plan.candidates"):
        row = _object(entry, {"symbol", "qty", "buffered_price_usd", "estimated_notional_usd", "hypothesis", "invalidation_conditions", "expected_return"}, "investment candidate")
        row["symbol"] = symbol_text(row["symbol"])
        if row["symbol"] not in symbols or row["symbol"] in research_symbols or row["symbol"] == plan["symbol"]:
            raise ContractValidationError("investment research symbols must be unique retained candidates distinct from the trading pilot")
        research_symbols.add(row["symbol"])
        row["qty"] = _bounded_integer(row["qty"], "investment candidate.qty", 0, 1000000000)
        _money(row, ("buffered_price_usd", "estimated_notional_usd"))
        row["hypothesis"] = _string(row["hypothesis"], "hypothesis", 10000)
        row["invalidation_conditions"] = _texts(row["invalidation_conditions"], "invalidation_conditions")
        _constant(row, "expected_return", None)
        research.append(row)
    if len(research) > 256:
        raise ContractValidationError("investment candidate count exceeds the supported bound")
    investment["candidates"] = research
    _money(investment, ("total_notional_usd", "cash_reserve_usd"))
    if Decimal(investment["total_notional_usd"]) > Decimal(budgets["INVESTMENT"]):
        raise ContractValidationError("investment research proposal exceeds its declared desk budget")
    with localcontext(Context(prec=256)):
        if Decimal(investment["total_notional_usd"]) + Decimal(investment["cash_reserve_usd"]) != Decimal(budgets["INVESTMENT"]):
            raise ContractValidationError("investment research notional and reserve must exactly reconcile to the declared budget")
    _fixed_boolean(investment, "allocation_authorized", False)
    result["investment_plan"] = investment
    ownership = _object(result["ownership_proposal"], {"TRADING", "INVESTMENT", "status"}, "ownership_proposal")
    _constant(ownership, "status", "PROPOSED_NOT_INSTALLED")
    for desk in ("TRADING", "INVESTMENT"):
        ownership[desk] = _texts(ownership[desk], "ownership_proposal." + desk, symbols=True)
        if set(ownership[desk]) - symbols:
            raise ContractValidationError("proposed ownership must bind retained candidates")
    if set(ownership["TRADING"]) & set(ownership["INVESTMENT"]):
        raise ContractValidationError("proposed desk ownership must be disjoint")
    if ownership["TRADING"] != ([] if plan["symbol"] is None else [plan["symbol"]]) or set(ownership["INVESTMENT"]) != research_symbols:
        raise ContractValidationError("proposed ownership must exactly match the two research plans")
    result["ownership_proposal"] = ownership
    for field in ("readiness", "auto_trading_enabled"):
        _fixed_boolean(result, field, False)
    _constant(result, "realized_trade_pnl", None)
    result["authority"] = disabled_authority(result["authority"])
    result["reason_codes"] = _texts(result["reason_codes"], "reason_codes")
    if result["limitations"] != list(DESK_REVIEW_LIMITATIONS):
        raise ContractValidationError("review limitations must retain the complete method limitations")
    return result
