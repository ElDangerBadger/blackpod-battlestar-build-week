"""Offline strict PAPER contracts and additive journal version isolation."""
from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from blackpod_build_week.contracts.decision_journal import (
    JournalEvent, JOURNAL_EVENT_V6_SCHEMA_VERSION, PAPER_BROKER_SNAPSHOT_EVENT_TYPE,
    TRADING_DESK_OWNERSHIP_EVENT_TYPE, TRADING_EXECUTION_RECONCILED_EVENT_TYPE,
)
from blackpod_build_week.contracts.trading_reconciliation import (
    BrokerSnapshotInput, DeskOwnershipInput, ReconciliationInput, BROKER_SNAPSHOT_SCHEMA_VERSION,
    DESK_OWNERSHIP_SCHEMA_VERSION, TRADING_RECONCILIATION_SCHEMA_VERSION, RECONCILIATION_LIMITATIONS,
    PAPER_ORIGIN, RECONCILIATION_SCOPE, validate_snapshot_assessment, validate_ownership_assessment,
    validate_reconciliation_result,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes

NOW = "2026-10-12T17:52:16Z"


def authority():
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def snapshot_mapping():
    return {
        "schema_version": BROKER_SNAPSHOT_SCHEMA_VERSION, "snapshot_id": "snapshot-001", "captured_at": NOW,
        "capture_window": {"started_at": "2026-10-12T17:52:15Z", "completed_at": NOW}, "mode": "PAPER",
        "account_id": "synthetic-paper-account", "account": {"status": "ACTIVE", "trading_blocked": False,
            "account_blocked": False, "currency": "USD", "equity": "100000.00", "cash": "100000.00", "buying_power": None},
        "positions": [], "orders": [],
        "completeness": {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": True},
        "capture_provenance": {"source_kind": "SYNTHETIC_FIXTURE", "origin": PAPER_ORIGIN,
            "source_evidence": {"path": "broker/synthetic-probe.json", "sha256": "a" * 64, "size_bytes": 10},
            "sequential_capture": True, "snapshot_atomic": False, "provider_verified": False}, "authority": authority(),
    }


def position_mapping():
    return {"symbol": "AAA", "qty": "2", "side": "long", "market_value": "200", "avg_entry_price": "90", "current_price": "100"}


def order_mapping():
    return {"id": "order-001", "client_order_id": "session:AAA:001", "symbol": "AAA", "side": "buy", "status": "new",
        "type": "market", "time_in_force": "day", "qty": "2", "notional": None, "filled_qty": "0", "filled_avg_price": None,
        "submitted_at": NOW, "updated_at": NOW, "filled_at": None, "canceled_at": None, "expired_at": None,
        "failed_at": None, "replaced_at": None, "replaces": None, "replaced_by": None, "parent_order_id": None, "leg_ids": []}


def ownership_mapping():
    return {"schema_version": DESK_OWNERSHIP_SCHEMA_VERSION, "ownership_id": "ownership-001", "recorded_at": NOW,
        "declared_by": "research-operator", "mode": "PAPER", "account_id": "synthetic-paper-account",
        "broker_snapshot_event_id": "journal-event-" + "b" * 64, "broker_snapshot_sha256": "c" * 64,
        "desks": {"TRADING": [], "INVESTMENT": []}, "status": "DECLARED", "supersedes_event_id": None,
        "identity_authenticated": False, "authority": authority()}


def reconciliation_mapping():
    return {"schema_version": TRADING_RECONCILIATION_SCHEMA_VERSION, "reconciliation_id": "reconciliation-001", "recorded_at": NOW,
        "mode": "PAPER", "account_id": "synthetic-paper-account", "broker_snapshot_event_id": "journal-event-" + "b" * 64,
        "broker_snapshot_sha256": "c" * 64, "ownership_event_id": None, "ownership_sha256": None,
        "runtime_evidence": None, "prior_reconciliation_event_id": None, "scope": RECONCILIATION_SCOPE,
        "realized_trade_pnl": None, "authority": authority()}


def snapshot_assessment_mapping(snapshot=None):
    snapshot = snapshot or BrokerSnapshotInput.from_mapping(snapshot_mapping())
    return {"position_count": len(snapshot.positions), "order_count": len(snapshot.orders),
        "position_classifications": [{"symbol": item["symbol"], "desk": "UNCLASSIFIED"} for item in snapshot.positions],
        "order_classifications": [{"order_id": item["id"], "symbol": item["symbol"], "desk": "UNCLASSIFIED"} for item in snapshot.orders],
        "execution_observed": any(float(item["filled_qty"]) > 0 for item in snapshot.orders),
        "provider_verified": False, "execution_authority_granted": False, "readiness": False,
        "realized_trade_pnl": None, "authority": authority()}


def ownership_assessment_mapping():
    return {"effective_at": NOW, "added_symbols": [], "released_symbols": [], "reassigned_symbols": [],
        "baseline_positions": [], "baseline_orders": [], "identity_authenticated": False,
        "execution_authority_granted": False, "readiness": False, "realized_trade_pnl": None, "authority": authority()}


def reconciliation_result_mapping():
    return {"status": "NO_EXECUTION_OBSERVED", "positions": [], "orders": [], "attempts": [],
        "restart_barrier": {"entries_blocked": False, "unresolved_attempts": [], "automatic_resubmission_enabled": False, "execution_authority_granted": False},
        "execution_observed": False, "attributable_execution_observed": False, "provider_verified": False,
        "ownership_authenticated": False, "execution_authority_granted": False, "readiness": False,
        "realized_trade_pnl": None, "authority": authority(), "limitations": list(RECONCILIATION_LIMITATIONS)}


def _event(kind):
    contract, factory, report, event_type, sourcekind, identity = {
        "snapshot": (BrokerSnapshotInput, snapshot_mapping, snapshot_assessment_mapping, PAPER_BROKER_SNAPSHOT_EVENT_TYPE, "PAPER_BROKER_SNAPSHOT", "snapshot_id"),
        "ownership": (DeskOwnershipInput, ownership_mapping, ownership_assessment_mapping, TRADING_DESK_OWNERSHIP_EVENT_TYPE, "TRADING_DESK_OWNERSHIP", "ownership_id"),
        "reconciliation": (ReconciliationInput, reconciliation_mapping, reconciliation_result_mapping, TRADING_EXECUTION_RECONCILED_EVENT_TYPE, "TRADING_EXECUTION_RECONCILIATION", "reconciliation_id"),
    }[kind]
    document = contract.from_mapping(factory())
    return {"schema_version": JOURNAL_EVENT_V6_SCHEMA_VERSION, "event_id": "journal-event-" + "d" * 64,
        "decision_id": "journal-decision-" + "e" * 64, "domain": "TRADING", "event_type": event_type, "recorded_at": NOW,
        "source": {"kind": sourcekind, identity: getattr(document, identity), "source_sha256": sha256_bytes(document.to_bytes())},
        "evidence": [], "payload": {kind: document.to_dict(), "result" if kind == "reconciliation" else "assessment": report()}}


def snapshot_event(): return _event("snapshot")
def ownership_event(): return _event("ownership")
def reconciliation_event(): return _event("reconciliation")


class TradingReconciliationContractTests(unittest.TestCase):
    def test_immutable_bytes_and_round_trip(self):
        for contract, factory in ((BrokerSnapshotInput, snapshot_mapping), (DeskOwnershipInput, ownership_mapping), (ReconciliationInput, reconciliation_mapping)):
            value = factory(); document = contract.from_mapping(value); original = document.to_bytes()
            value.clear(); document.to_dict().clear()
            self.assertEqual(original, document.to_bytes())
            self.assertEqual(document, contract.from_bytes(original))
            with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)): document._canonical_bytes = b"changed"

    def test_unknown_and_missing_nested_fields_reject(self):
        cases = ((BrokerSnapshotInput, snapshot_mapping, [(), ("capture_window",), ("account",), ("completeness",), ("capture_provenance",), ("capture_provenance", "source_evidence"), ("authority",)]),
                 (DeskOwnershipInput, ownership_mapping, [(), ("desks",), ("authority",)]),
                 (ReconciliationInput, reconciliation_mapping, [(), ("authority",)]))
        for contract, factory, paths in cases:
            for path in paths:
                for mutation in ("missing", "extra"):
                    value = factory(); target = value
                    for part in path: target = target[part]
                    if mutation == "missing": del target[next(iter(target))]
                    else: target["extra"] = True
                    with self.subTest(contract=contract.__name__, path=path, mutation=mutation), self.assertRaises(ContractValidationError): contract.from_mapping(value)

    def test_snapshot_paper_only_and_false_authority(self):
        for field, replacement in (("mode", "LIVE"), ("schema_version", "other")):
            value = snapshot_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)
        for contract, factory in ((BrokerSnapshotInput, snapshot_mapping), (DeskOwnershipInput, ownership_mapping), (ReconciliationInput, reconciliation_mapping)):
            for field in authority():
                for replacement in (True, 0, None):
                    value = factory(); value["authority"][field] = replacement
                    with self.assertRaises(ContractValidationError): contract.from_mapping(value)

    def test_snapshot_capture_window_chronology_and_time_normalization(self):
        value = snapshot_mapping(); value["captured_at"] = "2026-10-12T10:52:16-07:00"
        self.assertEqual(BrokerSnapshotInput.from_mapping(value).captured_at, NOW)
        for field, replacement in (("started_at", "2026-10-12T17:52:17Z"), ("completed_at", "2026-10-12T17:52:17Z"), ("started_at", "2026-10-12")):
            value = snapshot_mapping(); value["capture_window"][field] = replacement
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_decimal_strings_preserved_without_float_or_probability_invention(self):
        value = snapshot_mapping(); value["account"]["cash"] = "-1.2300"; value["account"]["equity"] = "0"
        document = BrokerSnapshotInput.from_mapping(value)
        self.assertEqual(document.account["cash"], "-1.2300")
        for replacement in (1, True, 1.5, "NaN", "Infinity", "1e999", "1e21", " 1", "1" * 129):
            value = snapshot_mapping(); value["account"]["equity"] = replacement
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_missing_optional_account_facts_remain_null(self):
        value = snapshot_mapping()
        for field in ("currency", "account_blocked", "buying_power"): value["account"][field] = None
        document = BrokerSnapshotInput.from_mapping(value)
        self.assertIsNone(document.account["account_blocked"])
        self.assertIsNone(document.account["currency"])
        self.assertIsNone(document.account["buying_power"])

    def test_observed_account_blocking_flags_are_not_execution_permission(self):
        value = snapshot_mapping(); value["account"]["trading_blocked"] = True; value["account"]["account_blocked"] = True
        self.assertTrue(BrokerSnapshotInput.from_mapping(value).account["trading_blocked"])
        for field in ("trading_blocked", "account_blocked"):
            value = snapshot_mapping(); value["account"][field] = 1
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_position_signed_side_consistency(self):
        value = snapshot_mapping(); value["positions"] = [position_mapping()]
        BrokerSnapshotInput.from_mapping(value)
        value["positions"][0].update(qty="-2", side="short", market_value="-200")
        BrokerSnapshotInput.from_mapping(value)
        for mutation in ({"qty": "0"}, {"side": "long"}, {"market_value": "200"}, {"current_price": "0"}, {"avg_entry_price": "-1"}):
            changed = copy.deepcopy(value); changed["positions"][0].update(mutation)
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(changed)

    def test_position_unknown_fields_and_duplicates(self):
        for mutation in ("extra", "missing", "duplicate"):
            value = snapshot_mapping(); value["positions"] = [position_mapping()]
            if mutation == "extra": value["positions"][0]["confidence"] = .9
            elif mutation == "missing": del value["positions"][0]["qty"]
            else: value["positions"].append(position_mapping())
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_order_open_terminal_partial_and_replaced_facts(self):
        for status in ("new", "partially_filled", "filled", "canceled", "expired", "rejected", "replaced"):
            value = snapshot_mapping(); item = order_mapping(); item.update(status=status, filled_qty="1", filled_avg_price="100")
            value["orders"] = [item]
            self.assertEqual(BrokerSnapshotInput.from_mapping(value).orders[0]["filled_qty"], "1")

    def test_order_quantities_and_missing_prices(self):
        value = snapshot_mapping(); value["orders"] = [order_mapping()]
        value["orders"][0].update(filled_qty="1", filled_avg_price=None)
        self.assertIsNone(BrokerSnapshotInput.from_mapping(value).orders[0]["filled_avg_price"])
        for mutation in ({"filled_qty": "3"}, {"filled_qty": "-1"}, {"qty": None, "notional": None}, {"filled_avg_price": "0"}, {"qty": 2}):
            changed = copy.deepcopy(value); changed["orders"][0].update(mutation)
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(changed)

    def test_order_exact_identity_nested_legs_and_self_reference(self):
        value = snapshot_mapping(); parent = order_mapping(); leg = order_mapping()
        parent["leg_ids"] = ["order-002"]; leg.update(id="order-002", parent_order_id="order-001")
        value["orders"] = [parent, leg]
        BrokerSnapshotInput.from_mapping(value)
        for mutation in ({"leg_ids": ["missing"]}, {"leg_ids": ["order-002", "order-002"]}, {"replaced_by": "order-001"}, {"parent_order_id": "order-001"}):
            changed = copy.deepcopy(value); changed["orders"][0].update(mutation)
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(changed)
        changed = copy.deepcopy(value); changed["orders"][1]["leg_ids"] = ["order-001"]
        with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(changed)
        value["orders"].append(order_mapping())
        with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_snapshot_completeness_is_explicit_without_atomic_claim(self):
        value = snapshot_mapping()
        for field in value["completeness"]: value["completeness"][field] = False
        self.assertFalse(BrokerSnapshotInput.from_mapping(value).completeness["positions_complete"])
        for field, replacement in (("snapshot_atomic", True), ("provider_verified", True), ("sequential_capture", False), ("origin", "https://api.alpaca.markets")):
            value = snapshot_mapping(); value["capture_provenance"][field] = replacement
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)

    def test_retained_evidence_refs_require_safe_path_hash_and_size(self):
        for mutation in ({"path": "../secret"}, {"path": "/absolute"}, {"sha256": "short"}, {"size_bytes": True}, {"size_bytes": 64 * 1024 * 1024 + 1}):
            value = snapshot_mapping(); value["capture_provenance"]["source_evidence"].update(mutation)
            with self.assertRaises(ContractValidationError): BrokerSnapshotInput.from_mapping(value)
            rec = reconciliation_mapping(); rec["runtime_evidence"] = {"path": "runtime/prefix.json", "sha256": "a" * 64, "size_bytes": 1}; rec["runtime_evidence"].update(mutation)
            with self.assertRaises(ContractValidationError): ReconciliationInput.from_mapping(rec)

    def test_explicit_empty_desk_baseline_is_not_an_inferred_allocation(self):
        document = DeskOwnershipInput.from_mapping(ownership_mapping())
        self.assertEqual(document.desks, {"TRADING": [], "INVESTMENT": []})
        self.assertFalse(document.identity_authenticated)
        value = ownership_mapping(); value["desks"] = {"TRADING": ["AAA"], "INVESTMENT": ["BBB"]}
        DeskOwnershipInput.from_mapping(value)
        for desks in ({"TRADING": ["AAA"], "INVESTMENT": ["AAA"]}, {"TRADING": ["AAA", "AAA"], "INVESTMENT": []}, {"TRADING": ["aaa"], "INVESTMENT": []}):
            value = ownership_mapping(); value["desks"] = desks
            with self.assertRaises(ContractValidationError): DeskOwnershipInput.from_mapping(value)

    def test_declaration_identity_and_scope_never_authorized(self):
        for field, replacement in (("status", "AUTHORIZED"), ("identity_authenticated", True), ("mode", "LIVE"), ("declared_by", "../operator")):
            value = ownership_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): DeskOwnershipInput.from_mapping(value)

    def test_reconciliation_link_pairings_full_ids_and_prior_append_link(self):
        value = reconciliation_mapping(); value.update(ownership_event_id="journal-event-" + "f" * 64, ownership_sha256="a" * 64,
                                                        prior_reconciliation_event_id="journal-event-" + "1" * 64)
        ReconciliationInput.from_mapping(value)
        for mutation in ({"ownership_sha256": None}, {"ownership_event_id": None}, {"prior_reconciliation_event_id": "journal-event-short"},
                         {"broker_snapshot_sha256": "A" * 64}, {"broker_snapshot_event_id": "journal-decision-" + "a" * 64}):
            changed = copy.deepcopy(value); changed.update(mutation)
            with self.assertRaises(ContractValidationError): ReconciliationInput.from_mapping(changed)

    def test_no_pnl_live_orders_or_capital_changes_in_reconciliation(self):
        for field, replacement in (("realized_trade_pnl", "0"), ("realized_trade_pnl", 0), ("scope", "EXECUTION_AUTHORIZED"), ("mode", "LIVE"), ("order_submission_enabled", True)):
            value = reconciliation_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): ReconciliationInput.from_mapping(value)

    def test_snapshot_assessment_requires_exact_unclassified_inventory(self):
        value = snapshot_mapping(); value["positions"] = [position_mapping()]; value["orders"] = [order_mapping()]
        document = BrokerSnapshotInput.from_mapping(value); report = snapshot_assessment_mapping(document)
        validate_snapshot_assessment(report, document)
        for change in (lambda v: v.update(position_count=True), lambda v: v["position_classifications"][0].update(desk="TRADING"),
                       lambda v: v["order_classifications"][0].update(order_id="wrong"), lambda v: v.update(execution_observed=True)):
            changed = copy.deepcopy(report); change(changed)
            with self.assertRaises(ContractValidationError): validate_snapshot_assessment(changed, document)

    def test_ownership_assessment_follows_declaration_and_original_time(self):
        value = ownership_mapping(); value["desks"]["TRADING"] = ["AAA"]
        document = DeskOwnershipInput.from_mapping(value); report = ownership_assessment_mapping()
        report["baseline_positions"] = [{"symbol": "AAA", "desk": "TRADING", "qty": "2"}]
        validate_ownership_assessment(report, document)
        report["baseline_positions"][0]["desk"] = "INVESTMENT"
        with self.assertRaises(ContractValidationError): validate_ownership_assessment(report, document)
        report = ownership_assessment_mapping(); report["effective_at"] = "2026-10-13T00:00:00Z"
        with self.assertRaises(ContractValidationError): validate_ownership_assessment(report, document)

    def test_reports_forbid_pnl_authenticated_providers_and_authority(self):
        cases = ((validate_snapshot_assessment, snapshot_assessment_mapping, BrokerSnapshotInput.from_mapping(snapshot_mapping())),
                 (validate_ownership_assessment, ownership_assessment_mapping, DeskOwnershipInput.from_mapping(ownership_mapping())),
                 (validate_reconciliation_result, reconciliation_result_mapping, ReconciliationInput.from_mapping(reconciliation_mapping())))
        for validator, factory, document in cases:
            for field in ("execution_authority_granted", "readiness", "realized_trade_pnl"):
                value = factory(); value[field] = True if field != "realized_trade_pnl" else "0"
                with self.assertRaises(ContractValidationError): validator(value, document)
            value = factory(); value["authority"]["execution_enabled"] = True
            with self.assertRaises(ContractValidationError): validator(value, document)

    def test_restart_barrier_exact_unresolved_attempts_without_resubmission(self):
        document = ReconciliationInput.from_mapping(reconciliation_mapping()); report = reconciliation_result_mapping()
        attempt = {"attempt_sha256": "a" * 64, "session_id": "session-001", "symbol": "AAA", "side": "buy", "qty": "2",
            "order_id": None, "client_order_id": "session:AAA:001", "status": "ACCEPTANCE_UNKNOWN", "broker_status": None,
            "filled_qty": None, "filled_avg_price": None, "replacement_order_ids": []}
        report["attempts"] = [attempt]
        report["restart_barrier"]["unresolved_attempts"] = [{"attempt_sha256": "a" * 64, "order_id": None, "reason_code": "ACCEPTANCE_UNKNOWN"}]
        report["restart_barrier"]["entries_blocked"] = True
        validate_reconciliation_result(report, document)
        for mutation in ({"entries_blocked": False}, {"automatic_resubmission_enabled": True}, {"execution_authority_granted": True}):
            changed = copy.deepcopy(report); changed["restart_barrier"].update(mutation)
            with self.assertRaises(ContractValidationError): validate_reconciliation_result(changed, document)
        changed = copy.deepcopy(report); changed["restart_barrier"]["unresolved_attempts"][0]["attempt_sha256"] = "b" * 64
        with self.assertRaises(ContractValidationError): validate_reconciliation_result(changed, document)

    def test_reconciliation_never_classifies_without_ownership_or_fabricates_fills(self):
        document = ReconciliationInput.from_mapping(reconciliation_mapping()); report = reconciliation_result_mapping()
        report["positions"] = [{"symbol": "AAA", "desk": "UNCLASSIFIED", "qty": "2"}]
        validate_reconciliation_result(report, document)
        report["positions"][0]["desk"] = "TRADING"
        with self.assertRaises(ContractValidationError): validate_reconciliation_result(report, document)
        report = reconciliation_result_mapping(); report["execution_observed"] = True
        with self.assertRaises(ContractValidationError): validate_reconciliation_result(report, document)
        report = reconciliation_result_mapping(); report["limitations"] = []
        with self.assertRaises(ContractValidationError): validate_reconciliation_result(report, document)

    def test_v6_source_and_timestamp_binding_with_immutable_round_trip(self):
        for factory in (snapshot_event, ownership_event, reconciliation_event):
            value = factory(); document = JournalEvent.from_mapping(value)
            self.assertEqual(document.to_bytes(), JournalEvent.from_bytes(document.to_bytes()).to_bytes())
            for field, replacement in (("domain", "INVESTMENT"), ("recorded_at", "2026-10-13T00:00:00Z")):
                changed = copy.deepcopy(value); changed[field] = replacement
                with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(changed)
            changed = copy.deepcopy(value); changed["source"]["source_sha256"] = "0" * 64
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(changed)

    def test_v6_addition_does_not_broaden_old_versions(self):
        for factory in (snapshot_event, ownership_event, reconciliation_event):
            for version in (1, 2, 3, 4, 5, 7):
                value = factory(); value["schema_version"] = f"blackpod.decision_journal_event.v{version}"
                with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)
        from test_investment_governance_contracts import governance_event
        from blackpod_build_week.trading_automation import build_automation_event
        from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
        for value in (governance_event(), build_automation_event(TradingAutomationControl.from_bytes(
            (Path(__file__).resolve().parents[1] / "examples/auto_trading.control.off.v1.json").read_bytes())).to_dict()):
            original = JournalEvent.from_mapping(value).to_bytes()
            self.assertEqual(original, canonical_json_bytes(value))
            value["schema_version"] = JOURNAL_EVENT_V6_SCHEMA_VERSION
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_bounded_parser_errors_nonfinite_duplicate_fields_and_deep_json(self):
        for contract in (BrokerSnapshotInput, DeskOwnershipInput, ReconciliationInput):
            for source in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'\xff', b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
                with self.assertRaises(ContractValidationError): contract.from_bytes(source)


if __name__ == "__main__": unittest.main()
