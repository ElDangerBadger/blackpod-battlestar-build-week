"""Frozen, offline representative research cases establish no economic edge."""
import ast
import contextlib
import inspect
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import research_acceptance_examples as examples
from blackpod_build_week.contracts.research_assessment import ResearchAssessmentRequest
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.research_acceptance import assess_research


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class ResearchAcceptanceExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve() / "acceptance-example"
        cls.checkout = Path(__file__).resolve().parents[1]
        cls.protected = [
            cls.checkout / "fixtures/investment_hypothesis",
            cls.checkout / "fixtures/investment_review",
            cls.checkout / "examples/investment_hypothesis.shadow.v1.json",
            cls.checkout / "examples/investment_challenge.shadow.v1.json",
            cls.checkout / "examples/investment_outcome_evaluation.final.v1.json",
        ]
        cls.before = {str(path): state(path) if path.is_dir() else path.read_bytes()
                      for path in cls.protected}
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("provider forbidden")):
            cls.material = examples.representative_material()
            cls.summary = examples.make_examples(cls.root)
            cls.events, cls.blobs = JournalStore(cls.root / "journal").verified_contents()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def case(self, identity):
        return next(case for case in self.summary["cases"] if case["case_id"] == identity)

    def assessment(self, identity):
        case = self.case(identity)
        return next(event.payload["assessment"] for event in self.events
                    if event.event_id == case["assessment_event_id"])

    def test_seven_traceable_cases_exercise_all_six_classifications(self):
        classifications = {case["classification"] for case in self.summary["cases"]}
        self.assertEqual(classifications, {
            "NOT_EVALUABLE", "EVALUABLE", "INCONCLUSIVE", "SUPPORTED", "CONTRADICTED", "INVALID"})
        self.assertEqual(self.summary["assessment_count"], 7)
        self.assertTrue(all(case["findings"] for case in self.summary["cases"]))
        self.assertTrue(all(case["claim_scope"] for case in self.summary["cases"]))

    def test_valid_specification_remains_evaluable_and_unproven(self):
        assessment = self.assessment("valid-unproven")
        self.assertEqual(assessment["classification"], "EVALUABLE")
        self.assertFalse(assessment["evaluation_performed"])
        self.assertIsNone(assessment["evaluation_timestamp"])
        self.assertFalse(assessment["economic_hypothesis_supported"])

    def test_missing_gate_study_defers_without_changing_original_risk(self):
        assessment = self.assessment("missing-prerequisites")
        self.assertEqual(assessment["classification"], "NOT_EVALUABLE")
        material = self.material["trading"]
        result = material["missing_evaluation_event"].payload["result"]
        self.assertEqual(result["status"], "DEFER_EVIDENCE_GATES")
        self.assertEqual(result["calculation_result"]["cost_stress_runs"], [])
        self.assertEqual(material["missing_study_event"].payload["study"]["risk_review_evidence"],
                         material["frozen"]["studies"][0]["study"].risk_review_evidence)

    def test_separate_claimed_success_is_invalid_and_original_is_preserved(self):
        assessment = self.assessment("methodologically-invalid")
        self.assertEqual(assessment["classification"], "INVALID")
        reference = assessment["request"]["candidate_result_evidence"]
        claim = json.loads(self.blobs[reference["sha256"]])
        self.assertEqual(claim["status"], "SUPPORTED")
        original = next(event for event in self.events
                        if event.event_id == assessment["request"]["evaluation_event_id"])
        self.assertEqual(original.payload["result"]["status"], "SHADOW_SIMULATED")
        self.assertTrue(any(finding["effect"] == "INVALID" for finding in assessment["findings"]))

    def test_negative_cash_result_contradicts_only_development_comparison(self):
        assessment = self.assessment("contradicted-comparison")
        self.assertEqual(assessment["classification"], "CONTRADICTED")
        self.assertFalse(assessment["economic_hypothesis_supported"])
        self.assertTrue(assessment["contradictory_findings"])
        self.assertIn("development intervals only", assessment["claim_scope"])

    def test_positive_base_cost_fixture_fails_robustness(self):
        assessment = self.assessment("positive-insufficient-robustness")
        self.assertEqual(assessment["classification"], "INCONCLUSIVE")
        original = next(event for event in self.events
                        if event.event_id == assessment["request"]["evaluation_event_id"])
        runs = original.payload["result"]["calculation_result"]["cost_stress_runs"]
        self.assertTrue(runs[0]["folds"][0]["comparison"]["positive_vs_cash"])
        self.assertFalse(runs[-1]["folds"][0]["comparison"]["positive_vs_cash"])
        self.assertTrue(any(finding["criterion"] == "ECONOMIC_ROBUSTNESS"
                            for finding in assessment["findings"]))

    def test_supported_predicates_do_not_establish_economic_thesis(self):
        narrow = self.assessment("supported-deadline-predicates")
        broad = self.assessment("unresolved-economic-thesis")
        self.assertEqual(narrow["classification"], "SUPPORTED")
        self.assertEqual(broad["classification"], "INCONCLUSIVE")
        self.assertEqual(narrow["claim_scope"], "DECLARED_DEADLINE_PREDICATES_ONLY")
        self.assertEqual(narrow["request"]["hypothesis"], broad["request"]["hypothesis"])
        self.assertEqual(narrow["request"]["evaluation_event_id"], broad["request"]["evaluation_event_id"])
        self.assertFalse(narrow["economic_hypothesis_supported"])
        self.assertFalse(broad["economic_hypothesis_supported"])

    def test_future_investment_measurements_are_explicitly_synthetic(self):
        self.assertTrue(self.summary["future_investment_observations_are_synthetic"])
        narrow = self.assessment("supported-deadline-predicates")
        self.assertEqual(narrow["evaluation_timestamp"], "2027-04-11T00:00:00Z")
        self.assertFalse(self.summary["real_market_performance_evaluated"])
        self.assertFalse(narrow["source_authentication_verified"])

    def test_twenty_five_original_events_preserved_in_same_journal(self):
        original = self.material["events"]
        self.assertEqual(len(original), 25)
        self.assertEqual(len(self.events), 32)
        self.assertEqual([event.to_bytes() for event in self.events[:25]],
                         [event.to_bytes() for event in original])
        self.assertTrue(all(event.schema_version == "blackpod.decision_journal_event.v17"
                            for event in self.events[25:]))

    def test_assessments_use_original_parent_decisions_and_document_revisions(self):
        indexed = {event.event_id: event for event in self.events}
        for event in self.events[25:]:
            assessment = event.payload["assessment"]
            hypothesis = assessment["request"]["hypothesis"]
            self.assertEqual(event.decision_id, indexed[hypothesis["source_event_id"]].decision_id)
            self.assertEqual(assessment["hypothesis_revision"]["sha256"], hypothesis["evidence"]["sha256"])
            self.assertEqual(sha256_bytes(self.blobs[hypothesis["evidence"]["sha256"]]),
                             hypothesis["evidence"]["sha256"])

    def test_journal_has_complete_retention_and_no_orphans(self):
        verified = self.summary["journal_verification"]
        self.assertEqual(verified["event_count"], 32)
        self.assertEqual(verified["orphan_evidence_count"], 0)
        self.assertEqual(verified["staging_orphan_count"], 0)
        self.assertGreater(verified["evidence_count"], 53)

    def test_all_authority_and_operational_actions_remain_disabled(self):
        self.assertEqual(self.summary["provider_calls"], 0)
        self.assertEqual(self.summary["model_inference_calls"], 0)
        self.assertEqual(self.summary["orders_submitted"], 0)
        self.assertFalse(self.summary["auto_trading_enabled"])
        self.assertFalse(self.summary["desk_budget_activated"])
        self.assertFalse(self.summary["capital_transfers_enabled"])
        for event in self.events[25:]:
            assessment = event.payload["assessment"]
            self.assertFalse(assessment["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in assessment["authority"].values()))
            self.assertEqual(assessment["governance_status"], "RESEARCH_ONLY_NOT_AUTHORIZATION")

    def test_final_holdout_and_hypothesis_parameters_remain_unchanged(self):
        self.assertFalse(self.summary["final_holdout_scored"])
        self.assertFalse(self.summary["hypotheses_tuned"])
        for row in self.material["trading"]["frozen"]["studies"]:
            self.assertEqual(row["hypothesis"].signal["parameter_selection"], "PREDECLARED_PROPOSED_NOT_TUNED")
            self.assertEqual(row["result"]["final_holdout"]["scoring_status"], "WITHHELD")

    def test_committed_fixture_documents_and_source_missions_are_unchanged(self):
        after = {str(path): state(path) if path.is_dir() else path.read_bytes()
                 for path in self.protected}
        self.assertEqual(self.before, after)

    def test_requests_are_strict_and_runnable_from_exported_bytes(self):
        for case in self.summary["cases"]:
            request = ResearchAssessmentRequest.from_bytes((self.root / case["request_path"]).read_bytes())
            result = assess_research(request, self.events, self.blobs)
            self.assertEqual(result["assessment"].classification, case["classification"])
            self.assertEqual(result["assessment"].hypothesis_revision, case["hypothesis_revision"])

    def test_retry_preserves_all_artifact_bytes_and_mtimes(self):
        before = state(self.root)
        result = examples.make_examples(self.root)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["journal_verification"], self.summary["journal_verification"])
        self.assertEqual(before, state(self.root))

    def test_retained_journal_replays_after_input_and_claim_files_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "copy"
            shutil.copytree(self.root, root)
            shutil.rmtree(root / "input")
            shutil.rmtree(root / "acceptance-examples")
            self.assertEqual(JournalStore(root / "journal").verify().to_dict(),
                             self.summary["journal_verification"])

    def test_module_has_no_legacy_strategy_or_provider_import(self):
        tree = ast.parse(inspect.getsource(examples))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(any(term in module for term in ("galactica", "alpaca", "modeldock", "navigator_adapter"))
                             for module in imports))

    def test_symlink_output_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = examples.main(["--output-root", str(link)])
            self.assertEqual(status, 2)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(errors.getvalue())


if __name__ == "__main__":
    unittest.main()
