"""Deterministic declared-human SHADOW approval gates, never actual investing."""
from __future__ import annotations

import copy
import unittest

import test_investment_review_engine as review_fixtures
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.investment_governance import ApprovalInput, ProposalInput
from blackpod_build_week.contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_approval import (
    ApprovalEvidenceError, approval_state, assess_approval, build_approval_event,
    evidence_for_approval, validate_approval_event,
)
from blackpod_build_week.investment_review import (
    build_challenge_event, evidence_for_challenge, build_outcome_event, evidence_for_outcome,
)
from blackpod_build_week.investment_governance import build_proposal_event, evidence_for_proposal


class ApprovalFixture:
    """Reuse the real MissionStore-backed synthetic source builder."""

    def __init__(self, *, due_at=None):
        self.research = review_fixtures.InvestmentReviewEngineTests("runTest")
        self.research.setUp()
        r = self.research
        if due_at is not None:
            for item in r.draft["expected_outcomes"]:
                item["due_at"] = due_at
            for item in r.draft["invalidation_conditions"]:
                item["check_by"] = due_at
            r.record_hypothesis()
        observations = []
        for label, role, metric in (("fundamental", "FUNDAMENTAL", 5.0), ("statistical", "STATISTICAL", 6.0)):
            event = r.native_source(label, "2026-10-12T00:00:00Z", {"metric": metric})
            observations.append({**r.observation(event, "metric", metric, label),
                                 "evidence_role": role, "provenance_group": label})
        challenge = r.challenge_mapping()
        challenge.update(observations=observations, disposition="REVIEW_SUPPORTS", unresolved_questions=[])
        for item in challenge["assumption_reviews"]:
            item.update(status="SUPPORTED", observation_ids=["fundamental", "statistical"])
        challenge["counter_hypotheses"][0]["observation_ids"] = ["fundamental", "statistical"]
        self.challenge = r.record_challenge(challenge)
        self.events, self.blobs = r.events, r.blobs
        authority = r.hypothesis.authority
        self.proposal_value = {
            "schema_version": "blackpod.investment_decision_proposal.v1", "proposal_id": "proposal-approval-fixture",
            "recorded_at": "2026-10-12T00:00:00Z", "evidence_cutoff_at": "2026-10-12T00:00:00Z",
            "submitted_by": "fixture-submitter", "hypothesis_event_id": r.parent.event_id,
            "hypothesis_id": r.hypothesis.hypothesis_id, "hypothesis_sha256": r.parent.source["source_sha256"],
            "challenge_event_id": self.challenge.event_id, "evaluation_event_id": None,
            "rationale": "Synthetic source-bound SHADOW portfolio risk review only.",
            "targets": [{"symbol": "MSFT", "weight": 0.1}],
            "risk_policy": {
                "schema_version": "blackpod.investment_shadow_risk_policy.v1", "policy_id": "risk-policy-fixture",
                "policy_version": 1, "recorded_at": "2026-10-11T00:00:00Z", "status": "SHADOW_PROPOSED",
                "domain": "INVESTMENT", "mode": "SHADOW", "method_version": "blackpod.shadow_long_only_risk.v1",
                "max_context_age_seconds": 600, "max_approval_lifetime_seconds": 600,
                "required_approver_role": "SHADOW_RESEARCH_REVIEWER", "authorized_approver_ids": ["fixture-approver"],
                "require_final_evaluation": False, "require_role_coverage": True,
                "require_distinct_role_artifacts": True, "require_no_active_dissent": True,
                "limits": {"max_position_weight": 0.3, "max_sector_weight": 0.8, "max_consolidated_gross": 0.8,
                           "max_investment_gross": 0.5, "min_cash_weight": 0.2, "min_liquidity_score": 0.5,
                           "max_stress_loss_weight": 0.3, "max_correlated_pair_weight": 0.8,
                           "high_correlation_threshold": 0.7}, "authority": authority,
            },
            "risk_context": {
                "schema_version": "blackpod.investment_risk_context.v1", "context_id": "context-approval-fixture",
                "as_of": "2026-10-12T00:00:00Z", "source_kind": "SYNTHETIC_FIXTURE",
                "portfolio_scope_id": "portfolio-fixture", "basis": "ACCOUNT_EQUITY_FRACTIONS",
                "scope_mode": "LONG_ONLY", "is_complete": True,
                "positions": [{"symbol": "MSFT", "desk": "INVESTMENT", "weight": 0.2},
                              {"symbol": "AAPL", "desk": "TRADING", "weight": 0.2}],
                "cash_by_desk": {"TRADING": 0.3, "INVESTMENT": 0.3},
                "instruments": [{"symbol": symbol, "sector": "TECH", "liquidity_score": 0.9,
                                 "stress_loss_fraction": 0.2} for symbol in ("MSFT", "AAPL")],
                "correlations": [{"symbol_a": "MSFT", "symbol_b": "AAPL", "correlation": 0.8}],
            },
            "valid_until": "2026-10-12T00:10:00Z", "supersedes_event_id": None,
            "domain": "INVESTMENT", "mode": "SHADOW", "authority": authority,
        }
        self.proposal = self.record_proposal(self.proposal_value)

    def close(self):
        self.research.doCleanups()

    def record_proposal(self, value):
        proposal = ProposalInput.from_mapping(value)
        event = build_proposal_event(proposal, self.events, self.blobs)
        evidence = evidence_for_proposal(proposal, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
        return event

    def approval(self, **changes):
        p = self.proposal
        report = p.payload["report"]
        value = {
            "schema_version": "blackpod.investment_shadow_approval.v1", "approval_id": "approval-fixture",
            "proposal_event_id": p.event_id, "proposal_id": p.payload["proposal"]["proposal_id"],
            "proposal_sha256": p.source["source_sha256"], "risk_policy_sha256": report["risk_policy_sha256"],
            "risk_context_sha256": report["risk_context_sha256"], "report_sha256": sha256_bytes(canonical_json_bytes(report)),
            "recorded_at": "2026-10-12T00:01:00Z", "approver_id": "fixture-approver",
            "approver_role": "SHADOW_RESEARCH_REVIEWER", "action": "APPROVE", "origin": "SIMULATED_TEST",
            "scope": "INVESTMENT_SHADOW_RESEARCH_ONLY", "acknowledged_residual_risks": report["residual_risks"],
            "expires_at": "2026-10-12T00:09:00Z", "revokes_approval_event_id": None,
            "confirmation": {"action": "APPROVE", "proposal_sha256": p.source["source_sha256"],
                             "acknowledges_shadow_only": True},
            "domain": "INVESTMENT", "mode": "SHADOW", "authority": p.payload["proposal"]["authority"],
        }
        value.update(changes)
        if "action" in changes:
            value["confirmation"] = {**value["confirmation"], "action": changes["action"]}
            if changes["action"] != "APPROVE":
                value["expires_at"] = None
        return ApprovalInput.from_mapping(value)

    def record(self, approval):
        event = build_approval_event(approval, self.events, self.blobs)
        evidence = evidence_for_approval(approval, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
        return event

    def later_evaluation(self, actual):
        r = self.research
        source = r.native_source("late-outcome", "2026-10-12T00:00:30Z", {"margin": actual},
                                 point_at=r.hypothesis.expected_outcomes[0]["due_at"])
        observation = r.observation(source, "margin", actual, "late-margin", unit="PERCENTAGE_POINTS")
        value = {**r.base_review(), "schema_version": "blackpod.investment_outcome_evaluation.v1",
                 "evaluation_id": "late-evaluation", "challenge_event_id": self.challenge.event_id,
                 "recorded_at": "2026-10-12T00:00:30Z", "evidence_cutoff_at": "2026-10-12T00:00:30Z",
                 "evaluator_id": "separate-evaluator", "evaluator_role": r.hypothesis.evaluation_plan["evaluator_role"],
                 "evaluation_stage": "INTERIM", "conclusion": "Synthetic deadline comparison only.",
                 "measurements": [
                     {"check_type": check_type, "check_id": check[id_field], "metric": check["metric"],
                      "unit": check["unit"], "observation": observation}
                     for check_type, rules, id_field in (("OUTCOME", r.hypothesis.expected_outcomes, "outcome_id"),
                         ("INVALIDATION", r.hypothesis.invalidation_conditions, "condition_id")) for check in rules
                 ]}
        evaluation = OutcomeEvaluationInput.from_mapping(value)
        event = build_outcome_event(evaluation, self.events, self.blobs)
        evidence = evidence_for_outcome(evaluation, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
        return event


class InvestmentApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ApprovalFixture()
        self.addCleanup(self.fixture.close)
        self.events, self.blobs = self.fixture.events, self.fixture.blobs

    def test_positive_is_simulated_shadow_only_and_pure(self):
        before = [event.to_bytes() for event in self.events], dict(self.blobs)
        result = assess_approval(self.fixture.approval(), self.events, self.blobs)
        self.assertEqual(self.fixture.proposal.payload["report"]["gate"], "REVIEW_READY")
        self.assertEqual(result["result"], "SIMULATED_SHADOW_APPROVED")
        self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertFalse(result["operational_authority_granted"])
        self.assertFalse(result["approver_identity_authenticated"])
        self.assertTrue(all(value is False for value in result["authority"].values()))
        self.assertEqual(before, ([event.to_bytes() for event in self.events], dict(self.blobs)))

    def test_reject_and_defer_have_no_expiry_or_permission(self):
        for action in ("REJECT", "DEFER"):
            with self.subTest(action=action):
                result = assess_approval(self.fixture.approval(action=action), self.events, self.blobs)
                self.assertEqual(result["result"], action + "RED" if action == "DEFER" else "REJECTED")
                self.assertIsNone(result["expires_at"])
                self.assertFalse(result["operational_authority_granted"])

    def test_hash_substitution_fails(self):
        for field in ("risk_policy_sha256", "risk_context_sha256", "report_sha256"):
            with self.subTest(field=field), self.assertRaises(ApprovalEvidenceError):
                assess_approval(self.fixture.approval(**{field: "f" * 64}), self.events, self.blobs)

    def test_proposal_identity_substitution_fails(self):
        for changes in ({"proposal_id": "wrong-proposal"}, {"proposal_event_id": "journal-event-" + "f" * 64}):
            with self.subTest(changes=changes), self.assertRaises(ApprovalEvidenceError):
                assess_approval(self.fixture.approval(**changes), self.events, self.blobs)

    def test_unlisted_actor_and_wrong_role_fail(self):
        for changes in ({"approver_id": "unknown-actor"}, {"approver_role": "CAPITAL_ALLOCATION"}):
            with self.subTest(changes=changes), self.assertRaises(ApprovalEvidenceError):
                assess_approval(self.fixture.approval(**changes), self.events, self.blobs)

    def test_role_separation_cannot_be_overridden_by_allowlist(self):
        for actor in ("fixture-submitter", self.fixture.research.hypothesis.author_id,
                      self.fixture.challenge.payload["challenge"]["reviewer_id"]):
            f = ApprovalFixture()
            self.addCleanup(f.close)
            value = copy.deepcopy(f.proposal_value)
            value["proposal_id"] += "-role"
            value["risk_policy"]["policy_id"] += "-role"
            value["risk_policy"]["authorized_approver_ids"] = [actor]
            f.proposal = f.record_proposal(value)
            with self.subTest(actor=actor), self.assertRaises(ApprovalEvidenceError):
                assess_approval(f.approval(approver_id=actor), f.events, f.blobs)

    def test_selected_evaluator_cannot_approve_even_when_allowlisted(self):
        f = ApprovalFixture(due_at="2026-10-12T00:00:00Z")
        self.addCleanup(f.close)
        evaluation = f.later_evaluation(-2.0)
        value = copy.deepcopy(f.proposal_value)
        value.update(proposal_id="proposal-selected-evaluator", recorded_at="2026-10-12T00:00:40Z",
                     evidence_cutoff_at="2026-10-12T00:00:40Z", evaluation_event_id=evaluation.event_id)
        value["risk_policy"]["policy_id"] += "-evaluator"
        value["risk_policy"]["authorized_approver_ids"] = ["separate-evaluator"]
        f.proposal = f.record_proposal(value)
        self.assertEqual(f.proposal.payload["report"]["gate"], "REVIEW_READY")
        with self.assertRaisesRegex(ApprovalEvidenceError, "must differ"):
            assess_approval(f.approval(approver_id="separate-evaluator"), f.events, f.blobs)

    def test_cannot_bypass_reject_risk_report(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value["proposal_id"] += "-reject"
        value["targets"][0]["weight"] = 0.9
        self.fixture.proposal = self.fixture.record_proposal(value)
        self.assertEqual(self.fixture.proposal.payload["report"]["gate"], "REJECT")
        with self.assertRaises(ApprovalEvidenceError):
            assess_approval(self.fixture.approval(), self.events, self.blobs)

    def test_cannot_bypass_defer_risk_report(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value["proposal_id"] += "-defer"
        value["risk_context"]["context_id"] += "-missing"
        value["risk_context"]["instruments"][0]["liquidity_score"] = None
        self.fixture.proposal = self.fixture.record_proposal(value)
        self.assertEqual(self.fixture.proposal.payload["report"]["gate"], "DEFER")
        with self.assertRaises(ApprovalEvidenceError):
            assess_approval(self.fixture.approval(), self.events, self.blobs)

    def test_context_freshness_is_rechecked_at_approval(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value["proposal_id"] += "-long-validity"
        value["valid_until"] = "2026-10-12T01:00:00Z"
        self.fixture.proposal = self.fixture.record_proposal(value)
        approval = self.fixture.approval(recorded_at="2026-10-12T00:11:00Z", expires_at="2026-10-12T00:12:00Z")
        with self.assertRaisesRegex(ApprovalEvidenceError, "stale"):
            assess_approval(approval, self.events, self.blobs)

    def test_expired_proposal_cannot_be_approved(self):
        approval = self.fixture.approval(recorded_at="2026-10-12T00:11:00Z", expires_at="2026-10-12T00:12:00Z")
        with self.assertRaisesRegex(ApprovalEvidenceError, "expired"):
            assess_approval(approval, self.events, self.blobs)

    def test_hypothesis_horizon_end_blocks_an_otherwise_unexpired_packet(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value.update(proposal_id="proposal-long-validity", valid_until="2027-04-12T00:00:00Z")
        value["risk_policy"]["policy_id"] += "-long-validity"
        value["risk_policy"].update(max_context_age_seconds=10**10, max_approval_lifetime_seconds=10**10)
        self.fixture.proposal = self.fixture.record_proposal(value)
        approval = self.fixture.approval(recorded_at="2027-04-11T00:00:00Z", expires_at="2027-04-11T01:00:00Z")
        with self.assertRaisesRegex(ApprovalEvidenceError, "horizon has ended"):
            assess_approval(approval, self.events, self.blobs)

    def test_approval_cannot_predate_proposal(self):
        with self.assertRaisesRegex(ApprovalEvidenceError, "predate"):
            assess_approval(self.fixture.approval(recorded_at="2026-10-11T23:59:00Z"), self.events, self.blobs)

    def test_expiry_cannot_outlive_bound_proposal(self):
        with self.assertRaisesRegex(ApprovalEvidenceError, "expiry"):
            assess_approval(self.fixture.approval(expires_at="2026-10-12T00:11:00Z"), self.events, self.blobs)

    def test_residual_acknowledgments_must_cover_exact_report(self):
        with self.assertRaisesRegex(ApprovalEvidenceError, "every recorded"):
            assess_approval(self.fixture.approval(acknowledged_residual_risks=["unrelated-risk"]), self.events, self.blobs)

    def test_new_dissent_blocks_an_older_packet(self):
        r = self.fixture.research
        value = self.fixture.challenge.payload["challenge"]
        value.update(challenge_id="later-dissent", recorded_at="2026-10-12T00:00:30Z",
                     evidence_cutoff_at="2026-10-12T00:00:30Z", disposition="REVIEW_CONTESTS")
        challenge = ChallengeInput.from_mapping(value)
        event = build_challenge_event(challenge, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence_for_challenge(challenge, self.events[:-1], self.blobs).values()})
        with self.assertRaisesRegex(ApprovalEvidenceError, "active challenge"):
            assess_approval(self.fixture.approval(), self.events, self.blobs)

    def test_new_support_with_untested_assumptions_or_questions_blocks(self):
        for field in ("assumption", "question"):
            f = ApprovalFixture()
            self.addCleanup(f.close)
            value = f.challenge.payload["challenge"]
            value.update(challenge_id="later-" + field, recorded_at="2026-10-12T00:00:30Z",
                         evidence_cutoff_at="2026-10-12T00:00:30Z")
            if field == "assumption":
                value["assumption_reviews"][0]["status"] = "UNTESTED"
            else:
                value["unresolved_questions"] = ["New unresolved source discrepancy."]
            challenge = ChallengeInput.from_mapping(value)
            event = build_challenge_event(challenge, f.events, f.blobs)
            evidence = evidence_for_challenge(challenge, f.events, f.blobs)
            f.events.append(event)
            f.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
            with self.subTest(field=field), self.assertRaisesRegex(ApprovalEvidenceError, "active challenge"):
                assess_approval(f.approval(), f.events, f.blobs)

    def test_known_later_invalidation_or_unmet_expectation_blocks(self):
        for actual, message in ((0.0, "invalidation"), (-0.5, "unmet expectations")):
            f = ApprovalFixture(due_at="2026-10-12T00:00:00Z")
            self.addCleanup(f.close)
            self.assertEqual(f.proposal.payload["report"]["gate"], "REVIEW_READY")
            f.later_evaluation(actual)
            with self.subTest(actual=actual), self.assertRaisesRegex(ApprovalEvidenceError, message):
                assess_approval(f.approval(), f.events, f.blobs)

    def test_very_large_policy_durations_do_not_overflow(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value["proposal_id"] += "-duration"
        value["risk_policy"]["policy_id"] += "-duration"
        value["risk_policy"].update(max_approval_lifetime_seconds=10**20, max_context_age_seconds=10**20)
        self.fixture.proposal = self.fixture.record_proposal(value)
        result = assess_approval(self.fixture.approval(), self.events, self.blobs)
        self.assertEqual(result["result"], "SIMULATED_SHADOW_APPROVED")

    def test_superseded_selected_review_requires_new_proposal(self):
        value = self.fixture.challenge.payload["challenge"]
        value.update(challenge_id="later-support", recorded_at="2026-10-12T00:00:30Z",
                     evidence_cutoff_at="2026-10-12T00:00:30Z", supersedes_event_id=self.fixture.challenge.event_id)
        challenge = ChallengeInput.from_mapping(value)
        event = build_challenge_event(challenge, self.events, self.blobs)
        evidence = evidence_for_challenge(challenge, self.events, self.blobs)
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
        with self.assertRaisesRegex(ApprovalEvidenceError, "superseded"):
            assess_approval(self.fixture.approval(), self.events, self.blobs)

    def test_newer_portfolio_context_requires_new_proposal(self):
        value = copy.deepcopy(self.fixture.proposal_value)
        value.update(proposal_id="newer-context", recorded_at="2026-10-12T00:00:30Z",
                     evidence_cutoff_at="2026-10-12T00:00:30Z")
        value["risk_context"].update(context_id="newer-context", as_of="2026-10-12T00:00:30Z")
        self.fixture.record_proposal(value)
        with self.assertRaisesRegex(ApprovalEvidenceError, "newer known"):
            assess_approval(self.fixture.approval(), self.events, self.blobs)

    def test_only_one_review_action_per_proposal(self):
        self.fixture.record(self.fixture.approval())
        with self.assertRaisesRegex(ApprovalEvidenceError, "already has"):
            assess_approval(self.fixture.approval(approval_id="second-action", action="REJECT"), self.events, self.blobs)

    def test_revoke_exact_prior_approve_and_retry_preserves_original(self):
        approval = self.fixture.approval()
        first = self.fixture.record(approval)
        revoke = self.fixture.approval(approval_id="revoke-fixture", action="REVOKE",
            revokes_approval_event_id=first.event_id, recorded_at="2026-10-12T00:02:00Z")
        second = self.fixture.record(revoke)
        self.assertEqual(second.payload["decision"]["result"], "REVOKED")
        self.assertEqual(build_approval_event(approval, self.events, self.blobs).to_bytes(), first.to_bytes())
        self.assertEqual(build_approval_event(revoke, self.events, self.blobs).to_bytes(), second.to_bytes())
        with self.assertRaisesRegex(ApprovalEvidenceError, "only once"):
            assess_approval(self.fixture.approval(approval_id="revoke-again", action="REVOKE",
                revokes_approval_event_id=first.event_id, recorded_at="2026-10-12T00:03:00Z"), self.events, self.blobs)

    def test_cannot_revoke_reject_or_unknown_approval(self):
        rejection = self.fixture.record(self.fixture.approval(action="REJECT"))
        with self.assertRaisesRegex(ApprovalEvidenceError, "earlier APPROVE"):
            assess_approval(self.fixture.approval(approval_id="wrong-revoke", action="REVOKE",
                revokes_approval_event_id=rejection.event_id), self.events, self.blobs)

    def test_revocation_cannot_predate_approval(self):
        first = self.fixture.record(self.fixture.approval())
        with self.assertRaisesRegex(ApprovalEvidenceError, "predate"):
            assess_approval(self.fixture.approval(approval_id="early-revoke", action="REVOKE",
                revokes_approval_event_id=first.event_id, recorded_at="2026-10-12T00:00:30Z"), self.events, self.blobs)

    def test_time_specific_state_expiry_and_revocation(self):
        p = self.fixture.proposal
        self.assertEqual(approval_state(p, self.events, "2026-10-12T00:00:00Z")["state"], "UNREVIEWED")
        first = self.fixture.record(self.fixture.approval())
        self.assertEqual(approval_state(p, self.events, "2026-10-12T00:02:00Z")["state"], "SIMULATED_SHADOW_APPROVED")
        self.assertEqual(approval_state(p, self.events, "2026-10-12T00:09:00Z")["state"], "EXPIRED")
        self.fixture.record(self.fixture.approval(approval_id="revocation", action="REVOKE",
            revokes_approval_event_id=first.event_id, recorded_at="2026-10-12T00:03:00Z"))
        self.assertEqual(approval_state(p, self.events, "2026-10-12T00:02:00Z")["state"], "SIMULATED_SHADOW_APPROVED")
        result = approval_state(p, self.events, "2026-10-12T00:10:00Z")
        self.assertEqual(result["state"], "REVOKED")
        self.assertFalse(result["operational_authority_granted"])

    def test_event_validation_rejects_rehashed_semantic_substitution(self):
        approval = self.fixture.approval()
        event = build_approval_event(approval, self.events, self.blobs)
        evidence = evidence_for_approval(approval, self.events, self.blobs)
        blobs = {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}}
        validate_approval_event(event, self.events, blobs)
        value = event.to_dict()
        value["event_id"] = "journal-event-" + "f" * 64
        with self.assertRaisesRegex(ApprovalEvidenceError, "source projection"):
            validate_approval_event(JournalEvent.from_mapping(value), self.events, blobs)


if __name__ == "__main__":
    unittest.main()
