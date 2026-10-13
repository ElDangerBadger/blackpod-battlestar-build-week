"""Offline risk gates, retained lineage, no transfers, and pure projections."""
from __future__ import annotations
import copy
import unittest

import test_investment_review_engine as review_fixture
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.investment_governance import ProposalInput
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
from blackpod_build_week.contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.investment_governance import (
    GovernanceEvidenceError, assess_proposal, build_proposal_event,
    evidence_for_proposal, proposal_context, validate_proposal_event,
)
from blackpod_build_week.investment_review import build_outcome_event, evidence_for_outcome


class GovernanceFixture:
    """Reusable real MissionStore histories with declared synthetic research."""
    def __init__(self):
        self.review = review_fixture.InvestmentReviewEngineTests(methodName="runTest")
        self.review.setUp()
        source = self.review.native_source("statistical", "2026-10-12T00:00:00Z", {"signal": 1.0})
        challenge = self.review.challenge_mapping()
        challenge["observations"].append({**self.review.observation(source, "signal", 1.0, "statistical"),
                                          "evidence_role": "STATISTICAL", "provenance_group": "synthetic-distinct"})
        challenge["disposition"] = "REVIEW_SUPPORTS"
        challenge["unresolved_questions"] = []
        for assumption in challenge["assumption_reviews"]:
            assumption["status"] = "SUPPORTED"
        self.review.record_challenge(challenge)
        self.value = {
            "schema_version": "blackpod.investment_decision_proposal.v1", "proposal_id": "proposal-fixture",
            "recorded_at": "2026-10-13T00:00:00Z", "evidence_cutoff_at": "2026-10-13T00:00:00Z",
            "submitted_by": "fixture-researcher", "hypothesis_event_id": self.review.parent.event_id,
            "hypothesis_id": self.review.hypothesis.hypothesis_id, "hypothesis_sha256": self.review.parent.source["source_sha256"],
            "challenge_event_id": self.review.challenge.event_id, "evaluation_event_id": None,
            "rationale": "Synthetic paper research; no live allocation authority.",
            "targets": [{"symbol": "MSFT", "weight": 0.2}],
            "valid_until": "2026-10-14T00:00:00Z", "supersedes_event_id": None,
            "domain": "INVESTMENT", "mode": "SHADOW", "authority": self.review.hypothesis.authority,
            "risk_policy": {
                "schema_version": "blackpod.investment_shadow_risk_policy.v1", "policy_id": "fixture-risk",
                "policy_version": 1, "recorded_at": "2026-10-13T00:00:00Z", "status": "SHADOW_PROPOSED",
                "domain": "INVESTMENT", "mode": "SHADOW", "method_version": "blackpod.shadow_long_only_risk.v1",
                "max_context_age_seconds": 86400, "max_approval_lifetime_seconds": 3600,
                "required_approver_role": "INVESTMENT_REVIEWER", "authorized_approver_ids": ["declared-approver"],
                "require_final_evaluation": False, "require_role_coverage": True,
                "require_distinct_role_artifacts": True, "require_no_active_dissent": True,
                "limits": {"max_position_weight": 0.4, "max_sector_weight": 0.5, "max_consolidated_gross": 0.8,
                           "max_investment_gross": 0.5, "min_cash_weight": 0.2, "min_liquidity_score": 0.6,
                           "max_stress_loss_weight": 0.2, "max_correlated_pair_weight": 0.5,
                           "high_correlation_threshold": 0.8}, "authority": self.review.hypothesis.authority},
            "risk_context": {
                "schema_version": "blackpod.investment_risk_context.v1", "context_id": "context-fixture",
                "as_of": "2026-10-13T00:00:00Z", "source_kind": "SYNTHETIC_FIXTURE",
                "portfolio_scope_id": "paper-account", "basis": "ACCOUNT_EQUITY_FRACTIONS", "scope_mode": "LONG_ONLY",
                "is_complete": True, "positions": [{"symbol": "MSFT", "desk": "INVESTMENT", "weight": 0.1},
                                                      {"symbol": "AAPL", "desk": "TRADING", "weight": 0.1}],
                "cash_by_desk": {"TRADING": 0.4, "INVESTMENT": 0.4},
                "instruments": [{"symbol": "MSFT", "sector": "TECH", "liquidity_score": 0.9, "stress_loss_fraction": 0.1},
                                {"symbol": "AAPL", "sector": "TECH", "liquidity_score": 0.8, "stress_loss_fraction": 0.2}],
                "correlations": [{"symbol_a": "MSFT", "symbol_b": "AAPL", "correlation": 0.3}]}}

    @property
    def events(self):
        return self.review.events

    @property
    def blobs(self):
        return self.review.blobs

    def close(self):
        self.review.doCleanups()

    def proposal(self, value=None):
        return ProposalInput.from_mapping(self.value if value is None else value)

    def report(self, value=None):
        return assess_proposal(self.proposal(value), self.events, self.blobs)

    def record(self, value=None):
        proposal = self.proposal(value)
        event = build_proposal_event(proposal, self.events, self.blobs)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_proposal(proposal, self.events, self.blobs).values()})
        self.events.append(event)
        return event


class InvestmentGovernanceEngineTests(unittest.TestCase):
    maxDiff = None
    def setUp(self):
        self.fixture = GovernanceFixture()
        self.addCleanup(self.fixture.close)

    def changed(self):
        return copy.deepcopy(self.fixture.value)

    def test_ready_is_pure_source_bound_and_never_authority(self):
        before = [event.to_bytes() for event in self.fixture.events], dict(self.fixture.blobs)
        report = self.fixture.report()
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertEqual(report["approval_scope"], "INVESTMENT_SHADOW_RESEARCH_ONLY")
        self.assertFalse(report["operational_authority_granted"])
        self.assertFalse(report["economic_truth_evaluated"])
        self.assertTrue(all(flag is False for flag in report["authority"].values()))
        self.assertIn("NO_FINAL_OUTCOME_EVALUATION", report["residual_risks"])
        self.assertEqual(report["metrics"]["projected_cash_weight"], 0.7)
        self.assertEqual(before, ([event.to_bytes() for event in self.fixture.events], self.fixture.blobs))
        proposal = self.fixture.proposal()
        event = build_proposal_event(proposal, self.fixture.events, self.fixture.blobs)
        self.assertEqual(event.to_bytes(), build_proposal_event(proposal, self.fixture.events, self.fixture.blobs).to_bytes())
        retained = {**self.fixture.blobs, **{sha256_bytes(raw): raw for raw in evidence_for_proposal(proposal, self.fixture.events, self.fixture.blobs).values()}}
        validate_proposal_event(event, self.fixture.events, retained)
        self.assertNotEqual(event.decision_id, self.fixture.review.parent.decision_id)

    def test_every_hard_cap_and_lower_bound_rejects(self):
        edits = [("max_position_weight", 0.19), ("max_sector_weight", 0.29),
                 ("max_consolidated_gross", 0.29), ("max_investment_gross", 0.19),
                 ("min_cash_weight", 0.71), ("min_liquidity_score", 0.95),
                 ("max_stress_loss_weight", 0.039)]
        for limit, value in edits:
            changed = self.changed()
            changed["risk_policy"]["limits"][limit] = value
            with self.subTest(limit=limit):
                self.assertEqual(self.fixture.report(changed)["gate"], "REJECT")

    def test_correlated_pair_uses_consolidated_weights_and_absolute_correlation(self):
        changed = self.changed()
        changed["risk_context"]["correlations"][0]["correlation"] = -0.8
        changed["risk_policy"]["limits"]["max_correlated_pair_weight"] = 0.29
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REJECT")
        pair = next(item for item in report["checks"] if item["check_id"] == "CORRELATED_PAIR_0")
        self.assertEqual(pair["observed"], 0.3)

    def test_budget_never_uses_trading_cash_or_resets_to_fifty_fifty(self):
        changed = self.changed()
        changed["risk_context"]["positions"][0]["weight"] = 0.2
        changed["risk_context"]["cash_by_desk"] = {"INVESTMENT": 0.4, "TRADING": 0.3}
        changed["targets"][0]["weight"] = 0.55
        changed["risk_policy"]["limits"].update(max_position_weight=0.7, max_sector_weight=0.8, max_investment_gross=0.7)
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertEqual(report["metrics"]["investment_budget_weight"], 0.6)
        changed["targets"][0]["weight"] = 0.61
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REJECT")
        self.assertTrue(any(item["check_id"] == "INVESTMENT_DESK_BUDGET" and item["status"] == "FAIL" for item in report["checks"]))

    def test_fractional_boundary_uses_decimal_and_no_normalization(self):
        changed = self.changed()
        changed["risk_context"]["positions"][1].update(symbol="MSFT", weight=0.1)
        changed["risk_policy"]["limits"]["max_position_weight"] = 0.3
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertEqual(report["metrics"]["projected_symbol_weights"], [{"symbol": "MSFT", "weight": 0.3}])
        changed["risk_context"]["cash_by_desk"]["TRADING"] = 0.4000000000001
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def test_missing_context_data_defers_instead_of_assuming_zero(self):
        edits = [lambda v: v["risk_context"].update(is_complete=False),
                 lambda v: v["risk_context"].update(instruments=[]),
                 lambda v: v["risk_context"]["instruments"][0].update(liquidity_score=None),
                 lambda v: v["risk_context"]["instruments"][0].update(stress_loss_fraction=None),
                 lambda v: v["risk_context"].update(correlations=[]),
                 lambda v: v["risk_context"]["correlations"][0].update(correlation=None),
                 lambda v: v.update(targets=[])]
        for edit in edits:
            changed = self.changed()
            edit(changed)
            with self.subTest(edit=edit):
                self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")
        changed = self.changed()
        changed["targets"][0]["weight"] = 0
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertEqual(report["metrics"]["proposed_investment_gross"], 0)

    def test_stale_context_and_expired_hypothesis_defer(self):
        changed = self.changed()
        changed["risk_context"]["as_of"] = "2026-10-11T00:00:00Z"
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")
        changed = self.changed()
        changed.update(recorded_at="2027-04-12T00:00:00Z", evidence_cutoff_at="2027-04-12T00:00:00Z", valid_until="2027-04-13T00:00:00Z")
        changed["risk_context"]["as_of"] = "2027-04-12T00:00:00Z"
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def test_future_or_fabricated_source_links_fail_integrity(self):
        edits = [lambda v: v.update(hypothesis_sha256="a" * 64),
                 lambda v: v.update(challenge_event_id="journal-event-" + "a" * 64),
                 lambda v: v.update(evaluation_event_id=self.fixture.review.challenge.event_id),
                 lambda v: v.update(evidence_cutoff_at="2026-10-11T00:00:00Z"),
                 lambda v: v["risk_context"].update(as_of="2026-10-14T00:00:00Z"),
                 lambda v: v["risk_policy"].update(recorded_at="2026-10-14T00:00:00Z")]
        for edit in edits:
            changed = self.changed()
            edit(changed)
            with self.subTest(edit=edit), self.assertRaises(GovernanceEvidenceError):
                self.fixture.report(changed)

    def test_duplicate_source_identity_rejected(self):
        with self.assertRaisesRegex(GovernanceEvidenceError, "ambiguous"):
            assess_proposal(self.fixture.proposal(), [*self.fixture.events, self.fixture.events[-1]], self.fixture.blobs)

    def test_report_hash_identity_or_evidence_tampering_rejected(self):
        event = self.fixture.record()
        prefix = self.fixture.events[:-1]
        changed = event.to_dict()
        changed["payload"]["report"]["metrics"]["projected_cash_weight"] = 0.99
        with self.assertRaisesRegex(GovernanceEvidenceError, "projection"):
            validate_proposal_event(JournalEvent.from_mapping(changed), prefix, self.fixture.blobs)
        changed = event.to_dict()
        changed["event_id"] = "journal-event-" + "b" * 64
        with self.assertRaisesRegex(GovernanceEvidenceError, "projection"):
            validate_proposal_event(JournalEvent.from_mapping(changed), prefix, self.fixture.blobs)
        changed_blobs = dict(self.fixture.blobs)
        changed_blobs[event.source["source_sha256"]] = b"wrong"
        with self.assertRaisesRegex(GovernanceEvidenceError, "retained proposal"):
            validate_proposal_event(event, prefix, changed_blobs)

    def new_challenge(self, *, supersedes=False, timestamp="2026-10-13T00:00:00Z", disposition="REVIEW_SUPPORTS", untested=False):
        value = copy.deepcopy(self.fixture.review.challenge.payload["challenge"])
        value.update(challenge_id="second-challenge", recorded_at=timestamp, evidence_cutoff_at=timestamp,
                     disposition=disposition, supersedes_event_id=self.fixture.review.challenge.event_id if supersedes else None)
        if untested:
            value["assumption_reviews"][0]["status"] = "UNTESTED"
        return self.fixture.review.record_challenge(value)

    def test_active_dissent_cannot_be_cherry_picked(self):
        for disposition in ("REVIEW_CONTESTS", "INSUFFICIENT_EVIDENCE"):
            with self.subTest(disposition=disposition):
                event = self.new_challenge(disposition=disposition)
                self.assertEqual(self.fixture.report()["gate"], "DEFER")
                self.fixture.events.remove(event)
        event = self.new_challenge(untested=True)
        self.assertEqual(self.fixture.report()["gate"], "DEFER")
        self.fixture.events.remove(event)
        value = copy.deepcopy(self.fixture.review.challenge.payload["challenge"])
        value.update(challenge_id="questions", unresolved_questions=["Need audited context."])
        self.fixture.review.record_challenge(value)
        self.assertEqual(self.fixture.report()["gate"], "DEFER")

    def test_superseded_selected_challenge_defers_and_new_reference_can_proceed(self):
        original = self.fixture.value["challenge_event_id"]
        event = self.new_challenge(supersedes=True)
        self.assertEqual(self.fixture.report()["gate"], "DEFER")
        changed = self.changed()
        changed["challenge_event_id"] = event.event_id
        self.assertEqual(self.fixture.report(changed)["gate"], "REVIEW_READY")
        self.assertNotEqual(original, event.event_id)

    def test_later_evidence_cannot_rewrite_original_cutoff(self):
        self.new_challenge(timestamp="2026-10-14T00:00:00Z", disposition="REVIEW_CONTESTS")
        self.assertEqual(self.fixture.report()["gate"], "REVIEW_READY")
        changed = self.changed()
        changed.update(recorded_at="2026-10-14T00:00:00Z", evidence_cutoff_at="2026-10-14T00:00:00Z", valid_until="2026-10-15T00:00:00Z")
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def test_missing_declared_role_or_shared_artifact_defers(self):
        value = copy.deepcopy(self.fixture.review.challenge.payload["challenge"])
        value.update(challenge_id="role-omitted")
        value["observations"] = value["observations"][:1]
        event = self.fixture.review.record_challenge(value)
        changed = self.changed()
        changed["challenge_event_id"] = event.event_id
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")
        value = copy.deepcopy(value)
        value.update(challenge_id="shared-role")
        value["observations"].append({**value["observations"][0], "observation_id": "stat-shared", "evidence_role": "STATISTICAL"})
        event = self.fixture.review.record_challenge(value)
        changed["challenge_event_id"] = event.event_id
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def test_final_evaluation_requirement_is_explicit(self):
        changed = self.changed()
        changed["risk_policy"]["require_final_evaluation"] = True
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def record_evaluation(self, *, actual=1, final=False):
        timestamp = "2027-04-11T00:00:00Z" if final else "2026-11-11T00:00:00Z"
        if not final:
            self.fixture.review.draft["invalidation_conditions"][0]["check_by"] = timestamp
            # Rebuild this synthetic parent, then rebuild the supporting challenge.
            self.fixture.review.record_hypothesis()
            self.fixture.events[:] = [event for event in self.fixture.events if event.event_type != "INVESTMENT_CHALLENGE_RECORDED"]
            del self.fixture.review.challenge
            source = self.fixture.review.native_source("new-stat", "2026-10-12T00:00:00Z", {"signal": 1.0})
            value = self.fixture.review.challenge_mapping()
            value["observations"].append({**self.fixture.review.observation(source, "signal", 1.0, "statistical"),
                                         "evidence_role": "STATISTICAL", "provenance_group": "distinct"})
            value.update(disposition="REVIEW_SUPPORTS", unresolved_questions=[])
            for item in value["assumption_reviews"]:
                item["status"] = "SUPPORTED"
            self.fixture.review.record_challenge(value)
            self.fixture.value.update(hypothesis_event_id=self.fixture.review.parent.event_id,
                                      hypothesis_sha256=self.fixture.review.parent.source["source_sha256"],
                                      challenge_event_id=self.fixture.review.challenge.event_id)
        value = self.fixture.review.evaluation_mapping(actual=actual, stage="FINAL" if final else "INTERIM", timestamp=timestamp)
        if not final:
            value["measurements"] = [value["measurements"][1]]
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        event = build_outcome_event(evaluation, self.fixture.events, self.fixture.blobs)
        self.fixture.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_outcome(evaluation, self.fixture.events, self.fixture.blobs).values()})
        self.fixture.events.append(event)
        self.fixture.value.update(recorded_at=timestamp, evidence_cutoff_at=timestamp,
                                  valid_until="2027-04-12T00:00:00Z" if final else "2026-11-12T00:00:00Z")
        self.fixture.value["risk_context"]["as_of"] = timestamp
        return event

    def test_known_invalidation_rejects_without_selected_evaluation(self):
        self.record_evaluation(actual=1)
        self.assertIsNone(self.fixture.value["evaluation_event_id"])
        report = self.fixture.report()
        self.assertEqual(report["gate"], "REJECT")
        self.assertTrue(any(item["reason_code"] == "KNOWN_ACTIVE_INVALIDATION" for item in report["checks"]))

    def test_unmet_final_evaluation_defers_even_when_omitted(self):
        self.record_evaluation(actual=-0.5, final=True)
        self.assertEqual(self.fixture.report()["gate"], "DEFER")

    def test_mature_final_plan_can_pass_at_exact_horizon_endpoint(self):
        event = self.record_evaluation(actual=-1.5, final=True)
        changed = self.changed()
        changed["evaluation_event_id"] = event.event_id
        changed["risk_policy"]["require_final_evaluation"] = True
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertNotIn("NO_FINAL_OUTCOME_EVALUATION", report["residual_risks"])
        self.assertIn("WHOLE_HORIZON_INVALIDATION_NOT_ESTABLISHED", report["residual_risks"])

    def test_policy_and_context_id_collisions_are_rejected(self):
        self.fixture.record()
        changed = self.changed()
        changed["proposal_id"] = "new-proposal"
        changed["risk_policy"]["limits"]["max_position_weight"] = 0.5
        with self.assertRaisesRegex(GovernanceEvidenceError, "policy identity"):
            self.fixture.report(changed)
        changed = self.changed()
        changed["proposal_id"] = "new-proposal"
        changed["risk_context"]["instruments"][0]["liquidity_score"] = 0.8
        with self.assertRaisesRegex(GovernanceEvidenceError, "context identity"):
            self.fixture.report(changed)

    def test_proposal_corrections_require_new_identity_and_nonretreating_cutoff(self):
        prior = self.fixture.record()
        changed = self.changed()
        changed.update(proposal_id="corrected-proposal", supersedes_event_id=prior.event_id)
        self.assertEqual(self.fixture.report(changed)["gate"], "REVIEW_READY")
        changed["proposal_id"] = self.fixture.value["proposal_id"]
        with self.assertRaisesRegex(GovernanceEvidenceError, "new proposal_id"):
            self.fixture.report(changed)
        changed.update(proposal_id="corrected-proposal", evidence_cutoff_at="2026-10-12T00:00:00Z")
        changed["risk_context"]["as_of"] = "2026-10-12T00:00:00Z"
        changed["risk_policy"]["recorded_at"] = "2026-10-12T00:00:00Z"
        with self.assertRaises(GovernanceEvidenceError):
            self.fixture.report(changed)

    def test_negative_rejected_cash_preserved_and_not_clamped(self):
        changed = self.changed()
        changed["targets"] = [{"symbol": "MSFT", "weight": 0.8}, {"symbol": "AAPL", "weight": 0.8}]
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REJECT")
        self.assertEqual(report["metrics"]["projected_cash_weight"], -0.7)

    def test_shared_symbol_exposure_aggregates_both_desks(self):
        changed = self.changed()
        changed["risk_context"]["positions"][1]["symbol"] = "MSFT"
        changed["risk_policy"]["limits"]["max_position_weight"] = 0.29
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REJECT")
        self.assertEqual(report["metrics"]["projected_symbol_weights"], [{"symbol": "MSFT", "weight": 0.3}])
        self.assertEqual(report["metrics"]["projected_sector_weights"], [{"sector": "TECH", "weight": 0.3}])
        self.assertEqual(report["metrics"]["projected_cash_weight"], 0.7)

    def test_cash_only_and_explicit_exits_need_no_unheld_pair_metadata(self):
        changed = self.changed()
        changed["targets"][0]["weight"] = 0
        changed["risk_context"]["correlations"] = []
        changed["risk_context"]["instruments"] = [changed["risk_context"]["instruments"][1]]
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertEqual(report["metrics"]["projected_consolidated_gross"], 0.1)
        self.assertEqual(report["metrics"]["projected_stress_loss_weight"], 0.02)

    def test_missing_trading_metadata_also_defers_consolidated_assessment(self):
        changed = self.changed()
        changed["risk_context"]["instruments"] = changed["risk_context"]["instruments"][:1]
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "DEFER")
        self.assertIsNone(report["metrics"]["projected_stress_loss_weight"])

    def test_staleness_fractional_second_boundary_is_not_truncated(self):
        changed = self.changed()
        changed["risk_context"]["as_of"] = "2026-10-11T23:59:59.5Z"
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")

    def test_hard_failure_precedes_unknown_input(self):
        changed = self.changed()
        changed["risk_context"]["is_complete"] = False
        changed["risk_policy"]["limits"]["max_position_weight"] = 0.1
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REJECT")
        self.assertEqual({item["status"] for item in report["checks"]}, {"PASS", "FAIL", "UNKNOWN"})

    def test_tampered_challenge_cannot_create_permission(self):
        source = self.fixture.review.challenge
        changed = source.to_dict()
        changed["payload"]["assessment"]["source_relationships"][0]["relationship"] = "DISTINCT_RETAINED_ARTIFACT"
        self.fixture.events[self.fixture.events.index(source)] = JournalEvent.from_mapping(changed)
        with self.assertRaisesRegex(GovernanceEvidenceError, "projection"):
            self.fixture.report()

    def test_missing_source_blob_fails_and_earlier_bytes_remain_unchanged(self):
        original = [event.to_bytes() for event in self.fixture.events]
        digest = self.fixture.review.parent.source["source_sha256"]
        del self.fixture.blobs[digest]
        with self.assertRaises(GovernanceEvidenceError):
            self.fixture.report()
        self.assertEqual(original, [event.to_bytes() for event in self.fixture.events])

    def test_superseded_selected_evaluation_defers_without_auto_selecting(self):
        original = self.record_evaluation(actual=-1.5, final=True)
        changed = self.changed()
        changed["evaluation_event_id"] = original.event_id
        value = copy.deepcopy(original.payload["evaluation"])
        value.update(evaluation_id="corrected-evaluation", supersedes_event_id=original.event_id)
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        revised = build_outcome_event(evaluation, self.fixture.events, self.fixture.blobs)
        self.fixture.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_outcome(evaluation, self.fixture.events, self.fixture.blobs).values()})
        self.fixture.events.append(revised)
        self.assertEqual(self.fixture.report(changed)["gate"], "DEFER")
        changed["evaluation_event_id"] = revised.event_id
        self.assertEqual(self.fixture.report(changed)["gate"], "REVIEW_READY")

    def test_optional_interim_no_measurements_is_research_only_ready(self):
        value = self.fixture.review.evaluation_mapping(stage="INTERIM", timestamp="2026-10-13T00:00:00Z")
        value["measurements"] = []
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        event = build_outcome_event(evaluation, self.fixture.events, self.fixture.blobs)
        self.fixture.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_outcome(evaluation, self.fixture.events, self.fixture.blobs).values()})
        self.fixture.events.append(event)
        changed = self.changed()
        changed["evaluation_event_id"] = event.event_id
        report = self.fixture.report(changed)
        self.assertEqual(report["gate"], "REVIEW_READY")
        self.assertIn("NO_FINAL_OUTCOME_EVALUATION", report["residual_risks"])

    def test_retrospective_hypothesis_defers(self):
        self.fixture.review.draft["research_mode"] = "RETROSPECTIVE"
        self.fixture.review.record_hypothesis()
        self.fixture.events[:] = [event for event in self.fixture.events if event.event_type != "INVESTMENT_CHALLENGE_RECORDED"]
        source = self.fixture.review.native_source("retro-stat", "2026-10-12T00:00:00Z", {"signal": 1.0})
        value = self.fixture.review.challenge_mapping()
        value["observations"].append({**self.fixture.review.observation(source, "signal", 1, "statistical"),
                                      "evidence_role": "STATISTICAL", "provenance_group": "distinct"})
        value.update(disposition="REVIEW_SUPPORTS", unresolved_questions=[])
        for assumption in value["assumption_reviews"]:
            assumption["status"] = "SUPPORTED"
        self.fixture.review.record_challenge(value)
        self.fixture.value.update(hypothesis_event_id=self.fixture.review.parent.event_id,
                                  hypothesis_sha256=self.fixture.review.parent.source["source_sha256"],
                                  challenge_event_id=self.fixture.review.challenge.event_id)
        self.assertEqual(self.fixture.report()["gate"], "DEFER")

    def test_source_links_cannot_cross_hypotheses_even_with_valid_hashes(self):
        original = self.fixture.review.hypothesis.to_dict()
        original["hypothesis_id"] = "other-hypothesis"
        hypothesis = InvestmentHypothesis.from_mapping(original)
        event = build_hypothesis_event(hypothesis, self.fixture.events, self.fixture.blobs)
        self.fixture.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_hypothesis(hypothesis, self.fixture.events, self.fixture.blobs).values()})
        self.fixture.events.append(event)
        changed = self.changed()
        changed.update(hypothesis_event_id=event.event_id, hypothesis_id=hypothesis.hypothesis_id,
                       hypothesis_sha256=event.source["source_sha256"])
        with self.assertRaisesRegex(GovernanceEvidenceError, "cross hypotheses"):
            self.fixture.report(changed)

    def test_supersession_validates_original_proposal_projection(self):
        prior = self.fixture.record()
        changed = prior.to_dict()
        changed["payload"]["report"]["metrics"]["projected_cash_weight"] = 0.99
        self.fixture.events[-1] = JournalEvent.from_mapping(changed)
        value = self.changed()
        value.update(proposal_id="correction", supersedes_event_id=prior.event_id)
        with self.assertRaisesRegex(GovernanceEvidenceError, "projection"):
            self.fixture.report(value)

    def test_retained_evidence_includes_original_events_and_hash_bound_bytes(self):
        proposal = self.fixture.proposal()
        evidence = evidence_for_proposal(proposal, self.fixture.events, self.fixture.blobs)
        for event in (self.fixture.review.parent, self.fixture.review.challenge):
            self.assertEqual(evidence[f"source_events/{event.event_id}/event.json"], event.to_bytes())
            for ref in event.evidence:
                self.assertEqual(sha256_bytes(evidence[f"source_evidence/{ref['sha256']}.blob"]), ref["sha256"])
        self.assertEqual(evidence["investment_proposals/proposal-fixture/proposal.json"], proposal.to_bytes())


if __name__ == "__main__":
    unittest.main()
