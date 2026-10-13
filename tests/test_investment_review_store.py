"""Offline, immutable v1/v2/v3 review-chain storage integration."""

from __future__ import annotations

import copy
import json
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionRequest, MissionSnapshot
from blackpod_build_week.contracts.decision_journal import EvaluationInput, JournalEvent
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.decision_journal_cli import build_evaluation_event
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.decision_journal_store import (
    JournalConflictError, JournalPersistenceError, JournalStore, JournalVerificationError,
    _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
from blackpod_build_week.investment_review import (
    ReviewEvidenceError, build_challenge_event, build_outcome_event,
    evidence_for_challenge, evidence_for_outcome,
)
from blackpod_build_week.mission_store import MissionStore


CHECKOUT = Path(__file__).resolve().parents[1]
MISSION = CHECKOUT / "fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example"
EXAMPLE = CHECKOUT / "examples/investment_hypothesis.shadow.v1.json"


def identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


class InvestmentReviewStoreTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "journal"
        self.store = JournalStore(self.root)
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))
        self.source_before = {str(path.relative_to(MISSION)): path.read_bytes()
                              for path in MISSION.rglob("*") if path.is_file()}
        history = load_verified_history(MISSION)
        self.missions = project_history(history)
        for event in self.missions:
            self.store.append(event, dict(history.source_files))
        self.hypothesis = InvestmentHypothesis.from_bytes(EXAMPLE.read_bytes())
        events, blobs = self.store.verified_contents()
        self.parent = build_hypothesis_event(self.hypothesis, events, blobs)
        self.store.append(self.parent, evidence_for_hypothesis(self.hypothesis, events, blobs))
        self.original_entries = {path.name: path.read_bytes() for path in (self.root / "entries").iterdir()}

    def later_source(self, *, mission_id="mission-outcome-fixture", observed_at="2027-04-11T00:00:00Z",
                     value=-2.0, document=None):
        """Record supplied synthetic later evidence via real mission persistence."""
        request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1", "mission_id": mission_id,
            "request_id": "request-" + mission_id, "run_mode": "REPLAY", "symbol": "MSFT",
            "requested_at": observed_at, "operator_id": "fixture-recorder",
        })
        producer = MissionStore(self.base / mission_id)
        initial = producer.initialize(request, mission_id=mission_id, started_at=observed_at,
                                      observed_at=observed_at)
        supplied = document if document is not None else {
            "schema_version": "blackpod.synthetic_review_evidence.v1", "as_of": observed_at,
            "source_kind": "SYNTHETIC_FIXTURE", "margin_change": value,
        }
        artifact = producer.write_immutable_artifact(
            mission_id, relative_path="research/later_observation.json",
            payload=canonical_json_bytes(supplied), name="later_observation",
            producer="offline-fixture-author", schema_version=None, observed_at=observed_at,
        )
        revision = initial.snapshot.to_dict()
        revision.update(snapshot_id=mission_id + "-r0002", revision=2,
                        previous_snapshot_sha256=initial.snapshot_sha256,
                        artifacts=[*revision["artifacts"], artifact.to_dict()])
        producer.commit_snapshot(initial.paths, MissionSnapshot.from_mapping(revision))
        history = load_verified_history(initial.paths.mission_root)
        events = project_history(history)
        for event in events:
            self.store.append(event, dict(history.source_files))
        return {
            "observation_id": "later-margin", "source_event_id": events[-1].event_id,
            "artifact_path": artifact.path, "artifact_sha256": artifact.sha256,
            "value_pointer": "/margin_change", "value": supplied.get("margin_change", value),
            "unit": "PERCENTAGE_POINTS", "as_of_pointer": "/as_of", "as_of": supplied["as_of"],
            "time_role": "AS_OF",
        }

    def assert_originals_unchanged(self):
        for name, raw in self.original_entries.items():
            self.assertEqual((self.root / "entries" / name).read_bytes(), raw)
        self.assertEqual(self.source_before, {str(path.relative_to(MISSION)): path.read_bytes()
                                             for path in MISSION.rglob("*") if path.is_file()})

    def challenge(self, **changes):
        hypothesis = self.hypothesis.to_dict()
        observation = {**hypothesis["observations"][0], "observation_id": "review-revenue",
                       "evidence_role": "FUNDAMENTAL", "provenance_group": "synthetic-initial"}
        value = {
            "schema_version": "blackpod.investment_challenge.v1", "challenge_id": "challenge-store-fixture",
            "hypothesis_event_id": self.parent.event_id, "hypothesis_id": self.hypothesis.hypothesis_id,
            "hypothesis_sha256": self.parent.source["source_sha256"],
            "recorded_at": "2026-10-12T00:00:00Z", "evidence_cutoff_at": "2026-10-12T00:00:00Z",
            "domain": "INVESTMENT", "mode": "SHADOW", "reviewer_id": "independent-fixture-reviewer",
            "supersedes_event_id": None, "observations": [observation],
            "assumption_reviews": [
                {"assumption_index": index, "status": "UNTESTED", "reason": "Synthetic evidence only.",
                 "observation_ids": [observation["observation_id"]]}
                for index in range(len(hypothesis["hypothesis"]["assumptions"]))
            ],
            "counter_hypotheses": [{"counter_id": "counter-fixture", "statement": "Pricing power may absorb costs.",
                                    "discriminating_test": "Compare fixed operating-margin deadline observations.",
                                    "observation_ids": [observation["observation_id"]]}],
            "disposition": "INSUFFICIENT_EVIDENCE", "unresolved_questions": ["No independent sources supplied."],
            "risk_notes": ["No portfolio or trading authority."], "authority": hypothesis["authority"],
        }
        value.update(changes)
        return ChallengeInput.from_mapping(value)

    def built_challenge(self, challenge=None):
        challenge = self.challenge() if challenge is None else challenge
        events, blobs = self.store.verified_contents()
        return (build_challenge_event(challenge, events, blobs),
                evidence_for_challenge(challenge, events, blobs))

    def record_challenge(self, challenge=None):
        event, evidence = self.built_challenge(challenge)
        self.store.append(event, evidence)
        return event

    def evaluation(self, challenge, observation=None, **changes):
        hypothesis = self.hypothesis.to_dict()
        measurements = []
        if observation is not None:
            for check_type, records, id_field in (
                ("OUTCOME", hypothesis["expected_outcomes"], "outcome_id"),
                ("INVALIDATION", hypothesis["invalidation_conditions"], "condition_id"),
            ):
                for check in records:
                    measurements.append({"check_type": check_type, "check_id": check[id_field],
                                         "metric": check["metric"], "unit": check["unit"],
                                         "observation": copy.deepcopy(observation)})
        value = {
            "schema_version": "blackpod.investment_outcome_evaluation.v1",
            "evaluation_id": "evaluation-store-fixture", "hypothesis_event_id": self.parent.event_id,
            "hypothesis_id": self.hypothesis.hypothesis_id, "hypothesis_sha256": self.parent.source["source_sha256"],
            "challenge_event_id": challenge.event_id, "recorded_at": "2027-04-12T00:00:00Z",
            "evidence_cutoff_at": "2027-04-12T00:00:00Z", "domain": "INVESTMENT", "mode": "SHADOW",
            "evaluator_id": "independent-fixture-evaluator",
            "evaluator_role": hypothesis["evaluation_plan"]["evaluator_role"], "evaluation_stage": "FINAL",
            "supersedes_event_id": None, "measurements": measurements,
            "conclusion": "Synthetic fixed-deadline source-bound comparison only.", "authority": hypothesis["authority"],
        }
        value.update(changes)
        return OutcomeEvaluationInput.from_mapping(value)

    def built_outcome(self, evaluation):
        events, blobs = self.store.verified_contents()
        return (build_outcome_event(evaluation, events, blobs), evidence_for_outcome(evaluation, events, blobs))

    def test_mixed_v1_v2_v3_challenge_later_sources_and_evaluation_exact_chain(self):
        challenge = self.challenge()
        challenged = self.record_challenge(challenge)
        observation = self.later_source()
        evaluation = self.evaluation(challenged, observation)
        evaluated, retained = self.built_outcome(evaluation)
        self.assertEqual(self.store.append(evaluated, retained).sequence, 7)
        events, blobs = self.store.verified_contents()
        self.assertEqual([event.schema_version for event in events],
                         ["blackpod.decision_journal_event.v1"] * 2 +
                         ["blackpod.decision_journal_event.v2", "blackpod.decision_journal_event.v3"] +
                         ["blackpod.decision_journal_event.v1"] * 2 + ["blackpod.decision_journal_event.v3"])
        for event, document, identity_key in ((challenged, challenge, "challenge_id"),
                                              (evaluated, evaluation, "evaluation_id")):
            self.assertEqual(event.domain, "INVESTMENT")
            self.assertEqual(event.decision_id, self.parent.decision_id)
            self.assertEqual(event.event_id, identity("journal-event", {
                "decision_id": self.parent.decision_id, "event_type": event.event_type,
                identity_key: document.to_dict()[identity_key],
            }))
            self.assertEqual(event.source["source_sha256"], sha256_bytes(document.to_bytes()))
            self.assertEqual(blobs[event.source["source_sha256"]], document.to_bytes())
        self.assertEqual(evaluated.payload["evaluation"]["challenge_event_id"], challenged.event_id)
        result = evaluated.payload["result"]
        self.assertEqual(result["comparison_summary"], "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
        self.assertEqual([check["status"] for check in result["check_results"]], ["MET", "NOT_TRIGGERED"])
        self.assertEqual(result["measurement_basis"], "RECORDED_DEADLINE_POINTS_ONLY")
        self.assertFalse(result["whole_horizon_invalidation_established"])
        self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_same_review_identity_retry_noop_changed_content_conflict(self):
        event, retained = self.built_challenge()
        self.store.append(event, retained)
        original = (self.root / "entries/00000004.json").read_bytes()
        self.assertFalse(self.store.append(event, {}).written)
        changed, changed_retained = self.built_challenge(self.challenge(risk_notes=["Changed supplied risk note."]))
        self.assertEqual(changed.event_id, event.event_id)
        with self.assertRaisesRegex(JournalConflictError, "different content"):
            self.store.append(changed, changed_retained)
        self.assertEqual((self.root / "entries/00000004.json").read_bytes(), original)
        self.assert_originals_unchanged()

    def test_outcome_retry_noop_and_changed_result_identity_conflict(self):
        challenge = self.record_challenge()
        observation = self.later_source()
        event, retained = self.built_outcome(self.evaluation(challenge, observation))
        self.store.append(event, retained)
        original = (self.root / "entries/00000007.json").read_bytes()
        self.assertFalse(self.store.append(event, {}).written)
        changed, evidence = self.built_outcome(self.evaluation(challenge, observation, conclusion="Changed commentary."))
        with self.assertRaises(JournalConflictError):
            self.store.append(changed, evidence)
        self.assertEqual((self.root / "entries/00000007.json").read_bytes(), original)

    def test_copied_shared_source_role_does_not_become_independent_evidence(self):
        initial = self.hypothesis.to_dict()["observations"][0]
        copied = {**initial, "observation_id": "copy-revenue", "evidence_role": "STATISTICAL",
                  "provenance_group": "declared-different-group"}
        original = self.challenge().to_dict()["observations"][0]
        challenge = self.challenge(observations=[original, copied])
        event = self.record_challenge(challenge)
        assessment = event.payload["assessment"]
        self.assertEqual(assessment["missing_evidence_roles"], [])
        self.assertFalse(assessment["source_independence_verified"])
        self.assertFalse(assessment["reviewer_identity_authenticated"])
        self.assertTrue(all(not item["independence_verified"] for item in assessment["source_relationships"]))
        self.assertTrue(all(item["relationship"] == "SAME_VALUE_BINDING" for item in assessment["source_relationships"]))
        self.assertEqual(self.store.verify().event_count, 4)

    def test_same_source_bytes_copied_to_another_mission_do_not_gain_independence(self):
        initial = self.hypothesis.to_dict()["observations"][0]
        _, blobs = self.store.verified_contents()
        copied_source = self.later_source(
            mission_id="mission-copied-source", observed_at="2026-10-12T00:00:00Z",
            document=json.loads(blobs[initial["artifact_sha256"]]),
        )
        copied = {**initial, "observation_id": "copied-source-revenue",
                  "source_event_id": copied_source["source_event_id"],
                  "artifact_path": copied_source["artifact_path"],
                  "artifact_sha256": copied_source["artifact_sha256"],
                  "evidence_role": "STATISTICAL", "provenance_group": "asserted-independent-provider"}
        self.assertNotEqual(copied["source_event_id"], initial["source_event_id"])
        self.assertNotEqual(copied["artifact_path"], initial["artifact_path"])
        self.assertEqual(copied["artifact_sha256"], initial["artifact_sha256"])
        first = self.challenge().to_dict()["observations"][0]
        event = self.record_challenge(self.challenge(observations=[first, copied]))
        assessment = event.payload["assessment"]
        self.assertFalse(assessment["source_independence_verified"])
        self.assertEqual(assessment["missing_evidence_roles"], [])
        self.assertTrue(all(item["relationship"] == "SAME_VALUE_BINDING"
                            for item in assessment["source_relationships"]))
        self.assertEqual(self.store.verify().event_count, 6)
        self.assert_originals_unchanged()

    def test_self_review_wrong_hypothesis_and_invalid_assumption_fail_before_append(self):
        for changes in (
            {"reviewer_id": self.hypothesis.author_id},
            {"hypothesis_id": "wrong-hypothesis"},
            {"hypothesis_event_id": identity("journal-event", {"missing": "hypothesis"})},
            {"hypothesis_sha256": sha256_bytes(b"wrong original")},
            {"assumption_reviews": [{"assumption_index": 999, "status": "UNTESTED", "reason": "Wrong index.",
                                     "observation_ids": []}]},
        ):
            with self.subTest(changes=changes), self.assertRaises((ReviewEvidenceError, ContractValidationError)):
                self.built_challenge(self.challenge(**changes))
        self.assertEqual(self.store.verify().event_count, 3)

    def test_observation_recording_cutoff_hash_pointer_and_time_guards(self):
        challenge = self.challenge().to_dict()
        for field, value in (
            ("source_event_id", self.parent.event_id),
            ("artifact_sha256", sha256_bytes(b"missing artifact")),
            ("value", 999), ("value_pointer", "/metrics/absent"),
            ("as_of_pointer", "/schema_version"),
        ):
            changed = copy.deepcopy(challenge)
            changed["observations"][0][field] = value
            with self.subTest(field=field), self.assertRaises((ReviewEvidenceError, ContractValidationError)):
                self.built_challenge(ChallengeInput.from_mapping(changed))
        late = self.later_source()
        late.update(evidence_role="FUNDAMENTAL", provenance_group="later-synthetic")
        changed = copy.deepcopy(challenge)
        changed["observations"] = [late]
        changed["assumption_reviews"] = [dict(item, observation_ids=[late["observation_id"]])
                                         for item in changed["assumption_reviews"]]
        changed["counter_hypotheses"][0]["observation_ids"] = [late["observation_id"]]
        with self.assertRaises((ReviewEvidenceError, ContractValidationError)):
            self.built_challenge(ChallengeInput.from_mapping(changed))

    def test_wrong_evaluator_role_self_evaluation_and_unlinked_challenge_rejected(self):
        challenge = self.record_challenge()
        for changes in (
            {"evaluator_role": "UNAPPROVED_ROLE"},
            {"evaluator_id": self.hypothesis.author_id},
            {"challenge_event_id": self.parent.event_id},
            {"challenge_event_id": identity("journal-event", {"missing": "challenge"})},
            {"hypothesis_id": "wrong-hypothesis"},
        ):
            with self.subTest(changes=changes), self.assertRaises((ReviewEvidenceError, ContractValidationError)):
                self.built_outcome(self.evaluation(challenge, **changes))
        self.assertEqual(self.store.verify().event_count, 4)

    def test_missing_final_measurements_append_inconclusive_without_fabrication(self):
        challenge = self.record_challenge()
        event, retained = self.built_outcome(self.evaluation(challenge))
        self.store.append(event, retained)
        result = self.store.events()[-1].payload["result"]
        self.assertEqual(result["comparison_summary"], "INCONCLUSIVE")
        self.assertEqual([item["status"] for item in result["check_results"]], ["MISSING", "MISSING"])
        self.assertTrue(all(item["observed_value"] is None for item in result["check_results"]))
        self.assert_originals_unchanged()

    def test_deadline_outcome_measurement_wrong_check_metric_unit_rejected(self):
        challenge = self.record_challenge()
        observation = self.later_source()
        base = self.evaluation(challenge, observation).to_dict()
        for field, value in (("check_id", "missing-check"), ("metric", "wrong-metric"), ("unit", "PERCENT")):
            changed = copy.deepcopy(base)
            changed["measurements"][0][field] = value
            with self.subTest(field=field), self.assertRaises((ReviewEvidenceError, ContractValidationError)):
                self.built_outcome(OutcomeEvaluationInput.from_mapping(changed))

    def test_old_observation_time_cannot_hide_future_source_recording(self):
        late = self.later_source(document={
            "schema_version": "blackpod.synthetic_review_evidence.v1", "as_of": "2026-10-11T00:00:00Z",
            "source_kind": "SYNTHETIC_FIXTURE", "margin_change": -2.0,
        })
        late.update(evidence_role="STATISTICAL", provenance_group="asserted-old-measurement")
        challenge = self.challenge().to_dict()
        challenge["observations"] = [late]
        for item in challenge["assumption_reviews"]:
            item["observation_ids"] = [late["observation_id"]]
        challenge["counter_hypotheses"][0]["observation_ids"] = [late["observation_id"]]
        with self.assertRaisesRegex(ReviewEvidenceError, "recorded after"):
            self.built_challenge(ChallengeInput.from_mapping(challenge))
        self.assertEqual(self.store.verify().event_count, 5)

    def test_challenge_link_from_another_actual_hypothesis_cannot_evaluate_original(self):
        original = self.record_challenge()
        other_hypothesis = self.hypothesis.to_dict()
        other_hypothesis["hypothesis_id"] = "other-shadow-hypothesis"
        other_hypothesis = InvestmentHypothesis.from_mapping(other_hypothesis)
        events, blobs = self.store.verified_contents()
        other_parent = build_hypothesis_event(other_hypothesis, events, blobs)
        self.store.append(other_parent, evidence_for_hypothesis(other_hypothesis, events, blobs))
        other_challenge = self.challenge(
            challenge_id="other-hypothesis-challenge", hypothesis_id=other_hypothesis.hypothesis_id,
            hypothesis_event_id=other_parent.event_id, hypothesis_sha256=other_parent.source["source_sha256"],
        )
        other_event = self.record_challenge(other_challenge)
        with self.assertRaisesRegex(ReviewEvidenceError, "same hypothesis"):
            self.built_outcome(self.evaluation(original, challenge_event_id=other_event.event_id))
        self.assertEqual(self.store.verify().event_count, 6)

    def test_superseding_challenge_and_evaluation_append_originals_and_plan_unchanged(self):
        first = self.record_challenge()
        first_raw = (self.root / "entries/00000004.json").read_bytes()
        second = self.record_challenge(self.challenge(
            challenge_id="challenge-correction", supersedes_event_id=first.event_id,
            recorded_at="2026-10-13T00:00:00Z", evidence_cutoff_at="2026-10-13T00:00:00Z",
            risk_notes=["Corrected supplied risk discussion."],
        ))
        first_eval, retained = self.built_outcome(self.evaluation(second))
        self.store.append(first_eval, retained)
        first_eval_raw = (self.root / "entries/00000006.json").read_bytes()
        observation = self.later_source()
        corrected, evidence = self.built_outcome(self.evaluation(
            second, observation, evaluation_id="evaluation-correction", supersedes_event_id=first_eval.event_id,
            recorded_at="2027-04-13T00:00:00Z", evidence_cutoff_at="2027-04-13T00:00:00Z",
        ))
        self.store.append(corrected, evidence)
        self.assertEqual(corrected.payload["evaluation"]["supersedes_event_id"], first_eval.event_id)
        self.assertEqual((self.root / "entries/00000004.json").read_bytes(), first_raw)
        self.assertEqual((self.root / "entries/00000006.json").read_bytes(), first_eval_raw)
        self.assertEqual(self.store.events()[2].payload["evaluation_plan"], self.hypothesis.to_dict()["evaluation_plan"])
        self.assert_originals_unchanged()

    def test_cross_type_missing_and_earlier_supersession_rejected(self):
        first = self.record_challenge()
        for changes in (
            {"supersedes_event_id": self.parent.event_id},
            {"supersedes_event_id": identity("journal-event", {"missing": "review"})},
            {"supersedes_event_id": first.event_id, "recorded_at": "2026-10-11T00:00:00Z",
             "evidence_cutoff_at": "2026-10-11T00:00:00Z"},
        ):
            with self.subTest(changes=changes), self.assertRaises((ReviewEvidenceError, ContractValidationError)):
                self.built_challenge(self.challenge(challenge_id="challenge-supersession-attempt", **changes))

    def test_corrupt_retained_review_source_blocks_verify_and_retry(self):
        event, retained = self.built_challenge()
        self.store.append(event, retained)
        source = self.root / "evidence" / event.source["source_sha256"]
        source.chmod(0o600)
        source.write_bytes(b"corrupt review input")
        for action in (self.store.verify, lambda: self.store.append(event, retained)):
            with self.subTest(action=action), self.assertRaisesRegex(JournalVerificationError, "hash mismatch"):
                action()
        self.assertEqual(len(list((self.root / "entries").iterdir())), 4)

    def test_rehashed_challenge_relationship_tamper_fails_semantic_verification(self):
        event = self.record_challenge()
        entry_path = self.root / "entries/00000004.json"
        entry = json.loads(entry_path.read_bytes())
        entry["event"]["payload"]["assessment"]["source_relationships"][0]["relationship"] = "DISTINCT_RETAINED_ARTIFACT"
        entry["event_sha256"] = sha256_bytes(canonical_json_bytes(entry["event"]))
        entry_path.chmod(0o600)
        entry_path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaisesRegex(JournalVerificationError, "investment review"):
            self.store.verify()

    def test_rehashed_outcome_result_tamper_fails_semantic_verification(self):
        challenge = self.record_challenge()
        observation = self.later_source()
        event, evidence = self.built_outcome(self.evaluation(challenge, observation))
        self.store.append(event, evidence)
        entry_path = self.root / "entries/00000007.json"
        entry = json.loads(entry_path.read_bytes())
        entry["event"]["payload"]["result"]["comparison_summary"] = "EXPECTATIONS_NOT_MET"
        entry["event_sha256"] = sha256_bytes(canonical_json_bytes(entry["event"]))
        entry_path.chmod(0o600)
        entry_path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaisesRegex(JournalVerificationError, "investment review"):
            self.store.verify()

    def test_invalid_review_identity_rejected_under_writer_lock(self):
        event, retained = self.built_challenge()
        for field in ("event_id", "decision_id"):
            changed = event.to_dict()
            changed[field] = identity("journal-" + field.replace("_id", ""), {"wrong": field})
            with self.subTest(field=field), self.assertRaises(JournalVerificationError):
                self.store.append(JournalEvent.from_mapping(changed), retained)
        self.assertEqual(self.store.verify().event_count, 3)

    def test_derived_tamper_rejected_under_writer_lock_before_publication(self):
        event, retained = self.built_challenge()
        changed = event.to_dict()
        changed["payload"]["assessment"]["source_relationships"][0]["relationship"] = "SHARED_ARTIFACT"
        with self.assertRaisesRegex(JournalVerificationError, "investment review"):
            self.store.append(JournalEvent.from_mapping(changed), retained)
        self.assertEqual(self.store.verify().event_count, 3)

    def test_interrupted_review_precommit_recovers_retained_orphan_evidence(self):
        event, retained = self.built_challenge()
        def fail_before_entry(staging, target, name, raw):
            if name == "00000004.json":
                raise JournalPersistenceError("injected before review commit")
            return _publish_immutable(staging, target, name, raw)
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=fail_before_entry):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, retained)
        self.assertEqual(self.store.verify().event_count, 3)
        self.assertGreater(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, retained).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_interrupted_review_postcommit_retry_is_noop(self):
        event, retained = self.built_challenge()
        def fail_after_entry(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name == "00000004.json":
                raise JournalPersistenceError("injected after review commit")
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=fail_after_entry):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, retained)
        self.assertEqual(self.store.verify().event_count, 4)
        original = (self.root / "entries/00000004.json").read_bytes()
        self.assertFalse(self.store.append(event, retained).written)
        self.assertEqual((self.root / "entries/00000004.json").read_bytes(), original)
        self.assert_originals_unchanged()

    def test_outcome_pre_and_postcommit_recovery_preserve_fixed_plan(self):
        challenge = self.record_challenge()
        for after_commit in (False, True):
            with self.subTest(after_commit=after_commit):
                event, retained = self.built_outcome(self.evaluation(
                    challenge, evaluation_id="evaluation-interrupted-" + str(after_commit).lower(),
                ))
                count_before = self.store.verify().event_count
                entry_name = f"{count_before + 1:08d}.json"
                def interrupt(staging, target, name, raw):
                    if name == entry_name and not after_commit:
                        raise JournalPersistenceError("injected before outcome commit")
                    _publish_immutable(staging, target, name, raw)
                    if name == entry_name and after_commit:
                        raise JournalPersistenceError("injected after outcome commit")
                with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
                    with self.assertRaises(JournalPersistenceError):
                        self.store.append(event, retained)
                self.assertEqual(self.store.verify().event_count, count_before + int(after_commit))
                self.assertEqual(self.store.append(event, retained).written, not after_commit)
                self.assertEqual(self.store.verify().event_count, count_before + 1)
                self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_missing_review_evidence_rejected_before_publication(self):
        event, _ = self.built_challenge()
        with self.assertRaisesRegex(JournalVerificationError, "evidence"):
            self.store.append(event, {})
        self.assertEqual(self.store.verify().event_count, 3)

    def test_concurrent_same_identity_commits_once_and_different_reviews_remain_contiguous(self):
        event, retained = self.built_challenge()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.append(event, retained), range(4)))
        self.assertEqual(sum(result.written for result in results), 1)
        self.assertTrue(all(result.sequence == 4 for result in results))
        candidates = [self.built_challenge(self.challenge(challenge_id="challenge-parallel-" + str(index)))
                      for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda candidate: self.store.append(*candidate), candidates))
        self.assertEqual(sorted(result.sequence for result in results), [5, 6])
        self.assertEqual(self.store.verify().event_count, 6)
        self.assert_originals_unchanged()

    def test_no_trade_pnl_or_capital_or_execution_authority_can_be_added(self):
        for document in (self.challenge().to_dict(),):
            for authority in document["authority"]:
                changed = copy.deepcopy(document)
                changed["authority"][authority] = True
                with self.subTest(authority=authority), self.assertRaises(ContractValidationError):
                    ChallengeInput.from_mapping(changed)
        challenge = self.record_challenge()
        outcome, retained = self.built_outcome(self.evaluation(challenge))
        for field, value in (("realized_trade_pnl", 42), ("execution_status", "EXECUTED")):
            changed = outcome.to_dict()
            changed["payload"]["result"][field] = value
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                JournalEvent.from_mapping(changed)
        legacy = EvaluationInput.from_mapping({
            "schema_version": "blackpod.decision_journal_evaluation.v1", "evaluation_id": "legacy-pnl",
            "decision_id": self.missions[-1].decision_id, "recorded_at": "2027-04-12T00:00:00Z",
            "evaluator": "fixture-reviewer", "evaluation_type": "TRADE", "conclusion": "Unsupported PNL.",
            "outcome_status": "OBSERVED", "realized_trade_pnl": 42,
        })
        with self.assertRaisesRegex(ContractValidationError, "P&L"):
            build_evaluation_event(legacy, self.missions[-1])
        self.assertTrue(all(not flag for flag in outcome.payload["result"]["authority"].values()))
        self.assert_originals_unchanged()


if __name__ == "__main__":
    unittest.main()
