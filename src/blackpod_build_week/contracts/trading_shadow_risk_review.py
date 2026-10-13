"""Closed, immutable declarations for simulation sizing and risk review.

An APPROVED_FOR_SHADOW status is a retained local review claim. It cannot
activate a desk budget, authenticate a human reviewer, approve a paper order,
or amend either desk's policies. The frozen source research plan is preserved.
"""
from __future__ import annotations

from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _decimal, _integer
from .trading_shadow_research import _references, _texts

TRADING_SHADOW_RISK_REVIEW_VERSION = "blackpod.trading_shadow_risk_review.v1"
SIMULATION_RISK_FIELDS = frozenset({
    "initial_cash", "max_order_notional", "max_position_fraction", "max_gross_exposure_fraction",
    "max_volume_participation_fraction", "max_staleness_seconds",
})
RISK_REVIEW_LIMITATIONS = (
    "LOCAL_REVIEW_CLAIM_NOT_AUTHENTICATED_HUMAN_APPROVAL",
    "SIMULATION_BUDGET_NOT_ACTIVATED_DESK_CAPITAL",
    "KNOWN_CLOSE_SIZING_NOT_EXECUTABLE_PRICE",
    "NO_EXECUTION_AUTHORITY",
)


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def validate_simulation_risk(value):
    """Retain the six existing risk declarations without importing live policy."""
    row = _object(value, SIMULATION_RISK_FIELDS, "simulation_risk")
    for field in ("initial_cash", "max_order_notional"):
        row[field] = _decimal(row[field], "simulation_risk." + field, positive=True)
    for field in ("max_position_fraction", "max_gross_exposure_fraction", "max_volume_participation_fraction"):
        row[field] = _decimal(row[field], "simulation_risk." + field, positive=True, maximum=Decimal("1"))
    row["max_staleness_seconds"] = _integer(row["max_staleness_seconds"], "max_staleness_seconds", 1, 366 * 86400)
    return row


def _review(value):
    row = _object(value, {
        "schema_version", "risk_review_id", "recorded_at", "reviewer_id", "review_notes", "domain", "mode",
        "scope", "status", "base_plan_evidence", "evidence_scope", "simulation_risk", "sizing",
        "source_evidence", "limitations", "auto_trading_enabled", "authority",
    }, "trading shadow risk review")
    for field, expected in {
        "schema_version": TRADING_SHADOW_RISK_REVIEW_VERSION, "domain": "TRADING",
        "mode": "SHADOW_RESEARCH", "scope": "SIMULATION_SIZING_ONLY",
    }.items():
        _constant(row, field, expected)
    for field in ("risk_review_id", "reviewer_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    row["status"] = _enum(row["status"], {"PROPOSED", "APPROVED_FOR_SHADOW", "REJECTED", "DEFERRED"}, "status")
    row["base_plan_evidence"] = evidence_reference(row["base_plan_evidence"], "base_plan_evidence")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    row["simulation_risk"] = validate_simulation_risk(row["simulation_risk"])
    sizing = _object(row["sizing"], {"method", "per_symbol_notional"}, "sizing")
    _constant(sizing, "method", "KNOWN_CLOSE_WHOLE_QUANTITY")
    sizing["per_symbol_notional"] = _decimal(sizing["per_symbol_notional"], "sizing.per_symbol_notional", positive=True)
    row["sizing"] = sizing
    with localcontext(Context(prec=256, rounding=ROUND_HALF_EVEN, traps=[])):
        risk, budget = row["simulation_risk"], Decimal(sizing["per_symbol_notional"])
        cash = Decimal(risk["initial_cash"])
        if budget > Decimal(risk["max_order_notional"]) or budget > cash or budget > cash * Decimal(risk["max_position_fraction"]):
            raise ContractValidationError("per-symbol notional must fit the declared order, cash and position caps")
    row["source_evidence"] = _references(row["source_evidence"], "source_evidence")
    if row["base_plan_evidence"]["path"] in {ref["path"] for ref in row["source_evidence"]}:
        raise ContractValidationError("risk review source evidence must be distinct from the original base plan")
    row["limitations"] = _texts(row["limitations"], "limitations")
    if not set(RISK_REVIEW_LIMITATIONS) <= set(row["limitations"]):
        raise ContractValidationError("risk review must retain all explicit simulation-authority limitations")
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


class TradingShadowRiskReview(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_review)
