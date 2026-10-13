"""Mock-only broker/runtime guard coverage; no native imports or broker calls."""
from __future__ import annotations

import asyncio
import copy
import os
import threading
import sys
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.galactica_trading_adapter import (
    GuardedTradingBroker, TradingAdapterError, run_guarded_navigator, validate_runtime_environment,
    NATIVE_SOURCE_FILES, NATIVE_RUNTIME_DEPENDENCIES, validate_runtime_dependencies,
)
from blackpod_build_week import galactica_trading_adapter as adapter_module

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def profile():
    return {"profile_id": "paper-owned-account", "mode": "PAPER", "symbols": ["AAA", "BBB"], "protected_symbols": ["INV"],
            "account_scope": "SHARED_DISJOINT", "account_id": "account-001", "capital_authorization_id": "capital-explicit-001",
            "trading_budget_usd": "5000", "max_account_gross_usd": "8000", "max_order_notional_usd": "1000",
            "price_max_age_seconds": 120, "price_buffer_fraction": ".05", "authorization_expires_at": "2026-10-12T00:00:00Z",
            "galactica_root": "/private/tmp", "frozen_inputs": {"bias_csv": {"path": "/private/tmp/bias.csv"},
                                                                  "mandate_path": {"path": "/private/tmp/mandate.json"}}, "native_settings": {}}


def position(symbol="AAA", qty="10", value="1000", price="100"):
    return SimpleNamespace(symbol=symbol, qty=qty, market_value=value, current_price=price, avg_entry_price="90", unrealized_plpc=".11")


def order(identity="pending-001", symbol="AAA", status="new"):
    return SimpleNamespace(id=identity, symbol=symbol, status=status, legs=None, filled_qty="0")


class Client:
    def __init__(self):
        self.account = SimpleNamespace(id="account-001", status="ACTIVE", trading_blocked=False, equity="10000", cash="9000")
        self.held = [position()]
        self.pending = []
        self.orders = {}
        self.fail = None
    def get_account(self):
        if self.fail == "account": raise RuntimeError("network")
        return self.account
    def get_all_positions(self):
        if self.fail == "positions": raise RuntimeError("network")
        return self.held
    def get_orders(self):
        if self.fail == "orders": raise RuntimeError("network")
        return self.pending
    def get_order_by_id(self, identity):
        return self.orders[identity]


class NativeBroker:
    def __init__(self):
        self.dry_run = False
        self.client = Client()
        self.submissions, self.closes = [], []
        self.result = None
        self.account_equity_calls = 0
        self.flatten_calls = 0
    def submit_market(self, symbol, side, qty, tif="day", *, reason="-"):
        self.submissions.append((symbol, side, qty))
        if self.result is not None: return self.result
        identity = "mock-order-" + str(len(self.submissions))
        self.client.orders[identity] = order(identity, symbol)
        return {"ok": True, "order_id": identity}
    def close_position(self, symbol, *, reason="-"):
        self.closes.append(symbol)
        identity = "mock-close-" + str(len(self.closes))
        self.client.orders[identity] = order(identity, symbol)
        return {"ok": True, "order_id": identity}
    def flatten_all(self):
        self.flatten_calls += 1
        raise AssertionError("account-wide flatten forbidden")
    def account_equity(self):
        self.account_equity_calls += 1
        return 10000
    def order_info(self, identity): return {"order_id": identity}
    def minutes_to_close(self): return 15


class GalacticaTradingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeBroker()
        self.state = {"entries_enabled": True}
        self.receipts = []
        self.guard = GuardedTradingBroker(self.native, profile(), lambda: self.state, self.receipts.append,
                                         now=lambda: NOW, mandate_checker=lambda *_: SimpleNamespace(ok=True, mandate_ok=True))
        self.guard.observe_bar("AAA", 100, NOW)
        self.guard.observe_bar("BBB", 100, NOW)

    def runtime_profile(self):
        from test_auto_trading_runtime import RuntimeFixture
        fixture = RuntimeFixture()
        self.addCleanup(fixture.close)
        p = fixture.profile
        p.update(mode="PAPER", symbols=["AAA", "BBB"], protected_symbols=["INV"], account_id="account-001",
                 trading_budget_usd="5000", max_account_gross_usd="8000", max_order_notional_usd="1000",
                 price_buffer_fraction="0.05", authorization_expires_at="2099-10-12T00:00:00Z")
        p["native_settings"]["per_trade_usd_cap"] = 500
        return fixture, p

    def test_owned_buy_reaches_native_with_receipt_and_fixed_budget(self):
        result = self.guard.submit_market("AAA", "buy", 5)
        self.assertTrue(result["ok"])
        self.assertEqual(self.native.submissions, [("AAA", "buy", 5)])
        self.assertEqual([r["outcome"] for r in self.receipts], ["ATTEMPT", "SUBMITTED"])
        self.assertEqual(self.guard.account_equity(), 10000)
        self.assertEqual(self.native.account_equity_calls, 0)

    def test_off_blocks_increases_and_allows_long_reduction(self):
        self.state["entries_enabled"] = False
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertTrue(self.guard.submit_market("AAA", "sell", 5)["ok"])
        self.assertEqual(self.native.submissions, [("AAA", "sell", 5)])

    def test_off_allows_short_cover_but_not_reverse_excess(self):
        self.state["entries_enabled"] = False
        self.native.client.held = [position(qty="-10", value="-1000")]
        self.assertFalse(self.guard.submit_market("AAA", "buy", 11)["ok"])
        self.assertTrue(self.guard.submit_market("AAA", "buy", 10)["ok"])

    def test_reductions_revalidate_account_identity_and_read_switch(self):
        reads = []
        self.guard._switch_reader = lambda: reads.append(True) or {"entries_enabled": False}
        self.native.client.account.id = "wrong-account"
        self.assertFalse(self.guard.submit_market("AAA", "sell", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.assertEqual(len(reads), 2)
        self.assertEqual(self.native.submissions, [])
        self.assertEqual(self.native.closes, [])

    def test_no_naked_shorts_or_oversells(self):
        for symbol, qty in (("BBB", 1), ("AAA", 11)):
            self.assertFalse(self.guard.submit_market(symbol, "sell", qty)["ok"])
        self.assertEqual(self.native.submissions, [])

    def test_protected_symbols_hidden_and_unmodifiable(self):
        self.native.client.held.append(position("INV", "20", "2000"))
        self.assertEqual(self.guard.positions(), {"AAA": 10})
        with self.assertRaises(TradingAdapterError): self.guard.position_info("INV")
        self.assertFalse(self.guard.close_position("INV")["ok"])
        self.assertFalse(self.guard.submit_market("INV", "sell", 1)["ok"])
        self.assertEqual(self.native.closes, [])

    def test_flatten_only_owned_symbols_without_accountwide_cancel(self):
        self.state["entries_enabled"] = False
        self.native.client.held.extend([position("BBB", "5", "500"), position("INV", "20", "2000")])
        result = self.guard.flatten_all()
        self.assertEqual(set(result), {"AAA", "BBB"})
        self.assertEqual(self.native.closes, ["AAA", "BBB"])
        self.assertEqual(self.native.flatten_calls, 0)

    def test_account_id_status_and_malformed_values_fail_closed(self):
        for field, bad in (("id", "wrong"), ("status", "CLOSED"), ("trading_blocked", None), ("equity", "NaN"), ("cash", "-1")):
            old = getattr(self.native.client.account, field)
            setattr(self.native.client.account, field, bad)
            with self.subTest(field=field): self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
            setattr(self.native.client.account, field, old)
        self.assertEqual(self.native.submissions, [])

    def test_pending_any_desk_blocks_increases_owned_pending_blocks_reduction(self):
        self.native.client.pending = [order(symbol="INV")]
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.native.client.pending = [order(symbol="AAA")]
        self.assertFalse(self.guard.submit_market("AAA", "sell", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.assertEqual(self.native.submissions, [])

    def test_pending_protected_order_does_not_block_owned_reduction(self):
        self.state["entries_enabled"] = False
        self.native.client.pending = [order(symbol="INV")]
        self.assertTrue(self.guard.submit_market("AAA", "sell", 1)["ok"])

    def test_malformed_missing_or_full_orders_data_fails_closed(self):
        for pending in (None, [SimpleNamespace(id="x", symbol="AAA")], [order(status="filled")], [order(str(i)) for i in range(500)]):
            self.native.client.pending = pending
            self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(self.native.submissions, [])

    def test_nested_pending_leg_prevents_duplicate_close(self):
        root = order(symbol="INV"); root.legs = [order("leg-001", "AAA")]
        self.native.client.pending = [root]
        self.assertFalse(self.guard.close_position("AAA")["ok"])

    def test_missing_current_prices_and_stale_future_prices_block_entries(self):
        for price_time in (NOW - timedelta(seconds=121), NOW + timedelta(seconds=1)):
            self.guard._prices.clear()
            self.guard.observe_bar("AAA", 100, price_time)
            self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.guard._prices.clear()
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        with self.assertRaises(TradingAdapterError): self.guard.observe_bar("AAA", "NaN", NOW)
        with self.assertRaises(TradingAdapterError): self.guard.observe_bar("AAA", 100, NOW.replace(tzinfo=None))

    def test_order_cap_buffer_budget_and_consolidated_caps(self):
        # 10*100 would fit exactly; conservative buffer refuses the increase.
        self.assertFalse(self.guard.submit_market("AAA", "buy", 10)["ok"])
        self.guard._budget = self.guard._budget.__class__("1050")
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.guard._budget = self.guard._budget.__class__("5000")
        self.guard._gross_cap = self.guard._gross_cap.__class__("1050")
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.guard._gross_cap = self.guard._gross_cap.__class__("8000")
        self.native.client.account.cash = "100"
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])

    def test_expired_budget_authorization_blocks_increase_keeps_exit(self):
        self.guard._expires = NOW
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertTrue(self.guard.close_position("AAA")["ok"])

    def test_unknown_holdings_and_consolidated_shorts_block_entries(self):
        for holding in (position("UNK"), position("INV", "-1", "-100")):
            self.native.client.held = [position(), holding]
            self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(self.native.submissions, [])

    def test_native_mandate_checked_at_order_and_cannot_be_bypassed(self):
        self.guard.mandate_checker = None
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.guard.mandate_checker = lambda *_: SimpleNamespace(ok=True, mandate_ok=False)
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertTrue(self.guard.submit_market("AAA", "sell", 1)["ok"])

    def test_switch_errors_and_final_reread_block_orders(self):
        self.guard._switch_reader = lambda: (_ for _ in ()).throw(RuntimeError("corrupt switch"))
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        states = iter([{"entries_enabled": True}, {"entries_enabled": True}, {"entries_enabled": False}])
        self.guard._switch_reader = lambda: next(states)
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(self.native.submissions, [])

    def test_inflight_reservation_survives_invisible_pending_order(self):
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertFalse(self.guard.submit_market("BBB", "buy", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.native.client.orders["mock-order-1"].status = "filled"
        self.native.client.orders["mock-order-1"].filled_qty = "1"
        self.native.client.held[0].qty = "11"; self.native.client.held[0].market_value = "1100"
        self.assertTrue(self.guard.submit_market("BBB", "buy", 1)["ok"])

    def test_terminal_fill_waits_for_position_endpoint_reflection(self):
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        remote = self.native.client.orders["mock-order-1"]
        remote.status = "filled"; remote.filled_qty = "1"
        self.assertFalse(self.guard.submit_market("BBB", "buy", 1)["ok"])
        self.assertEqual(len(self.native.submissions), 1)
        self.native.client.held[0].qty = "11"
        self.native.client.held[0].market_value = "1100"
        self.assertTrue(self.guard.submit_market("BBB", "buy", 1)["ok"])

    def test_concurrent_submissions_serialized_one_inflight(self):
        barrier = threading.Barrier(2)
        results = []
        def submit(symbol):
            barrier.wait(); results.append(self.guard.submit_market(symbol, "buy", 1))
        workers = [threading.Thread(target=submit, args=(symbol,)) for symbol in ("AAA", "BBB")]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertEqual(len(self.native.submissions), 1)
        self.assertEqual(sum(item["ok"] for item in results), 1)

    def test_ambiguous_submission_and_missing_id_require_manual_reconciliation(self):
        for result in ({"ok": False, "error": True}, {"ok": False}, {"ok": True}, {"ok": True, "order_id": "DRY-RUN"}):
            self.guard._ambiguous = False
            self.native.result = result
            self.guard.submit_market("AAA", "buy", 1)
            before = len(self.native.submissions)
            self.assertFalse(self.guard.submit_market("BBB", "buy", 1)["ok"])
            self.assertEqual(before, len(self.native.submissions))

    def test_receipt_failure_prevents_submission(self):
        self.guard._receipts = lambda *_: (_ for _ in ()).throw(RuntimeError("audit unavailable"))
        with self.assertRaises(RuntimeError): self.guard.submit_market("AAA", "buy", 1)
        self.assertEqual(self.native.submissions, [])

    def test_submission_admission_spans_intent_native_submit_and_receipt(self):
        active = []
        chronology = []
        @contextmanager
        def admission():
            active.append(True); chronology.append("enter")
            try: yield
            finally: active.pop(); chronology.append("exit")
        native_submit = self.native.submit_market
        def submit(*args, **kwargs):
            self.assertEqual(active, [True]); chronology.append("native")
            return native_submit(*args, **kwargs)
        def receipt(value):
            self.assertEqual(active, [True]); chronology.append(value["outcome"])
        self.guard._submission_admission = admission
        self.guard._receipts = receipt
        self.native.submit_market = submit
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(chronology, ["enter", "ATTEMPT", "native", "SUBMITTED", "exit"])
        self.assertEqual(active, [])

    def test_close_admission_spans_intent_native_close_and_receipt(self):
        active = []
        chronology = []
        @contextmanager
        def admission():
            active.append(True); chronology.append("enter")
            try: yield
            finally: active.pop(); chronology.append("exit")
        native_close = self.native.close_position
        def close(*args, **kwargs):
            self.assertEqual(active, [True]); chronology.append("native")
            return native_close(*args, **kwargs)
        def receipt(value):
            self.assertEqual(active, [True]); chronology.append(value["outcome"])
        self.guard._submission_admission = admission
        self.guard._receipts = receipt
        self.native.close_position = close
        self.state["entries_enabled"] = False
        self.assertTrue(self.guard.close_position("AAA")["ok"])
        self.assertEqual(chronology, ["enter", "ATTEMPT", "native", "SUBMITTED", "exit"])

    def test_failed_submission_admission_never_reaches_broker(self):
        @contextmanager
        def admission():
            raise RuntimeError("admission unavailable")
            yield
        self.guard._submission_admission = admission
        with self.assertRaises(RuntimeError): self.guard.submit_market("AAA", "buy", 1)
        with self.assertRaises(RuntimeError): self.guard.close_position("AAA")
        self.assertEqual(self.native.submissions, [])
        self.assertEqual(self.native.closes, [])

    def test_strict_positions_no_fallback_equity_or_empty_positions_on_error(self):
        for failure in ("positions", "account", "orders"):
            self.native.client.fail = failure
            self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.native.client.fail = "account"
        with self.assertRaises(RuntimeError): self.guard.account_equity()
        self.native.client.fail = "positions"
        with self.assertRaises(RuntimeError): self.guard.positions()

    def test_safe_stop_requires_flat_account_orders_reconciled(self):
        self.assertFalse(self.guard.safe_to_stop())
        self.native.client.held = [position("INV")]
        self.assertTrue(self.guard.safe_to_stop())
        self.native.client.pending = [order(symbol="INV")]
        self.assertTrue(self.guard.safe_to_stop())
        self.native.client.pending = [order(symbol="AAA")]
        self.assertFalse(self.guard.safe_to_stop())

    def test_constructor_rejects_overlapping_unverified_scopes(self):
        for mutation in ({"protected_symbols": ["AAA"]}, {"account_scope": "UNCLASSIFIED"},
                         {"account_scope": "DEDICATED_TRADING"}, {"symbols": []}, {"price_max_age_seconds": True},
                         {"trading_budget_usd": "NaN"}, {"capital_authorization_id": ""}):
            p = profile(); p.update(mutation)
            with self.assertRaises(TradingAdapterError): GuardedTradingBroker(self.native, p, lambda: self.state)

    def test_environment_credentials_presence_and_mode_match(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(TradingAdapterError): validate_runtime_environment(profile())
        with patch.dict("os.environ", {"APCA_API_KEY_ID": "MOCK_KEY", "APCA_API_SECRET_KEY": "MOCK_SECRET", "ALPACA_PAPER": "true"}, clear=True):
            validate_runtime_environment(profile())
            live = profile(); live["mode"] = "LIVE"
            with self.assertRaises(TradingAdapterError): validate_runtime_environment(live)

    def test_runtime_distribution_pins_checked_without_code_import(self):
        with patch.object(adapter_module.distribution_metadata, "version", side_effect=lambda name: NATIVE_RUNTIME_DEPENDENCIES[name]):
            validate_runtime_dependencies()
        with patch.object(adapter_module.distribution_metadata, "version", return_value="incorrect"):
            with self.assertRaises(TradingAdapterError): validate_runtime_dependencies()
        missing = adapter_module.distribution_metadata.PackageNotFoundError
        with patch.object(adapter_module.distribution_metadata, "version", side_effect=missing("mock")):
            with self.assertRaises(TradingAdapterError): validate_runtime_dependencies()

    def test_invalid_profile_pins_reject_before_native_import(self):
        fixture, p = self.runtime_profile()
        (fixture.source / NATIVE_SOURCE_FILES[0]).write_text("# changed after profile pin\n")
        with patch.dict("os.environ", {"APCA_API_KEY_ID": "MOCK_KEY", "APCA_API_SECRET_KEY": "MOCK_SECRET", "ALPACA_PAPER": "true"}, clear=True), \
             patch.object(adapter_module.importlib, "import_module") as importer:
            with self.assertRaises(ValueError): asyncio.run(run_guarded_navigator(p, lambda: {"entries_enabled": True}))
            importer.assert_not_called()

    def test_missing_dependency_rejects_before_native_import(self):
        _, p = self.runtime_profile()
        missing = adapter_module.distribution_metadata.PackageNotFoundError
        with patch.dict("os.environ", {"APCA_API_KEY_ID": "MOCK_KEY", "APCA_API_SECRET_KEY": "MOCK_SECRET", "ALPACA_PAPER": "true"}, clear=True), \
             patch.object(adapter_module.distribution_metadata, "version", side_effect=missing("mock")), \
             patch.object(adapter_module.importlib, "import_module") as importer:
            with self.assertRaises(TradingAdapterError): asyncio.run(run_guarded_navigator(p, lambda: {"entries_enabled": True}))
            importer.assert_not_called()

    def test_runtime_off_before_import_is_offline(self):
        with patch("blackpod_build_week.galactica_trading_adapter.importlib.import_module") as importer:
            with self.assertRaises(TradingAdapterError): asyncio.run(run_guarded_navigator(profile(), lambda: {"entries_enabled": False}))
            importer.assert_not_called()

    def test_native_runtime_integration_mock_preserves_mandate_and_scope(self):
        fixture, p = self.runtime_profile()
        captured = {}
        client = self.native.client
        class Configuration:
            @staticmethod
            def ExecutionConfig(**kwargs):
                captured["config"] = kwargs
                return SimpleNamespace(**kwargs)
        native = SimpleNamespace()
        def broker_factory(cfg):
            captured["broker_mode"] = cfg.paper
            return self.native
        native.Broker = broker_factory
        class Navigator:
            def __init__(nav, cfg):
                nav.broker = native.Broker(cfg); nav.broker.account_equity()
                nav.cfg = cfg; nav._stop = asyncio.Event(); nav.stream = None; nav.trade_counts = {}
                nav.mandate_gate = SimpleNamespace(check_entry=lambda *_: SimpleNamespace(ok=True, mandate_ok=True), refresh=lambda: None)
            async def on_bar(nav, bar): captured["bar"] = bar
            async def run(nav):
                captured["guard"] = nav.broker
                self.assertEqual(nav.broker.positions(), {"AAA": 10})
                self.native.client.held = []  # Simulate independently confirmed flat broker truth.
        native.NavigatorTrickle = Navigator
        modules = {"blackwell_navigator_trickle": native, "execution.config": Configuration,
                   "alpaca.trading.requests": SimpleNamespace(GetOrdersRequest=lambda **kw: kw),
                   "alpaca.trading.enums": SimpleNamespace(QueryOrderStatus=SimpleNamespace(OPEN="open"))}
        native_modules = {}
        for path in NATIVE_SOURCE_FILES:
            name = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            module = modules.get(name, SimpleNamespace())
            module.__file__ = str(fixture.source / path)
            native_modules[name] = module
        native_modules["setup"] = SimpleNamespace(__file__=str(fixture.source / "setup/__init__.py"))
        native_modules["mandate"] = SimpleNamespace(__file__=str(fixture.source / "mandate/__init__.py"))
        client.get_orders = lambda filter=None: []
        with patch.dict("os.environ", {"APCA_API_KEY_ID": "MOCK_KEY", "APCA_API_SECRET_KEY": "MOCK_SECRET", "ALPACA_PAPER": "true"}, clear=True), \
             patch.dict(sys.modules, native_modules), \
             patch.object(adapter_module.distribution_metadata, "version", side_effect=lambda name: NATIVE_RUNTIME_DEPENDENCIES[name]), \
             patch("blackpod_build_week.galactica_trading_adapter.sys.path", []), \
             patch("blackpod_build_week.galactica_trading_adapter.importlib.import_module", side_effect=lambda name: modules[name]):
            asyncio.run(run_guarded_navigator(p, lambda: {"entries_enabled": True}))
        self.assertTrue(captured["config"]["paper"])
        self.assertFalse(captured["config"]["dry_run"])
        self.assertIs(native.Broker, broker_factory)
        self.assertIsInstance(captured["guard"], GuardedTradingBroker)
        self.assertEqual(self.native.submissions, [])

    def test_actual_worker_mapping_reaches_guarded_adapter_with_mock_native_only(self):
        from blackpod_build_week.auto_trading_worker import run_worker
        from blackpod_build_week.auto_trading_runtime import RuntimeLedger, account_lock
        from blackpod_build_week.decision_journal_store import JournalStore
        from blackpod_build_week.paper_account_safety import install_paper_book
        from blackpod_build_week import trading_reconciliation as reconciliation
        from test_trading_reconciliation_engine import ReconciliationFixture
        fixture, p = self.runtime_profile()
        book = ReconciliationFixture()
        self.addCleanup(book.close)
        book.events = []
        snapshot = book.snapshot_for(snapshot_id="worker-baseline", account_id=p["account_id"], positions=[], orders=[])
        snapshot_event = reconciliation.build_snapshot_event(snapshot, book.events, book.blobs)
        snapshot_evidence = reconciliation.evidence_for_snapshot(snapshot, book.events, book.blobs)
        book.add(snapshot_event, snapshot_evidence)
        ownership = book.ownership_for(ownership_id="worker-book", account_id=p["account_id"],
            desks={"TRADING": p["symbols"], "INVESTMENT": p["protected_symbols"]})
        ownership_event = reconciliation.build_ownership_event(ownership, book.events, book.blobs)
        journal = JournalStore(fixture.base / "paper-book-journal")
        journal.append(snapshot_event, snapshot_evidence)
        journal.append(ownership_event, reconciliation.evidence_for_ownership(ownership, book.events, book.blobs))
        self.enterContext(patch("blackpod_build_week.paper_account_safety.account_state_root", return_value=fixture.base / "account-state"))
        install_paper_book(journal.root, ownership_event.event_id, confirm_account_id=p["account_id"])
        session = fixture.enable()["session_id"]  # fake spawn; never a subprocess
        captured = {}
        config = SimpleNamespace(ExecutionConfig=lambda **kw: SimpleNamespace(**kw))
        native = SimpleNamespace(Broker=lambda cfg: self.native)
        class Navigator:
            def __init__(nav, cfg):
                nav.broker = native.Broker(cfg); nav.broker.account_equity()
                nav._stop = asyncio.Event(); nav.stream = None; nav.trade_counts = {}
                nav.mandate_gate = SimpleNamespace(check_entry=lambda *_: SimpleNamespace(ok=True, mandate_ok=True), refresh=lambda: None)
            async def on_bar(nav, bar): pass
            async def run(nav):
                captured["enabled"] = nav.broker._enabled()
                captured["type"] = type(nav.broker)
        native.NavigatorTrickle = Navigator
        modules = {"blackwell_navigator_trickle": native, "execution.config": config,
                   "alpaca.trading.requests": SimpleNamespace(GetOrdersRequest=lambda **kw: kw),
                   "alpaca.trading.enums": SimpleNamespace(QueryOrderStatus=SimpleNamespace(OPEN="open"))}
        loaded = {}
        for path in NATIVE_SOURCE_FILES:
            name = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
            item = modules.get(name, SimpleNamespace()); item.__file__ = str(fixture.source / path); loaded[name] = item
        loaded["setup"] = SimpleNamespace(__file__=str(fixture.source / "setup/__init__.py"))
        loaded["mandate"] = SimpleNamespace(__file__=str(fixture.source / "mandate/__init__.py"))
        self.native.client.get_orders = lambda filter=None: []
        self.native.client.held = []
        actual_adapter = adapter_module.run_guarded_navigator
        async def snapshot_adapter(execution_profile, switch_reader, receipt_callback=None, **kwargs):
            # The actual worker supplies an immutable private import snapshot.
            # Mock modules must attest the derived paths, not the source checkout.
            derived = Path(execution_profile["galactica_root"])
            for relative in NATIVE_SOURCE_FILES:
                name = relative.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
                loaded[name].__file__ = str(derived / relative)
            for package in ("setup", "mandate"):
                loaded[package].__file__ = str(derived / package / "__init__.py")
            return await actual_adapter(execution_profile, switch_reader, receipt_callback, **kwargs)
        with patch.dict("os.environ", {"APCA_API_KEY_ID": "MOCK_KEY", "APCA_API_SECRET_KEY": "MOCK_SECRET", "ALPACA_PAPER": "true"}, clear=True), \
             patch.dict(sys.modules, loaded), \
             patch.object(adapter_module.distribution_metadata, "version", side_effect=lambda name: NATIVE_RUNTIME_DEPENDENCIES[name]), \
             patch.object(adapter_module.sys, "path", []), \
             patch.object(adapter_module, "run_guarded_navigator", snapshot_adapter), \
             patch.object(adapter_module.importlib, "import_module", side_effect=lambda name: modules[name]):
            with account_lock(p) as admission:
                result = run_worker(fixture.root, session, account_lock_fd=os.dup(admission))
        self.assertEqual(result, 0)
        self.assertTrue(captured["enabled"])
        self.assertIs(captured["type"], GuardedTradingBroker)
        statuses = [item["payload"]["state"] for item in RuntimeLedger(fixture.root).events() if item["kind"] == "WORKER_STATUS"]
        self.assertEqual(statuses, ["STARTING", "RUNNING", "STOPPED"])
        self.assertEqual(self.native.submissions, [])
        self.assertEqual(self.native.closes, [])
        self.assertEqual(journal.verify().event_count, 2)
        self.assertEqual(len(RuntimeLedger(fixture.base / "account-state").events()), 1)

    def test_native_receipts_round_trip_through_real_runtime_ledger(self):
        from blackpod_build_week.auto_trading_runtime import RuntimeLedger, utc_now
        from blackpod_build_week.decision_journal_store import JournalStore
        from blackpod_build_week.paper_account_safety import PaperSessionSafety, install_paper_book
        from blackpod_build_week import trading_reconciliation as reconciliation
        from test_trading_reconciliation_engine import ReconciliationFixture
        fixture, p = self.runtime_profile()
        book = ReconciliationFixture()
        self.addCleanup(book.close)
        book.events = []
        snapshot = book.snapshot_for(snapshot_id="receipt-baseline", account_id=p["account_id"], positions=[], orders=[])
        snapshot_event = reconciliation.build_snapshot_event(snapshot, book.events, book.blobs)
        snapshot_evidence = reconciliation.evidence_for_snapshot(snapshot, book.events, book.blobs)
        book.add(snapshot_event, snapshot_evidence)
        ownership = book.ownership_for(ownership_id="receipt-book", account_id=p["account_id"],
            desks={"TRADING": p["symbols"], "INVESTMENT": p["protected_symbols"]})
        ownership_event = reconciliation.build_ownership_event(ownership, book.events, book.blobs)
        journal = JournalStore(fixture.base / "paper-book-journal")
        journal.append(snapshot_event, snapshot_evidence)
        journal.append(ownership_event, reconciliation.evidence_for_ownership(ownership, book.events, book.blobs))
        self.enterContext(patch("blackpod_build_week.paper_account_safety.account_state_root", return_value=fixture.base / "account-state"))
        install_paper_book(journal.root, ownership_event.event_id, confirm_account_id=p["account_id"])
        session = fixture.enable()["session_id"]
        ledger = RuntimeLedger(fixture.root)
        safety = PaperSessionSafety(p, ledger.latest_control())
        for state in ("STARTING", "RUNNING"):
            ledger.append("WORKER_STATUS", {"session_id": session, "mode": "PAPER", "recorded_at": utc_now(), "state": state})
        def receipt(value):
            value = {**value, "session_id": session, "mode": "PAPER", "recorded_at": utc_now()}
            safety.record_receipt(value)
            ledger.append("BROKER_GUARD", value)
        guard = GuardedTradingBroker(self.native, p, lambda: {"entries_enabled": ledger.entries_enabled(session, p)}, receipt,
                                    now=lambda: NOW, mandate_checker=lambda *_: SimpleNamespace(ok=True, mandate_ok=True),
                                    persistent_gate=safety.permit_mutation, restored_inflight=safety.restored_inflight())
        guard.observe_bar("AAA", 100, NOW)
        self.assertTrue(guard.submit_market("AAA", "buy", 1)["ok"])
        outcomes = [item["payload"]["outcome"] for item in ledger.events() if item["kind"] == "BROKER_GUARD"]
        self.assertEqual(outcomes, ["ATTEMPT", "SUBMITTED"])
        self.assertEqual(self.native.submissions, [("AAA", "buy", 1)])  # Mock-only native boundary.
        shared = RuntimeLedger(fixture.base / "account-state").events()
        self.assertEqual([item["payload"]["outcome"] for item in shared if item["kind"] == "BROKER_GUARD"], outcomes)
        self.assertTrue(safety.state()["entries_blocked"])
        self.assertEqual(journal.verify().event_count, 2)


if __name__ == "__main__": unittest.main()
