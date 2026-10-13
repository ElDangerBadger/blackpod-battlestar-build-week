"""Exact native-source closure review; authored quotes establish no alpha."""
import copy
import json
import socket
import unittest
from decimal import localcontext, Inexact, Rounded
from unittest.mock import patch

from blackpod_build_week import native_evidence_closure as engine
from blackpod_build_week.contracts.native_evidence_closure import (
    NativeEvidenceClosureReviewRequest, NativeEvidenceSupplementalReview,
    REQUEST_VERSION, SUPPLEMENTAL_VERSION, CATEGORIES, REVIEW_TYPE,
    validate_result, validate_journal_event,
)
from blackpod_build_week.contracts.segmented_evidence_qualification import SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.segmented_evidence_qualification_journal import binding_material, qualification_material
from blackpod_build_week.native_evidence_closure_journal import review_material
from blackpod_build_week.trading_evidence_qualification_journal import policy_material
from test_segmented_evidence_qualification import fixture_material as segmented_fixture


def reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def append_material(context, material):
    context["events"] = tuple(context["events"]) + (material["event"],)
    context["event_evidence"] = tuple(context["event_evidence"]) + (material["evidence"],)
    context["blobs"].update({sha256_bytes(raw): raw for raw in material["evidence"].values()})


def fixture_material(*, policy_case="clean-declared-design", partial=False, missing_native_coverage=False, spread_override=None):
    """Native prefix ending with exact v20 qualification, before the new review."""
    context = segmented_fixture(policy_case=policy_case, partial=partial, missing_native_coverage=missing_native_coverage, spread_override=spread_override, include_binding=True)
    material = qualification_material(context["request"], context["events"], context["blobs"])
    append_material(context, material)
    context["anchor_qualification_event"] = material["event"]
    context["review_request"] = NativeEvidenceClosureReviewRequest.from_mapping({
        "schema_version": REQUEST_VERSION, "review_id": "unit-native-closure-review", "recorded_at": "2025-04-06T12:00:00Z", "data_cutoff_at": "2025-04-06T11:00:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "NATIVE_EVIDENCE_CLOSURE_REVIEW_ONLY",
        "anchor_qualification_event_id": material["event"].event_id, "candidate_qualification_event_id": None,
        "supplemental_review_evidence": None, "supersedes_event_id": None,
        "auto_trading_enabled": False, "authority": engine.AUTHORITY})
    return context


def supplemental(context, *, noncanonical=False):
    request = context["review_request"]
    value = {"schema_version": SUPPLEMENTAL_VERSION, "supplemental_review_id": "unit-supplemental", "recorded_at": "2025-04-06T08:00:00Z",
        "anchor_qualification_event_id": request.anchor_qualification_event_id, "candidate_qualification_event_id": request.candidate_qualification_event_id,
        "reviewer_id": "declared-unit-reviewer", "review_notes": "This is a fixture review claim, not verified approval.",
        "categories": [{"category": category, "status": "SOURCE_REVIEW_RECORDED", "source_event_ids": [request.anchor_qualification_event_id], "source_documents": [],
            "notes": "Source reviewed; applicability and every native gate remain unchanged."} for category in CATEGORIES],
        "auto_trading_enabled": False, "authority": engine.AUTHORITY}
    raw = json.dumps(value, indent=3, sort_keys=False).encode() if noncanonical else canonical_json_bytes(value)
    ref = reference("unit-native-closure/supplemental.json", raw)
    context["blobs"][ref["sha256"]] = raw
    changed = request.to_dict(); changed["supplemental_review_evidence"] = ref
    return NativeEvidenceClosureReviewRequest.from_mapping(changed), value, raw


def candidate_for(context, *, reviewed_policy=False):
    """Add a later exact native candidate without changing its original inputs."""
    material = copy.copy(context)
    material["blobs"] = dict(context["blobs"])
    if reviewed_policy:
        policy = next(row for row in context["original"]["cases"] if row["case_id"] == "insufficient-joint-sample")["policy_event"]
        value = context["binding"].to_dict()
        value.update(binding_id="unit-candidate-reviewed-binding", recorded_at="2025-04-07T10:00:00Z", qualification_policy_event_id=policy.event_id, supersedes_binding_event_id=context["binding_event"].event_id)
        bound = binding_material(SegmentedEvidenceBinding.from_mapping(value), material["events"], material["blobs"])
        append_material(material, bound)
        binding_id = bound["event"].event_id
        supersedes = None
    else:
        binding_id = context["binding_event"].event_id
        supersedes = context["anchor_qualification_event"].event_id
    value = context["request"].to_dict()
    value.update(qualification_id="unit-later-native-qualification", binding_event_id=binding_id, recorded_at="2025-04-08T12:00:00Z", data_cutoff_at="2025-04-08T11:00:00Z", supersedes_event_id=supersedes)
    qualified = qualification_material(SegmentedEvidenceQualificationRequest.from_mapping(value), material["events"], material["blobs"])
    append_material(material, qualified)
    material["candidate_qualification_event"] = qualified["event"]
    value = context["review_request"].to_dict()
    value.update(candidate_qualification_event_id=qualified["event"].event_id, recorded_at="2025-04-09T12:00:00Z", data_cutoff_at="2025-04-09T11:00:00Z")
    material["review_request"] = NativeEvidenceClosureReviewRequest.from_mapping(value)
    return material


class NativeEvidenceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")):
            cls.clean = fixture_material()
            cls.proposed = fixture_material(policy_case="inactive-proposed-design")
            cls.partial = fixture_material(partial=True)
            cls.missing_coverage = fixture_material(missing_native_coverage=True)
            cls.expensive = fixture_material(spread_override=1.2)
            cls.candidate = candidate_for(cls.clean)
            cls.resolved = candidate_for(cls.proposed, reviewed_policy=True)
            cls.clean_result = engine.review_native_evidence_closure(cls.clean["review_request"], cls.clean["events"], cls.clean["blobs"])

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("inference forbidden")))

    def assess(self, context, request=None):
        return engine.review_native_evidence_closure(request or context["review_request"], context["events"], context["blobs"])

    def test_exact_native_ready_fixture_remains_design_only(self):
        result = self.clean_result["result"]
        self.assertEqual(result["status"], "DESCRIPTIVE_REVIEW_ONLY")
        self.assertEqual(result["anchor_qualification"]["result"], self.clean["anchor_qualification_event"].payload["result"])
        self.assertEqual(result["anchor_qualification"]["result"]["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertFalse(result["uncertainty_computed"])
        self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(result["realized_trade_pnl"])

    def test_source_findings_are_exact_native_pointers_and_hashes(self):
        result = self.clean_result["result"]
        self.assertEqual([item["category"] for item in result["source_findings"]], list(CATEGORIES))
        for finding in result["source_findings"]:
            section = finding["native_value_pointer"].split("/")[-1]
            expected = self.clean["anchor_qualification_event"].payload["result"][section]
            self.assertEqual(finding["native_value_sha256"], sha256_bytes(canonical_json_bytes(expected)))
            self.assertEqual(finding["source_qualification_event_id"], self.clean["anchor_qualification_event"].event_id)

    def test_native_missing_assumptions_and_protocol_are_never_invented(self):
        result = self.assess(self.proposed)["result"]
        native = result["anchor_qualification"]["result"]
        self.assertEqual(native["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", result["missing_prerequisites"])
        self.assertEqual(result["missing_prerequisites"], native["reason_codes"])
        self.assertEqual(native["uncertainty_status"], "MISSING")
        self.assertTrue(all(fold["cost_model"] is None for fold in native["training_calibration"]["folds"]))

    def test_all_supplemental_categories_cannot_clear_missing_native_gates(self):
        context = copy.copy(self.proposed); context["blobs"] = dict(context["blobs"])
        request, _, _ = supplemental(context)
        result = self.assess(context, request)["result"]
        self.assertEqual(result["anchor_qualification"]["result"], self.proposed["anchor_qualification_event"].payload["result"])
        self.assertEqual(result["missing_prerequisites"], self.proposed["anchor_qualification_event"].payload["result"]["reason_codes"])
        self.assertTrue(all(item["status"] == "SOURCE_REVIEW_RECORDED" for item in result["supplemental_review"]["categories"]))
        self.assertFalse(result["supplemental_review_applied_to_native_gates"])
        self.assertFalse(result["reviewer_identity_authenticated"])

    def test_partial_capture_and_terminal_coverage_are_reported_without_models(self):
        result = self.assess(self.partial)["result"]
        self.assertFalse(result["anchor_diagnostics"]["coverage"]["capture_complete"])
        self.assertGreater(result["anchor_diagnostics"]["coverage"]["missing_segments"], 0)
        self.assertTrue(all(fold["cost_model"] is None for fold in result["anchor_qualification"]["result"]["training_calibration"]["folds"]))

    def test_missing_native_independent_continuity_remains_deferred(self):
        result = self.assess(self.missing_coverage)["result"]
        self.assertIn("INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED", result["missing_prerequisites"])
        self.assertFalse(result["anchor_qualification"]["result"]["continuity"]["coverage_supported"])
        self.assertEqual(result["anchor_qualification"]["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")

    def test_wide_spread_extrema_and_native_rows_are_preserved(self):
        result = self.assess(self.expensive)["result"]
        diagnostic = result["anchor_diagnostics"]
        self.assertEqual(diagnostic["totals"]["spread_only_exceedance_counts"]["1"], diagnostic["totals"]["admitted_quote_count"])
        self.assertGreater(int(diagnostic["symbols"][0]["max_spread_bps"].split(".")[0]), 1000)
        self.assertIsNotNone(diagnostic["symbols"][0]["max_spread_witness"])
        self.assertEqual(result["anchor_qualification"]["result"], self.expensive["anchor_qualification_event"].payload["result"])

    def test_later_candidate_preserves_exact_scope_and_both_native_results(self):
        result = self.assess(self.candidate)["result"]
        self.assertEqual(result["anchor_qualification"]["result"], self.candidate["anchor_qualification_event"].payload["result"])
        self.assertEqual(result["candidate_qualification"]["result"], self.candidate["candidate_qualification_event"].payload["result"])
        self.assertEqual(result["reason_comparison"], {"resolved_reason_codes": [], "persisting_reason_codes": [], "new_reason_codes": []})
        self.assertEqual(result["anchor_diagnostics"], result["candidate_diagnostics"])

    def test_resolved_reasons_require_exact_later_native_output(self):
        result = self.assess(self.resolved)["result"]
        self.assertIn("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW", result["reason_comparison"]["resolved_reason_codes"])
        before = set(self.resolved["anchor_qualification_event"].payload["result"]["reason_codes"])
        after = set(self.resolved["candidate_qualification_event"].payload["result"]["reason_codes"])
        self.assertEqual(result["reason_comparison"], {"resolved_reason_codes": sorted(before - after), "persisting_reason_codes": sorted(before & after), "new_reason_codes": sorted(after - before)})
        self.assertEqual(result["candidate_qualification"]["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertFalse(result["native_gate_override"])

    def test_new_native_reasons_and_absent_risk_are_preserved_as_native_gaps(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        value = context["policy"].to_dict()
        value.update(policy_id="unit-later-policy-with-missing-native-risk", recorded_at="2025-04-06T10:00:00Z", risk_review_event_id=None, uncertainty_protocol=None, supersedes_policy_event_id=context["policy_event"].event_id)
        registered = policy_material(value, context["events"], context["blobs"])
        append_material(context, registered)
        value = context["binding"].to_dict()
        value.update(binding_id="unit-missing-native-risk-binding", recorded_at="2025-04-07T10:00:00Z", qualification_policy_event_id=registered["event"].event_id, supersedes_binding_event_id=context["binding_event"].event_id)
        bound = binding_material(value, context["events"], context["blobs"])
        append_material(context, bound)
        value = context["request"].to_dict()
        value.update(qualification_id="unit-missing-native-risk-qualification", binding_event_id=bound["event"].event_id, recorded_at="2025-04-08T12:00:00Z", data_cutoff_at="2025-04-08T11:00:00Z", supersedes_event_id=None)
        qualified = qualification_material(value, context["events"], context["blobs"])
        append_material(context, qualified)
        request = context["review_request"].to_dict()
        request.update(candidate_qualification_event_id=qualified["event"].event_id, recorded_at="2025-04-09T12:00:00Z", data_cutoff_at="2025-04-09T11:00:00Z")
        result = self.assess(context, request)["result"]
        self.assertIn("SIMULATION_RISK_REVIEW_MISSING", result["reason_comparison"]["new_reason_codes"])
        self.assertIn("UNCERTAINTY_STABILITY_PROTOCOL_MISSING", result["reason_comparison"]["new_reason_codes"])
        self.assertIsNone(result["candidate_qualification"]["result"]["risk"]["native_assessment"])
        self.assertEqual(result["candidate_qualification"]["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertEqual(result["reason_comparison"]["new_reason_codes"], qualified["event"].payload["result"]["reason_codes"])

    def test_compact_new_evidence_links_native_corpus_without_duplicate_bytes(self):
        material = self.clean_result
        raw_hashes = {page["body_evidence"]["sha256"] for event in self.clean["segment_events"] for page in event.payload["request"]["pages"]}
        self.assertTrue(raw_hashes.isdisjoint(sha256_bytes(raw) for raw in material["evidence"].values()))
        self.assertFalse(any(path.startswith("unit-segmented/") for path in material["evidence"]))
        self.assertEqual(material["parent"].decision_id, self.clean["anchor_qualification_event"].decision_id)

    def test_noncanonical_supplemental_original_bytes_are_retained_and_replayable(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        request, value, raw = supplemental(context, noncanonical=True)
        self.assertNotEqual(raw, canonical_json_bytes(value))
        first = self.assess(context, request)
        self.assertIn(raw, first["evidence"].values())
        retained = {sha256_bytes(data): data for evidence in context["event_evidence"] for data in evidence.values()}
        retained.update({sha256_bytes(data): data for data in first["evidence"].values()})
        replay = engine.review_native_evidence_closure(request, context["events"], retained)
        self.assertEqual(first, replay)

    def test_supplemental_source_metadata_stays_declared_unverified(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        _, value, _ = supplemental(context)
        raw = b"Authored source-applicability discussion without approval."
        ref = reference("unit-native-closure/source-notes.txt", raw)
        document = {"evidence": ref, "source_url": "https://example.org/review", "captured_at": "2025-04-06T07:00:00Z", "effective_coverage_start_at": "2025-01-01T00:00:00Z", "effective_coverage_end_at": "2025-03-31T23:59:59Z"}
        value["categories"][0]["source_documents"] = [document]
        supplemental_raw = canonical_json_bytes(value); supplemental_ref = reference("unit-native-closure/metadata.json", supplemental_raw)
        context["blobs"].update({ref["sha256"]: raw, supplemental_ref["sha256"]: supplemental_raw})
        request = context["review_request"].to_dict(); request["supplemental_review_evidence"] = supplemental_ref
        result = self.assess(context, request)["result"]
        self.assertEqual(result["supplemental_review"]["categories"][0]["source_documents"], [document])
        self.assertFalse(result["source_applicability_verified"])
        self.assertFalse(result["source_authentication_verified"])

    def test_reference_to_existing_native_raw_source_does_not_duplicate_it(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        _, value, _ = supplemental(context)
        ref = context["segment_events"][0].payload["request"]["pages"][0]["body_evidence"]
        value["categories"][-1]["source_documents"] = [{"evidence": ref, "source_url": None, "captured_at": None, "effective_coverage_start_at": None, "effective_coverage_end_at": None}]
        raw = canonical_json_bytes(value); reviewed = reference("unit-native-closure/native-ref.json", raw)
        context["blobs"][reviewed["sha256"]] = raw
        request = context["review_request"].to_dict(); request["supplemental_review_evidence"] = reviewed
        material = self.assess(context, request)
        self.assertNotIn(ref["sha256"], {sha256_bytes(data) for data in material["evidence"].values()})

    def test_native_result_and_source_tampering_rejects(self):
        context = copy.copy(self.clean)
        value = context["anchor_qualification_event"].to_dict(); value["payload"]["result"]["continuity"]["counts"]["combined_eligible"] += 1
        altered = JournalEvent.from_mapping(value)
        context["events"] = context["events"][:-1] + (altered,)
        with self.assertRaisesRegex(ValueError, "replay"): self.assess(context)
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        ref = context["segment_events"][0].payload["request"]["pages"][0]["body_evidence"]
        context["blobs"][ref["sha256"]] += b" "
        with self.assertRaises(ValueError): self.assess(context)

    def test_pure_api_requires_retained_native_result_and_implementation_leaves(self):
        event = self.clean["anchor_qualification_event"]
        result = next(ref for ref in event.evidence if ref["path"] == "segmented-qualification/result.v1.json")
        implementation = next(ref for ref in event.evidence if ref["path"].startswith("segmented-qualification/implementation/"))
        for reference in (result, implementation):
            for absent in (True, False):
                with self.subTest(path=reference["path"], absent=absent):
                    context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
                    if absent: del context["blobs"][reference["sha256"]]
                    else: context["blobs"][reference["sha256"]] += b" "
                    with self.assertRaises(ValueError): self.assess(context)

    def test_pure_api_requires_related_binding_leaf_even_if_payload_replays(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        reference = next(ref for ref in context["binding_event"].evidence if ref["path"] == "segmented-qualification/binding.v1.json")
        del context["blobs"][reference["sha256"]]
        with self.assertRaises(ValueError): self.assess(context)

    def test_cutoff_cannot_exclude_exact_selected_native_record(self):
        request = self.clean["review_request"].to_dict(); request["data_cutoff_at"] = "2025-04-05T11:59:59Z"
        with self.assertRaisesRegex(ValueError, "cutoff"): self.assess(self.clean, request)

    def test_candidate_cannot_be_earlier_or_different_frozen_capture(self):
        request = self.candidate["review_request"].to_dict()
        request.update(anchor_qualification_event_id=self.candidate["candidate_qualification_event"].event_id, candidate_qualification_event_id=self.candidate["anchor_qualification_event"].event_id)
        with self.assertRaisesRegex(ValueError, "later"): self.assess(self.candidate, request)
        events = self.clean["events"] + tuple(event for event in self.proposed["events"] if event.event_id not in {row.event_id for row in self.clean["events"]})
        request = self.clean["review_request"].to_dict(); request["candidate_qualification_event_id"] = self.proposed["anchor_qualification_event"].event_id
        with self.assertRaises(ValueError): engine.review_native_evidence_closure(request, events, {**self.clean["blobs"], **self.proposed["blobs"]})

    def test_supplemental_clocks_scope_and_unknown_native_event_reject(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        request, value, _ = supplemental(context)
        for change, expected in (({"recorded_at": "2025-04-07T00:00:00Z"}, "cutoff"), ({"anchor_qualification_event_id": self.clean["events"][0].event_id}, "anchor")):
            changed = {**value, **change}; raw = canonical_json_bytes(changed); ref = reference("unit-native-closure/changed.json", raw)
            context["blobs"][ref["sha256"]] = raw
            document = request.to_dict(); document["supplemental_review_evidence"] = ref
            with self.assertRaisesRegex(ValueError, expected): self.assess(context, document)
        changed = copy.deepcopy(value); changed["categories"][0]["source_event_ids"] = [self.clean["original"]["cases"][1]["policy_event"].event_id]
        raw = canonical_json_bytes(changed); ref = reference("unit-native-closure/unrelated.json", raw); context["blobs"][ref["sha256"]] = raw
        document = request.to_dict(); document["supplemental_review_evidence"] = ref
        with self.assertRaisesRegex(ValueError, "native closure"): self.assess(context, document)

    def test_request_and_review_contracts_are_closed_and_immutable(self):
        request = self.clean["review_request"]
        self.assertEqual(request, NativeEvidenceClosureReviewRequest.from_bytes(request.to_bytes()))
        changed = request.to_dict(); changed["authority"]["execution_enabled"] = True
        self.assertFalse(request.authority["execution_enabled"])
        with self.assertRaises(ContractValidationError): NativeEvidenceClosureReviewRequest.from_mapping(changed)
        for field, value in (("auto_trading_enabled", 0), ("scope", "EXECUTION"), ("candidate_qualification_event_id", request.anchor_qualification_event_id), ("data_cutoff_at", "2025-04-07T00:00:00Z")):
            changed = request.to_dict(); changed[field] = value
            with self.assertRaises(ContractValidationError): NativeEvidenceClosureReviewRequest.from_mapping(changed)
        changed = request.to_dict(); changed["extra"] = False
        with self.assertRaises(ContractValidationError): NativeEvidenceClosureReviewRequest.from_mapping(changed)

    def test_nested_review_malformed_values_raise_contract_errors(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        _, original, _ = supplemental(context)
        mutations = [lambda value: value["categories"].append({}), lambda value: value["categories"].__setitem__(0, {}),
            lambda value: value["categories"][0].__setitem__("source_event_ids", [{}]),
            lambda value: value["categories"][0].__setitem__("status", "APPROVED"),
            lambda value: value["categories"][0].__setitem__("source_documents", [{}]),
            lambda value: value.__setitem__("authority", {}), lambda value: value.__setitem__("auto_trading_enabled", True)]
        for mutation in mutations:
            changed = copy.deepcopy(original); mutation(changed)
            with self.assertRaises(ContractValidationError): NativeEvidenceSupplementalReview.from_mapping(changed)

    def test_result_contract_rejects_authority_metrics_reason_and_diagnostic_upgrades(self):
        original = self.clean_result["result"]
        mutations = [lambda value: value.__setitem__("economic_hypothesis_supported", True),
            lambda value: value.__setitem__("uncertainty_computed", True), lambda value: value.__setitem__("native_gate_override", True),
            lambda value: value.__setitem__("realized_trade_pnl", "1"), lambda value: value.__setitem__("status", "APPROVED"),
            lambda value: value.__setitem__("missing_prerequisites", ["MADE_UP"]),
            lambda value: value["reason_comparison"].__setitem__("resolved_reason_codes", ["MADE_UP"]),
            lambda value: value["source_findings"][0].__setitem__("native_status", "APPROVED"),
            lambda value: value.__setitem__("limitations", [{}]), lambda value: value.__setitem__("authority", {}),
            lambda value: value["anchor_diagnostics"].__setitem__("cost_applicability_verified", True)]
        for mutation in mutations:
            changed = copy.deepcopy(original); mutation(changed)
            with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_native_nested_missing_status_raises_contract_error_without_keyerror(self):
        result = copy.deepcopy(self.clean_result["result"])
        del result["anchor_qualification"]["result"]["risk"]["native_assessment"]["status"]
        result["anchor_qualification"]["result_sha256"] = sha256_bytes(canonical_json_bytes(result["anchor_qualification"]["result"]))
        with self.assertRaises(ContractValidationError): validate_result(result)

    def test_exact_retry_and_linked_supersession_preserve_original_review(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        recorded = review_material(context["review_request"], context["events"], context["blobs"])
        append_material(context, recorded)
        request = context["review_request"].to_dict(); request.update(review_id="unit-linked-native-review", recorded_at="2025-04-07T12:00:00Z", data_cutoff_at="2025-04-07T11:00:00Z", supersedes_event_id=recorded["event"].event_id)
        later = review_material(request, context["events"], context["blobs"])
        append_material(context, later)
        retry = review_material(self.clean["review_request"], context["events"], context["blobs"])
        self.assertEqual(retry["event"].to_bytes(), recorded["event"].to_bytes())
        self.assertEqual(retry["evidence"], recorded["evidence"])
        self.assertEqual(later["event"].payload["prior_review_event_ids"], [recorded["event"].event_id])
        request.update(review_id="unit-forked-native-review")
        with self.assertRaisesRegex(ValueError, "unsuperseded"): self.assess(context, request)

    def test_supersession_cannot_retreat_cutoff_or_native_candidate(self):
        context = copy.copy(self.candidate); context["blobs"] = dict(context["blobs"])
        recorded = review_material(context["review_request"], context["events"], context["blobs"])
        append_material(context, recorded)
        request = context["review_request"].to_dict(); request.update(review_id="unit-candidate-retreat", recorded_at="2025-04-10T12:00:00Z", data_cutoff_at="2025-04-10T11:00:00Z", supersedes_event_id=recorded["event"].event_id, candidate_qualification_event_id=None)
        with self.assertRaisesRegex(ValueError, "retreat"): self.assess(context, request)
        request = context["review_request"].to_dict(); request.update(review_id="unit-cutoff-retreat", recorded_at="2025-04-10T12:00:00Z", data_cutoff_at="2025-04-08T12:00:00Z", supersedes_event_id=recorded["event"].event_id)
        with self.assertRaisesRegex(ValueError, "backwards"): self.assess(context, request)

    def test_backdated_prior_history_identity_conflicts_and_duplicate_history_reject(self):
        context = copy.copy(self.clean); context["blobs"] = dict(context["blobs"])
        recorded = review_material(context["review_request"], context["events"], context["blobs"])
        append_material(context, recorded)
        request = context["review_request"].to_dict(); request.update(review_id="unit-backdated-review", recorded_at="2025-04-06T10:00:00Z", data_cutoff_at="2025-04-06T09:00:00Z")
        with self.assertRaisesRegex(ValueError, "backdate"): self.assess(context, request)
        request = context["review_request"].to_dict(); request["recorded_at"] = "2025-04-07T12:00:00Z"
        with self.assertRaisesRegex(ValueError, "immutable"): self.assess(context, request)
        context["events"] += (context["events"][0],)
        with self.assertRaisesRegex(ValueError, "ambiguous"): self.assess(context)

    def test_decimal_host_context_cannot_change_native_review(self):
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True; context.traps[Rounded] = True
            result = self.assess(self.clean)
        self.assertEqual(result, self.clean_result)

    def test_original_events_blobs_and_return_aliases_remain_immutable(self):
        events = tuple(event.to_bytes() for event in self.clean["events"]); blobs = dict(self.clean["blobs"])
        result = self.assess(self.clean)
        result["result"]["anchor_qualification"]["result"]["continuity"]["counts"]["combined_eligible"] = 10000
        self.assertEqual(tuple(event.to_bytes() for event in self.clean["events"]), events)
        self.assertEqual(self.clean["blobs"], blobs)
        self.assertEqual(self.assess(self.clean), self.clean_result)


if __name__ == "__main__":
    unittest.main()
