"""Runnable governance examples use verified but explicitly synthetic sources."""
from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts.decision_journal import CapitalPolicyProposal
from blackpod_build_week.contracts.investment_governance import (
    ApprovalInput, ProposalInput, RiskContextInput, ShadowRiskPolicy,
)
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.contracts.investment_review import ChallengeInput
from blackpod_build_week.decision_journal_cli import build_policy_event
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.investment_approval import (
    assess_approval, approval_state, build_approval_event, evidence_for_approval,
)
from blackpod_build_week.investment_governance import (
    assess_proposal, build_proposal_event, evidence_for_proposal,
)
from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
from blackpod_build_week.investment_review import build_challenge_event, evidence_for_challenge

CHECKOUT = Path(__file__).resolve().parents[1]
FIXTURES = CHECKOUT / "fixtures/investment_governance"
EXAMPLES = CHECKOUT / "examples"


class InvestmentGovernanceExamplesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = JournalStore(Path(directory.name).resolve() / "journal")
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("process forbidden")))
        self.original_sources = {str(path.relative_to(FIXTURES)): path.read_bytes()
                                 for path in (FIXTURES / "sources").rglob("*") if path.is_file()}
        for label in ("initial", "statistical"):
            root = FIXTURES / "sources" / label / "missions" / ("mission-review-" + label)
            history = load_verified_history(root)
            for event in project_history(history):
                self.store.append(event, dict(history.source_files))
        self.hypothesis = InvestmentHypothesis.from_bytes((FIXTURES / "hypothesis.shadow.v1.json").read_bytes())
        self.challenge = ChallengeInput.from_bytes((FIXTURES / "challenge.shadow.v1.json").read_bytes())
        self.proposal = ProposalInput.from_bytes((EXAMPLES / "investment_proposal.shadow.v1.json").read_bytes())
        self.approval = ApprovalInput.from_bytes((EXAMPLES / "investment_approval.simulated.v1.json").read_bytes())

    def research(self):
        events, blobs = self.store.verified_contents()
        parent = build_hypothesis_event(self.hypothesis, events, blobs)
        self.store.append(parent, evidence_for_hypothesis(self.hypothesis, events, blobs))
        events, blobs = self.store.verified_contents()
        challenge = build_challenge_event(self.challenge, events, blobs)
        self.store.append(challenge, evidence_for_challenge(self.challenge, events, blobs))

    def proposal_event(self):
        events, blobs = self.store.verified_contents()
        event = build_proposal_event(self.proposal, events, blobs)
        self.store.append(event, evidence_for_proposal(self.proposal, events, blobs))
        return event

    def complete(self):
        self.research()
        self.proposal_event()
        events, blobs = self.store.verified_contents()
        approval = build_approval_event(self.approval, events, blobs)
        self.store.append(approval, evidence_for_approval(self.approval, events, blobs))
        policy = CapitalPolicyProposal.from_bytes((EXAMPLES / "capital_policy.proposed.v1.json").read_bytes())
        event = build_policy_event(policy)
        self.store.append(event, {sha256_bytes(policy.to_bytes()): policy.to_bytes()})

    def test_standalone_policy_and_context_bind_embedded_proposal_bytes(self):
        policy = ShadowRiskPolicy.from_bytes((EXAMPLES / "investment_risk_policy.shadow.v1.json").read_bytes())
        context = RiskContextInput.from_bytes((EXAMPLES / "investment_risk_context.shadow.v1.json").read_bytes())
        self.assertEqual(policy.to_dict(), self.proposal.risk_policy)
        self.assertEqual(context.to_dict(), self.proposal.risk_context)
        self.assertEqual(context.source_kind, "SYNTHETIC_FIXTURE")
        self.assertEqual(policy.status, "SHADOW_PROPOSED")

    def test_complete_example_matches_expected_chain_and_evidence_counts(self):
        self.complete()
        expected = json.loads((FIXTURES / "expected/verification.json").read_bytes())
        self.assertEqual(self.store.verify().to_dict(), expected)
        self.assertEqual(expected["event_count"], 9)
        self.assertEqual(expected["evidence_count"], 18)
        for path in (FIXTURES / "expected/entries").iterdir():
            self.assertEqual((self.store.root / "entries" / path.name).read_bytes(), path.read_bytes())

    def test_expected_events_are_exact_source_projections(self):
        self.complete()
        expected = json.loads((FIXTURES / "expected/events.json").read_bytes())
        self.assertEqual([event.to_dict() for event in self.store.events()], expected)
        self.assertEqual(self.original_sources, {str(path.relative_to(FIXTURES)): path.read_bytes()
                                                for path in (FIXTURES / "sources").rglob("*") if path.is_file()})

    def test_ready_reject_defer_reports_match_fixed_fixtures(self):
        self.research()
        events, blobs = self.store.verified_contents()
        self.assertEqual(assess_proposal(self.proposal, events, blobs)["gate"], "REVIEW_READY")
        for label, expected in (("reject", "REJECT"), ("defer", "DEFER")):
            variant = ProposalInput.from_bytes((FIXTURES / ("proposal." + label + ".shadow.v1.json")).read_bytes())
            report = assess_proposal(variant, events, blobs)
            self.assertEqual(report["gate"], expected)
            self.assertEqual(report, json.loads((FIXTURES / "expected" / ("report." + label + ".json")).read_bytes()))

    def test_approval_example_is_simulated_and_scope_bound(self):
        self.research()
        event = self.proposal_event()
        events, blobs = self.store.verified_contents()
        decision = assess_approval(self.approval, events, blobs)
        self.assertEqual(self.approval.origin, "SIMULATED_TEST")
        self.assertEqual(self.approval.proposal_event_id, event.event_id)
        self.assertEqual(self.approval.proposal_sha256, event.source["source_sha256"])
        self.assertEqual(self.approval.scope, "INVESTMENT_SHADOW_RESEARCH_ONLY")
        self.assertEqual(decision["result"], "SIMULATED_SHADOW_APPROVED")
        self.assertFalse(decision["approver_identity_authenticated"])
        self.assertFalse(decision["operational_authority_granted"])
        self.assertTrue(all(value is False for value in decision["authority"].values()))

    def test_initial_capital_policy_does_not_become_rebalance_instruction(self):
        self.complete()
        events, _ = self.store.verified_contents()
        policy = events[-1].payload
        self.assertEqual(policy["status"], "PROPOSED")
        self.assertEqual(policy["rebalance_mode"], "INITIAL_ALLOCATION_ONLY")
        self.assertFalse(policy["activation_enabled"])
        self.assertFalse(policy["capital_transfers_enabled"])
        self.assertFalse(policy["automated_reallocation_enabled"])
        proposal = next(event for event in events if event.event_type == "INVESTMENT_DECISION_PROPOSAL_RECORDED")
        self.assertEqual(proposal.payload["report"]["metrics"]["investment_budget_weight"], 0.5)
        self.assertEqual(proposal.payload["report"]["metrics"]["proposed_investment_gross"], 0.2)
        self.assertEqual(self.proposal.risk_context["cash_by_desk"]["TRADING"], 0.4)

    def test_no_forecast_probabilities_or_realized_trade_outcome_are_invented(self):
        self.complete()
        for event in self.store.events():
            if event.event_type == "INVESTMENT_SHADOW_APPROVAL_RECORDED":
                self.assertIsNone(event.payload["decision"]["realized_trade_pnl"])
                self.assertEqual(event.payload["decision"]["execution_status"], "NOT_EXECUTED")
            if event.event_type in {"INVESTMENT_DECISION_PROPOSAL_RECORDED", "INVESTMENT_SHADOW_APPROVAL_RECORDED"}:
                self.assertNotIn("forecast", event.payload)
                self.assertNotIn("confidence_probability", event.payload)

    def test_explicit_time_query_distinguishes_simulation_from_permission(self):
        self.complete()
        events, _ = self.store.verified_contents()
        proposal = next(event for event in events if event.event_type == "INVESTMENT_DECISION_PROPOSAL_RECORDED")
        self.assertEqual(approval_state(proposal, events, "2026-10-13T00:00:00Z")["state"], "UNREVIEWED")
        state = approval_state(proposal, events, "2026-10-13T00:02:00Z")
        self.assertEqual(state["state"], "SIMULATED_SHADOW_APPROVED")
        self.assertFalse(state["operational_authority_granted"])
        self.assertEqual(approval_state(proposal, events, "2026-10-13T00:30:00Z")["state"], "EXPIRED")


if __name__ == "__main__":
    unittest.main()
