"""Deterministic PAPER reconciliation; synthetic broker facts, no live calls."""
from __future__ import annotations
import copy
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_reconciliation import BrokerSnapshotInput, DeskOwnershipInput, TradingReconciliationInput
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week import trading_reconciliation as engine
from blackpod_build_week.paper_account_probe import ENDPOINTS

NOW = "2026-10-15T00:00:00Z"
LATER = "2026-10-15T00:01:00Z"
AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def broker_order(identity="order-1", symbol="MSFT", status="filled", **changes):
    result = {"id": identity, "client_order_id": "client-1", "symbol": symbol, "side": "buy", "status": status,
              "type": "market", "time_in_force": "day", "qty": "2", "notional": None, "filled_qty": "2",
              "filled_avg_price": "10", "submitted_at": NOW, "updated_at": NOW, "filled_at": NOW,
              "canceled_at": None, "expired_at": None, "failed_at": None, "replaced_at": None,
              "replaces": None, "replaced_by": None, "parent_order_id": None, "leg_ids": []}
    result.update(changes)
    return result


def position(symbol="MSFT", qty="2"):
    return {"symbol": symbol, "qty": qty, "side": "long", "market_value": str(int(qty) * 10),
            "avg_entry_price": "10", "current_price": "10"}


def runtime_event(prior, kind, payload):
    unsigned = {"schema_version": "blackpod.auto_trading_runtime_event.v1", "sequence": len(prior) + 1,
                "previous_sha256": prior[-1]["event_sha256"] if prior else None, "kind": kind, "payload": payload}
    return {**unsigned, "event_sha256": sha256_bytes(canonical_json_bytes(unsigned))}


class ReconciliationFixture:
    """Shared engine/store fixture; baseline event prefix has no reconciliations."""
    def __init__(self):
        from test_auto_trading_runtime import RuntimeFixture
        self.native = RuntimeFixture()
        self.profile = self.native.profile
        self.profile_sha = sha256_bytes(canonical_json_bytes(self.profile))
        control = {"action_id": "fixture-enable", "session_id": "fixture-session", "profile_sha256": self.profile_sha,
                   "entries_enabled": True, "recorded_at": NOW, "operator_id": "fixture-operator"}
        events = [runtime_event([], "CONTROL", control)]
        receipt = {"schema_version": "blackpod.trading_execution_receipt.v2", "account_id": "fixture-account",
                   "attempt_id": "attempt-1", "prior_qty": "0", "client_order_id": "client-1",
                   "session_id": "fixture-session", "mode": "PAPER", "recorded_at": NOW,
                   "profile_id": self.profile["profile_id"], "domain": "TRADING", "account_mode": "PAPER",
                   "symbol": "MSFT", "side": "buy", "qty": "2", "outcome": "ATTEMPT", "reason_code": "RISK_INCREASE",
                   "order_id": None, "capital_authorization_id": self.profile["capital_authorization_id"]}
        events.append(runtime_event(events, "BROKER_GUARD", receipt))
        events.append(runtime_event(events, "BROKER_GUARD", {**receipt, "outcome": "SUBMITTED", "reason_code": "NATIVE_ORDER_ACCEPTED", "order_id": "order-1"}))
        self.capture = {"schema_version": "blackpod.runtime_export.v1", "events": events, "profiles": {self.profile_sha: self.profile}}
        self.blobs, self.events = {}, []
        self.snapshot = self.snapshot_for()
        self.snapshot_event = engine.build_snapshot_event(self.snapshot, self.events, self.blobs)
        self.add(self.snapshot_event, engine.evidence_for_snapshot(self.snapshot, self.events, self.blobs))
        self.ownership = self.ownership_for()
        self.ownership_event = engine.build_ownership_event(self.ownership, self.events, self.blobs)
        self.add(self.ownership_event, engine.evidence_for_ownership(self.ownership, self.events, self.blobs))
        self.reconciliation = self.reconciliation_for()

    def close(self): self.native.close()

    def add(self, event, evidence):
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})

    def snapshot_for(self, **changes):
        value = {"schema_version": "blackpod.paper_broker_snapshot.v1", "snapshot_id": "snapshot-1", "captured_at": NOW,
                 "capture_window": {"started_at": NOW, "completed_at": NOW}, "mode": "PAPER", "account_id": "fixture-account",
                 "account": {"status": "ACTIVE", "trading_blocked": False, "account_blocked": False, "currency": "USD",
                             "equity": "100000", "cash": "99980", "buying_power": "99980"},
                 "positions": [position(), position("AAPL", "1")], "orders": [broker_order()],
                 "completeness": {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": True},
                 "capture_provenance": {"source_kind": "SYNTHETIC_FIXTURE", "origin": "https://paper-api.alpaca.markets",
                     "source_evidence": {}, "sequential_capture": True, "snapshot_atomic": False, "provider_verified": False},
                 "authority": AUTHORITY}
        value.update(changes)
        source = {"schema_version": "blackpod.paper_broker_fixture.v1", **{key: value[key] for key in ("account_id", "mode", "account", "positions", "orders", "capture_window", "completeness")}}
        raw = canonical_json_bytes(source)
        digest = sha256_bytes(raw)
        self.blobs[digest] = raw
        value["capture_provenance"]["source_evidence"] = {"path": "broker/fixture-source.json", "sha256": digest, "size_bytes": len(raw)}
        return BrokerSnapshotInput.from_mapping(value)

    def ownership_for(self, **changes):
        latest = next(event for event in reversed(self.events) if event.event_type == engine.SNAPSHOT_EVENT_TYPE)
        value = {"schema_version": "blackpod.trading_desk_ownership.v1", "ownership_id": "ownership-1", "recorded_at": NOW,
                 "declared_by": "fixture-human", "mode": "PAPER", "account_id": "fixture-account",
                 "broker_snapshot_event_id": latest.event_id, "broker_snapshot_sha256": latest.source["source_sha256"],
                 "desks": {"TRADING": ["MSFT"], "INVESTMENT": ["AAPL"]}, "status": "DECLARED",
                 "supersedes_event_id": None, "identity_authenticated": False, "authority": AUTHORITY}
        value.update(changes)
        return DeskOwnershipInput.from_mapping(value)

    def reconciliation_for(self, **changes):
        latest = next(event for event in reversed(self.events) if event.event_type == engine.SNAPSHOT_EVENT_TYPE)
        ownership = next((event for event in reversed(self.events) if event.event_type == engine.OWNERSHIP_EVENT_TYPE), None)
        raw = canonical_json_bytes(self.capture)
        self.blobs[sha256_bytes(raw)] = raw
        value = {"schema_version": "blackpod.trading_execution_reconciliation.v1", "reconciliation_id": "reconciliation-1", "recorded_at": NOW,
                 "mode": "PAPER", "account_id": "fixture-account", "broker_snapshot_event_id": latest.event_id,
                 "broker_snapshot_sha256": latest.source["source_sha256"], "ownership_event_id": None if ownership is None else ownership.event_id,
                 "ownership_sha256": None if ownership is None else ownership.source["source_sha256"],
                 "runtime_evidence": {"path": "trading/runtime-prefix.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
                 "prior_reconciliation_event_id": None, "scope": "PAPER_RECONCILIATION_ONLY", "realized_trade_pnl": None, "authority": AUTHORITY}
        value.update(changes)
        return TradingReconciliationInput.from_mapping(value)


class TradingReconciliationEngineTests(unittest.TestCase):
    def setUp(self):
        self.f = ReconciliationFixture()
        self.addCleanup(self.f.close)
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def report(self, document=None):
        return engine.assess_reconciliation(document or self.f.reconciliation, self.f.events, self.f.blobs)

    def test_exact_fill_observation_has_no_profit_or_authority(self):
        report = self.report()
        self.assertEqual(report["status"], "RECONCILED")
        self.assertTrue(report["attributable_execution_observed"])
        self.assertEqual(report["attempts"][0]["filled_qty"], "2")
        self.assertFalse(report["restart_barrier"]["entries_blocked"])
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertFalse(report["readiness"])
        self.assertTrue(all(value is False for value in report["authority"].values()))

    def test_snapshot_is_always_unclassified(self):
        assessment = self.f.snapshot_event.payload["assessment"]
        self.assertTrue(all(item["desk"] == "UNCLASSIFIED" for item in assessment["position_classifications"]))

    def test_empty_book_without_runtime_does_not_invent_execution(self):
        f = self.f
        f.events, f.blobs = [], {}
        snapshot = f.snapshot_for(positions=[], orders=[], completeness={"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": False})
        event = engine.build_snapshot_event(snapshot, f.events, f.blobs)
        f.add(event, engine.evidence_for_snapshot(snapshot, f.events, f.blobs))
        report = self.report(f.reconciliation_for(runtime_evidence=None))
        self.assertEqual(report["status"], "NO_EXECUTION_OBSERVED")
        self.assertFalse(report["execution_observed"])
        self.assertEqual(report["attempts"], [])

    def test_no_ownership_keeps_positions_and_orders_unclassified(self):
        self.f.events.pop()
        report = self.report(self.f.reconciliation_for(ownership_event_id=None, ownership_sha256=None))
        self.assertTrue(all(item["desk"] == "UNCLASSIFIED" for item in report["positions"] + report["orders"]))
        self.assertFalse(report["attributable_execution_observed"])

    def test_known_ownership_cannot_be_omitted(self):
        with self.assertRaises(engine.TradingReconciliationError):
            self.report(self.f.reconciliation_for(ownership_event_id=None, ownership_sha256=None))

    def test_account_mismatch_and_snapshot_hash_mismatch_reject(self):
        for changes in ({"account_id": "different-account"}, {"broker_snapshot_sha256": "a" * 64}):
            with self.subTest(changes=changes), self.assertRaises(engine.TradingReconciliationError):
                self.report(self.f.reconciliation_for(**changes))

    def test_source_bytes_are_required_and_projection_is_reproducible(self):
        event = engine.build_reconciliation_event(self.f.reconciliation, self.f.events, self.f.blobs)
        evidence = engine.evidence_for_reconciliation(self.f.reconciliation, self.f.events, self.f.blobs)
        blobs = {**self.f.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}}
        engine.validate_trading_reconciliation_event(event, self.f.events, blobs)
        del blobs[self.f.snapshot.capture_provenance["source_evidence"]["sha256"]]
        with self.assertRaises(engine.TradingReconciliationError):
            engine.validate_trading_reconciliation_event(event, self.f.events, blobs)

    def test_lost_acceptance_remains_blocked_when_book_is_empty(self):
        capture = copy.deepcopy(self.f.capture)
        capture["events"].pop()
        barrier = engine.durable_restart_barrier(capture, [], account_id="fixture-account", complete=True, positions=[])
        self.assertTrue(barrier["entries_blocked"])
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "SUBMISSION_ACCEPTANCE_UNKNOWN")
        self.assertFalse(barrier["automatic_resubmission_enabled"])

    def test_same_symbol_different_order_cannot_reconcile(self):
        barrier = engine.durable_restart_barrier(self.f.capture, [broker_order("other-order")], account_id="fixture-account", complete=True)
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "EXACT_ORDER_NOT_OBSERVED")

    def test_terminal_fill_waits_for_position_endpoint(self):
        barrier = engine.durable_restart_barrier(self.f.capture, self.f.snapshot.orders, account_id="fixture-account", complete=True, positions=[])
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "TERMINAL_FILL_NOT_REFLECTED_IN_POSITION")

    def test_partial_cancellation_preserves_fill_and_resolves_reflected_quantity(self):
        order = broker_order(status="canceled", filled_qty="1", filled_at=None, canceled_at=NOW)
        barrier = engine.durable_restart_barrier(self.f.capture, [order], account_id="fixture-account", complete=True, positions=[position(qty="1")])
        self.assertFalse(barrier["entries_blocked"])
        self.assertEqual(order["filled_qty"], "1")

    def test_replaced_order_requires_successor_and_fill_attribution(self):
        original = broker_order(status="replaced", filled_qty="1", replaced_by="replacement-1", replaced_at=NOW, filled_at=None)
        barrier = engine.durable_restart_barrier(self.f.capture, [original], account_id="fixture-account", complete=True, positions=[position(qty="1")])
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "REPLACEMENT_SUCCESSOR_UNVERIFIED")
        successor = broker_order("replacement-1", replaces="order-1", client_order_id="client-2")
        barrier = engine.durable_restart_barrier(self.f.capture, [original, successor], account_id="fixture-account", complete=True, positions=[position()])
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "REPLACEMENT_FILL_ATTRIBUTION_UNVERIFIED")

    def test_cumulative_fill_cannot_retreat_even_after_an_absent_snapshot(self):
        empty = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER}, orders=[])
        event = engine.build_snapshot_event(empty, self.f.events, self.f.blobs)
        self.f.add(event, engine.evidence_for_snapshot(empty, self.f.events, self.f.blobs))
        bad = self.f.snapshot_for(snapshot_id="snapshot-3", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER}, orders=[broker_order(filled_qty="1", status="partially_filled", filled_at=None)])
        with self.assertRaises(engine.TradingReconciliationError): engine.build_snapshot_event(bad, self.f.events, self.f.blobs)

    def test_terminal_order_cannot_reopen(self):
        bad = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER}, orders=[broker_order(status="new", filled_at=None)])
        with self.assertRaises(engine.TradingReconciliationError): engine.build_snapshot_event(bad, self.f.events, self.f.blobs)

    def test_ownership_release_rejects_existing_holdings(self):
        updated = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER})
        event = engine.build_snapshot_event(updated, self.f.events, self.f.blobs)
        self.f.add(event, engine.evidence_for_snapshot(updated, self.f.events, self.f.blobs))
        ownership = self.f.ownership_for(ownership_id="ownership-2", recorded_at=LATER, desks={"TRADING": [], "INVESTMENT": ["MSFT", "AAPL"]}, supersedes_event_id=self.f.ownership_event.event_id)
        with self.assertRaises(engine.TradingReconciliationError): engine.build_ownership_event(ownership, self.f.events, self.f.blobs)

    def test_flat_ownership_amendment_preserves_original_and_requires_chain(self):
        updated = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER}, positions=[], orders=[])
        event = engine.build_snapshot_event(updated, self.f.events, self.f.blobs)
        self.f.add(event, engine.evidence_for_snapshot(updated, self.f.events, self.f.blobs))
        ownership = self.f.ownership_for(ownership_id="ownership-2", recorded_at=LATER, desks={"TRADING": [], "INVESTMENT": ["MSFT", "AAPL"]}, supersedes_event_id=self.f.ownership_event.event_id)
        original = self.f.ownership_event.to_bytes()
        amended = engine.build_ownership_event(ownership, self.f.events, self.f.blobs)
        self.assertEqual(amended.payload["assessment"]["reassigned_symbols"], ["MSFT"])
        self.assertEqual(original, self.f.ownership_event.to_bytes())

    def test_runtime_prefix_hash_corruption_and_account_drift_fail_closed(self):
        bad = copy.deepcopy(self.f.capture)
        bad["events"][-1]["payload"]["qty"] = "999"
        with self.assertRaises(engine.TradingReconciliationError): engine.verified_runtime_capture(canonical_json_bytes(bad))
        with self.assertRaises(engine.TradingReconciliationError): engine.durable_restart_barrier(self.f.capture, [], account_id="other-account")

    def test_rehashed_boolean_runtime_sequence_is_rejected(self):
        capture = copy.deepcopy(self.f.capture)
        capture["events"] = capture["events"][:1]
        capture["events"][0]["sequence"] = True
        unsigned = {key: value for key, value in capture["events"][0].items() if key != "event_sha256"}
        capture["events"][0]["event_sha256"] = sha256_bytes(canonical_json_bytes(unsigned))
        with self.assertRaises(engine.TradingReconciliationError): engine.parse_runtime_capture(canonical_json_bytes(capture))

    def test_worker_status_unknown_authority_and_lifecycle_reset_reject(self):
        base = {"session_id": "fixture-session", "mode": "PAPER", "recorded_at": NOW}
        for payload in ({**base, "state": "RUNNING"}, {**base, "state": "STARTING", "execution_authorized": True},
                        {**base, "state": "STARTING", "auto_restart_enabled": True}):
            capture = copy.deepcopy(self.f.capture)
            capture["events"].append(runtime_event(capture["events"], "WORKER_STATUS", payload))
            with self.subTest(payload=payload), self.assertRaises(engine.TradingReconciliationError):
                engine.parse_runtime_capture(canonical_json_bytes(capture))
        capture = copy.deepcopy(self.f.capture)
        for state in ("STARTING", "RUNNING", "STOPPED", "RUNNING"):
            capture["events"].append(runtime_event(capture["events"], "WORKER_STATUS", {**base, "state": state}))
        with self.assertRaises(engine.TradingReconciliationError): engine.parse_runtime_capture(canonical_json_bytes(capture))

    def test_legacy_malformed_scalar_fields_cannot_pass_rehashed_export(self):
        for field, value in (("qty", 2), ("reason_code", {}), ("order_id", [])):
            capture = copy.deepcopy(self.f.capture)
            events = []
            for old in capture["events"]:
                payload = {key: item for key, item in old["payload"].items() if key not in {"schema_version", "account_id", "attempt_id", "prior_qty", "client_order_id"}}
                if old["kind"] == "BROKER_GUARD": payload[field] = value
                events.append(runtime_event(events, old["kind"], payload))
            capture["events"] = events
            with self.subTest(field=field), self.assertRaises(engine.TradingReconciliationError):
                engine.parse_runtime_capture(canonical_json_bytes(capture))

    def test_legacy_missing_position_baseline_blocks_restart(self):
        events = []
        for old in self.f.capture["events"]:
            payload = {key: value for key, value in old["payload"].items() if key not in {"schema_version", "account_id", "attempt_id", "prior_qty", "client_order_id"}}
            events.append(runtime_event(events, old["kind"], payload))
        capture = {**self.f.capture, "events": events}
        barrier = engine.durable_restart_barrier(capture, self.f.snapshot.orders, account_id="fixture-account", complete=True, positions=self.f.snapshot.positions)
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "POSITION_BASELINE_NOT_RECORDED")

    def test_retry_after_append_reproduces_original_input_and_event_bytes(self):
        f = self.f
        event = engine.build_reconciliation_event(f.reconciliation, f.events, f.blobs)
        f.add(event, engine.evidence_for_reconciliation(f.reconciliation, f.events, f.blobs))
        for document, original, builder, evidence in (
            (f.snapshot, f.snapshot_event, engine.build_snapshot_event, engine.evidence_for_snapshot),
            (f.ownership, f.ownership_event, engine.build_ownership_event, engine.evidence_for_ownership),
            (f.reconciliation, event, engine.build_reconciliation_event, engine.evidence_for_reconciliation),
        ):
            self.assertEqual(builder(document, f.events, f.blobs).to_bytes(), original.to_bytes())
            self.assertTrue(evidence(document, f.events, f.blobs))

    def test_retry_identity_conflicts_on_changed_input_bytes(self):
        document = self.f.ownership.to_dict()
        document["declared_by"] = "different-author"
        with self.assertRaises(engine.TradingReconciliationError):
            engine.build_ownership_event(DeskOwnershipInput.from_mapping(document), self.f.events, self.f.blobs)

    def test_timestamp_retreat_cannot_create_a_new_initial_account_declaration(self):
        ownership = self.f.ownership_for(ownership_id="ownership-2", recorded_at="2026-10-14T00:00:00Z")
        with self.assertRaises(engine.TradingReconciliationError): engine.build_ownership_event(ownership, self.f.events, self.f.blobs)
        snapshot = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at="2026-10-14T00:00:00Z", capture_window={"started_at": "2026-10-14T00:00:00Z", "completed_at": "2026-10-14T00:00:00Z"}, orders=[])
        with self.assertRaises(engine.TradingReconciliationError): engine.build_snapshot_event(snapshot, self.f.events, self.f.blobs)

    def test_ownership_release_is_blocked_by_open_orders_even_with_no_positions(self):
        updated = self.f.snapshot_for(snapshot_id="snapshot-2", captured_at=LATER, capture_window={"started_at": LATER, "completed_at": LATER}, positions=[], orders=[broker_order("open-order", status="new", filled_qty="0", filled_avg_price=None, filled_at=None)])
        event = engine.build_snapshot_event(updated, self.f.events, self.f.blobs)
        self.f.add(event, engine.evidence_for_snapshot(updated, self.f.events, self.f.blobs))
        ownership = self.f.ownership_for(ownership_id="ownership-2", recorded_at=LATER, desks={"TRADING": [], "INVESTMENT": ["AAPL"]}, supersedes_event_id=self.f.ownership_event.event_id)
        with self.assertRaises(engine.TradingReconciliationError): engine.build_ownership_event(ownership, self.f.events, self.f.blobs)

    def test_declared_ownership_never_rewrites_earlier_order_desk(self):
        self.f.events = self.f.events[:1]
        ownership = self.f.ownership_for(recorded_at=LATER)
        event = engine.build_ownership_event(ownership, self.f.events, self.f.blobs)
        self.f.add(event, engine.evidence_for_ownership(ownership, self.f.events, self.f.blobs))
        report = self.report(self.f.reconciliation_for(recorded_at=LATER))
        self.assertEqual(report["orders"][0]["desk"], "UNCLASSIFIED")
        self.assertFalse(report["attributable_execution_observed"])

    def test_runtime_prefix_cannot_retreat_on_later_reconciliation(self):
        f = self.f
        event = engine.build_reconciliation_event(f.reconciliation, f.events, f.blobs)
        f.add(event, engine.evidence_for_reconciliation(f.reconciliation, f.events, f.blobs))
        f.capture["events"].pop()
        document = f.reconciliation_for(reconciliation_id="reconciliation-2", prior_reconciliation_event_id=event.event_id)
        with self.assertRaises(engine.TradingReconciliationError): engine.build_reconciliation_event(document, f.events, f.blobs)

    def test_exact_client_identity_recovers_known_acceptance_without_resubmit(self):
        capture = copy.deepcopy(self.f.capture)
        capture["events"].pop()
        barrier = engine.durable_restart_barrier(capture, self.f.snapshot.orders, account_id="fixture-account", complete=True, positions=self.f.snapshot.positions)
        self.assertFalse(barrier["entries_blocked"])
        self.assertFalse(barrier["automatic_resubmission_enabled"])

    def test_ambiguous_returned_id_requires_exact_broker_confirmation(self):
        capture = copy.deepcopy(self.f.capture)
        old = capture["events"].pop()
        payload = {**old["payload"], "outcome": "AMBIGUOUS", "reason_code": "RESULT_RECEIPT_PERSISTENCE_UNVERIFIED"}
        capture["events"].append(runtime_event(capture["events"], "BROKER_GUARD", payload))
        unresolved = engine.durable_restart_barrier(capture, [], account_id="fixture-account", complete=True, positions=[])
        self.assertTrue(unresolved["entries_blocked"])
        confirmed = engine.durable_restart_barrier(capture, self.f.snapshot.orders, account_id="fixture-account", complete=True, positions=self.f.snapshot.positions)
        self.assertFalse(confirmed["entries_blocked"])
        self.assertFalse(confirmed["automatic_resubmission_enabled"])

    def test_exact_id_with_wrong_side_or_quantity_is_blocked(self):
        for changes in ({"side": "sell"}, {"qty": "3"}):
            barrier = engine.durable_restart_barrier(self.f.capture, [broker_order(**changes)], account_id="fixture-account", complete=True, positions=self.f.snapshot.positions)
            self.assertTrue(barrier["entries_blocked"])

    def test_incomplete_capture_keeps_accepted_order_reserved(self):
        barrier = engine.durable_restart_barrier(self.f.capture, self.f.snapshot.orders, account_id="fixture-account", complete=False, positions=self.f.snapshot.positions)
        self.assertEqual(barrier["unresolved_attempts"][0]["reason_code"], "BROKER_SNAPSHOT_INCOMPLETE")

    def test_probe_source_is_retained_exactly_and_unknown_fields_are_not_projected(self):
        requests = [{"method": "GET", "path": path, "http_status": 200, "result": "VERIFIED_SELECTED_FIELDS"} for _, path in ENDPOINTS]
        source = {"schema_version": "blackpod.alpaca_paper_probe.v1", "result": "CONFIRMED", "mode": "PAPER", "paper_origin": "https://paper-api.alpaca.markets",
                  "complete": True, "account_authenticated": True, "account_identity_verified": True, "snapshot_atomic": False,
                  "orders_submitted": 0, "orders_cancelled": 0, "positions_closed": 0, "capture_started_at": NOW, "capture_completed_at": NOW,
                  "account": {"id": "fixture-account", "status": "ACTIVE", "trading_blocked": False, "account_blocked": False,
                              "currency": "USD", "equity": "100000", "cash": "99980", "buying_power": None},
                  "positions": [], "open_orders": [], "clock": {}, "requests": requests}
        self.probe_source = source
        raw = json.dumps(source, separators=(",", ":")).encode()
        snapshot = engine.snapshot_input_from_probe(raw, snapshot_id="probe-1", evidence_path="broker/probe.json")
        blobs = {sha256_bytes(raw): raw}
        evidence = engine.evidence_for_snapshot(snapshot, [], blobs)
        self.assertEqual(evidence["broker/probe.json"], raw)
        self.assertFalse(snapshot.completeness["tracked_orders_complete"])
        self.assertEqual(snapshot.orders, [])

    def test_composite_exact_terminal_read_is_scoped_and_retains_cumulative_fills(self):
        self.test_probe_source_is_retained_exactly_and_unknown_fields_are_not_projected()
        order = broker_order()
        order.pop("parent_order_id"); order.pop("leg_ids"); order["legs"] = None
        source = {"schema_version": "blackpod.paper_broker_capture.v1", "probe": self.probe_source,
                  "tracked_order_ids": ["order-1"], "tracked_order_requests": [{"method": "GET", "path": "/v2/orders/order-1", "http_status": 200, "started_at": NOW, "completed_at": NOW}],
                  "tracked_orders": [order], "capture_completed_at": NOW}
        raw = canonical_json_bytes(source)
        snapshot = engine.snapshot_input_from_probe(raw, snapshot_id="composite-1", evidence_path="broker/composite.json")
        self.assertTrue(snapshot.completeness["tracked_orders_complete"])
        self.assertEqual(snapshot.orders[0]["filled_qty"], "2")
        source["tracked_order_requests"][0]["path"] = "/v2/orders/different-order"
        with self.assertRaises(engine.TradingReconciliationError): engine.snapshot_input_from_probe(canonical_json_bytes(source), snapshot_id="bad-1", evidence_path="broker/bad.json")

    def test_normalization_retains_provider_fields_and_canonicalizes_nanos_in_projection(self):
        order = {**broker_order(), "submitted_at": "2026-10-15T00:00:00.123456789Z", "legs": None, "unknown": "not-projected"}
        normalized = engine.normalize_broker_orders([order])[0]
        self.assertEqual(normalized["submitted_at"], "2026-10-15T00:00:00.123456Z")
        self.assertNotIn("unknown", normalized)


if __name__ == "__main__": unittest.main()
