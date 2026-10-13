"""Offline research review tests using actual MissionStore source histories."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import MissionRequest, MissionSnapshot
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
from blackpod_build_week.investment_review import (
    ReviewEvidenceError, assess_challenge, build_challenge_event, build_outcome_event,
    evaluate_outcome, evidence_for_challenge, evidence_for_outcome, validate_review_event,
)
from blackpod_build_week.mission_store import MissionStore


CHECKOUT = Path(__file__).resolve().parents[1]


class InvestmentReviewEngineTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.events, self.blobs = [], {}
        self.native_source("initial", "2026-10-11T00:00:00Z", {"growth": 5.0, "financing": 6.0})
        self.initial_event = self.events[-1]
        self.draft = json.loads((CHECKOUT / "examples/investment_hypothesis.shadow.v1.json").read_bytes())
        self.draft["observations"] = [self.observation(self.initial_event, "growth", 5.0, "growth"),
                                      self.observation(self.initial_event, "financing", 6.0, "financing")]
        self.draft["hypothesis"]["observation_ids"] = ["growth", "financing"]
        self.draft["alternatives"][0]["observation_ids"] = ["growth", "financing"]
        self.record_hypothesis()

    def native_source(self, label, timestamp, metrics, *, point_at=None):
        request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1", "mission_id": "mission-review-" + label,
            "request_id": "request-review-" + label, "run_mode": "REPLAY", "symbol": "MSFT",
            "requested_at": timestamp, "operator_id": "offline-fixture-author",
        })
        store = MissionStore(self.base / label)
        initialized = store.initialize(request, mission_id=request.mission_id,
                                       started_at=timestamp, observed_at=timestamp)
        artifact = store.write_immutable_artifact(
            request.mission_id, relative_path="research/observations.json",
            payload=canonical_json_bytes({"source_kind": "SYNTHETIC_FIXTURE", "as_of": point_at or timestamp,
                                          "metrics": metrics}),
            name="review_observations", producer="offline-fixture-author",
            schema_version="blackpod.investment_review_fixture.v1", observed_at=timestamp,
        )
        revision = initialized.snapshot.to_dict()
        revision.update(snapshot_id=request.mission_id + "-r0002", revision=2,
                        previous_snapshot_sha256=initialized.snapshot_sha256,
                        artifacts=[*revision["artifacts"], artifact.to_dict()])
        store.commit_snapshot(initialized.paths, MissionSnapshot.from_mapping(revision))
        history = load_verified_history(initialized.paths.mission_root)
        self.events.extend(project_history(history))
        self.blobs.update({sha256_bytes(raw): raw for raw in history.source_files.values()})
        return self.events[-1]

    def observation(self, event, key, value, identity, *, unit="PERCENT"):
        ref = next(ref for ref in event.evidence if ref["path"] == "research/observations.json")
        raw = json.loads(self.blobs[ref["sha256"]])
        return {"observation_id": identity, "source_event_id": event.event_id,
                "artifact_path": ref["path"], "artifact_sha256": ref["sha256"],
                "value_pointer": "/metrics/" + key, "value": value, "unit": unit,
                "as_of_pointer": "/as_of", "as_of": raw["as_of"], "time_role": "AS_OF"}

    def record_hypothesis(self):
        self.events = [event for event in self.events if event.event_type != "INVESTMENT_HYPOTHESIS_RECORDED"]
        self.hypothesis = InvestmentHypothesis.from_mapping(self.draft)
        self.parent = build_hypothesis_event(self.hypothesis, self.events, self.blobs)
        evidence = evidence_for_hypothesis(self.hypothesis, self.events, self.blobs)
        self.events.append(self.parent)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})

    def base_review(self):
        return {"hypothesis_event_id": self.parent.event_id, "hypothesis_id": self.hypothesis.hypothesis_id,
                "hypothesis_sha256": self.parent.source["source_sha256"],
                "recorded_at": "2026-10-12T00:00:00Z", "evidence_cutoff_at": "2026-10-12T00:00:00Z",
                "domain": "INVESTMENT", "mode": "SHADOW", "supersedes_event_id": None,
                "authority": self.hypothesis.authority}

    def challenge_mapping(self):
        observation = {**self.hypothesis.observations[0], "evidence_role": "FUNDAMENTAL",
                       "provenance_group": "declared-fixture-source"}
        return {**self.base_review(), "schema_version": "blackpod.investment_challenge.v1",
                "challenge_id": "challenge-fixture", "reviewer_id": "independent-declared-reviewer",
                "observations": [observation],
                "assumption_reviews": [{"assumption_index": index, "status": "UNTESTED",
                                        "reason": "Fixture assumption requires subsequent evidence.",
                                        "observation_ids": [observation["observation_id"]]}
                                       for index in range(len(self.hypothesis.hypothesis["assumptions"]))],
                "counter_hypotheses": [{"counter_id": "counter-fixture", "statement": "Fixture alternate cause.",
                                        "discriminating_test": "Compare the recorded deadline metric.",
                                        "observation_ids": [observation["observation_id"]]}],
                "disposition": "INSUFFICIENT_EVIDENCE", "unresolved_questions": ["Fixture data is synthetic."],
                "risk_notes": ["No economic independence is verified."]}

    def record_challenge(self, value=None):
        challenge = ChallengeInput.from_mapping(self.challenge_mapping() if value is None else value)
        event = build_challenge_event(challenge, self.events, self.blobs)
        evidence = evidence_for_challenge(challenge, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
        self.challenge = event
        return event

    def evaluation_mapping(self, *, actual=-1.5, stage="FINAL", timestamp="2027-04-11T00:00:00Z"):
        if not hasattr(self, "challenge"):
            self.record_challenge()
        source = self.native_source("outcome-" + str(len(self.events)), timestamp, {"margin": actual})
        observation = self.observation(source, "margin", actual, "measured-margin", unit="PERCENTAGE_POINTS")
        return {**self.base_review(), "schema_version": "blackpod.investment_outcome_evaluation.v1",
                "evaluation_id": "evaluation-fixture", "recorded_at": timestamp,
                "evidence_cutoff_at": timestamp, "challenge_event_id": self.challenge.event_id,
                "evaluator_id": "independent-declared-reviewer",
                "evaluator_role": self.hypothesis.evaluation_plan["evaluator_role"],
                "evaluation_stage": stage,
                "measurements": [
                    {"check_type": "OUTCOME", "check_id": self.hypothesis.expected_outcomes[0]["outcome_id"],
                     "metric": "OPERATING_MARGIN_CHANGE_PCT_POINTS", "unit": "PERCENTAGE_POINTS",
                     "observation": observation},
                    {"check_type": "INVALIDATION", "check_id": self.hypothesis.invalidation_conditions[0]["condition_id"],
                     "metric": "OPERATING_MARGIN_CHANGE_PCT_POINTS", "unit": "PERCENTAGE_POINTS",
                     "observation": copy.deepcopy(observation)},
                ], "conclusion": "Supplied fixed-deadline fixture comparison, not thesis proof."}

    def evaluate(self, value):
        return evaluate_outcome(OutcomeEvaluationInput.from_mapping(value), self.events, self.blobs)

    def test_challenge_is_source_bound_pure_and_conservative(self):
        challenge = ChallengeInput.from_mapping(self.challenge_mapping())
        original_events = [event.to_bytes() for event in self.events]
        original_blobs = dict(self.blobs)
        report = assess_challenge(challenge, self.events, self.blobs)
        self.assertEqual(report["source_relationships"][0]["relationship"], "SAME_VALUE_BINDING")
        self.assertEqual(report["missing_evidence_roles"], ["STATISTICAL"])
        self.assertFalse(report["reviewer_identity_authenticated"])
        self.assertFalse(report["source_independence_verified"])
        self.assertFalse(report["economic_truth_evaluated"])
        self.assertTrue(all(flag is False for flag in report["authority"].values()))
        self.assertEqual(report["assessment_method_version"], "blackpod.source_relationship_assessment.v1")
        first = build_challenge_event(challenge, self.events, self.blobs)
        second = build_challenge_event(challenge, self.events, self.blobs)
        self.assertEqual(first.to_bytes(), second.to_bytes())
        self.assertEqual(first.decision_id, self.parent.decision_id)
        self.assertEqual(first.source["source_sha256"], sha256_bytes(challenge.to_bytes()))
        self.assertEqual(original_events, [event.to_bytes() for event in self.events])
        self.assertEqual(original_blobs, self.blobs)
        evidence = evidence_for_challenge(challenge, self.events, self.blobs)
        self.assertEqual(len(evidence), 3)
        validate_review_event(first, self.events, {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}})

    def test_shared_artifact_and_distinct_source_do_not_establish_independence(self):
        self.draft["observations"] = [self.draft["observations"][0]]
        self.draft["hypothesis"]["observation_ids"] = ["growth"]
        self.draft["alternatives"][0]["observation_ids"] = ["growth"]
        self.record_hypothesis()
        value = self.challenge_mapping()
        shared = self.observation(self.initial_event, "financing", 6.0, "shared-financing")
        distinct_source = self.native_source("distinct", "2026-10-12T00:00:00Z", {"signal": 1.0})
        distinct = self.observation(distinct_source, "signal", 1.0, "distinct-signal")
        value["observations"].extend([
            {**shared, "evidence_role": "FUNDAMENTAL", "provenance_group": "independent-looking-group"},
            {**distinct, "evidence_role": "STATISTICAL", "provenance_group": "another-declared-group"},
        ])
        report = assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)
        self.assertEqual([item["relationship"] for item in report["source_relationships"]],
                         ["SAME_VALUE_BINDING", "SHARED_ARTIFACT", "DISTINCT_RETAINED_ARTIFACT"])
        self.assertEqual(report["missing_evidence_roles"], [])
        self.assertFalse(report["source_independence_verified"])
        self.assertTrue(all(item["independence_verified"] is False for item in report["source_relationships"]))

    def test_empty_challenge_evidence_flags_both_missing_roles(self):
        value = self.challenge_mapping()
        value["observations"] = []
        for item in (*value["assumption_reviews"], *value["counter_hypotheses"]):
            item["observation_ids"] = []
        report = assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)
        self.assertEqual(report["missing_evidence_roles"], ["FUNDAMENTAL", "STATISTICAL"])
        self.assertEqual(report["source_relationships"], [])

    def test_challenge_self_review_missing_assumption_and_wrong_parent_rejected(self):
        edits = [{"reviewer_id": self.hypothesis.author_id}, {"hypothesis_id": "other-hypothesis"},
                 {"hypothesis_sha256": "a" * 64}, {"hypothesis_event_id": self.initial_event.event_id},
                 {"hypothesis_event_id": "journal-event-" + "f" * 64},
                 {"assumption_reviews": self.challenge_mapping()["assumption_reviews"][:-1]}]
        for edit in edits:
            value = {**self.challenge_mapping(), **edit}
            with self.subTest(edit=edit), self.assertRaises(ReviewEvidenceError):
                assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)

    def test_challenge_original_hash_retention_and_cutoff_guards(self):
        challenge = ChallengeInput.from_mapping(self.challenge_mapping())
        changed = dict(self.blobs)
        changed[self.parent.source["source_sha256"]] = b"changed original"
        with self.assertRaises(ReviewEvidenceError):
            assess_challenge(challenge, self.events, changed)
        value = self.challenge_mapping()
        value.update(recorded_at="2026-10-10T00:00:00Z", evidence_cutoff_at="2026-10-10T00:00:00Z",
                     observations=[])
        for item in (*value["assumption_reviews"], *value["counter_hypotheses"]):
            item["observation_ids"] = []
        with self.assertRaisesRegex(ReviewEvidenceError, "precede"):
            assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)

    def test_challenge_exact_source_value_and_no_late_source(self):
        value = self.challenge_mapping()
        value["observations"][0]["value"] = 99
        with self.assertRaisesRegex(ReviewEvidenceError, "value differs"):
            assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)
        source = self.native_source("late", "2026-10-13T00:00:00Z", {"signal": 1.0})
        observation = self.observation(source, "signal", 1.0, "growth")
        value = self.challenge_mapping()
        value["observations"] = [{**observation, "evidence_role": "STATISTICAL", "provenance_group": "late"}]
        with self.assertRaises(ContractValidationError):
            ChallengeInput.from_mapping(value)

    def test_all_expectations_met_is_deadline_only_not_economic_truth_or_pnl(self):
        value = self.evaluation_mapping()
        result = self.evaluate(value)
        self.assertEqual(result["comparison_summary"], "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
        self.assertEqual([item["status"] for item in result["check_results"]], ["MET", "NOT_TRIGGERED"])
        self.assertEqual(result["measurement_basis"], "RECORDED_DEADLINE_POINTS_ONLY")
        self.assertEqual(result["comparison_method_version"], "blackpod.deadline_point_comparison.v1")
        self.assertFalse(result["whole_horizon_invalidation_established"])
        self.assertFalse(result["economic_truth_evaluated"])
        self.assertTrue(result["manual_review_required"])
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertTrue(all(flag is False for flag in result["authority"].values()))
        self.assertEqual(result["hypothesis_research_mode"], "PROSPECTIVE")
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        event = build_outcome_event(evaluation, self.events, self.blobs)
        evidence = evidence_for_outcome(evaluation, self.events, self.blobs)
        self.assertEqual(len(evidence), 4)  # Shared observation is retained once.
        self.assertEqual(event.decision_id, self.parent.decision_id)
        self.assertEqual(event.to_bytes(), build_outcome_event(evaluation, self.events, self.blobs).to_bytes())
        validate_review_event(event, self.events,
                              {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}})

    def test_failure_and_invalidation_comparison_precedence(self):
        for actual, expected in ((-0.5, "EXPECTATIONS_NOT_MET"), (0.5, "INVALIDATION_TRIGGERED")):
            with self.subTest(actual=actual):
                result = self.evaluate(self.evaluation_mapping(actual=actual))
                self.assertEqual(result["comparison_summary"], expected)

    def test_missing_null_bool_and_type_mismatch_are_inconclusive(self):
        for actual in (None, True, "-1.5"):
            with self.subTest(actual=actual):
                result = self.evaluate(self.evaluation_mapping(actual=actual))
                self.assertEqual(result["comparison_summary"], "INCONCLUSIVE")
                self.assertEqual([item["status"] for item in result["check_results"]], ["INCONCLUSIVE"] * 2)
        value = self.evaluation_mapping()
        value["measurements"] = []
        result = self.evaluate(value)
        self.assertEqual(result["comparison_summary"], "INCONCLUSIVE")
        self.assertEqual([item["status"] for item in result["check_results"]], ["MISSING"] * 2)

    def test_interim_not_due_and_early_final_rejected(self):
        value = self.evaluation_mapping(stage="INTERIM", timestamp="2026-11-11T00:00:00Z")
        value["measurements"] = []
        result = self.evaluate(value)
        self.assertEqual(result["comparison_summary"], "PENDING")
        self.assertEqual([item["status"] for item in result["check_results"]], ["NOT_DUE"] * 2)
        value["evaluation_stage"] = "FINAL"
        with self.assertRaisesRegex(ReviewEvidenceError, "FINAL"):
            self.evaluate(value)

    def test_premature_and_misaligned_deadline_measurements_are_rejected(self):
        value = self.evaluation_mapping(stage="INTERIM", timestamp="2026-11-11T00:00:00Z")
        with self.assertRaisesRegex(ReviewEvidenceError, "before its original deadline"):
            self.evaluate(value)
        value = self.evaluation_mapping(timestamp="2027-04-12T00:00:00Z")
        with self.assertRaisesRegex(ReviewEvidenceError, "exact original deadline"):
            self.evaluate(value)

    def test_fixed_role_metric_unit_and_check_guards(self):
        original = self.evaluation_mapping()
        edits = [("role", lambda value: value.update(evaluator_role="invented-role")),
                 ("self", lambda value: value.update(evaluator_id=self.hypothesis.author_id)),
                 ("metric", lambda value: value["measurements"][0].update(metric="different-metric")),
                 ("check", lambda value: value["measurements"][0].update(check_id="invented-check")),
                 ("unit", lambda value: (value["measurements"][0].update(unit="BASIS_POINTS"),
                                         value["measurements"][0]["observation"].update(unit="BASIS_POINTS", observation_id="changed-unit")))]
        for label, edit in edits:
            value = copy.deepcopy(original)
            edit(value)
            with self.subTest(label=label), self.assertRaises(ReviewEvidenceError):
                self.evaluate(value)

    def test_evaluation_requires_existing_correct_challenge_and_cutoff(self):
        value = self.evaluation_mapping()
        for identity in (self.initial_event.event_id, "journal-event-" + "f" * 64):
            changed = {**value, "challenge_event_id": identity}
            with self.subTest(identity=identity), self.assertRaises(ReviewEvidenceError):
                self.evaluate(changed)
        changed = copy.deepcopy(value)
        changed.update(recorded_at="2026-10-11T12:00:00Z", evidence_cutoff_at="2026-10-11T12:00:00Z",
                       evaluation_stage="INTERIM", measurements=[])
        with self.assertRaisesRegex(ReviewEvidenceError, "precede its challenge"):
            self.evaluate(changed)

    def test_duplicate_observation_identity_requires_identical_binding(self):
        value = self.evaluation_mapping()
        value["measurements"][1]["observation"]["value_pointer"] = "/metrics/different-margin"
        with self.assertRaises(ValueError):
            self.evaluate(value)

    def test_event_hash_identity_and_recomputed_report_tampering_rejected(self):
        challenge = ChallengeInput.from_mapping(self.challenge_mapping())
        event = build_challenge_event(challenge, self.events, self.blobs)
        retained = {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence_for_challenge(challenge, self.events, self.blobs).values()}}
        for field in ("event_id", "decision_id"):
            value = event.to_dict()
            value[field] = value[field].split("-", 2)[0] + "-" + ("event" if field == "event_id" else "decision") + "-" + "a" * 64
            with self.subTest(field=field), self.assertRaises(ReviewEvidenceError):
                validate_review_event(JournalEvent.from_mapping(value), self.events, retained)
        value = event.to_dict()
        value["payload"]["assessment"]["source_relationships"][0]["relationship"] = "DISTINCT_RETAINED_ARTIFACT"
        with self.assertRaisesRegex(ReviewEvidenceError, "projection"):
            validate_review_event(JournalEvent.from_mapping(value), self.events, retained)
        del retained[event.source["source_sha256"]]
        with self.assertRaisesRegex(ReviewEvidenceError, "retained review input"):
            validate_review_event(event, self.events, retained)

    def test_duplicate_parent_identity_is_rejected(self):
        with self.assertRaisesRegex(ReviewEvidenceError, "ambiguous"):
            assess_challenge(ChallengeInput.from_mapping(self.challenge_mapping()), [*self.events, self.parent], self.blobs)

    def test_all_six_numeric_predicates_true_and_false(self):
        cases = (("GT", 4, "MET"), ("GT", 6, "NOT_MET"), ("GTE", 5, "MET"), ("GTE", 6, "NOT_MET"),
                 ("LT", 6, "MET"), ("LT", 4, "NOT_MET"), ("LTE", 5, "MET"), ("LTE", 4, "NOT_MET"),
                 ("EQ", 5.0, "MET"), ("EQ", 4, "NOT_MET"), ("NE", 4, "MET"), ("NE", 5.0, "NOT_MET"))
        for index, (operator, threshold, expected) in enumerate(cases):
            with self.subTest(operator=operator, threshold=threshold):
                self.draft["expected_outcomes"][0].update(operator=operator, threshold=threshold)
                self.record_hypothesis()
                if hasattr(self, "challenge"):
                    del self.challenge
                self.events = [event for event in self.events if event.event_type != "INVESTMENT_CHALLENGE_RECORDED"]
                result = self.evaluate(self.evaluation_mapping(actual=5))
                self.assertEqual(result["check_results"][0]["status"], expected)

    def test_string_eq_and_ne_predicates_do_not_coerce_types(self):
        self.draft["expected_outcomes"][0].update(operator="EQ", threshold="MATCH")
        self.draft["invalidation_conditions"][0].update(operator="NE", threshold="MATCH")
        self.record_hypothesis()
        for actual, summary in (("MATCH", "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION"),
                                ("MISMATCH", "INVALIDATION_TRIGGERED"), (5, "INCONCLUSIVE")):
            with self.subTest(actual=actual):
                self.assertEqual(self.evaluate(self.evaluation_mapping(actual=actual))["comparison_summary"], summary)

    def test_interim_triggered_invalidation_takes_precedence_over_not_due(self):
        self.draft["invalidation_conditions"][0]["check_by"] = "2026-11-11T00:00:00Z"
        self.record_hypothesis()
        value = self.evaluation_mapping(stage="INTERIM", timestamp="2026-11-11T00:00:00Z", actual=1)
        value["measurements"] = [value["measurements"][1]]
        result = self.evaluate(value)
        self.assertEqual([item["status"] for item in result["check_results"]], ["NOT_DUE", "TRIGGERED"])
        self.assertEqual(result["comparison_summary"], "INVALIDATION_TRIGGERED")

    def test_missing_invalidation_takes_precedence_over_failed_expectation(self):
        value = self.evaluation_mapping(actual=-0.5)
        value["measurements"] = [value["measurements"][0]]
        result = self.evaluate(value)
        self.assertEqual([item["status"] for item in result["check_results"]], ["NOT_MET", "MISSING"])
        self.assertEqual(result["comparison_summary"], "INCONCLUSIVE")

    def test_late_source_record_is_rejected_even_when_observation_deadline_matches(self):
        value = self.evaluation_mapping()
        source = self.native_source("late-published", "2027-04-12T00:00:00Z", {"margin": -1.5},
                                    point_at="2027-04-11T00:00:00Z")
        observed = self.observation(source, "margin", -1.5, "late-margin", unit="PERCENTAGE_POINTS")
        for measurement in value["measurements"]:
            measurement["observation"] = copy.deepcopy(observed)
        with self.assertRaisesRegex(ReviewEvidenceError, "after the evidence cutoff"):
            self.evaluate(value)

    def test_superseding_challenge_appends_without_rewriting_and_identity_is_stable(self):
        original = self.record_challenge()
        original_bytes = original.to_bytes()
        value = self.challenge_mapping()
        value.update(challenge_id="challenge-fixture-revised", supersedes_event_id=original.event_id,
                     recorded_at="2026-10-13T00:00:00Z", evidence_cutoff_at="2026-10-13T00:00:00Z")
        revised = build_challenge_event(ChallengeInput.from_mapping(value), self.events, self.blobs)
        self.assertNotEqual(revised.event_id, original.event_id)
        self.assertEqual(revised.decision_id, original.decision_id)
        self.assertEqual(original.to_bytes(), original_bytes)
        value = self.challenge_mapping()
        value["disposition"] = "REVIEW_CONTESTS"
        changed = build_challenge_event(ChallengeInput.from_mapping(value), self.events, self.blobs)
        self.assertEqual(changed.event_id, original.event_id)
        self.assertNotEqual(changed.to_bytes(), original_bytes)
        for identity in (self.parent.event_id, "journal-event-" + "f" * 64):
            value.update(supersedes_event_id=identity)
            with self.subTest(identity=identity), self.assertRaisesRegex(ReviewEvidenceError, "earlier review"):
                build_challenge_event(ChallengeInput.from_mapping(value), self.events, self.blobs)
        value.update(supersedes_event_id=original.event_id, recorded_at="2026-10-11T12:00:00Z",
                     evidence_cutoff_at="2026-10-11T12:00:00Z")
        with self.assertRaisesRegex(ReviewEvidenceError, "before the earlier review"):
            build_challenge_event(ChallengeInput.from_mapping(value), self.events, self.blobs)

    def test_supersession_and_outcome_challenge_cannot_cross_hypotheses(self):
        other_mapping = self.hypothesis.to_dict()
        other_mapping["hypothesis_id"] = "second-hypothesis"
        other = InvestmentHypothesis.from_mapping(other_mapping)
        other_event = build_hypothesis_event(other, self.events, self.blobs)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_hypothesis(other, self.events, self.blobs).values()})
        self.events.append(other_event)
        other_review = self.challenge_mapping()
        other_review.update(hypothesis_id=other.hypothesis_id, hypothesis_event_id=other_event.event_id,
                            hypothesis_sha256=other_event.source["source_sha256"], challenge_id="other-challenge")
        other_review = ChallengeInput.from_mapping(other_review)
        other_challenge = build_challenge_event(other_review, self.events, self.blobs)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_challenge(other_review, self.events, self.blobs).values()})
        self.events.append(other_challenge)
        value = self.challenge_mapping()
        value["supersedes_event_id"] = other_challenge.event_id
        with self.assertRaisesRegex(ReviewEvidenceError, "cross hypotheses"):
            assess_challenge(ChallengeInput.from_mapping(value), self.events, self.blobs)
        evaluation = self.evaluation_mapping()
        evaluation["challenge_event_id"] = other_challenge.event_id
        with self.assertRaisesRegex(ReviewEvidenceError, "same hypothesis"):
            self.evaluate(evaluation)

    def test_superseding_outcome_retains_original_and_rejects_wrong_event_type(self):
        value = self.evaluation_mapping(stage="INTERIM", timestamp="2026-11-11T00:00:00Z")
        value["measurements"] = []
        first_input = OutcomeEvaluationInput.from_mapping(value)
        first = build_outcome_event(first_input, self.events, self.blobs)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_outcome(first_input, self.events, self.blobs).values()})
        self.events.append(first)
        original = first.to_bytes()
        final_value = self.evaluation_mapping()
        final_value.update(evaluation_id="evaluation-final", supersedes_event_id=first.event_id)
        final = build_outcome_event(OutcomeEvaluationInput.from_mapping(final_value), self.events, self.blobs)
        self.assertNotEqual(first.event_id, final.event_id)
        self.assertEqual(final.payload["result"]["comparison_summary"], "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
        self.assertEqual(first.to_bytes(), original)
        final_value["supersedes_event_id"] = self.challenge.event_id
        with self.assertRaisesRegex(ReviewEvidenceError, "same event type"):
            self.evaluate(final_value)

    def test_outcome_computed_report_tampering_is_rejected(self):
        value = self.evaluation_mapping()
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        event = build_outcome_event(evaluation, self.events, self.blobs)
        retained = {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence_for_outcome(evaluation, self.events, self.blobs).values()}}
        changed = event.to_dict()
        changed["payload"]["result"]["check_results"][0]["status"] = "NOT_MET"
        with self.assertRaisesRegex(ReviewEvidenceError, "projection"):
            validate_review_event(JournalEvent.from_mapping(changed), self.events, retained)

    def test_retrospective_parent_remains_explicit_in_report(self):
        self.draft["research_mode"] = "RETROSPECTIVE"
        self.draft["recorded_at"] = "2026-10-11T01:00:00Z"
        self.record_hypothesis()
        result = self.evaluate(self.evaluation_mapping())
        self.assertEqual(result["hypothesis_research_mode"], "RETROSPECTIVE")

    def test_challenge_correction_cannot_retreat_evidence_cutoff(self):
        original_value = self.challenge_mapping()
        original_value.update(recorded_at="2026-10-14T00:00:00Z", evidence_cutoff_at="2026-10-13T00:00:00Z")
        original = self.record_challenge(original_value)
        revised = self.challenge_mapping()
        revised.update(challenge_id="correction-old-cutoff", supersedes_event_id=original.event_id,
                       recorded_at="2026-10-15T00:00:00Z", evidence_cutoff_at="2026-10-12T00:00:00Z")
        with self.assertRaisesRegex(ReviewEvidenceError, "earlier evidence cutoff"):
            assess_challenge(ChallengeInput.from_mapping(revised), self.events, self.blobs)

    def test_final_outcome_correction_cannot_retreat_cutoff_or_maturity(self):
        value = self.evaluation_mapping()
        value.update(recorded_at="2027-04-13T00:00:00Z", evidence_cutoff_at="2027-04-12T00:00:00Z")
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        original = build_outcome_event(evaluation, self.events, self.blobs)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_outcome(evaluation, self.events, self.blobs).values()})
        self.events.append(original)
        revised = copy.deepcopy(value)
        revised.update(evaluation_id="correction-old-cutoff", supersedes_event_id=original.event_id,
                       recorded_at="2027-04-14T00:00:00Z", evidence_cutoff_at="2027-04-11T00:00:00Z")
        with self.assertRaisesRegex(ReviewEvidenceError, "earlier evidence cutoff"):
            self.evaluate(revised)
        revised.update(evaluation_id="correction-interim", evidence_cutoff_at="2027-04-14T00:00:00Z",
                       evaluation_stage="INTERIM")
        with self.assertRaisesRegex(ReviewEvidenceError, "FINAL.*INTERIM"):
            self.evaluate(revised)

    def test_later_review_can_bind_original_exact_deadline_without_window_aggregation(self):
        value = self.evaluation_mapping()
        value.update(recorded_at="2027-04-12T00:00:00Z", evidence_cutoff_at="2027-04-12T00:00:00Z")
        result = self.evaluate(value)
        self.assertEqual(result["comparison_summary"], "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
        self.assertTrue(all(item["due_at"] == "2027-04-11T00:00:00Z" for item in result["check_results"]))


if __name__ == "__main__":
    unittest.main()
