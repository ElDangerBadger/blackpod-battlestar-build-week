"""Deterministic SHADOW draft and version-isolation tests, without inference."""

from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError

from blackpod_build_week.contracts.decision_journal import (
    INVESTMENT_HYPOTHESIS_EVENT_TYPE,
    JOURNAL_EVENT_SCHEMA_VERSION,
    JOURNAL_EVENT_V2_SCHEMA_VERSION,
    JournalEvent,
)
from blackpod_build_week.contracts.investment_hypothesis import (
    INVESTMENT_HYPOTHESIS_SCHEMA_VERSION,
    InvestmentHypothesis,
    validate_json_pointer,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


def hypothesis_mapping() -> dict:
    """Contract-only fixture; source hashes are placeholders, not verified evidence."""
    return {
        "schema_version": INVESTMENT_HYPOTHESIS_SCHEMA_VERSION,
        "hypothesis_id": "hypothesis-001", "recorded_at": "2026-10-11T00:00:00Z",
        "author_id": "researcher-001", "domain": "INVESTMENT", "mode": "SHADOW", "status": "SHADOW_DRAFT",
        "research_mode": "PROSPECTIVE", "evidence_cutoff_at": "2026-10-11T00:00:00Z",
        "scope": {"kind": "SECTOR", "identifiers": ["technology"]},
        "observations": [{
            "observation_id": "observation-001", "source_event_id": "journal-event-" + "a" * 64,
            "artifact_path": "oracle/attempt-0001/context.json", "artifact_sha256": "b" * 64,
            "value_pointer": "/metrics/growth", "value": 3.5, "unit": "percent",
            "as_of_pointer": "/as_of", "as_of": "2026-10-10T00:00:00Z", "time_role": "AS_OF",
        }],
        "hypothesis": {
            "statement": "Observed growth may persist through the review horizon.",
            "causal_mechanism": "Recurring demand could support continued growth.",
            "assumptions": ["The measurement definition remains stable."],
            "observation_ids": ["observation-001"],
        },
        "horizon": {"start_at": "2026-10-11T00:00:00Z", "review_at": "2026-11-11T00:00:00Z", "end_at": "2027-01-11T00:00:00Z"},
        "expected_outcomes": [{
            "outcome_id": "outcome-001", "description": "Growth remains positive.",
            "metric": "growth", "unit": "percent", "operator": "GT", "threshold": 0,
            "due_at": "2027-01-11T00:00:00Z",
        }],
        "alternatives": [{
            "alternative_id": "alternative-001", "statement": "Growth could reflect temporary demand.",
            "distinguishing_observation": "Subsequent measurements reverse after demand normalizes.",
            "observation_ids": ["observation-001"],
        }],
        "invalidation_conditions": [{
            "condition_id": "condition-001", "description": "Growth turns negative.",
            "metric": "growth", "unit": "percent", "operator": "LT", "threshold": 0,
            "check_by": "2027-01-11T00:00:00Z",
        }],
        "evaluation_plan": {
            "plan_id": "plan-001", "method": "MANUAL_SOURCE_BOUND_REVIEW", "evaluate_at": "2027-01-11T00:00:00Z",
            "outcome_ids": ["outcome-001"], "condition_ids": ["condition-001"],
            "success_rule": "ALL_EXPECTED_OUTCOMES_AND_NO_INVALIDATION", "missing_data_policy": "INCONCLUSIVE",
            "evaluator_role": "investment-research-reviewer",
        },
        "authority": {"authorization_enabled": False, "capital_activation_enabled": False,
                      "execution_enabled": False, "policy_changes_enabled": False},
    }


def hypothesis_event() -> dict:
    payload = InvestmentHypothesis.from_mapping(hypothesis_mapping()).to_dict()
    return {
        "schema_version": JOURNAL_EVENT_V2_SCHEMA_VERSION, "event_type": INVESTMENT_HYPOTHESIS_EVENT_TYPE,
        "event_id": "journal-event-" + "c" * 64, "decision_id": "journal-decision-" + "d" * 64,
        "domain": "INVESTMENT", "recorded_at": payload["recorded_at"],
        "source": {"kind": "INVESTMENT_HYPOTHESIS", "hypothesis_id": payload["hypothesis_id"],
                   "source_sha256": sha256_bytes(canonical_json_bytes(payload))},
        "evidence": [], "payload": payload,
    }


class InvestmentHypothesisContractTests(unittest.TestCase):
    def test_canonical_immutable_round_trip(self):
        value = hypothesis_mapping()
        document = InvestmentHypothesis.from_mapping(value)
        before = document.to_bytes()
        value["hypothesis"]["statement"] = "changed"
        document.hypothesis["statement"] = "changed"
        document.to_dict()["observations"][0]["value"] = 999
        self.assertEqual(document.to_bytes(), before)
        self.assertEqual(InvestmentHypothesis.from_bytes(before), document)
        self.assertEqual(document.to_bytes(), canonical_json_bytes(document.to_dict()))
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            document._canonical_bytes = b"changed"

    def test_unknown_and_missing_fields_at_each_level(self):
        locations = [(), ("scope",), ("observations", 0), ("hypothesis",), ("horizon",),
                     ("expected_outcomes", 0), ("alternatives", 0), ("invalidation_conditions", 0),
                     ("evaluation_plan",), ("authority",)]
        for location in locations:
            for change in ("unknown", "missing"):
                value = hypothesis_mapping()
                target = value
                for key in location:
                    target = target[key]
                if change == "unknown":
                    target["order"] = "BUY"
                else:
                    target.pop(next(iter(target)))
                with self.subTest(location=location, change=change), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)

    def test_strict_bytes_reject_duplicates_nan_encoding_and_nonobjects(self):
        for source in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'[]', b'\xff', b'{'):
            with self.subTest(source=source), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_bytes(source)
        source = canonical_json_bytes(hypothesis_mapping()).replace(b'"unit": "percent"', b'"unit": "percent", "unit": "percent"', 1)
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            InvestmentHypothesis.from_bytes(source)

    def test_excessive_json_nesting_is_a_contract_error(self):
        source = b'{"observations":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'
        with self.assertRaisesRegex(ContractValidationError, "nesting"):
            InvestmentHypothesis.from_bytes(source)

    def test_disabled_authority_and_no_order_budget_probability_fields(self):
        for field in hypothesis_mapping()["authority"]:
            for bad in (True, 0, None, "false"):
                value = hypothesis_mapping()
                value["authority"][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)
        for field in ("order", "allocation", "capital_budget", "confidence_probability", "forecast"):
            value = hypothesis_mapping()
            value[field] = 0.9
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_fixed_domain_mode_status_and_research_modes(self):
        for field, bad in (("schema_version", "v2"), ("domain", "TRADING"), ("mode", "LIVE"), ("status", "AUTHORIZED"), ("research_mode", "INFERRED")):
            value = hypothesis_mapping()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_identifiers_and_text_are_strict(self):
        for field in ("hypothesis_id", "author_id"):
            for bad in ("", "../escape", " padded", "space here", "x" * 129, 1):
                value = hypothesis_mapping()
                value[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)
        for bad in ("", " ", " padded", "a\x00b", "\ud800", 3):
            value = hypothesis_mapping()
            value["hypothesis"]["statement"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_nonempty_lists_and_unique_ids(self):
        for field in ("observations", "expected_outcomes", "alternatives", "invalidation_conditions"):
            for bad in ([], {}, None):
                value = hypothesis_mapping()
                value[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)
            value = hypothesis_mapping()
            value[field].append(copy.deepcopy(value[field][0]))
            with self.subTest(field=field), self.assertRaisesRegex(ContractValidationError, "duplicate"):
                InvestmentHypothesis.from_mapping(value)
        for location in (("scope", "identifiers"), ("hypothesis", "assumptions"), ("hypothesis", "observation_ids"),
                         ("evaluation_plan", "outcome_ids"), ("evaluation_plan", "condition_ids")):
            value = hypothesis_mapping()
            value[location[0]][location[1]] *= 2
            with self.subTest(location=location), self.assertRaisesRegex(ContractValidationError, "duplicate"):
                InvestmentHypothesis.from_mapping(value)

    def test_observation_references_and_complete_evaluation_plan(self):
        for location in (("hypothesis",), ("alternatives", 0)):
            value = hypothesis_mapping()
            target = value
            for key in location:
                target = target[key]
            target["observation_ids"] = ["missing"]
            with self.subTest(location=location), self.assertRaisesRegex(ContractValidationError, "unknown"):
                InvestmentHypothesis.from_mapping(value)
        for field in ("outcome_ids", "condition_ids"):
            value = hypothesis_mapping()
            value["evaluation_plan"][field] = ["missing"]
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)
        for field in ("method", "success_rule", "missing_data_policy"):
            value = hypothesis_mapping()
            value["evaluation_plan"][field] = "AUTOMATIC"
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_pointer_syntax_and_safe_paths(self):
        for valid in ("", "/", "/metrics/growth", "/a~0b/~1", "/~01", "/a b"):
            self.assertEqual(validate_json_pointer(valid), valid)
        for bad in ("growth", "#/growth", "/~", "/~2", "/~x", 0, "\ud800"):
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                validate_json_pointer(bad)
        for bad in ("/absolute", "a/../b", "a//b", "a\\b", "a:"):
            value = hypothesis_mapping()
            value["observations"][0]["artifact_path"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_observation_source_ids_hashes_and_time_roles(self):
        for field, bad in (("source_event_id", "journal-event-short"),
                           ("source_event_id", "journal-decision-" + "a" * 64),
                           ("artifact_sha256", "A" * 64), ("time_role", "INFERRED"),
                           ("as_of", "2026-10-10"), ("unit", "")):
            value = hypothesis_mapping()
            value["observations"][0][field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_observation_scalar_is_exact_finite_json(self):
        for valid in (True, False, None, 0, 3.5, "", "growth"):
            value = hypothesis_mapping()
            value["observations"][0]["value"] = valid
            self.assertEqual(InvestmentHypothesis.from_mapping(value).observations[0]["value"], valid)
        for bad in ([], {}, float("nan"), float("inf"), "\ud800"):
            value = hypothesis_mapping()
            value["observations"][0]["value"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)

    def test_metric_comparison_thresholds_and_boolean_rejection(self):
        for field in ("expected_outcomes", "invalidation_conditions"):
            for bad in (True, False, None, float("nan"), float("inf"), "positive", [], {}):
                value = hypothesis_mapping()
                value[field][0]["threshold"] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)
            for operator in ("EQ", "NE"):
                value = hypothesis_mapping()
                value[field][0].update(operator=operator, threshold="positive")
                self.assertEqual(InvestmentHypothesis.from_mapping(value).to_dict()[field][0]["threshold"], "positive")

    def test_timestamps_normalize_and_prospective_rejects_lookahead(self):
        value = hypothesis_mapping()
        for field in ("recorded_at", "evidence_cutoff_at"):
            value[field] = "2026-10-10T17:00:00-07:00"
        self.assertEqual(InvestmentHypothesis.from_mapping(value).recorded_at, "2026-10-11T00:00:00Z")
        value = hypothesis_mapping()
        value["observations"][0]["as_of"] = "2026-10-11T00:00:00.000001Z"
        with self.assertRaisesRegex(ContractValidationError, "after evidence"):
            InvestmentHypothesis.from_mapping(value)
        value = hypothesis_mapping()
        value["recorded_at"] = "2026-10-12T00:00:00Z"
        with self.assertRaisesRegex(ContractValidationError, "PROSPECTIVE"):
            InvestmentHypothesis.from_mapping(value)
        value["research_mode"] = "RETROSPECTIVE"
        self.assertEqual(InvestmentHypothesis.from_mapping(value).research_mode, "RETROSPECTIVE")
        value["recorded_at"] = "2026-10-09T00:00:00Z"
        with self.assertRaises(ContractValidationError):
            InvestmentHypothesis.from_mapping(value)

    def test_horizon_and_fixed_evaluation_dates(self):
        for field, bad in (("start_at", "2026-10-12T00:00:00Z"), ("review_at", "2026-10-11T00:00:00Z"), ("end_at", "2026-11-10T00:00:00Z")):
            value = hypothesis_mapping()
            value["horizon"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                InvestmentHypothesis.from_mapping(value)
        value = hypothesis_mapping()
        value["evaluation_plan"]["evaluate_at"] = "2027-01-12T00:00:00Z"
        with self.assertRaises(ContractValidationError):
            InvestmentHypothesis.from_mapping(value)
        for collection, field in (("expected_outcomes", "due_at"), ("invalidation_conditions", "check_by")):
            for bad in ("2026-10-11T00:00:00Z", "2027-01-12T00:00:00Z", "invalid"):
                value = hypothesis_mapping()
                value[collection][0][field] = bad
                with self.subTest(collection=collection, bad=bad), self.assertRaises(ContractValidationError):
                    InvestmentHypothesis.from_mapping(value)

    def test_no_arbitrary_minimum_horizon_and_historical_cutoff_allowed(self):
        value = hypothesis_mapping()
        value["horizon"].update(review_at="2026-10-11T00:00:00.000001Z", end_at="2026-10-11T00:00:00.000002Z")
        value["expected_outcomes"][0]["due_at"] = value["horizon"]["end_at"]
        value["invalidation_conditions"][0]["check_by"] = value["horizon"]["end_at"]
        value["evaluation_plan"]["evaluate_at"] = value["horizon"]["end_at"]
        self.assertEqual(InvestmentHypothesis.from_mapping(value).horizon, value["horizon"])
        value = hypothesis_mapping()
        value.update(research_mode="RETROSPECTIVE", recorded_at="2027-02-11T00:00:00Z")
        self.assertEqual(InvestmentHypothesis.from_mapping(value).recorded_at, value["recorded_at"])


class HypothesisJournalV2Tests(unittest.TestCase):
    def test_v2_round_trip_and_no_authority(self):
        event = JournalEvent.from_mapping(hypothesis_event())
        self.assertEqual(JournalEvent.from_bytes(event.to_bytes()), event)
        self.assertEqual(event.domain, "INVESTMENT")
        self.assertTrue(all(value is False for value in event.payload["authority"].values()))

    def test_v1_cannot_contain_hypotheses(self):
        value = hypothesis_event()
        value["schema_version"] = JOURNAL_EVENT_SCHEMA_VERSION
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)

    def test_v2_does_not_reinterpret_v1_event_types(self):
        for kind in ("MISSION_SNAPSHOT_RECORDED", "EVALUATION_RECORDED", "CAPITAL_POLICY_PROPOSED", "ORDER_SUBMITTED"):
            value = hypothesis_event()
            value["event_type"] = kind
            with self.subTest(kind=kind), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_v2_domain_identity_time_and_source_hash_are_strict(self):
        changes = [("domain", "TRADING"), ("event_id", "short"), ("decision_id", "../escape"),
                   ("recorded_at", "2026-10-12T00:00:00Z")]
        for field, bad in changes:
            value = hypothesis_event()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        for field, bad in (("kind", "MISSION"), ("hypothesis_id", "different-id"), ("source_sha256", "a" * 64)):
            value = hypothesis_event()
            value["source"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        value = hypothesis_event()
        value["source"]["scope"] = "TRADE"
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
