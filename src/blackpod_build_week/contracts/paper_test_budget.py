"""Inactive PAPER test budget declaration, independent of execution authority."""
from decimal import Context, Decimal, ROUND_DOWN, localcontext

from .decision_journal import _identifier, _object
from .investment_review import _event_id, _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, normalize_rfc3339, parse_rfc3339
from .trading_accounting import accounting_decimal
from .trading_reconciliation import _ReconciliationDocument

SCHEMA_VERSION = "blackpod.paper_test_budget.v1"


def budget_amounts(equity):
    equity = Decimal(accounting_decimal(equity, "equity_usd", positive=True))
    with localcontext(Context(prec=256)):
        if equity != equity.quantize(Decimal("0.01")):
            raise ContractValidationError("paper test budget equity must be expressed in whole USD cents")
        cap = (equity * Decimal("0.25")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        desk = (equity * Decimal("0.125")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if desk <= 0:
            raise ContractValidationError("paper test equity cannot support positive desk budgets")
        return {"test_cap_usd": format(cap, ".2f"), "desk_budgets_usd": {"TRADING": format(desk, ".2f"), "INVESTMENT": format(desk, ".2f")},
            "unassigned_test_reserve_usd": format(cap - 2 * desk, ".2f"), "outside_test_usd": format(equity - cap, ".2f")}


def _validate(value):
    result = _object(value, {"schema_version", "budget_id", "recorded_at", "declared_by", "mode", "account_id", "status", "scope", "basis",
        "fraction_of_equity", "desk_weights_within_test", "rounding_policy", "test_cap_usd", "desk_budgets_usd", "unassigned_test_reserve_usd", "outside_test_usd",
        "ownership_event_id", "max_entry_notional_usd", "total_entry_test_notional_usd", "expires_at", "enforcement_status", "identity_authenticated",
        "activation_enabled", "capital_transfers_enabled", "automated_reallocation_enabled", "authority"}, "paper test budget")
    constants = {"schema_version": SCHEMA_VERSION, "mode": "PAPER", "status": "DECLARED_INACTIVE", "scope": "PAPER_TEST_BUDGET_ONLY",
        "fraction_of_equity": "0.25", "rounding_policy": "ROUND_DOWN_USD_CENTS", "enforcement_status": "NOT_INSTALLED"}
    for field, expected in constants.items():
        if result[field] != expected:
            raise ContractValidationError(field + " must be " + repr(expected))
    for field in ("budget_id", "declared_by", "account_id"):
        result[field] = _identifier(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    basis = _object(result["basis"], {"snapshot_event_id", "snapshot_sha256", "captured_at", "equity_usd", "currency"}, "budget basis")
    from .decision_journal import _hash
    basis["snapshot_event_id"] = _event_id(basis["snapshot_event_id"], "basis.snapshot_event_id")
    basis["snapshot_sha256"] = _hash(basis["snapshot_sha256"], "basis.snapshot_sha256")
    basis["captured_at"] = normalize_rfc3339(basis["captured_at"], "basis.captured_at")
    if basis["currency"] != "USD" or parse_rfc3339(basis["captured_at"], "captured_at") > parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("budget requires prior USD equity evidence")
    result["basis"] = basis
    weights = _object(result["desk_weights_within_test"], {"TRADING", "INVESTMENT"}, "desk weights")
    if weights != {"TRADING": "0.50", "INVESTMENT": "0.50"}:
        raise ContractValidationError("test desk weights must be explicitly 0.50 each")
    result["desk_weights_within_test"] = weights
    expected = budget_amounts(basis["equity_usd"])
    for field, calculated in expected.items():
        if result[field] != calculated:
            raise ContractValidationError(field + " differs from the fixed equity-based test allocation")
    for field in ("ownership_event_id", "max_entry_notional_usd", "total_entry_test_notional_usd", "expires_at"):
        if result[field] is not None:
            raise ContractValidationError(field + " remains unset in this inactive budget declaration")
    for field in ("identity_authenticated", "activation_enabled", "capital_transfers_enabled", "automated_reallocation_enabled"):
        _fixed_boolean(result, field, False)
    result["authority"] = disabled_authority(result["authority"])
    return result


class PaperTestBudget(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_validate)
