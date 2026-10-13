"""Source-backed FIFO and fees from synthetic PAPER executions; no live activity."""
from __future__ import annotations
import copy
from decimal import Decimal, Inexact, Rounded, localcontext
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_accounting as engine
from blackpod_build_week import trading_reconciliation as reconciliation
from blackpod_build_week.contracts.trading_accounting import TradingAccountingInput, validate_accounting_result
from blackpod_build_week.contracts.trading_reconciliation import TradingReconciliationInput
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_activity_import import activities_input_from_export
from test_trading_reconciliation_engine import ReconciliationFixture, broker_order, runtime_event, AUTHORITY

def checked_report(document, events=(), blobs=None):
    report = engine.assess_accounting(document, events, blobs)
    validate_accounting_result(report, document)
    return report

BASE = "2026-10-15T00:00:00Z"
OWNER = "2026-10-15T00:00:01Z"
BUY1 = "2026-10-15T00:01:00Z"
BUY2 = "2026-10-15T00:02:00Z"
SELL = "2026-10-15T00:03:00Z"
END = "2026-10-15T00:04:00Z"
RECORDED = "2026-10-15T00:05:00Z"


def raw_fill(identity, order_id, qty, price, occurred_at, side="buy", symbol="MSFT"):
    return {"activity_type": "FILL", "id": identity, "order_id": order_id, "symbol": symbol,
            "side": side, "qty": qty, "price": price, "transaction_time": occurred_at}


def raw_fee(identity, order_id, amount, fill_id=None, occurred_at=SELL):
    # net_amount is a signed account cash flow: negative = fee charge.
    return {"activity_type": "FEE", "id": identity, "order_id": order_id,
            "fill_activity_id": fill_id, "net_amount": format(Decimal(amount).copy_negate(), "f"), "date": occurred_at}


class AccountingFixture:
    """Reusable complete exact execution proof for engine/store/CLI tests."""
    def __init__(self, *, raw_rows=None, fees_complete=True, fills_complete=True,
                 orders=None, end_positions=None, runtime=True, ownership_at=OWNER,
                 start_positions=None, start_orders=None, start_completeness=None, end_completeness=None):
        self.native = ReconciliationFixture()
        self.native.events, self.native.blobs = [], {}
        self.events, self.blobs = self.native.events, self.native.blobs
        self.profile = self.native.profile
        self.start_snapshot = self.native.snapshot_for(snapshot_id="accounting-start", captured_at=BASE,
            capture_window={"started_at": BASE, "completed_at": BASE}, positions=start_positions or [], orders=start_orders or [],
            completeness=start_completeness or {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": True})
        self.start_event = reconciliation.build_snapshot_event(self.start_snapshot, self.events, self.blobs)
        self.add(self.start_event, reconciliation.evidence_for_snapshot(self.start_snapshot, self.events, self.blobs))
        self.ownership = self.native.ownership_for(ownership_id="accounting-owner", recorded_at=ownership_at)
        self.ownership_event = reconciliation.build_ownership_event(self.ownership, self.events, self.blobs)
        self.add(self.ownership_event, reconciliation.evidence_for_ownership(self.ownership, self.events, self.blobs))
        self.orders = orders if orders is not None else [
            broker_order("buy-1", client_order_id="client-buy-1", qty="2", filled_qty="2", filled_avg_price="10", submitted_at=BUY1, updated_at=BUY1, filled_at=BUY1),
            broker_order("buy-2", client_order_id="client-buy-2", qty="3", filled_qty="3", filled_avg_price="12", submitted_at=BUY2, updated_at=BUY2, filled_at=BUY2),
            broker_order("sell-1", client_order_id="client-sell-1", side="sell", qty="4", filled_qty="4", filled_avg_price="15", submitted_at=SELL, updated_at=SELL, filled_at=SELL)]
        self.end_positions = end_positions if end_positions is not None else [
            {"symbol": "MSFT", "qty": "1", "side": "long", "market_value": "15", "avg_entry_price": "12", "current_price": "15"}]
        profile_sha = sha256_bytes(canonical_json_bytes(self.profile))
        control = {"action_id": "accounting-enable-fixture", "session_id": "accounting-session", "profile_sha256": profile_sha,
                   "entries_enabled": True, "recorded_at": OWNER, "operator_id": "fixture-operator"}
        events = [runtime_event([], "CONTROL", control)] if runtime else []
        prior = Decimal("0")
        for index, order in enumerate(self.orders):
            if not runtime:
                break
            receipt = {"schema_version": "blackpod.trading_execution_receipt.v2", "account_id": "fixture-account",
                "attempt_id": "accounting-attempt-" + str(index), "prior_qty": str(prior), "client_order_id": order["client_order_id"],
                "session_id": "accounting-session", "mode": "PAPER", "recorded_at": order["submitted_at"],
                "profile_id": self.profile["profile_id"], "domain": "TRADING", "account_mode": "PAPER",
                "symbol": order["symbol"], "side": order["side"], "qty": order["qty"], "outcome": "ATTEMPT", "reason_code": "FIXTURE",
                "order_id": None, "capital_authorization_id": self.profile["capital_authorization_id"]}
            events.append(runtime_event(events, "BROKER_GUARD", receipt))
            events.append(runtime_event(events, "BROKER_GUARD", {**receipt, "outcome": "SUBMITTED", "order_id": order["id"]}))
            prior += Decimal(order["filled_qty"]) * (1 if order["side"] == "buy" else -1)
        self.capture = {"schema_version": "blackpod.runtime_export.v1", "events": events,
                        "profiles": {profile_sha: self.profile} if runtime else {}}
        self.native.capture = self.capture
        self.end_snapshot = self.native.snapshot_for(snapshot_id="accounting-end", captured_at=END,
            capture_window={"started_at": END, "completed_at": END}, positions=self.end_positions, orders=self.orders,
            completeness=end_completeness or {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": True})
        self.end_snapshot_event = reconciliation.build_snapshot_event(self.end_snapshot, self.events, self.blobs)
        self.add(self.end_snapshot_event, reconciliation.evidence_for_snapshot(self.end_snapshot, self.events, self.blobs))
        self.reconciliation = self.native.reconciliation_for(reconciliation_id="accounting-end-reconciliation", recorded_at=RECORDED)
        self.reconciliation_event = reconciliation.build_reconciliation_event(self.reconciliation, self.events, self.blobs)
        self.add(self.reconciliation_event, reconciliation.evidence_for_reconciliation(self.reconciliation, self.events, self.blobs))
        self.rows = raw_rows if raw_rows is not None else [
            raw_fill("fill-buy-1", "buy-1", "2", "10", BUY1), raw_fill("fill-buy-2", "buy-2", "3", "12", BUY2),
            raw_fill("fill-sell-1", "sell-1", "4", "15", SELL, "sell"),
            raw_fee("fee-buy-1", "buy-1", "0.02", "fill-buy-1", BUY1),
            raw_fee("fee-buy-2", "buy-2", "0.03", "fill-buy-2", BUY2), raw_fee("fee-sell-1", "sell-1", "0.04", "fill-sell-1")]
        self.set_activities(self.rows, fees_complete=fees_complete, fills_complete=fills_complete)
        self.accounting = self.accounting_for()

    def close(self): self.native.close()

    def add(self, event, evidence):
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})

    def set_activities(self, rows, *, fees_complete=True, fills_complete=True, activity_set_id="accounting-activities", scope=None,
                       started_at=BASE, ended_at=END, recorded_at=RECORDED):
        self.rows = copy.deepcopy(rows)
        self.rawsource = canonical_json_bytes({"schema_version": "blackpod.paper_activity_export.v1", "recorded_at": recorded_at,
            "account_id": "fixture-account", "mode": "PAPER", "currency": "USD", "window": {"started_at": started_at, "ended_at": ended_at},
            "coverage": {"fills_complete": fills_complete, "fees_complete": fees_complete,
                         "scope_order_ids": scope if scope is not None else [order["id"] for order in self.orders]},
            "source_kind": "SYNTHETIC_FIXTURE", "activities": self.rows})
        self.activities = activities_input_from_export(self.rawsource, activity_set_id=activity_set_id, evidence_path="broker/activity-source.json")
        self.blobs[sha256_bytes(self.rawsource)] = self.rawsource
        self.blobs[sha256_bytes(self.activities.to_bytes())] = self.activities.to_bytes()
        return self.activities

    def accounting_for(self, **changes):
        value = {"schema_version": "blackpod.trading_fill_lot_accounting.v1", "accounting_id": "accounting-1", "recorded_at": RECORDED,
            "mode": "PAPER", "account_id": "fixture-account", "start_snapshot_event_id": self.start_event.event_id,
            "start_snapshot_sha256": self.start_event.source["source_sha256"], "end_reconciliation_event_id": self.reconciliation_event.event_id,
            "end_reconciliation_sha256": self.reconciliation_event.source["source_sha256"], "ownership_event_id": self.ownership_event.event_id,
            "ownership_sha256": self.ownership_event.source["source_sha256"],
            "activities_evidence": {"path": "trading/activities.json", "sha256": sha256_bytes(self.activities.to_bytes()), "size_bytes": len(self.activities.to_bytes())},
            "prior_accounting_event_id": None, "accounting_method": "FIFO_LONG_ONLY", "scope": "PAPER_FILL_LOT_ACCOUNTING_ONLY", "authority": AUTHORITY}
        value.update(changes)
        return TradingAccountingInput.from_mapping(value)

    def record(self, document=None):
        document = document or self.accounting
        event = engine.build_accounting_event(document, self.events, self.blobs)
        self.add(event, engine.evidence_for_accounting(document, self.events, self.blobs))
        return event


    def replace_capture(self, capture):
        """Rebuild the fixture's ending proof after an exact receipt alteration."""
        if self.events[-1].event_type != reconciliation.RECONCILIATION_EVENT_TYPE:
            raise AssertionError("replace_capture requires the original reconciliation suffix")
        self.events.pop()
        self.capture = copy.deepcopy(capture)
        self.native.capture = self.capture
        self.reconciliation = self.native.reconciliation_for(reconciliation_id="updated-accounting-reconciliation", recorded_at=RECORDED)
        self.reconciliation_event = reconciliation.build_reconciliation_event(self.reconciliation, self.events, self.blobs)
        self.add(self.reconciliation_event, reconciliation.evidence_for_reconciliation(self.reconciliation, self.events, self.blobs))
        self.accounting = self.accounting_for()


class TradingAccountingEngineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.f = AccountingFixture()
        self.addCleanup(self.f.close)

    def report(self, document=None):
        return checked_report(document or self.f.accounting, self.f.events, self.f.blobs)

    def test_fifo_partial_close_has_exact_source_cost_basis_and_fees(self):
        report = self.report()
        self.assertEqual(report["status"], "RECONCILED")
        self.assertEqual([row["qty"] for row in report["closed_lots"]], ["2", "2"])
        self.assertEqual([row["buy_price"] for row in report["closed_lots"]], ["10", "12"])
        self.assertEqual(report["totals"]["gross_realized_pnl"], "16")
        self.assertEqual(report["realized_trade_pnl"], "15.92")
        self.assertEqual(report["open_lots"][0]["remaining_qty"], "1")
        self.assertEqual(report["open_lots"][0]["allocated_entry_fees"], "0.01")
        self.assertTrue(all(row["matches"] for row in report["positions"] + report["order_checks"]))
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_builder_replays_original_evidence_exactly(self):
        event = engine.build_accounting_event(self.f.accounting, self.f.events, self.f.blobs)
        evidence = engine.evidence_for_accounting(self.f.accounting, self.f.events, self.f.blobs)
        blobs = {**self.f.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}}
        engine.validate_accounting_event(event, self.f.events, blobs)
        self.assertEqual(set(evidence), {"trading/accounting.json", "trading/activities.json", "broker/activity-source.json"})

    def test_unknown_fees_are_not_zero(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"], fees_complete=False)
        report = self.report(self.f.accounting_for())
        self.assertEqual(report["status"], "GROSS_RECONCILED_FEES_PENDING")
        self.assertEqual(report["totals"]["gross_realized_pnl"], "16")
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertTrue(all(row["fee_amount"] is None for row in report["matched_fills"]))

    def test_account_fee_without_exact_link_is_retained_unallocated(self):
        self.f.set_activities(self.f.rows + [raw_fee("account-fee", None, "1")])
        report = self.report(self.f.accounting_for())
        self.assertEqual(report["status"], "GROSS_RECONCILED_FEES_PENDING")
        self.assertEqual(report["unmatched_fees"][0]["activity_id"], "account-fee")
        self.assertIsNone(report["realized_trade_pnl"])

    def test_realized_pnl_requires_individual_fills_not_snapshot_averages(self):
        self.f.set_activities([], fees_complete=True)
        report = self.report(self.f.accounting_for())
        self.assertEqual(report["status"], "PENDING")
        self.assertEqual(report["matched_fills"], [])
        self.assertIsNone(report["totals"]["gross_realized_pnl"])
        self.assertIsNone(report["realized_trade_pnl"])

    def test_incomplete_fill_coverage_withholds_all_pnl(self):
        self.f.set_activities(self.f.rows, fills_complete=False)
        report = self.report(self.f.accounting_for())
        self.assertEqual(report["status"], "PENDING")
        self.assertIsNone(report["totals"]["gross_realized_pnl"])
        self.assertTrue(all(row["gross_pnl"] is None and row["net_pnl"] is None for row in report["closed_lots"]))

    def test_missing_fill_identity_is_not_guessed_from_same_symbol_time(self):
        rows = copy.deepcopy(self.f.rows)
        rows[0]["order_id"] = "unknown-order"
        rows[3]["order_id"] = "unknown-order"
        self.f.set_activities(rows, scope=["buy-1", "buy-2", "sell-1", "unknown-order"])
        report = self.report(self.f.accounting_for())
        self.assertEqual(report["status"], "PENDING")
        self.assertIn("EXACT_BROKER_ORDER_NOT_OBSERVED", report["reason_codes"])

    def test_missing_source_or_changed_bytes_reject(self):
        reference = self.f.activities.provenance["source_evidence"]
        self.f.blobs.pop(reference["sha256"])
        with self.assertRaises(engine.TradingAccountingError): self.report()

    def test_account_and_hash_mismatch_reject(self):
        for change in ({"account_id": "other"}, {"start_snapshot_sha256": "a" * 64}, {"ownership_sha256": "b" * 64}):
            with self.subTest(change=change), self.assertRaises(engine.TradingAccountingError):
                self.report(self.f.accounting_for(**change))

    def test_late_fee_appends_and_never_mutates_original(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"], fees_complete=False)
        original_doc = self.f.accounting_for()
        original = self.f.record(original_doc)
        original_bytes = original.to_bytes()
        self.f.set_activities(self.f.rows + [raw_fee("late-fee", "sell-1", "0.5", "fill-sell-1")], activity_set_id="accounting-late-activities")
        update = self.f.accounting_for(accounting_id="accounting-late", prior_accounting_event_id=original.event_id)
        result = self.report(update)
        self.assertEqual(result["realized_trade_pnl"], "15.5")
        self.assertEqual(original.to_bytes(), original_bytes)
        self.assertEqual(engine.build_accounting_event(original_doc, self.f.events, self.f.blobs).to_bytes(), original_bytes)

    def test_prior_fill_cannot_be_rewritten_or_removed(self):
        original = self.f.record()
        for rows in (self.f.rows[1:], [{**self.f.rows[0], "price": "11"}, *self.f.rows[1:]]):
            self.f.set_activities(rows, activity_set_id="changed-activities")
            with self.assertRaises(engine.TradingAccountingError):
                self.report(self.f.accounting_for(accounting_id="changed", prior_accounting_event_id=original.event_id))

    def test_append_cannot_branch_or_omit_prior(self):
        self.f.record()
        with self.assertRaises(engine.TradingAccountingError):
            self.report(self.f.accounting_for(accounting_id="new"))

    def test_fee_rounding_conserves_source_charge_and_remaining_basis(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"] + [raw_fee("thirds", "buy-2", "1", "fill-buy-2")])
        result = self.report(self.f.accounting_for())
        closed = sum(Decimal(row["allocated_entry_fees"]) for row in result["closed_lots"])
        remaining = sum(Decimal(row["allocated_entry_fees"]) for row in result["open_lots"])
        self.assertEqual(closed + remaining, Decimal("1"))
        self.assertEqual(result["open_lots"][0]["allocated_entry_fees"], "0.333333333333333333")

    def test_ambient_decimal_context_cannot_change_report(self):
        expected = canonical_json_bytes(self.report())
        with localcontext() as context:
            context.prec = 2
            actual = canonical_json_bytes(self.report())
        self.assertEqual(actual, expected)

    def test_fee_rebate_increases_net_without_changing_gross(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"] + [raw_fee("rebate", "sell-1", "-0.25", "fill-sell-1")])
        result = self.report(self.f.accounting_for())
        self.assertEqual(result["realized_trade_pnl"], "16.25")
        self.assertEqual(result["totals"]["gross_realized_pnl"], "16")

    def test_no_execution_has_no_realized_pnl_even_declared_zero_fees(self):
        f = AccountingFixture(raw_rows=[], orders=[], end_positions=[], runtime=False)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "NO_EXECUTION_OBSERVED")
        self.assertFalse(result["execution_observed"])
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertIsNone(result["totals"]["gross_realized_pnl"])

    def test_broker_execution_without_runtime_authority_is_unattributed(self):
        f = AccountingFixture(runtime=False)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(result["matched_fills"], [])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_ownership_after_attempt_before_fill_is_still_unclassified(self):
        rows = copy.deepcopy(self.f.rows)
        rows[0]["transaction_time"] = "2026-10-15T00:01:02Z"
        rows[3]["date"] = "2026-10-15T00:01:02Z"
        f = AccountingFixture(raw_rows=rows, ownership_at="2026-10-15T00:01:01Z")
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertIn("EXECUTION_PREDATES_TRADING_OWNERSHIP_OR_IS_UNCLASSIFIED", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_different_price_timestamp_ties_do_not_invent_fifo_order(self):
        orders = copy.deepcopy(self.f.orders)
        for field in ("submitted_at", "updated_at", "filled_at"): orders[1][field] = BUY1
        rows = copy.deepcopy(self.f.rows)
        rows[1]["transaction_time"] = BUY1
        rows[4]["date"] = BUY1
        f = AccountingFixture(raw_rows=rows, orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("AMBIGUOUS_EXECUTION_ORDER", result["reason_codes"])
        self.assertIsNone(result["totals"]["gross_realized_pnl"])

    def test_snapshot_price_is_not_cost_basis(self):
        orders = copy.deepcopy(self.f.orders)
        orders[0]["filled_avg_price"] = "9999"
        f = AccountingFixture(orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["closed_lots"][0]["buy_price"], "10")
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("INDIVIDUAL_FILL_VALUE_DIFFERS_FROM_BROKER_AVERAGE", result["reason_codes"])
        self.assertIsNone(result["totals"]["gross_realized_pnl"])


    def test_missing_average_price_is_explicit_price_proof_gap(self):
        orders = copy.deepcopy(self.f.orders)
        orders[0]["filled_avg_price"] = None
        f = AccountingFixture(orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("BROKER_AVERAGE_PRICE_MISSING", result["reason_codes"])
        self.assertIsNone(result["order_checks"][0]["broker_gross_value"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_individual_price_conflicting_with_average_withholds_profit(self):
        rows = copy.deepcopy(self.f.rows)
        rows[0]["price"] = "999"
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("INDIVIDUAL_FILL_VALUE_DIFFERS_FROM_BROKER_AVERAGE", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_multiple_individual_prices_are_checked_by_weighted_gross(self):
        rows = [raw_fill("fill-buy-1a", "buy-1", "1", "8", BUY1),
                raw_fill("fill-buy-1b", "buy-1", "1", "12", "2026-10-15T00:01:01Z"),
                *[row for row in self.f.rows if row.get("id") not in {"fill-buy-1", "fee-buy-1"}],
                raw_fee("fee-buy-1", "buy-1", "0.02", occurred_at="2026-10-15T00:01:02Z")]
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertEqual(result["status"], "RECONCILED")
        check = next(row for row in result["order_checks"] if row["order_id"] == "buy-1")
        self.assertEqual(check["activity_gross_value"], "20")
        self.assertEqual(check["broker_gross_value"], "20")
        self.assertTrue(check["price_matches"])
        self.assertEqual([row["buy_price"] for row in result["closed_lots"][:2]], ["8", "12"])
        self.assertEqual(result["realized_trade_pnl"], "15.92")

    def test_distinct_duplicate_fill_id_cannot_double_count_cumulative_quantity(self):
        rows = self.f.rows + [{**self.f.rows[0], "id": "different-id-same-fill"}]
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("INDIVIDUAL_FILLS_DO_NOT_MATCH_CUMULATIVE_ORDER_QUANTITY", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_identical_duplicate_source_activity_is_idempotent(self):
        expected = self.report()
        self.f.set_activities(self.f.rows + [copy.deepcopy(self.f.rows[0])])
        result = self.report(self.f.accounting_for())
        self.assertEqual(len(result["matched_fills"]), 3)
        self.assertEqual(result["totals"], expected["totals"])

    def test_nonflat_start_does_not_infer_lots_from_average_entry(self):
        f = AccountingFixture(start_positions=[{"symbol": "MSFT", "qty": "1", "side": "long", "market_value": "10",
            "avg_entry_price": "10", "current_price": "10"}])
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("STARTING_TRADING_BOOK_NOT_FLAT", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_existing_investment_holdings_do_not_invent_trading_lots(self):
        f = AccountingFixture(start_positions=[{"symbol": "AAPL", "qty": "1", "side": "long", "market_value": "10",
            "avg_entry_price": "10", "current_price": "10"}],
            end_positions=self.f.end_positions + [{"symbol": "AAPL", "qty": "1", "side": "long", "market_value": "10",
            "avg_entry_price": "10", "current_price": "10"}])
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "RECONCILED")
        self.assertEqual([row["symbol"] for row in result["positions"]], ["MSFT"])
        self.assertEqual(result["realized_trade_pnl"], "15.92")

    def test_incomplete_flat_source_is_not_verified_baseline(self):
        f = AccountingFixture(start_completeness={"positions_complete": False, "open_orders_complete": True, "tracked_orders_complete": True})
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertIn("STARTING_BOOK_INCOMPLETE", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_incomplete_ending_positions_do_not_assume_missing_symbol_is_flat(self):
        f = AccountingFixture(end_positions=[], end_completeness={"positions_complete": False, "open_orders_complete": True, "tracked_orders_complete": True})
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["positions"][0]["observed_qty"], None)
        self.assertIn("ENDING_POSITIONS_INCOMPLETE", result["reason_codes"])
        self.assertIsNone(result["totals"]["gross_realized_pnl"])

    def test_ending_quantity_mismatch_is_explicit(self):
        f = AccountingFixture(end_positions=[])
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertIn("SOURCE_BACKED_LOTS_DO_NOT_MATCH_ENDING_POSITION", result["reason_codes"])
        self.assertEqual(result["positions"][0]["expected_qty"], "1")
        self.assertEqual(result["positions"][0]["observed_qty"], "0")
        self.assertIsNone(result["realized_trade_pnl"])

    def test_replacement_lineage_is_conservatively_pending(self):
        orders = copy.deepcopy(self.f.orders)
        orders[0].update(status="replaced", replaced_by="buy-2", replaced_at=BUY2)
        orders[1]["replaces"] = "buy-1"
        f = AccountingFixture(orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertIn("REPLACEMENT_OR_LEG_ATTRIBUTION_UNSUPPORTED", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_partial_fill_cancellation_uses_individual_fills_only(self):
        orders = copy.deepcopy(self.f.orders)
        orders[0].update(status="canceled", qty="3", canceled_at=BUY1)
        f = AccountingFixture(orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertEqual(result["status"], "RECONCILED")
        self.assertEqual(result["matched_fills"][0]["qty"], "2")
        self.assertEqual(result["realized_trade_pnl"], "15.92")

    def test_tiny_charge_allocation_preserves_total_and_never_invents_rebate(self):
        with localcontext() as context:
            context.prec = 256
            amounts = engine._split(Decimal("0.000000000000000002"), [Decimal(".26"), Decimal(".26"), Decimal(".26"), Decimal(".22")])
        self.assertEqual(sum(amounts), Decimal("0.000000000000000002"))
        self.assertTrue(all(amount >= 0 for amount in amounts))

    def test_tiny_rebate_allocation_preserves_total_and_never_invents_charge(self):
        with localcontext() as context:
            context.prec = 256
            amounts = engine._split(Decimal("-0.000000000000000002"), [Decimal(".26"), Decimal(".26"), Decimal(".26"), Decimal(".22")])
        self.assertEqual(sum(amounts), Decimal("-0.000000000000000002"))
        self.assertTrue(all(amount <= 0 for amount in amounts))

    def test_prior_raw_activity_metadata_cannot_be_rewritten(self):
        original = self.f.record()
        rows = copy.deepcopy(self.f.rows)
        rows[0]["description"] = "changed original activity"
        self.f.set_activities(rows, activity_set_id="changed-source-metadata")
        with self.assertRaises(engine.TradingAccountingError):
            self.report(self.f.accounting_for(accounting_id="changed-metadata", prior_accounting_event_id=original.event_id))

    def test_evidence_path_collision_is_rejected(self):
        self.f.set_activities(self.f.rows)
        input_dict = self.f.activities.to_dict()
        input_dict["provenance"]["source_evidence"]["path"] = "trading/activities.json"
        from blackpod_build_week.contracts.trading_accounting import PaperActivitiesInput
        self.f.activities = PaperActivitiesInput.from_mapping(input_dict)
        self.f.blobs[sha256_bytes(self.f.activities.to_bytes())] = self.f.activities.to_bytes()
        with self.assertRaises(engine.TradingAccountingError): self.report(self.f.accounting_for())

    def test_changed_accounting_id_input_conflicts_on_retry(self):
        self.f.record()
        with self.assertRaises(engine.TradingAccountingError):
            self.report(self.f.accounting_for(recorded_at="2026-10-15T00:06:00Z"))

    def test_report_precision_policy_is_detached_from_future_calculation(self):
        report = self.report()
        report["precision_policy"]["calculation_precision"] = 2
        self.assertEqual(self.report()["precision_policy"]["calculation_precision"], 256)


    def test_every_receipt_prior_position_must_agree_with_flat_source_history(self):
        capture = copy.deepcopy(self.f.capture)
        rebuilt = []
        for index, event in enumerate(capture["events"]):
            payload = copy.deepcopy(event["payload"])
            if index in {1, 2}: payload["prior_qty"] = "100"
            rebuilt.append(runtime_event(rebuilt, event["kind"], payload))
        capture["events"] = rebuilt
        self.f.replace_capture(capture)
        result = self.report()
        self.assertEqual(result["status"], "PENDING")
        self.assertIn("EXECUTION_RECEIPT_PRIOR_POSITION_DIFFERS_FROM_SOURCE_FILLS", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_legacy_receipt_without_prior_position_cannot_prove_fifo_history(self):
        capture = copy.deepcopy(self.f.capture)
        rebuilt = []
        for event in capture["events"]:
            payload = copy.deepcopy(event["payload"])
            if event["kind"] == "BROKER_GUARD":
                for field in ("schema_version", "account_id", "attempt_id", "prior_qty", "client_order_id"):
                    payload.pop(field)
            rebuilt.append(runtime_event(rebuilt, event["kind"], payload))
        capture["events"] = rebuilt
        self.f.replace_capture(capture)
        result = self.report()
        self.assertIn("EXECUTION_RECEIPT_PRIOR_POSITION_UNAVAILABLE", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_an_activity_set_identity_cannot_be_reused_with_changed_bytes(self):
        original = self.f.record()
        self.f.set_activities(self.f.rows + [raw_fee("late-new-fee", "sell-1", "0.01", "fill-sell-1")])
        with self.assertRaises(engine.TradingAccountingError):
            self.report(self.f.accounting_for(accounting_id="same-activity-id", prior_accounting_event_id=original.event_id))

    def test_same_time_other_order_fill_does_not_prove_prior_position(self):
        rows = copy.deepcopy(self.f.rows)
        rows[0]["transaction_time"] = BUY2
        rows[3]["date"] = BUY2
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertIn("AMBIGUOUS_PRIOR_POSITION_AT_ATTEMPT", result["reason_codes"])
        self.assertIsNone(result["totals"]["gross_realized_pnl"])


    def test_unsupported_broker_numeric_precision_is_journalable_pending(self):
        orders = copy.deepcopy(self.f.orders)
        orders[0]["filled_avg_price"] = "1e-100"
        f = AccountingFixture(orders=orders)
        self.addCleanup(f.close)
        result = checked_report(f.accounting, f.events, f.blobs)
        self.assertIn("UNSUPPORTED_BROKER_NUMERIC_PRECISION", result["reason_codes"])
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertIsNone(result["order_checks"][0]["broker_gross_value"])
        engine.build_accounting_event(f.accounting, f.events, f.blobs)


    def test_missing_buy_fill_cannot_create_short_fifo_position(self):
        rows = [row for row in self.f.rows if row["id"] not in {"fill-buy-1", "fee-buy-1"}]
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertIn("LONG_ONLY_SELL_EXCEEDS_SOURCE_BACKED_LOTS", result["reason_codes"])
        self.assertEqual(result["closed_lots"], [])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_tiny_order_fee_allocates_across_real_source_fills_without_negative_residual(self):
        rows = [raw_fill("tiny-buy-1", "buy-1", "0.52", "10", BUY1),
                raw_fill("tiny-buy-2", "buy-1", "0.52", "10", "2026-10-15T00:01:01Z"),
                raw_fill("tiny-buy-3", "buy-1", "0.52", "10", "2026-10-15T00:01:02Z"),
                raw_fill("tiny-buy-4", "buy-1", "0.44", "10", "2026-10-15T00:01:03Z"),
                *[row for row in self.f.rows if row["id"] not in {"fill-buy-1", "fee-buy-1", "fee-buy-2", "fee-sell-1"}],
                raw_fee("tiny-fee", "buy-1", "0.000000000000000002", occurred_at="2026-10-15T00:01:04Z")]
        self.f.set_activities(rows)
        result = self.report(self.f.accounting_for())
        self.assertEqual(result["status"], "RECONCILED")
        allocations = [Decimal(row["fee_amount"]) for row in result["matched_fills"] if row["order_id"] == "buy-1"]
        self.assertEqual(sum(allocations), Decimal("0.000000000000000002"))
        self.assertTrue(all(amount >= 0 for amount in allocations))
        self.assertEqual(result["realized_trade_pnl"], "15.999999999999999998")

    def test_ambient_decimal_traps_and_exponent_limits_cannot_change_accounting(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"] + [raw_fee("thirds-trap", "buy-2", "1", "fill-buy-2")])
        document = self.f.accounting_for()
        expected = canonical_json_bytes(self.report(document))
        with localcontext() as context:
            context.prec = 2
            context.Emax = 1
            context.Emin = -1
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            actual = canonical_json_bytes(self.report(document))
            engine.evidence_for_accounting(document, self.f.events, self.f.blobs)
        self.assertEqual(actual, expected)


if __name__ == "__main__": unittest.main()
