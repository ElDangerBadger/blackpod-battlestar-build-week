"""Durable v2 intent receipts and replay guards; native/broker calls are mocks."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from decimal import Decimal
import unittest

from blackpod_build_week.auto_trading_runtime import (
    RuntimeLedger, TradingRuntimeError, TRADING_EXECUTION_RECEIPT_V2_SCHEMA,
    _immutable, profile_hash, validate_execution_receipt_v2,
)
from blackpod_build_week.galactica_trading_adapter import GuardedTradingBroker, TradingAdapterError
from blackpod_build_week.hashing import canonical_json_bytes
from test_auto_trading_runtime import RuntimeFixture
from test_galactica_trading_adapter import NativeBroker, NOW, position, order


class TradingReceiptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RuntimeFixture(); self.addCleanup(self.fixture.close)
        self.profile = self.fixture.profile
        self.profile.update(symbols=["AAA", "BBB"], protected_symbols=["INV"], account_id="account-001",
            trading_budget_usd="5000", max_account_gross_usd="8000", max_order_notional_usd="1000",
            price_buffer_fraction="0.05", authorization_expires_at="2099-10-12T00:00:00Z")
        self.profile["native_settings"]["per_trade_usd_cap"] = 500
        self.ledger = RuntimeLedger(self.fixture.root)
        digest = profile_hash(self.profile)
        _immutable(self.fixture.root / "profiles" / (digest + ".json"), canonical_json_bytes(self.profile))
        self.ledger.append("CONTROL", {"action_id": "fixture-on", "operator_id": "fixture-operator", "session_id": "fixture-session",
            "profile_sha256": digest, "entries_enabled": True, "recorded_at": NOW.isoformat()})
        for state in ("STARTING", "RUNNING"):
            self.ledger.append("WORKER_STATUS", {"session_id": "fixture-session", "mode": "PAPER", "recorded_at": NOW.isoformat(), "state": state})
        self.native = NativeBroker()
        self.state = {"entries_enabled": True}
        self.recorded = []
        def receipt(value):
            payload = {**value, "session_id": "fixture-session", "mode": "PAPER", "recorded_at": NOW.isoformat()}
            self.ledger.append("BROKER_GUARD", payload)
            self.recorded.append(payload)
        self.receipt = receipt
        self.guard = self.make_guard()

    def make_guard(self, **changes):
        kwargs = {"now": lambda: NOW, "mandate_checker": lambda *_: {"ok": True, "mandate_ok": True}}
        kwargs.update(changes)
        guard = GuardedTradingBroker(self.native, self.profile, lambda: self.state, self.receipt, **kwargs)
        guard.observe_bar("AAA", 100, NOW); guard.observe_bar("BBB", 100, NOW)
        return guard

    def test_original_intent_durable_before_native_mutation(self):
        submit = self.native.submit_market
        def observe(*args, **kwargs):
            last = self.ledger.events()[-1]["payload"]
            self.assertEqual(last["outcome"], "ATTEMPT")
            self.assertEqual(last["prior_qty"], "10")
            self.assertIsNone(last["order_id"])
            return submit(*args, **kwargs)
        self.native.submit_market = observe
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual([entry["outcome"] for entry in self.recorded], ["ATTEMPT", "SUBMITTED"])
        self.assertEqual(self.recorded[0]["attempt_id"], self.recorded[1]["attempt_id"])
        self.assertEqual(self.recorded[1]["schema_version"], TRADING_EXECUTION_RECEIPT_V2_SCHEMA)

    def test_returned_exact_order_client_and_account_ids_retained(self):
        self.native.result = {"ok": True, "order_id": "returned-order-001", "client_order_id": "session:AAA:001"}
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(self.recorded[-1]["order_id"], "returned-order-001")
        self.assertEqual(self.recorded[-1]["client_order_id"], "session:AAA:001")
        self.assertEqual(self.recorded[-1]["account_id"], "account-001")
        self.assertEqual(self.recorded[-1]["prior_qty"], "10")
        self.assertIsNone(self.recorded[0]["client_order_id"])

    def test_missing_client_order_id_stays_explicit_null(self):
        self.assertTrue(self.guard.close_position("AAA")["ok"])
        self.assertIsNone(self.recorded[-1]["client_order_id"])
        self.assertEqual(self.recorded[-1]["qty"], "10")
        self.assertEqual(self.recorded[-1]["side"], "close")

    def test_transport_exception_is_ambiguous_with_original_identity(self):
        def unsafe(*args, **kwargs): raise RuntimeError("SENSITIVE_FAKE_ERROR_MUST_NOT_BE_RETAINED")
        self.native.submit_market = unsafe
        result = self.guard.submit_market("AAA", "buy", 1)
        self.assertFalse(result["ok"])
        self.assertEqual([entry["outcome"] for entry in self.recorded], ["ATTEMPT", "AMBIGUOUS"])
        self.assertEqual(self.recorded[0]["attempt_id"], self.recorded[-1]["attempt_id"])
        self.assertEqual(self.recorded[-1]["prior_qty"], "10")
        self.assertNotIn(b"SENSITIVE_FAKE_ERROR", canonical_json_bytes(self.ledger.events()))

    def test_native_error_missing_identity_and_malformed_result_are_ambiguous(self):
        for result in ({"ok": False, "error": True}, {"ok": False}, {"ok": True}, "unexpected"):
            with self.subTest(result=result):
                self.native.result = result; self.guard = self.make_guard()
                before = len(self.recorded)
                self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
                self.assertEqual(self.recorded[before + 1]["outcome"], "AMBIGUOUS")
                self.assertEqual(self.recorded[before]["attempt_id"], self.recorded[before + 1]["attempt_id"])

    def test_native_known_skip_records_post_intent_block_without_erasing_intent(self):
        self.native.result = {"ok": False, "skipped": True, "reason": "known-native-precheck"}
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual([item["outcome"] for item in self.recorded], ["ATTEMPT", "BLOCKED"])
        self.assertEqual(self.recorded[0]["attempt_id"], self.recorded[-1]["attempt_id"])
        self.assertIsNone(self.recorded[-1]["order_id"])
        self.assertEqual(len([e for e in self.ledger.events() if e["kind"] == "BROKER_GUARD"]), 2)

    def test_preadmission_block_has_no_attempt_or_prior_quantity(self):
        self.state["entries_enabled"] = False
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(len(self.recorded), 1)
        self.assertEqual(self.recorded[0]["outcome"], "BLOCKED")
        for field in ("attempt_id", "prior_qty", "order_id", "client_order_id"):
            self.assertIsNone(self.recorded[0][field])
        self.assertEqual(self.native.submissions, [])

    def test_intent_receipt_failure_prevents_native_submission(self):
        def failure(_): raise RuntimeError("durability unavailable")
        self.guard._receipts = failure
        with self.assertRaises(RuntimeError): self.guard.submit_market("AAA", "buy", 1)
        self.assertEqual(self.native.submissions, [])

    def test_result_receipt_failure_marks_ambiguous_without_retrying_native(self):
        original = self.receipt
        def receipt(value):
            if value["outcome"] == "SUBMITTED": raise RuntimeError("result durability unavailable")
            original(value)
        self.guard._receipts = receipt
        with self.assertRaises(RuntimeError): self.guard.submit_market("AAA", "buy", 1)
        self.assertEqual(len(self.native.submissions), 1)
        self.assertEqual([item["outcome"] for item in self.recorded], ["ATTEMPT", "AMBIGUOUS"])
        self.assertIsNotNone(self.recorded[-1]["order_id"])
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(len(self.native.submissions), 1)

    def test_global_persistent_gate_covers_increase_partial_exit_and_close(self):
        checks = []
        self.guard = self.make_guard(persistent_gate=lambda symbol, increasing: checks.append((symbol, increasing)) or False)
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertFalse(self.guard.submit_market("AAA", "sell", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.assertEqual(checks, [("AAA", True), ("AAA", False), ("AAA", False)])
        self.assertTrue(all(item["attempt_id"] is None for item in self.recorded))
        self.assertEqual(self.native.submissions, []); self.assertEqual(self.native.closes, [])

    def test_persistent_gate_error_fails_closed(self):
        def broken(*_): raise RuntimeError("journal unavailable")
        self.guard = self.make_guard(persistent_gate=broken)
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.assertEqual(self.native.closes, [])

    def test_admission_context_covers_global_gate_intent_api_and_result(self):
        active = []
        @contextmanager
        def admission():
            active.append(True)
            try: yield
            finally: active.pop()
        def gate(*_): self.assertEqual(active, [True]); return True
        original_receipt = self.receipt
        def receipt(value): self.assertEqual(active, [True]); original_receipt(value)
        self.guard = self.make_guard(persistent_gate=gate, submission_admission=admission)
        self.guard._receipts = receipt
        submit = self.native.submit_market
        def native(*args, **kwargs): self.assertEqual(active, [True]); return submit(*args, **kwargs)
        self.native.submit_market = native
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertEqual(active, [])

    def test_restored_accepted_order_reserves_until_broker_fill_and_position_agree(self):
        pending = {"order_id": "restored-001", "symbol": "AAA", "side": "buy", "qty": "2", "prior_qty": "8"}
        self.native.client.orders["restored-001"] = order("restored-001", "AAA")
        self.guard = self.make_guard(restored_inflight=[pending])
        self.assertEqual(self.guard._inflight["restored-001"]["qty"], Decimal("2"))
        self.assertFalse(self.guard.submit_market("BBB", "buy", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        remote = self.native.client.orders["restored-001"]; remote.status = "filled"; remote.filled_qty = "2"
        self.assertTrue(self.guard.submit_market("BBB", "buy", 1)["ok"])
        self.assertEqual(self.native.submissions, [("BBB", "buy", 1)])

    def test_restored_pending_preserves_unrelated_protective_exit(self):
        pending = {"order_id": "restored-001", "symbol": "AAA", "side": "buy", "qty": "2", "prior_qty": "8"}
        self.native.client.orders["restored-001"] = order("restored-001", "AAA")
        self.native.client.held.append(position("BBB", "5", "500"))
        self.guard = self.make_guard(restored_inflight=[pending]); self.state["entries_enabled"] = False
        self.assertTrue(self.guard.close_position("BBB")["ok"])
        self.assertEqual(self.native.closes, ["BBB"])
        self.assertEqual(self.native.submissions, [])

    def test_unknown_acceptance_blocks_same_symbol_exit_but_allows_other_owned_reduction(self):
        self.native.client.held.append(position("BBB", "5", "500"))
        self.native.result = {"ok": False, "error": True}
        self.assertFalse(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.assertFalse(self.guard.close_position("AAA")["ok"])
        self.assertTrue(self.guard.close_position("BBB")["ok"])
        self.assertFalse(self.guard.submit_market("BBB", "buy", 1)["ok"])

    def test_invalid_restored_orders_fail_closed_without_mutation(self):
        baseline = {"order_id": "restored-001", "symbol": "AAA", "side": "buy", "qty": "2", "prior_qty": "8"}
        for change in ({"symbol": "INV"}, {"qty": True}, {"prior_qty": "NaN"}, {"side": "invalid"},
                       {"order_id": "../invalid"}, {"extra": 1}, {"side": "close", "prior_qty": "0"}):
            value = {**baseline, **change}
            with self.assertRaises(TradingAdapterError): self.make_guard(restored_inflight=[value])
        with self.assertRaises(TradingAdapterError): self.make_guard(restored_inflight=[baseline, baseline])
        self.assertEqual(self.native.submissions, []); self.assertEqual(self.native.closes, [])

    def test_v2_validation_binds_all_original_attempt_fields(self):
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        events = self.ledger.events(); original_prefix = events[:-1]; result = self.recorded[-1]
        for field, changed in (("account_id", "wrong"), ("qty", "1.0"), ("prior_qty", "9"), ("symbol", "BBB"),
                               ("attempt_id", "different"), ("side", "sell"), ("session_id", "another-session"),
                               ("recorded_at", "2020-01-01T00:00:00Z")):
            value = copy.deepcopy(result); value[field] = changed
            with self.subTest(field=field), self.assertRaises(TradingRuntimeError):
                validate_execution_receipt_v2(value, self.profile, original_prefix)

    def test_duplicate_intent_result_unknown_schema_and_nullability_reject(self):
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        events = self.ledger.events()
        for payload in (self.recorded[0], self.recorded[1]):
            with self.assertRaises(TradingRuntimeError): self.ledger.append("BROKER_GUARD", payload)
        for changes in ({"schema_version": "unknown"}, {"order_id": None}, {"client_order_id": {}}, {"prior_qty": None}, {"attempt_id": None}):
            value = {**self.recorded[1], **changes}
            with self.assertRaises(TradingRuntimeError): validate_execution_receipt_v2(value, self.profile, events[:-1])
        self.assertEqual(len(self.ledger.events()), len(events))

    def test_admitted_v2_receipts_cannot_invent_short_or_reverse_authority(self):
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        original = self.recorded[0]
        prefix = self.ledger.events()[:3]
        for change in ({"side": "sell", "prior_qty": "0"}, {"side": "sell", "prior_qty": "0.5"},
                       {"side": "buy", "prior_qty": "-0.5"}, {"side": "close", "prior_qty": "0"},
                       {"side": "close", "prior_qty": "2"}):
            value = {**original, **change}
            with self.assertRaises(TradingRuntimeError): validate_execution_receipt_v2(value, self.profile, prefix)

    def test_ambiguous_result_cannot_discard_already_known_broker_identity(self):
        self.native.result = {"ok": True, "order_id": "returned-001", "client_order_id": "native:AAA:001"}
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        value = {**self.recorded[-1], "outcome": "AMBIGUOUS", "reason_code": "LATER_DURABILITY_UNVERIFIED"}
        validate_execution_receipt_v2(value, self.profile, self.ledger.events())
        for field in ("order_id", "client_order_id"):
            changed = {**value, field: None}
            with self.assertRaises(TradingRuntimeError): validate_execution_receipt_v2(changed, self.profile, self.ledger.events())

    def test_legacy_receipt_bytes_stay_accepted_and_unchanged_in_mixed_chain(self):
        legacy = {"session_id": "fixture-session", "mode": "PAPER", "recorded_at": NOW.isoformat(), "profile_id": self.profile["profile_id"],
            "domain": "TRADING", "account_mode": "PAPER", "symbol": "AAA", "side": "buy", "qty": "1", "outcome": "ATTEMPT",
            "reason_code": "LEGACY_INTENT", "order_id": None, "capital_authorization_id": self.profile["capital_authorization_id"]}
        self.ledger.append("BROKER_GUARD", legacy)
        path = self.fixture.root / "events" / "000000000004.json"; before = path.read_bytes()
        self.assertTrue(self.guard.submit_market("AAA", "buy", 1)["ok"])
        self.ledger.events()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.ledger.events()[3]["payload"], legacy)


if __name__ == "__main__": unittest.main()
