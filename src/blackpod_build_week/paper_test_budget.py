"""Pure source-bound inactive testing budgets; never execution configuration."""
from decimal import Context, localcontext
from .contracts.paper_test_budget import PaperTestBudget, SCHEMA_VERSION, budget_amounts
from .contracts.trading_reconciliation import BrokerSnapshotInput
from .hashing import canonical_json_bytes, sha256_bytes


def _build(snapshot_event, *, budget_id, recorded_at, declared_by):
    if snapshot_event.event_type != "PAPER_BROKER_SNAPSHOT_RECORDED":
        raise ValueError("test budget requires a verified paper snapshot event")
    snapshot = BrokerSnapshotInput.from_mapping(snapshot_event.payload["snapshot"])
    if (snapshot.account["currency"] != "USD" or snapshot.account["status"] != "ACTIVE"
            or snapshot.account["trading_blocked"] or snapshot.account["account_blocked"] is not False):
        raise ValueError("test budget requires a confirmed active unblocked USD paper account")
    return PaperTestBudget.from_mapping({"schema_version": SCHEMA_VERSION, "budget_id": budget_id, "recorded_at": recorded_at,
        "declared_by": declared_by, "mode": "PAPER", "account_id": snapshot.account_id, "status": "DECLARED_INACTIVE", "scope": "PAPER_TEST_BUDGET_ONLY",
        "basis": {"snapshot_event_id": snapshot_event.event_id, "snapshot_sha256": snapshot_event.source["source_sha256"],
            "captured_at": snapshot.captured_at, "equity_usd": snapshot.account["equity"], "currency": "USD"},
        "fraction_of_equity": "0.25", "desk_weights_within_test": {"TRADING": "0.50", "INVESTMENT": "0.50"}, "rounding_policy": "ROUND_DOWN_USD_CENTS",
        **budget_amounts(snapshot.account["equity"]), "ownership_event_id": None, "max_entry_notional_usd": None,
        "total_entry_test_notional_usd": None, "expires_at": None, "enforcement_status": "NOT_INSTALLED", "identity_authenticated": False,
        "activation_enabled": False, "capital_transfers_enabled": False, "automated_reallocation_enabled": False,
        "authority": {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}})


def build_paper_test_budget(snapshot_event, *, budget_id, recorded_at, declared_by):
    with localcontext(Context(prec=256)):
        return _build(snapshot_event, budget_id=budget_id, recorded_at=recorded_at, declared_by=declared_by)


def validate_budget_source(budget, events):
    event = next((event for event in events if event.event_id == budget.basis["snapshot_event_id"]), None)
    if event is None:
        raise ValueError("test budget source event is missing")
    rebuilt = build_paper_test_budget(event, budget_id=budget.budget_id, recorded_at=budget.recorded_at, declared_by=budget.declared_by)
    if rebuilt.to_bytes() != budget.to_bytes():
        raise ValueError("test budget differs from retained paper equity source")


def budget_filename(budget):
    identity = {"budget_id": budget.budget_id, "account_id": budget.account_id, "mode": budget.mode}
    return "paper-test-budget-" + sha256_bytes(canonical_json_bytes(identity)) + ".json"
