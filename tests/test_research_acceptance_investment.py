"""Offline investment acceptance over unchanged committed research fixtures."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
from blackpod_build_week.investment_review import (
    build_challenge_event, build_outcome_event, evidence_for_challenge, evidence_for_outcome,
)
from blackpod_build_week.research_acceptance_investment import assess_investment_acceptance

CHECKOUT = Path(__file__).resolve().parents[1]


class FrozenInvestmentContext:
    """Compose original examples without changing their definitions or sources."""
    def __init__(self, outcome=None, challenge=True):
        self.events, self.blobs = [], {}
        self.import_history("fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example")
        self.hypothesis = InvestmentHypothesis.from_bytes(self.read("examples/investment_hypothesis.shadow.v1.json"))
        self.hypothesis_event = build_hypothesis_event(self.hypothesis, self.events, self.blobs)
        self.add(self.hypothesis_event, evidence_for_hypothesis(self.hypothesis, self.events, self.blobs))
        self.challenge_event, self.evaluation_event = None, None
        if challenge:
            self.import_history("fixtures/investment_review/missions/mission-investment-challenge-evidence")
            review = ChallengeInput.from_bytes(self.read("examples/investment_challenge.shadow.v1.json"))
            self.challenge_event = build_challenge_event(review, self.events, self.blobs)
            self.add(self.challenge_event, evidence_for_challenge(review, self.events, self.blobs))
        if outcome is not None:
            if outcome in {"final", "invalidation"}:
                self.import_history("fixtures/investment_review/missions/mission-investment-outcome-evidence")
            evaluation = OutcomeEvaluationInput.from_bytes(self.read("examples/investment_outcome_evaluation." + outcome + ".v1.json"))
            self.evaluation_event = build_outcome_event(evaluation, self.events, self.blobs)
            self.add(self.evaluation_event, evidence_for_outcome(evaluation, self.events, self.blobs))

    @staticmethod
    def read(path):
        return (CHECKOUT / path).read_bytes()

    def import_history(self, path):
        history = load_verified_history(CHECKOUT / path)
        self.events.extend(project_history(history))
        self.blobs.update({sha256_bytes(raw): raw for raw in history.source_files.values()})

    def add(self, event, evidence):
        self.events.append(event)
        self.blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})

    def request(self, scope="EXPLORATORY_RESEARCH"):
        research = self.challenge_event or self.hypothesis_event
        selected = self.evaluation_event or research
        canonical_ref = next(dict(ref) for ref in self.hypothesis_event.evidence
                             if self.blobs[ref["sha256"]] == self.hypothesis.to_bytes())
        return {
            "schema_version": "blackpod.research_assessment_request.v1",
            "assessment_id": "investment-acceptance-fixture-001", "domain": "INVESTMENT",
            "recorded_at": selected.recorded_at, "data_cutoff_at": selected.recorded_at,
            "assessment_scope": scope, "methodology_version": "blackpod.investment_research_acceptance.v1",
            "hypothesis": {"hypothesis_id": self.hypothesis.hypothesis_id,
                "source_event_id": self.hypothesis_event.event_id,
                "document_schema_version": self.hypothesis.schema_version, "evidence": canonical_ref},
            "research_event_id": research.event_id,
            "evaluation_event_id": None if self.evaluation_event is None else self.evaluation_event.event_id,
            "candidate_result_evidence": None, "supersedes_event_id": None,
            "governance_status": "RESEARCH_ONLY_NOT_AUTHORIZATION", "auto_trading_enabled": False,
            "authority": self.hypothesis.authority,
        }

    def candidate(self, request, candidate=None, raw=None, path="candidates/investment-result.json"):
        raw = canonical_json_bytes(candidate) if raw is None else raw
        ref = {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        self.blobs[ref["sha256"]] = raw
        request["candidate_result_evidence"] = ref
        return ref

    def assess(self, request=None):
        return assess_investment_acceptance(self.request() if request is None else request, self.events, self.blobs)


class InvestmentAcceptanceTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.network = patch("socket.socket", side_effect=AssertionError("network forbidden"))
        self.process = patch("subprocess.run", side_effect=AssertionError("producer subprocess forbidden"))
        self.network.start()
        self.process.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.process.stop)

    def test_original_draft_is_evaluable_but_unproven(self):
        context = FrozenInvestmentContext(challenge=False)
        result = context.assess()["assessment_fields"]
        self.assertEqual(result["classification"], "EVALUABLE")
        self.assertFalse(result["evaluation_performed"])
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertIn("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED", result["limitations"])
        self.assertTrue(any(item["criterion"] == "INDEPENDENT_CHALLENGE" for item in result["findings"]))

    def test_declared_challenge_is_opinion_not_economic_support(self):
        context = FrozenInvestmentContext()
        result = context.assess()["assessment_fields"]
        self.assertEqual(result["classification"], "EVALUABLE")
        statuses = {item["native_status"]: item["mapped_classification"] for item in result["native_status_mapping"]}
        self.assertEqual(statuses["SHADOW_DRAFT"], "EVALUABLE")
        self.assertEqual(statuses["REVIEW_CONTESTS"], "INCONCLUSIVE")
        self.assertIn("SYNTHETIC_FIXTURE_NOT_REAL_INVESTMENT_EVIDENCE", result["limitations"])
        self.assertFalse(result["source_authentication_verified"])
        self.assertFalse(result["historical_point_in_time_verified"])

    def test_missing_economic_prerequisites_are_not_evaluable(self):
        context = FrozenInvestmentContext()
        result = context.assess(context.request("ECONOMIC_VALIDATION"))["assessment_fields"]
        self.assertEqual(result["classification"], "NOT_EVALUABLE")
        self.assertTrue(any(item["criterion"] == "ECONOMIC_VALIDATION" and item["effect"] == "PREREQUISITE" for item in result["findings"]))

    def test_narrow_deadline_without_evaluation_is_not_evaluable(self):
        context = FrozenInvestmentContext()
        result = context.assess(context.request("DECLARED_DEADLINE_PREDICATES"))["assessment_fields"]
        self.assertEqual(result["classification"], "NOT_EVALUABLE")
        self.assertFalse(result["evaluation_performed"])

    def test_existing_pending_comparison_is_unresolved_not_failure(self):
        context = FrozenInvestmentContext("interim")
        for scope in ("EXPLORATORY_RESEARCH", "DECLARED_DEADLINE_PREDICATES"):
            with self.subTest(scope=scope):
                result = context.assess(context.request(scope))["assessment_fields"]
                self.assertEqual(result["classification"], "INCONCLUSIVE")
                self.assertTrue(result["evaluation_performed"])
                self.assertIn("PENDING", [item["native_status"] for item in result["native_status_mapping"]])
                self.assertFalse(any(item["effect"] == "CONTRADICTS" for item in result["findings"]))
                self.assertIn("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED", result["limitations"])

    def test_existing_missing_mature_comparison_is_inconclusive(self):
        context = FrozenInvestmentContext("missing")
        result = context.assess(context.request("DECLARED_DEADLINE_PREDICATES"))["assessment_fields"]
        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertNotIn("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED", result["limitations"])
        self.assertFalse(any(item["effect"] == "CONTRADICTS" for item in result["findings"]))

    def test_frozen_positive_endpoint_does_not_support_economic_thesis(self):
        context = FrozenInvestmentContext("final")
        result = context.assess()["assessment_fields"]
        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertEqual(result["claim_scope"], "INVESTMENT_THESIS_EVIDENTIARY_STRENGTH")
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertIn("ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION", [item["native_status"] for item in result["native_status_mapping"]])

    def test_frozen_endpoint_support_is_restricted_to_original_predicates(self):
        context = FrozenInvestmentContext("final")
        result = context.assess(context.request("DECLARED_DEADLINE_PREDICATES"))["assessment_fields"]
        self.assertEqual(result["classification"], "SUPPORTED")
        self.assertEqual(result["claim_scope"], "DECLARED_DEADLINE_PREDICATES_ONLY")
        self.assertEqual(result["maturity"], "DESCRIPTIVE_ONLY")
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertIn("SYNTHETIC_FIXTURE_NOT_REAL_INVESTMENT_EVIDENCE", result["limitations"])
        self.assertIn("SUPPORT_OR_CONTRADICTION_RESTRICTED_TO_EXACT_RECORDED_PREDICATES", result["limitations"])

    def test_narrow_original_invalidation_is_contradicted(self):
        context = FrozenInvestmentContext("invalidation")
        result = context.assess(context.request("DECLARED_DEADLINE_PREDICATES"))["assessment_fields"]
        self.assertEqual(result["classification"], "CONTRADICTED")
        self.assertIn("INVALIDATION_TRIGGERED", [item["native_status"] for item in result["native_status_mapping"]])
        observed = [item["observed"] for item in result["findings"] if item["criterion"] == "DECLARED_DEADLINE_COMPARISON"]
        self.assertEqual(observed, [0.5, 0.5])
        self.assertFalse(result["economic_hypothesis_supported"])

    def test_synthetic_invalidation_does_not_establish_real_economic_failure(self):
        context = FrozenInvestmentContext("invalidation")
        result = context.assess()["assessment_fields"]
        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertTrue(any(item["effect"] == "CONTRADICTS" for item in result["findings"]))

    def test_full_economic_validation_requires_more_than_passed_comparisons(self):
        context = FrozenInvestmentContext("final")
        result = context.assess(context.request("ECONOMIC_VALIDATION"))["assessment_fields"]
        self.assertEqual(result["classification"], "NOT_EVALUABLE")
        criteria = {item["criterion"] for item in result["findings"] if item["effect"] == "PREREQUISITE"}
        self.assertTrue({"VALUATION_APPLICABILITY", "FUNDAMENTAL_METRIC_SEMANTICS", "ECONOMIC_VALIDATION"} <= criteria)

    def test_candidate_mismatch_is_invalid_and_retained_without_mutation(self):
        context = FrozenInvestmentContext("final")
        originals = [event.to_bytes() for event in context.events]
        candidate = copy.deepcopy(context.evaluation_event.payload["result"])
        candidate["comparison_summary"] = "INVALIDATION_TRIGGERED"
        request = context.request("DECLARED_DEADLINE_PREDICATES")
        ref = context.candidate(request, candidate)
        before = dict(context.blobs)
        result = context.assess(request)
        self.assertEqual(result["assessment_fields"]["classification"], "INVALID")
        self.assertEqual(result["evidence"][ref["path"]], context.blobs[ref["sha256"]])
        self.assertEqual(originals, [event.to_bytes() for event in context.events])
        self.assertEqual(before, context.blobs)
        self.assertTrue(any(item["effect"] == "INVALID" for item in result["assessment_fields"]["findings"]))

    def test_exact_candidate_is_replayed_but_not_promoted(self):
        context = FrozenInvestmentContext("final")
        request = context.request()
        context.candidate(request, context.evaluation_event.payload["result"])
        result = context.assess(request)["assessment_fields"]
        self.assertEqual(result["classification"], "INCONCLUSIVE")
        self.assertTrue(any(item["criterion"] == "RESULT_REPLAY_CONSISTENCY" and item["effect"] == "SUPPORTS" for item in result["findings"]))

    def test_noncanonical_whitespace_candidate_keeps_same_semantics(self):
        context = FrozenInvestmentContext("final")
        request = context.request("DECLARED_DEADLINE_PREDICATES")
        context.candidate(request, raw=json.dumps(context.evaluation_event.payload["result"], indent=4).encode())
        self.assertEqual(context.assess(request)["assessment_fields"]["classification"], "SUPPORTED")

    def test_malformed_candidate_is_invalid_not_native_validation_bypass(self):
        for raw in (b"broken", b'{"comparison_summary":"PENDING","comparison_summary":"INCONCLUSIVE"}', b'{"value":NaN}'):
            with self.subTest(raw=raw):
                context = FrozenInvestmentContext("final")
                request = context.request()
                context.candidate(request, raw=raw, path="candidates/broken.raw")
                self.assertEqual(context.assess(request)["assessment_fields"]["classification"], "INVALID")

    def test_missing_candidate_bytes_rejected(self):
        context = FrozenInvestmentContext("final")
        request = context.request()
        ref = context.candidate(request, context.evaluation_event.payload["result"])
        del context.blobs[ref["sha256"]]
        with self.assertRaises(ValueError):
            context.assess(request)

    def test_wrong_hypothesis_identity_or_schema_rejected(self):
        context = FrozenInvestmentContext()
        for field, value in (("hypothesis_id", "other-hypothesis"), ("document_schema_version", "blackpod.investment_hypothesis.v2")):
            with self.subTest(field=field):
                request = context.request()
                request["hypothesis"][field] = value
                with self.assertRaises(ValueError):
                    context.assess(request)

    def test_exact_hypothesis_ref_membership_required(self):
        context = FrozenInvestmentContext()
        request = context.request()
        request["hypothesis"]["evidence"]["path"] = "renamed/hypothesis.json"
        with self.assertRaises(ValueError):
            context.assess(request)

    def test_retained_hypothesis_bytes_corruption_rejected(self):
        context = FrozenInvestmentContext()
        request = context.request()
        digest = request["hypothesis"]["evidence"]["sha256"]
        context.blobs[digest] += b" "
        with self.assertRaises(ValueError):
            context.assess(request)

    def test_original_observation_corruption_rejected(self):
        context = FrozenInvestmentContext()
        digest = context.hypothesis.observations[0]["artifact_sha256"]
        context.blobs[digest] = b"{}"
        with self.assertRaises(ValueError):
            context.assess()

    def test_duplicate_source_event_identity_rejected(self):
        context = FrozenInvestmentContext()
        context.events.append(context.hypothesis_event)
        with self.assertRaises(ValueError):
            context.assess()

    def test_cutoff_before_selected_source_rejected(self):
        context = FrozenInvestmentContext("final")
        request = context.request()
        request["data_cutoff_at"] = "2027-04-10T23:59:59Z"
        with self.assertRaises(ValueError):
            context.assess(request)

    def test_selected_hypothesis_with_outcome_retains_implicit_exact_challenge(self):
        context = FrozenInvestmentContext("final")
        request = context.request("DECLARED_DEADLINE_PREDICATES")
        request["research_event_id"] = context.hypothesis_event.event_id
        result = context.assess(request)
        self.assertEqual(result["assessment_fields"]["classification"], "SUPPORTED")
        self.assertTrue(any(context.challenge_event.event_id in path for path in result["evidence"]))
        self.assertIn(context.challenge_event.event_id, [item["source_event_id"] for item in result["assessment_fields"]["native_status_mapping"]])

    def test_event_order_not_arbitrary_latest_selection(self):
        context = FrozenInvestmentContext("final")
        request = context.request()
        context.events.remove(context.challenge_event)
        context.events.append(context.challenge_event)
        with self.assertRaises(ValueError):
            context.assess(request)

    def test_pure_deterministic_output_and_byte_preservation(self):
        context = FrozenInvestmentContext("final")
        before_events = [event.to_bytes() for event in context.events]
        before_blobs = dict(context.blobs)
        request = context.request("DECLARED_DEADLINE_PREDICATES")
        before_request = copy.deepcopy(request)
        first, second = context.assess(request), context.assess(request)
        self.assertEqual(first, second)
        self.assertEqual(request, before_request)
        self.assertEqual(context.blobs, before_blobs)
        self.assertEqual([event.to_bytes() for event in context.events], before_events)

    def test_every_scalar_finding_pointer_resolves_original_event(self):
        from blackpod_build_week.research_acceptance import _validate_findings
        for outcome in (None, "interim", "missing", "final", "invalidation"):
            with self.subTest(outcome=outcome):
                context = FrozenInvestmentContext(outcome)
                result = context.assess(context.request("DECLARED_DEADLINE_PREDICATES"))
                _validate_findings(result["assessment_fields"], context.events)

    def test_shared_strict_assessment_preserves_scope_evidence_and_disabled_authority(self):
        from blackpod_build_week.research_acceptance import assess_research
        context = FrozenInvestmentContext("final")
        result = assess_research(context.request("DECLARED_DEADLINE_PREDICATES"), context.events, context.blobs)
        document = result["assessment"]
        self.assertEqual(document.classification, "SUPPORTED")
        self.assertEqual(document.hypothesis_revision["sha256"], context.hypothesis_event.source["source_sha256"])
        self.assertFalse(document.auto_trading_enabled)
        self.assertTrue(all(value is False for value in document.authority.values()))
        self.assertFalse(document.economic_hypothesis_supported)
        self.assertEqual(document.evaluation_timestamp, context.evaluation_event.recorded_at)

    def test_missing_declared_role_is_indexed_exactly_and_not_independence(self):
        from blackpod_build_week.research_acceptance import _validate_findings
        context = FrozenInvestmentContext()
        original = context.challenge_event
        value = copy.deepcopy(original.payload["challenge"])
        value["challenge_id"] = "missing-statistical-role-challenge"
        for observation in value["observations"]:
            if observation["evidence_role"] == "STATISTICAL":
                observation["evidence_role"] = "MACRO"
        review = ChallengeInput.from_mapping(value)
        context.challenge_event = build_challenge_event(review, context.events, context.blobs)
        context.add(context.challenge_event, evidence_for_challenge(review, context.events, context.blobs))
        result = context.assess(context.request("ECONOMIC_VALIDATION"))["assessment_fields"]
        _validate_findings(result, context.events)
        self.assertEqual(result["classification"], "NOT_EVALUABLE")
        role = next(item for item in result["findings"] if item["criterion"] == "FUNDAMENTAL_AND_STATISTICAL_EVIDENCE")
        self.assertEqual(role["observed"], "STATISTICAL")
        self.assertEqual(role["value_pointer"], "/payload/assessment/missing_evidence_roles/0")

    def test_different_relative_source_paths_preserve_all_bytes(self):
        context = FrozenInvestmentContext("final")
        result = context.assess()
        evidence = result["evidence"]
        self.assertTrue(any("research/synthetic_observations.json" in path for path in evidence))
        self.assertTrue(any("outcomes/synthetic_measurements.json" in path for path in evidence))
        self.assertEqual(len(evidence), len(set(evidence)))
        for raw in evidence.values():
            self.assertEqual(context.blobs[sha256_bytes(raw)], raw)

    def test_frozen_examples_and_fixtures_unchanged_by_evaluation(self):
        paths = [CHECKOUT / "examples/investment_hypothesis.shadow.v1.json",
                 CHECKOUT / "examples/investment_challenge.shadow.v1.json",
                 CHECKOUT / "examples/investment_outcome_evaluation.final.v1.json",
                 CHECKOUT / "fixtures/investment_review/missions/mission-investment-outcome-evidence/outcomes/synthetic_measurements.json"]
        before = {path: path.read_bytes() for path in paths}
        FrozenInvestmentContext("final").assess()
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_no_trading_metric_or_pnl_substitution(self):
        result = FrozenInvestmentContext("final").assess()["assessment_fields"]
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertTrue(all(item["criterion"] not in {"GROSS_RETURN", "NET_RETURN", "SHARPE", "TRADE_PNL"} for item in result["findings"]))
        self.assertIn("SHADOW_RESEARCH_HAS_NO_REALIZED_TRADE_PNL", result["limitations"])


if __name__ == "__main__":
    unittest.main()
