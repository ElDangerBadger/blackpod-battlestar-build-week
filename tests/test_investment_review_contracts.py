"""Offline contract and version isolation tests for SHADOW reviews."""

from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError

from blackpod_build_week.contracts.decision_journal import (
    INVESTMENT_CHALLENGE_EVENT_TYPE, INVESTMENT_OUTCOME_EVALUATION_EVENT_TYPE,
    JOURNAL_EVENT_V3_SCHEMA_VERSION, JournalEvent,
)
from blackpod_build_week.contracts.investment_review import (
    ChallengeInput, OutcomeEvaluationInput, INVESTMENT_CHALLENGE_SCHEMA_VERSION,
    INVESTMENT_OUTCOME_EVALUATION_SCHEMA_VERSION, ASSESSMENT_METHOD_VERSION, COMPARISON_METHOD_VERSION,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


def authority() -> dict:
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def observation_mapping() -> dict:
    """Contract fixture uses placeholder hashes; it is not verified evidence."""
    return {
        "observation_id": "observation-001", "source_event_id": "journal-event-" + "a" * 64,
        "artifact_path": "research/observation.json", "artifact_sha256": "b" * 64,
        "value_pointer": "/metrics/growth", "value": 3.5, "unit": "percent",
        "as_of_pointer": "/as_of", "as_of": "2026-10-10T00:00:00Z", "time_role": "AS_OF",
    }


def _common() -> dict:
    return {
        "hypothesis_event_id": "journal-event-" + "c" * 64,
        "hypothesis_id": "hypothesis-001", "hypothesis_sha256": "d" * 64,
        "recorded_at": "2026-10-11T00:00:00Z", "domain": "INVESTMENT", "mode": "SHADOW",
        "evidence_cutoff_at": "2026-10-11T00:00:00Z", "supersedes_event_id": None,
        "authority": authority(),
    }


def challenge_mapping() -> dict:
    return {
        **_common(), "schema_version": INVESTMENT_CHALLENGE_SCHEMA_VERSION,
        "challenge_id": "challenge-001", "reviewer_id": "reviewer-002",
        "observations": [{**observation_mapping(), "evidence_role": "FUNDAMENTAL", "provenance_group": "filing-series"}],
        "assumption_reviews": [{"assumption_index": 0, "status": "CONTESTED",
                                "reason": "Measurement definitions may have changed.",
                                "observation_ids": ["observation-001"]}],
        "counter_hypotheses": [{"counter_id": "counter-001", "statement": "A changed definition could explain growth.",
                                "discriminating_test": "Compare measures with unchanged definitions.",
                                "observation_ids": ["observation-001"]}],
        "disposition": "REVIEW_CONTESTS", "unresolved_questions": [], "risk_notes": [],
    }


def evaluation_mapping() -> dict:
    return {
        **_common(), "schema_version": INVESTMENT_OUTCOME_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": "evaluation-001", "challenge_event_id": "journal-event-" + "e" * 64,
        "evaluator_id": "evaluator-002", "evaluator_role": "investment-research-reviewer", "evaluation_stage": "INTERIM",
        "measurements": [{"check_type": "OUTCOME", "check_id": "outcome-001", "metric": "growth",
                          "unit": "percent", "observation": observation_mapping()}],
        "conclusion": "This point observation needs review against the fixed plan.",
    }


def assessment_mapping() -> dict:
    return {
        "assessment_method_version": ASSESSMENT_METHOD_VERSION,
        "reviewer_distinct": True, "reviewer_identity_authenticated": False,
        "source_relationships": [{"observation_id": "observation-001", "relationship": "SHARED_ARTIFACT",
                                  "independence_verified": False, "evidence_role": "FUNDAMENTAL", "provenance_group": "filing-series"}],
        "declared_evidence_roles": ["FUNDAMENTAL"], "missing_evidence_roles": ["STATISTICAL"],
        "source_independence_verified": False, "economic_truth_evaluated": False,
        "execution_status": "NOT_EXECUTED", "authority": authority(),
    }


def result_mapping() -> dict:
    return {
        "comparison_method_version": COMPARISON_METHOD_VERSION,
        "plan_id": "plan-001", "evaluation_stage": "INTERIM", "comparison_summary": "PENDING",
        "check_results": [{"check_type": "OUTCOME", "check_id": "outcome-001", "status": "NOT_DUE",
                           "metric": "growth", "unit": "percent", "due_at": "2027-01-11T00:00:00Z",
                           "observed_value": None, "observation_id": None}],
        "measurement_basis": "RECORDED_DEADLINE_POINTS_ONLY", "whole_horizon_invalidation_established": False,
        "manual_review_required": True, "hypothesis_research_mode": "PROSPECTIVE", "economic_truth_evaluated": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "authority": authority(),
    }


def _event(document: dict, event_type: str, input_key: str, report_key: str, report: dict, identity: str) -> dict:
    contract = ChallengeInput if input_key == "challenge" else OutcomeEvaluationInput
    normalized = contract.from_mapping(document)
    return {
        "schema_version": JOURNAL_EVENT_V3_SCHEMA_VERSION, "event_id": "journal-event-" + "f" * 64,
        "decision_id": "journal-decision-" + "1" * 64, "domain": "INVESTMENT", "event_type": event_type,
        "recorded_at": normalized.recorded_at, "source": {
            "kind": "INVESTMENT_CHALLENGE" if input_key == "challenge" else "INVESTMENT_OUTCOME_EVALUATION",
            identity: getattr(normalized, identity), "source_sha256": sha256_bytes(normalized.to_bytes()),
        }, "evidence": [], "payload": {input_key: normalized.to_dict(), report_key: report},
    }


def challenge_event() -> dict:
    return _event(challenge_mapping(), INVESTMENT_CHALLENGE_EVENT_TYPE, "challenge", "assessment", assessment_mapping(), "challenge_id")


def evaluation_event() -> dict:
    return _event(evaluation_mapping(), INVESTMENT_OUTCOME_EVALUATION_EVENT_TYPE, "evaluation", "result", result_mapping(), "evaluation_id")


class InvestmentReviewContractTests(unittest.TestCase):
    def test_immutable_canonical_round_trip(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            supplied = factory()
            document = contract.from_mapping(supplied)
            before = document.to_bytes()
            supplied["authority"]["execution_enabled"] = True
            document.authority["execution_enabled"] = True
            self.assertEqual(document.to_bytes(), before)
            self.assertEqual(contract.from_bytes(before), document)
            self.assertEqual(canonical_json_bytes(document.to_dict()), before)
            with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
                document._canonical_bytes = b"changed"

    def test_unknown_missing_and_nested_fields(self):
        for contract, factory, locations in (
            (ChallengeInput, challenge_mapping, [(), ("observations", 0), ("assumption_reviews", 0), ("counter_hypotheses", 0), ("authority",)]),
            (OutcomeEvaluationInput, evaluation_mapping, [(), ("measurements", 0), ("measurements", 0, "observation"), ("authority",)]),
        ):
            for location in locations:
                for change in ("unknown", "missing"):
                    value = factory()
                    target = value
                    for key in location:
                        target = target[key]
                    if change == "unknown":
                        target["order"] = "BUY"
                    else:
                        target.pop(next(iter(target)))
                    with self.subTest(contract=contract, location=location, change=change), self.assertRaises(ContractValidationError):
                        contract.from_mapping(value)

    def test_strict_json_rejects_duplicates_nonfinite_invalid_utf8_and_roots(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            for source in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}', b'[]', b'null', b'\xff', b'{'):
                with self.subTest(contract=contract, source=source), self.assertRaises(ContractValidationError):
                    contract.from_bytes(source)
            source = canonical_json_bytes(factory()).replace(b'"unit": "percent"', b'"unit": "percent", "unit": "percent"', 1)
            with self.assertRaisesRegex(ContractValidationError, "duplicate"):
                contract.from_bytes(source)

    def test_excessive_json_nesting_and_integer_limits_are_contract_errors(self):
        for contract in (ChallengeInput, OutcomeEvaluationInput):
            for source in (b'{"a":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}', b'{"a":' + b'1' * 6000 + b'}'):
                with self.subTest(contract=contract), self.assertRaises(ContractValidationError):
                    contract.from_bytes(source)

    def test_programmatic_oversized_scalars_are_contract_errors(self):
        oversized = 10 ** 6000
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            value = factory()
            observation = value["observations"][0] if contract is ChallengeInput else value["measurements"][0]["observation"]
            observation["value"] = oversized
            with self.subTest(contract=contract), self.assertRaisesRegex(ContractValidationError, "supported limits"):
                contract.from_mapping(value)

    def test_domains_modes_versions_and_hypothesis_refs(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            for field, bad in (("schema_version", "v0"), ("domain", "TRADING"), ("mode", "LIVE"),
                               ("hypothesis_event_id", "journal-decision-" + "a" * 64), ("hypothesis_sha256", "A" * 64),
                               ("supersedes_event_id", "journal-decision-" + "a" * 64), ("hypothesis_id", "../escape")):
                value = factory()
                value[field] = bad
                with self.subTest(contract=contract, field=field), self.assertRaises(ContractValidationError):
                    contract.from_mapping(value)

    def test_disabled_authority_and_no_execution_or_capital_fields(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            for field in authority():
                for bad in (True, 0, None, "false"):
                    value = factory()
                    value["authority"][field] = bad
                    with self.subTest(contract=contract, field=field, bad=bad), self.assertRaises(ContractValidationError):
                        contract.from_mapping(value)
            for field in ("realized_trade_pnl", "order", "allocation", "capital_transfer", "authorization", "confidence_probability"):
                value = factory()
                value[field] = 1
                with self.subTest(contract=contract, field=field), self.assertRaises(ContractValidationError):
                    contract.from_mapping(value)

    def test_cutoff_observation_dates_and_timezone_normalization(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            value = factory()
            value["recorded_at"] = "2026-10-10T17:00:00-07:00"
            self.assertEqual(contract.from_mapping(value).recorded_at, "2026-10-11T00:00:00Z")
            value["evidence_cutoff_at"] = "2026-10-12T00:00:00Z"
            with self.assertRaisesRegex(ContractValidationError, "cutoff"):
                contract.from_mapping(value)
            value = factory()
            observation = value["observations"][0] if contract is ChallengeInput else value["measurements"][0]["observation"]
            observation["as_of"] = "2026-10-12T00:00:00Z"
            with self.assertRaisesRegex(ContractValidationError, "as_of"):
                contract.from_mapping(value)

    def test_empty_evidence_is_allowed_but_reviews_and_counterhypotheses_are_required(self):
        value = challenge_mapping()
        value["observations"] = []
        value["assumption_reviews"][0]["observation_ids"] = []
        value["counter_hypotheses"][0]["observation_ids"] = []
        self.assertEqual(ChallengeInput.from_mapping(value).observations, [])
        for field in ("assumption_reviews", "counter_hypotheses"):
            bad = copy.deepcopy(value)
            bad[field] = []
            with self.assertRaisesRegex(ContractValidationError, "nonempty"):
                ChallengeInput.from_mapping(bad)
        value = evaluation_mapping()
        value["measurements"] = []
        self.assertEqual(OutcomeEvaluationInput.from_mapping(value).measurements, [])

    def test_challenge_duplicate_ids_indices_and_reference_lists(self):
        for field in ("observations", "assumption_reviews", "counter_hypotheses"):
            value = challenge_mapping()
            value[field].append(copy.deepcopy(value[field][0]))
            with self.subTest(field=field), self.assertRaisesRegex(ContractValidationError, "duplicate"):
                ChallengeInput.from_mapping(value)
        for field in ("assumption_reviews", "counter_hypotheses"):
            for refs in (["unknown"], ["observation-001", "observation-001"]):
                value = challenge_mapping()
                value[field][0]["observation_ids"] = refs
                with self.subTest(field=field, refs=refs), self.assertRaises(ContractValidationError):
                    ChallengeInput.from_mapping(value)
        for field in ("unresolved_questions", "risk_notes"):
            value = challenge_mapping()
            value[field] = ["same", "same"]
            with self.assertRaisesRegex(ContractValidationError, "duplicate"):
                ChallengeInput.from_mapping(value)

    def test_challenge_strict_indices_enums_and_metadata(self):
        for bad in (True, -1, 0.0, "0", None):
            value = challenge_mapping()
            value["assumption_reviews"][0]["assumption_index"] = bad
            with self.subTest(bad=bad), self.assertRaises(ContractValidationError):
                ChallengeInput.from_mapping(value)
        for location, bad in ((("disposition",), "AUTHORIZE"), (("observations", 0, "evidence_role"), "INDEPENDENT"),
                              (("observations", 0, "provenance_group"), " "), (("assumption_reviews", 0, "status"), "TRUE")):
            value = challenge_mapping()
            target = value
            for key in location[:-1]:
                target = target[key]
            target[location[-1]] = bad
            with self.subTest(location=location), self.assertRaises(ContractValidationError):
                ChallengeInput.from_mapping(value)

    def test_evaluation_duplicate_checks_and_observation_reuse(self):
        value = evaluation_mapping()
        value["measurements"].append(copy.deepcopy(value["measurements"][0]))
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            OutcomeEvaluationInput.from_mapping(value)
        value["measurements"][1]["check_type"] = "INVALIDATION"
        self.assertEqual(len(OutcomeEvaluationInput.from_mapping(value).measurements), 2)
        value["measurements"][1]["observation"]["value_pointer"] = "/different"
        with self.assertRaisesRegex(ContractValidationError, "different binding"):
            OutcomeEvaluationInput.from_mapping(value)

    def test_reused_observation_id_does_not_coerce_boolean_and_number(self):
        value = evaluation_mapping()
        value["measurements"][0]["observation"]["value"] = False
        other = copy.deepcopy(value["measurements"][0])
        other["check_type"] = "INVALIDATION"
        other["observation"]["value"] = 0
        value["measurements"].append(other)
        with self.assertRaisesRegex(ContractValidationError, "different binding"):
            OutcomeEvaluationInput.from_mapping(value)

    def test_evaluation_shape_stage_roles_and_scalar_values(self):
        for field, bad in (("evaluation_stage", "COMPLETED"), ("challenge_event_id", "journal-decision-" + "a" * 64), ("evaluator_role", ""), ("conclusion", " ")):
            value = evaluation_mapping()
            value[field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                OutcomeEvaluationInput.from_mapping(value)
        for scalar in (None, True, False, 0, 1.5, "unchanged", ""):
            value = evaluation_mapping()
            value["measurements"][0]["observation"]["value"] = scalar
            self.assertEqual(OutcomeEvaluationInput.from_mapping(value).measurements[0]["observation"]["value"], scalar)
        for scalar in (float("nan"), float("inf"), [], {}, b"bytes"):
            value = evaluation_mapping()
            value["measurements"][0]["observation"]["value"] = scalar
            with self.subTest(scalar=scalar), self.assertRaises(ContractValidationError):
                OutcomeEvaluationInput.from_mapping(value)
        value = evaluation_mapping()
        value["measurements"][0]["unit"] = "ratio"
        with self.assertRaisesRegex(ContractValidationError, "unit"):
            OutcomeEvaluationInput.from_mapping(value)

    def test_source_binding_paths_hashes_and_pointer_checks_reused(self):
        for contract, factory in ((ChallengeInput, challenge_mapping), (OutcomeEvaluationInput, evaluation_mapping)):
            for field, bad in (("artifact_path", "../escape.json"), ("artifact_sha256", "0" * 63),
                               ("source_event_id", "journal-decision-" + "a" * 64), ("value_pointer", "/bad~2"),
                               ("as_of_pointer", "#fragment"), ("time_role", "RELEASED")):
                value = factory()
                obs = value["observations"][0] if contract is ChallengeInput else value["measurements"][0]["observation"]
                obs[field] = bad
                with self.subTest(contract=contract, field=field), self.assertRaises(ContractValidationError):
                    contract.from_mapping(value)


class InvestmentReviewEventContractTests(unittest.TestCase):
    def test_v3_canonical_round_trip(self):
        for factory in (challenge_event, evaluation_event):
            event = JournalEvent.from_mapping(factory())
            self.assertEqual(JournalEvent.from_bytes(event.to_bytes()), event)

    def test_journal_event_parser_bounds_deep_v3_and_numeric_json(self):
        prefix = b'{"schema_version":"blackpod.decision_journal_event.v3","payload":'
        for source in (prefix + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
                       prefix + b'1' * 6000 + b'}'):
            with self.subTest(source_size=len(source)), self.assertRaisesRegex(ContractValidationError, "supported limits"):
                JournalEvent.from_bytes(source)
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_bytes(b'{"schema_version":"blackpod.decision_journal_event.v3","schema_version":"other"}')
        value = evaluation_event()
        value["payload"]["result"]["check_results"][0].update(
            status="MET", observed_value=10 ** 6000, observation_id="observation-001")
        with self.assertRaisesRegex(ContractValidationError, "supported limits"):
            JournalEvent.from_mapping(value)

    def test_version_type_domain_source_and_time_confusion_rejected(self):
        for factory, key, identity in ((challenge_event, "challenge", "challenge_id"), (evaluation_event, "evaluation", "evaluation_id")):
            for location, bad in ((("schema_version",), "blackpod.decision_journal_event.v2"), (("event_type",), "EVALUATION_RECORDED"),
                                  (("domain",), "TRADING"), (("source", "kind"), "MISSION"), (("source", identity), "different-001"),
                                  (("source", "source_sha256"), "0" * 64), (("recorded_at",), "2026-10-12T00:00:00Z")):
                value = factory()
                target = value
                for field in location[:-1]:
                    target = target[field]
                target[location[-1]] = bad
                with self.subTest(factory=factory, location=location), self.assertRaises(ContractValidationError):
                    JournalEvent.from_mapping(value)

    def test_v3_extra_missing_nested_and_authority_claims_rejected(self):
        for factory, report_key in ((challenge_event, "assessment"), (evaluation_event, "result")):
            for location in ((), ("source",), ("payload",), ("payload", report_key), ("payload", report_key, "authority")):
                for change in ("missing", "unknown"):
                    value = factory()
                    target = value
                    for key in location:
                        target = target[key]
                    if change == "missing":
                        target.pop(next(iter(target)))
                    else:
                        target["order"] = "BUY"
                    with self.subTest(factory=factory, location=location, change=change), self.assertRaises(ContractValidationError):
                        JournalEvent.from_mapping(value)
            value = factory()
            value["payload"][report_key]["authority"]["execution_enabled"] = True
            with self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_assessment_cannot_claim_authentication_independence_or_truth(self):
        for field, expected in (("reviewer_distinct", True), ("reviewer_identity_authenticated", False),
                                ("source_independence_verified", False), ("economic_truth_evaluated", False)):
            for bad in (not expected, int(expected), None):
                value = challenge_event()
                value["payload"]["assessment"][field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError):
                    JournalEvent.from_mapping(value)
        value = challenge_event()
        value["payload"]["assessment"]["source_relationships"][0]["independence_verified"] = True
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)

    def test_assessment_exact_observation_coverage_metadata_and_roles(self):
        for field, bad in (("source_relationships", []), ("declared_evidence_roles", []),
                           ("missing_evidence_roles", []), ("execution_status", "EXECUTED")):
            value = challenge_event()
            value["payload"]["assessment"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        for field, bad in (("observation_id", "unknown"), ("provenance_group", "other"), ("evidence_role", "STATISTICAL"), ("relationship", "INDEPENDENT")):
            value = challenge_event()
            value["payload"]["assessment"]["source_relationships"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        value = challenge_event()
        value["payload"]["assessment"]["source_relationships"] *= 2
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_mapping(value)

    def test_no_evidence_assessment_is_explicit_missing(self):
        document = challenge_mapping()
        document["observations"] = []
        document["assumption_reviews"][0]["observation_ids"] = []
        document["counter_hypotheses"][0]["observation_ids"] = []
        report = assessment_mapping()
        report.update(source_relationships=[], declared_evidence_roles=[], missing_evidence_roles=["FUNDAMENTAL", "STATISTICAL"])
        event = _event(document, INVESTMENT_CHALLENGE_EVENT_TYPE, "challenge", "assessment", report, "challenge_id")
        self.assertEqual(JournalEvent.from_mapping(event).payload["assessment"]["missing_evidence_roles"], ["FUNDAMENTAL", "STATISTICAL"])

    def test_result_conservative_status_and_no_realized_trade_pnl(self):
        for field, bad in (("measurement_basis", "WHOLE_HORIZON"), ("whole_horizon_invalidation_established", True),
                           ("manual_review_required", False), ("economic_truth_evaluated", True), ("execution_status", "EXECUTED"),
                           ("realized_trade_pnl", 0), ("comparison_summary", "HYPOTHESIS_PROVEN"), ("evaluation_stage", "FINAL")):
            value = evaluation_event()
            value["payload"]["result"][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)

    def test_computed_method_versions_are_explicit_and_fixed(self):
        for factory, report, field in ((challenge_event, "assessment", "assessment_method_version"),
                                       (evaluation_event, "result", "comparison_method_version")):
            value = factory()
            value["payload"][report][field] = "unreviewed-method.v2"
            with self.subTest(field=field), self.assertRaisesRegex(ContractValidationError, "method_version"):
                JournalEvent.from_mapping(value)

    def test_check_result_shape_duplicates_and_type_specific_status(self):
        for field, bad in (("status", "TRIGGERED"), ("check_type", "FORECAST"), ("due_at", "2027-01-11"),
                           ("observed_value", 0), ("observation_id", "observation-001")):
            value = evaluation_event()
            value["payload"]["result"]["check_results"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(value)
        value = evaluation_event()
        value["payload"]["result"]["check_results"] *= 2
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            JournalEvent.from_mapping(value)
        value = evaluation_event()
        value["payload"]["result"]["check_results"][0]["order"] = "BUY"
        with self.assertRaises(ContractValidationError):
            JournalEvent.from_mapping(value)

    def test_v1_and_v2_round_trip_bytes_remain_unchanged(self):
        from test_decision_journal_contracts import mission_event
        from test_investment_hypothesis_contracts import hypothesis_event

        for factory in (mission_event, hypothesis_event):
            before = JournalEvent.from_mapping(factory()).to_bytes()
            self.assertEqual(JournalEvent.from_bytes(before).to_bytes(), before)


if __name__ == "__main__":
    unittest.main()
