"""Offline contract tests: no providers, inference, broker, or source writes."""

from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from blackpod_build_week.contracts.decision_journal import (
    CAPITAL_POLICY_SCHEMA_VERSION,
    EVALUATION_SCHEMA_VERSION,
    JOURNAL_EVENT_SCHEMA_VERSION,
    CapitalPolicyProposal,
    EvaluationInput,
    JournalEvent,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes

DECISION_ID = "journal-decision-" + "a" * 64


def mission_event() -> dict:
    return {
        "schema_version": JOURNAL_EVENT_SCHEMA_VERSION,
        "event_id": "journal-event-" + "b" * 64,
        "decision_id": DECISION_ID,
        "domain": "UNCLASSIFIED",
        "event_type": "MISSION_SNAPSHOT_RECORDED",
        "recorded_at": "2026-10-11T00:00:00Z",
        "source": {
            "kind": "MISSION", "mission_id": "mission-test-001", "request_id": "request-test-001",
            "run_mode": "REPLAY", "revision": 1, "source_sha256": "c" * 64,
        },
        "evidence": [{"path": "snapshots/000001.json", "sha256": "c" * 64, "size_bytes": 0}],
        "payload": {
            "classification": {"basis": "HISTORICAL_UNCLASSIFIED", "reason": "Historical mission does not identify a desk."},
            "symbol": "AAPL", "mission_outcome": "HELD", "current_phase": "COMPLETE", "terminal": True,
            "stages": [{"name": "governor", "status": "SUCCEEDED", "native_state": "BLOCKED"}],
            "decision": {"disposition": "BLOCKED", "authority": "GOVERNOR", "decision_id": "governor-decision-001"},
            "authorization": {"status": "NOT_RECORDED", "scope": None, "operator_id": None, "action_id": None},
            "execution_status": "NOT_EXECUTED",
            "historical_semantics": {field: "NOT_RECORDED" for field in ("hypothesis", "expectations", "investment_horizon", "confidence_probability", "evaluation")},
        },
    }


def evaluation_input(**overrides) -> dict:
    result = {
        "schema_version": EVALUATION_SCHEMA_VERSION, "evaluation_id": "evaluation-001", "decision_id": DECISION_ID,
        "recorded_at": "2026-10-12T00:00:00Z", "evaluator": "operator-test-001", "evaluation_type": "PROCESS",
        "conclusion": "Governor correctly retained a blocked disposition.", "outcome_status": "OBSERVED", "realized_trade_pnl": None,
    }
    result.update(overrides)
    return result


def evaluation_event(**overrides) -> dict:
    evaluation = EvaluationInput.from_mapping(evaluation_input(**overrides)).to_dict()
    return {
        "schema_version": JOURNAL_EVENT_SCHEMA_VERSION, "event_id": "journal-event-" + "d" * 64,
        "decision_id": DECISION_ID, "domain": "UNCLASSIFIED", "event_type": "EVALUATION_RECORDED",
        "recorded_at": evaluation["recorded_at"],
        "source": {"kind": "EVALUATION", "evaluation_id": evaluation["evaluation_id"], "source_sha256": sha256_bytes(canonical_json_bytes(evaluation))},
        "evidence": [], "payload": {**evaluation, "execution_status": "NOT_EXECUTED"},
    }


def capital_policy() -> dict:
    return {
        "schema_version": CAPITAL_POLICY_SCHEMA_VERSION, "policy_id": "initial-two-desk-50-50", "proposed_at": "2026-10-11T00:00:00Z",
        "status": "PROPOSED", "allocations": {"TRADING": 0.5, "INVESTMENT": 0.5},
        "allocation_basis": "ACCOUNT_EQUITY", "rebalance_mode": "INITIAL_ALLOCATION_ONLY",
        "activation_enabled": False, "capital_transfers_enabled": False, "automated_reallocation_enabled": False,
        "consolidated_account_risk_required": True, "subsequent_changes_require_explicit_authorization": True,
    }


def policy_event() -> dict:
    policy = CapitalPolicyProposal.from_mapping(capital_policy()).to_dict()
    return {
        "schema_version": JOURNAL_EVENT_SCHEMA_VERSION, "event_id": "journal-event-" + "e" * 64,
        "decision_id": DECISION_ID, "domain": "CAPITAL_ALLOCATION", "event_type": "CAPITAL_POLICY_PROPOSED",
        "recorded_at": policy["proposed_at"],
        "source": {"kind": "CAPITAL_POLICY", "policy_id": policy["policy_id"], "source_sha256": sha256_bytes(canonical_json_bytes(policy))},
        "evidence": [], "payload": policy,
    }


class JournalEventContractTests(unittest.TestCase):
    def test_historical_unclassified_and_canonical_round_trip(self):
        event = JournalEvent.from_mapping(mission_event())
        self.assertEqual(event.domain, "UNCLASSIFIED")
        self.assertEqual(event.to_bytes(), canonical_json_bytes(event.to_dict()))
        self.assertEqual(JournalEvent.from_bytes(event.to_bytes()), event)
        self.assertEqual(event.to_mapping(), event.to_dict())

    def test_each_explicit_domain_requires_provenance_reason(self):
        for domain in ("TRADING", "INVESTMENT", "CAPITAL_ALLOCATION"):
            with self.subTest(domain=domain):
                value = mission_event()
                value["domain"] = domain
                with self.assertRaises(ContractValidationError):
                    JournalEvent.from_mapping(value)
                value["payload"]["classification"] = {"basis": "EXPLICIT_IMPORT_CLASSIFICATION", "reason": "Explicit operator import classification."}
                self.assertEqual(JournalEvent.from_mapping(value).domain, domain)
                value["payload"]["classification"]["reason"] = " "
                with self.assertRaises(ContractValidationError):
                    JournalEvent.from_mapping(value)

    def test_nested_data_are_immutable_and_defensively_copied(self):
        value = mission_event()
        event = JournalEvent.from_mapping(value)
        before = event.to_bytes()
        value["payload"]["decision"]["disposition"] = "PROCEED"
        event.payload["decision"]["disposition"] = "PROCEED"
        event.evidence[0]["path"] = "changed"
        event.to_dict()["source"]["revision"] = 99
        self.assertEqual(event.to_bytes(), before)
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            event._canonical_bytes = b"changed"

    def test_rejects_unknown_or_missing_fields_at_every_level(self):
        locations = [(), ("source",), ("payload",), ("payload", "classification"), ("payload", "decision"), ("payload", "authorization"), ("payload", "historical_semantics"), ("evidence", 0), ("payload", "stages", 0)]
        for location in locations:
            for mutation in ("unknown", "missing"):
                with self.subTest(location=location, mutation=mutation):
                    value = mission_event()
                    target = value
                    for key in location:
                        target = target[key]
                    if mutation == "unknown":
                        target["unexpected"] = "value"
                    else:
                        target.pop(next(iter(target)))
                    with self.assertRaises(ContractValidationError):
                        JournalEvent.from_mapping(value)

    def test_strict_json_rejects_duplicates_constants_encoding_and_root(self):
        for source in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'[]', b'\xff', b'{'):
            with self.subTest(source=source), self.assertRaises(ContractValidationError):
                JournalEvent.from_bytes(source)
        value = mission_event()
        source = canonical_json_bytes(value).replace(b'"revision": 1', b'"revision": 1, "revision": 1')
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_bytes(source)

    def test_version_and_identity_validation(self):
        for field, bad in (("schema_version", "blackpod.decision_journal_event.v2"), ("domain", "ALL"), ("event_type", "ORDER_SUBMITTED"), ("event_id", "journal-event-abc"), ("decision_id", "journal-decision-" + "A" * 64)):
            value = mission_event()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_booleans_are_not_integer_fields(self):
        for field in ("revision", "size_bytes"):
            value = mission_event()
            (value["source"] if field == "revision" else value["evidence"][0])[field] = True
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        value = mission_event()
        value["payload"]["terminal"] = 1
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)

    def test_evidence_paths_hashes_and_duplicates_are_strict(self):
        for path in ("/absolute", "../escape", "a/../b", "a/./b", "a//b", "a\\b", "C:/path", "a/", "a\x00b"):
            value = mission_event()
            value["evidence"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        for field, bad in (("sha256", "C" * 64), ("size_bytes", -1), ("size_bytes", 0.1)):
            value = mission_event()
            value["evidence"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        value = mission_event()
        value["evidence"].append(copy.deepcopy(value["evidence"][0]))
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_mapping(value)

    def test_timestamps_normalize_but_require_timezone(self):
        value = mission_event()
        value["recorded_at"] = "2026-10-10T17:00:00-07:00"
        self.assertEqual(JournalEvent.from_mapping(value).recorded_at, "2026-10-11T00:00:00Z")
        for timestamp in ("2026-10-11T00:00:00", "2026-02-30T00:00:00Z", "2026-10-11"):
            value["recorded_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_shadow_is_not_trading_authorization(self):
        value = mission_event()
        value["payload"]["execution_status"] = "SHADOW_ONLY"
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)
        value["payload"]["authorization"] = {"status": "SHADOW_APPROVED", "scope": "NAVIGATOR_SHADOW_HANDOFF", "operator_id": "operator-001", "action_id": "action-001"}
        self.assertEqual(JournalEvent.from_mapping(value).payload["execution_status"], "SHADOW_ONLY")
        for field, bad in (("scope", "TRADE"), ("scope", None), ("operator_id", None), ("action_id", None), ("status", "TRADE_APPROVED")):
            bad_value = copy.deepcopy(value)
            bad_value["payload"]["authorization"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(bad_value)

    def test_missing_historical_semantics_cannot_be_invented(self):
        for field, invented in (("hypothesis", "Rates will fall."), ("expectations", "Positive returns."), ("investment_horizon", "1Y"), ("confidence_probability", 0.9), ("evaluation", "SUCCESS")):
            value = mission_event()
            value["payload"]["historical_semantics"][field] = invented
            with self.subTest(field=field), self.assertRaisesRegex(ContractValidationError, "NOT_RECORDED"):
                JournalEvent.from_mapping(value)

    def test_stage_and_source_duplicates_types(self):
        value = mission_event()
        value["payload"]["stages"].append(copy.deepcopy(value["payload"]["stages"][0]))
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_mapping(value)
        for field, bad in (("kind", "EVALUATION"), ("run_mode", "PAPER"), ("revision", 0), ("source_sha256", "bad")):
            value = mission_event()
            value["source"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)


class EvaluationContractTests(unittest.TestCase):
    def test_valid_evaluation_round_trip(self):
        evaluation = EvaluationInput.from_mapping(evaluation_input())
        self.assertEqual(EvaluationInput.from_bytes(evaluation.to_bytes()), evaluation)
        event = JournalEvent.from_mapping(evaluation_event())
        self.assertEqual(event.payload["realized_trade_pnl"], None)

    def test_nonexecuted_and_shadow_cannot_have_trade_pnl(self):
        for status in ("NOT_EXECUTED", "SHADOW_ONLY"):
            for pnl in (None, 0, 100.0, -5.0):
                value = evaluation_event(evaluation_type="TRADE", realized_trade_pnl=pnl)
                value["payload"]["execution_status"] = status
                with self.subTest(status=status, pnl=pnl), self.assertRaisesRegex(ContractValidationError, "cannot have"):
                    JournalEvent.from_mapping(value)

    def test_counterfactual_is_distinct_from_realized_profit(self):
        event = JournalEvent.from_mapping(evaluation_event(evaluation_type="COUNTERFACTUAL", conclusion="Counterfactual observation only."))
        self.assertEqual(event.payload["evaluation_type"], "COUNTERFACTUAL")
        with self.assertRaises(ContractValidationError):
            EvaluationInput.from_mapping(evaluation_input(evaluation_type="COUNTERFACTUAL", realized_trade_pnl=5))

    def test_nan_infinity_booleans_and_unbounded_text_rejected(self):
        for pnl in (float("nan"), float("inf"), True, "5"):
            with self.subTest(pnl=pnl), self.assertRaises(ContractValidationError):
                EvaluationInput.from_mapping(evaluation_input(evaluation_type="TRADE", realized_trade_pnl=pnl))
        for conclusion in ("", " ", "x" * 10001):
            with self.subTest(length=len(conclusion)), self.assertRaises(ContractValidationError):
                EvaluationInput.from_mapping(evaluation_input(conclusion=conclusion))

    def test_link_timestamp_and_source_hash_must_match(self):
        for location, field, bad in (("source", "evaluation_id", "evaluation-other"), ("source", "source_sha256", "a" * 64), (None, "decision_id", "journal-decision-" + "b" * 64), (None, "recorded_at", "2026-10-13T00:00:00Z")):
            value = evaluation_event()
            (value if location is None else value[location])[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_unknown_evaluation_fields_are_rejected(self):
        for factory, value in ((EvaluationInput, evaluation_input()), (JournalEvent, evaluation_event())):
            target = value if factory is EvaluationInput else value["payload"]
            target["hypothesis"] = "invented"
            with self.subTest(factory=factory), self.assertRaises(ContractValidationError):
                factory.from_mapping(value)


class CapitalPolicyContractTests(unittest.TestCase):
    def test_baseline_example_is_valid_and_inactive(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "capital_policy.proposed.v1.json"
        policy = CapitalPolicyProposal.from_bytes(example.read_bytes())
        self.assertEqual(policy.to_dict(), capital_policy())
        self.assertEqual(policy.allocations, {"INVESTMENT": 0.5, "TRADING": 0.5})
        self.assertFalse(policy.activation_enabled)
        self.assertFalse(policy.capital_transfers_enabled)
        self.assertFalse(policy.automated_reallocation_enabled)
        self.assertEqual(policy.rebalance_mode, "INITIAL_ALLOCATION_ONLY")
        self.assertEqual(JournalEvent.from_mapping(policy_event()).domain, "CAPITAL_ALLOCATION")

    def test_activation_transfer_and_rebalance_are_disabled_constants(self):
        overrides = {"activation_enabled": True, "capital_transfers_enabled": True, "automated_reallocation_enabled": True, "consolidated_account_risk_required": False, "subsequent_changes_require_explicit_authorization": False, "status": "ACTIVE", "rebalance_mode": "PERPETUAL_50_50", "policy_id": "other", "allocation_basis": "CASH", "schema_version": "blackpod.capital_policy_proposal.v2"}
        for field, bad in overrides.items():
            value = capital_policy()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                CapitalPolicyProposal.from_mapping(value)

    def test_allocations_are_exact_finite_nonboolean_fractions(self):
        for fraction in (True, 50, 0.4, "0.5", float("nan"), float("inf"), -0.5):
            value = capital_policy()
            value["allocations"]["TRADING"] = fraction
            with self.subTest(fraction=fraction), self.assertRaises(ContractValidationError):
                CapitalPolicyProposal.from_mapping(value)
        value = capital_policy()
        value["allocations"]["CAPITAL_ALLOCATION"] = 0
        with self.assertRaises(ContractValidationError):
            CapitalPolicyProposal.from_mapping(value)

    def test_boolean_constants_require_boolean_types(self):
        for field in ("activation_enabled", "capital_transfers_enabled", "automated_reallocation_enabled", "consolidated_account_risk_required", "subsequent_changes_require_explicit_authorization"):
            value = capital_policy()
            value[field] = int(value[field])
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                CapitalPolicyProposal.from_mapping(value)

    def test_policy_source_domain_and_timestamp_are_bound(self):
        for location, field, bad in ((None, "domain", "TRADING"), (None, "recorded_at", "2026-10-12T00:00:00Z"), ("source", "policy_id", "other"), ("source", "source_sha256", "a" * 64)):
            value = policy_event()
            (value if location is None else value[location])[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_proposal_time_is_canonical_not_a_perpetual_policy_date(self):
        value = capital_policy()
        value["proposed_at"] = "2026-10-12T11:00:00-07:00"
        self.assertEqual(CapitalPolicyProposal.from_mapping(value).proposed_at, "2026-10-12T18:00:00Z")


if __name__ == "__main__":
    unittest.main()
