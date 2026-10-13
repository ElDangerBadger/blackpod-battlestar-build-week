"""Strict shared research contracts cannot grant operational authority."""
import copy
import unittest

from blackpod_build_week.contracts.research_assessment import ResearchAssessmentRequest, ResearchAssessment
from blackpod_build_week.research_acceptance import assess_research
from test_research_acceptance_trading import material_with_blobs, acceptance_request
from test_research_acceptance_investment import FrozenInvestmentContext


class ResearchAssessmentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = material_with_blobs()
        cls.request = acceptance_request(cls.material)
        cls.assessment = assess_research(cls.request, cls.material["events"], cls.material["blobs"])["assessment"]

    def changed_request_rejects(self, field, value):
        document = copy.deepcopy(self.request); document[field] = value
        with self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(document)

    def changed_assessment_rejects(self, field, value):
        document = self.assessment.to_dict(); document[field] = value
        with self.assertRaises(ValueError): ResearchAssessment.from_mapping(document)

    def test_request_canonical_roundtrip_and_immutability(self):
        request = ResearchAssessmentRequest.from_mapping(self.request)
        self.assertEqual(request.to_bytes(), ResearchAssessmentRequest.from_bytes(request.to_bytes()).to_bytes())
        value = request.to_dict(); value["hypothesis"]["hypothesis_id"] = "altered"
        self.assertEqual(request.hypothesis["hypothesis_id"], self.request["hypothesis"]["hypothesis_id"])
        with self.assertRaises((AttributeError, TypeError)): request.domain = "INVESTMENT"

    def test_exact_fields_and_version(self):
        for field, value in (("schema_version", "future"), ("unexpected", True), ("domain", "CAPITAL_ALLOCATION"), ("assessment_scope", "LIVE_TRADING")):
            with self.subTest(field=field): self.changed_request_rejects(field, value)
        value = copy.deepcopy(self.request); del value["data_cutoff_at"]
        with self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(value)

    def test_unknown_classification_rejects(self):
        self.changed_assessment_rejects("classification", "PROFITABLE")

    def test_malformed_json_duplicate_keys_and_nonfinite_reject(self):
        for raw in (b'{"schema_version":"x","schema_version":"x"}', b'{"x":NaN}', b'[]', b'{'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): ResearchAssessmentRequest.from_bytes(raw)

    def test_domain_methodology_and_document_mismatch_reject(self):
        self.changed_request_rejects("methodology_version", "blackpod.investment_research_acceptance.v1")
        value = copy.deepcopy(self.request); value["hypothesis"]["document_schema_version"] = "blackpod.investment_hypothesis.v1"
        with self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(value)

    def test_cutoff_after_record_clock_rejects(self):
        self.changed_request_rejects("data_cutoff_at", "2025-04-03T00:00:00Z")

    def test_authority_all_disabled_strict_boolean(self):
        for field in self.request["authority"]:
            for unsafe in (True, 1, "false", None):
                value = copy.deepcopy(self.request); value["authority"][field] = unsafe
                with self.subTest(field=field, unsafe=unsafe), self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(value)
        for field in ("auto_trading_enabled", "economic_hypothesis_supported", "source_authentication_verified", "historical_point_in_time_verified"):
            self.changed_assessment_rejects(field, True)
        self.changed_request_rejects("auto_trading_enabled", True)

    def test_governance_status_and_maturity_are_not_promotion(self):
        self.changed_request_rejects("governance_status", "APPROVED")
        self.changed_assessment_rejects("governance_status", "AUTHORIZED")
        self.changed_assessment_rejects("maturity", "VALIDATED_EDGE")

    def test_no_supported_trading_classification(self):
        self.changed_assessment_rejects("classification", "SUPPORTED")
        self.changed_request_rejects("assessment_scope", "DECLARED_DEADLINE_PREDICATES")

    def test_no_supported_broad_investment_classification(self):
        context = FrozenInvestmentContext("final")
        assessment = assess_research(context.request(), context.events, context.blobs)["assessment"].to_dict()
        self.assertEqual(assessment["classification"], "INCONCLUSIVE")
        assessment["classification"] = "SUPPORTED"
        with self.assertRaises(ValueError): ResearchAssessment.from_mapping(assessment)

    def test_exact_native_revision_not_invented_counter(self):
        self.changed_assessment_rejects("hypothesis_revision", {"revision": 1})
        value = self.assessment.hypothesis_revision; value["sha256"] = "a" * 64
        self.changed_assessment_rejects("hypothesis_revision", value)

    def test_candidate_requires_original_evaluation_and_safe_path(self):
        reference = {"path": "claims/result.json", "sha256": "a" * 64, "size_bytes": 1}
        value = copy.deepcopy(self.request); value.update(evaluation_event_id=None, candidate_result_evidence=reference)
        with self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(value)
        for path in ("../claim.json", "/claim.json", "research-acceptance/request.v1.json", "x\\claim.json"):
            value = copy.deepcopy(self.request); value["candidate_result_evidence"] = {**reference, "path": path}
            with self.subTest(path=path), self.assertRaises(ValueError): ResearchAssessmentRequest.from_mapping(value)

    def test_evaluation_timestamp_is_not_invented(self):
        self.changed_assessment_rejects("evaluation_timestamp", None)
        self.changed_assessment_rejects("evaluation_timestamp", "2025-04-03T00:00:00Z")

    def test_performed_evaluation_and_classification_consistency(self):
        self.changed_assessment_rejects("evaluation_performed", False)
        self.changed_assessment_rejects("classification", "EVALUABLE")

    def test_supporting_and_contradictory_indexes_derive_exactly(self):
        self.changed_assessment_rejects("supporting_findings", [])
        self.changed_assessment_rejects("contradictory_findings", [])

    def test_scalar_findings_and_pointer_constraints(self):
        for field, value in (("observed", {}), ("observed", float("inf")), ("effect", "AUTHORIZE"), ("criterion", "inferred support"), ("value_pointer", "not-a-pointer")):
            document = self.assessment.to_dict(); document["findings"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): ResearchAssessment.from_mapping(document)

    def test_duplicate_and_unbounded_findings_reject(self):
        value = self.assessment.findings; value.append(copy.deepcopy(value[0]))
        self.changed_assessment_rejects("findings", value)
        self.changed_assessment_rejects("findings", [])
        self.changed_assessment_rejects("findings", [self.assessment.findings[0]] * 4097)

    def test_limitations_and_next_evidence_required(self):
        self.changed_assessment_rejects("limitations", [])
        self.changed_assessment_rejects("next_evidence_requirements", [])

    def test_hypothesis_evidence_must_be_retained(self):
        value = [ref for ref in self.assessment.evidence if ref != self.request["hypothesis"]["evidence"]]
        self.changed_assessment_rejects("evidence", value)
