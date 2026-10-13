"""Deterministic segmented qualification; authored data demonstrate no alpha."""
import copy
from datetime import timedelta
from decimal import Decimal, localcontext, Inexact, Rounded
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import segmented_evidence_qualification as engine
from blackpod_build_week.contracts.segmented_evidence_qualification import (
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest, validate_result,
    BINDING_VERSION, REQUEST_VERSION, BINDING_TYPE,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError, parse_rfc3339
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.train_market_evidence import TrainMarketSegmentRequest, TrainMarketExportRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_evidence_qualification_example import example_material as original_material
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.train_market_evidence_journal import capture_plan_material, segment_material, export_material
from blackpod_build_week.segmented_evidence_qualification_journal import binding_material, qualification_material
from blackpod_build_week.trading_evidence_qualification_journal import policy_material
from blackpod_build_week.trading_shadow_review_journal import build_evidence_intake_event, evidence_for_intake
from blackpod_build_week.trading_continuity_intake import build_continuity_intake


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def fixture_material(*, partial=False, empty=False, policy_case="clean-declared-design", spread_override=None, include_binding=False,
                     missing_native_coverage=False, conflicting_export_source=False):
    """Return source events and one new binding/request without changing them.

    The default events end immediately before the binding, letting journal
    tests publish the same frozen source prefix once and copy it efficiently.
    """
    original = original_material()
    case = next(row for row in original["cases"] if row["case_id"] == policy_case)
    events, event_evidence, blobs = list(original["events"]), list(original["event_evidence"]), dict(original["blobs"])
    policy = case["policy"]
    extra_continuity = None
    if missing_native_coverage or conflicting_export_source:
        continuity_request = original["original"]["continuity"]["request"].to_dict()
        continuity_request.update(run_id="unit-additional-native-continuity", recorded_at="2025-04-02T08:00:00Z")
        if missing_native_coverage:
            continuity_request.update(coverage_review_evidence=None, coverage_basis="EX_DATE_COVERAGE_UNVERIFIED")
        continuity = build_continuity_intake(continuity_request, blobs)
        blobs.update(continuity["blobs"])
        extra_continuity = build_evidence_intake_event("CONTINUITY", continuity["export"], blobs, recorded_at="2025-04-02T08:00:00Z")
        events.append(extra_continuity)
        retained = evidence_for_intake("CONTINUITY", continuity["export"], blobs)
        event_evidence.append(retained); blobs.update({sha256_bytes(raw): raw for raw in retained.values()})
        if missing_native_coverage:
            value = policy.to_dict(); value.update(policy_id="unit-missing-native-coverage-policy", recorded_at="2025-04-02T12:00:00Z", continuity_event_id=extra_continuity.event_id)
            registered = policy_material(value, events, blobs)
            policy = type(policy).from_mapping(value); case = {**case, "policy": policy, "policy_event": registered["event"]}
            events.append(registered["event"]); event_evidence.append(registered["evidence"])
            blobs.update({sha256_bytes(raw): raw for raw in registered["evidence"].values()})
    capture = prepare_capture_plan(events, blobs, capture_id="unit-segmented-source-capture", created_at="2025-04-03T10:00:00Z", base_plan_event_id=policy.base_plan_event_id)
    created = capture_plan_material(capture, events, blobs)
    events.append(created["event"]); event_evidence.append(created["evidence"])
    blobs.update({sha256_bytes(raw): raw for raw in created["evidence"].values()})
    quotes = json.loads(original["original"]["evidence"]["synthetic-reviewed/quotes.raw"])["quotes"]
    segment_events = []
    for index, segment in enumerate(capture.segments):
        if partial and index >= 2: break
        start, end = (parse_rfc3339(segment["query"][key], "fixture query") for key in ("start", "end"))
        body = {"quotes": {symbol: [copy.deepcopy(row) for row in native if start <= parse_rfc3339(row["t"], "fixture quote") <= end]
                           for symbol, native in quotes.items()}, "next_page_token": None}
        if empty and index == 0: body["quotes"][capture.segments[0]["query"]["symbols"].split(",")[0]] = []
        if spread_override is not None:
            for native in body["quotes"].values():
                for row in native: row["ap"] = row["bp"] * spread_override
        raw = canonical_json_bytes(body)
        body_ref = ref("unit-segmented/source-%03d.raw" % index, raw)
        receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": "https://data.alpaca.markets/v2/stocks/quotes",
            "query": segment["query"], "captured_at": "2025-04-04T00:00:00Z", "status": 200, "body_sha256": body_ref["sha256"], "size_bytes": len(raw)}
        receipt_raw = canonical_json_bytes(receipt); receipt_ref = ref("unit-segmented/receipt-%03d.json" % index, receipt_raw)
        blobs.update({body_ref["sha256"]: raw, receipt_ref["sha256"]: receipt_raw})
        request = TrainMarketSegmentRequest.from_mapping({"schema_version": "blackpod.train_market_segment_export_request.v1", "export_id": "unit-segmented-export",
            "capture_plan_event_id": created["event"].event_id, "segment_id": segment["segment_id"],
            "pages": [{"body_evidence": body_ref, "receipt_evidence": receipt_ref}], "failure": None, "exported_at": "2025-04-05T00:00:00Z",
            "auto_trading_enabled": False, "authority": policy.authority})
        material = segment_material(request, events, blobs)
        events.append(material["event"]); event_evidence.append(material["evidence"]); segment_events.append(material["event"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
    export_request = TrainMarketExportRequest.from_mapping({"schema_version": "blackpod.train_market_export_request.v1", "export_id": "unit-segmented-export",
        "capture_plan_event_id": created["event"].event_id, "segment_event_ids": sorted(event.event_id for event in segment_events),
        "exported_at": "2025-04-05T00:00:00Z", "continuity_event_id": extra_continuity.event_id if conflicting_export_source else policy.continuity_event_id, "coverage_review_evidence": None,
        "capture_snapshot_evidence": None, "capture_checkpoint_evidence": [], "auto_trading_enabled": False, "authority": policy.authority})
    exported = export_material(export_request, events, blobs)
    events.append(exported["event"]); event_evidence.append(exported["evidence"])
    blobs.update({sha256_bytes(raw): raw for raw in exported["evidence"].values()})
    binding = SegmentedEvidenceBinding.from_mapping({"schema_version": BINDING_VERSION, "binding_id": "unit-segmented-binding", "recorded_at": "2025-04-05T10:00:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_ONLY",
        "qualification_policy_event_id": case["policy_event"].event_id, "capture_plan_event_id": created["event"].event_id,
        "calibration_source": "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY", "supersedes_binding_event_id": None, "auto_trading_enabled": False, "authority": policy.authority})
    bound = binding_material(binding, events, blobs)
    request = SegmentedEvidenceQualificationRequest.from_mapping({"schema_version": REQUEST_VERSION, "qualification_id": "unit-segmented-qualification",
        "binding_event_id": bound["event"].event_id, "aggregate_export_event_id": exported["event"].event_id,
        "recorded_at": "2025-04-05T12:00:00Z", "data_cutoff_at": "2025-04-05T11:00:00Z", "supersedes_event_id": None,
        "auto_trading_enabled": False, "authority": policy.authority})
    blobs.update({sha256_bytes(raw): raw for raw in bound["evidence"].values()})
    if include_binding: events.append(bound["event"]); event_evidence.append(bound["evidence"])
    return {"events": tuple(events), "event_evidence": tuple(event_evidence), "blobs": blobs, "binding": binding, "request": request,
        "binding_event": bound["event"], "binding_evidence": bound["evidence"], "policy": policy, "policy_event": case["policy_event"],
        "capture_plan": capture, "capture_plan_event": created["event"], "aggregate_export_event": exported["event"],
        "segment_events": tuple(segment_events), "original": original}


class SegmentedQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")):
            cls.complete = fixture_material(include_binding=True)
            cls.partial = fixture_material(partial=True, include_binding=True)
            cls.empty = fixture_material(empty=True, include_binding=True)
            cls.proposed = fixture_material(policy_case="inactive-proposed-design", include_binding=True)
            cls.expensive = fixture_material(spread_override=1.1, include_binding=True)
            cls.coverage_missing = fixture_material(missing_native_coverage=True, include_binding=True)
            cls.conflicting_continuity = fixture_material(conflicting_export_source=True, include_binding=True)
            cls.old_forbidden_chain = fixture_material(policy_case="forbidden-holdout-cost-evidence", include_binding=True)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("inference forbidden")))

    def assess(self, material=None, request=None):
        material = material or self.complete
        return engine.qualify_segmented_evidence(request or material["request"], material["events"], material["blobs"])

    def test_complete_declared_fixture_qualifies_design_without_performance_claim(self):
        result = self.assess()["result"]
        self.assertEqual(result["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertFalse(result["uncertainty_computed"])
        self.assertFalse(result["existing_gate_override"])
        self.assertEqual(result["uncertainty_status"], "FROZEN_NOT_EVALUATED")
        self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(result["realized_trade_pnl"])

    def test_partial_capture_has_exact_missing_pairs_and_no_usable_model(self):
        result = self.assess(self.partial)["result"]
        fold = result["training_calibration"]["folds"][0]
        self.assertEqual(result["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertEqual(len(fold["missing_symbol_sessions"]), 20)
        self.assertIsNone(fold["training_measurements"])
        self.assertIsNone(fold["cost_model"])

    def test_terminal_empty_response_does_not_manufacture_coverage(self):
        fold = self.assess(self.empty)["result"]["training_calibration"]["folds"][0]
        self.assertTrue(fold["capture_complete"])
        self.assertFalse(fold["coverage_complete"])
        self.assertEqual(len(fold["missing_symbol_sessions"]), 1)
        self.assertIsNone(fold["cost_model"])

    def test_absent_assumptions_and_proposed_policy_remain_deferred(self):
        result = self.assess(self.proposed)["result"]
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", result["reason_codes"])
        self.assertIn("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW", result["reason_codes"])
        self.assertIsNone(result["training_calibration"]["folds"][0]["cost_model"])

    def test_high_spread_is_retained_and_stress_bound_defers_without_clipping(self):
        result = self.assess(self.expensive)["result"]
        fold = result["training_calibration"]["folds"][0]
        self.assertGreater(Decimal(fold["training_measurements"][0]["max_spread_bps"]), 600)
        self.assertGreater(Decimal(fold["cost_stress_assessment"][-1]["declared_cost_model"]["spread_bps"]), 1000)
        self.assertIn("TRAINING_COST_STRESS_EXCEEDS_EXISTING_MODEL_BOUND", result["reason_codes"])
        self.assertIsNone(fold["cost_model"])

    def test_inherited_native_coverage_does_not_depend_on_export_optional_packet(self):
        result = self.assess()["result"]
        self.assertTrue(result["provenance"]["inherited_native_coverage_supported"])
        self.assertEqual(result["provenance"]["export_continuity_coverage"]["status"], "UNRESOLVED")
        self.assertFalse(result["provenance"]["export_continuity_packet_applied_to_native_windows"])
        self.assertTrue(result["eligible_for_study_design"])

    def test_missing_independent_native_coverage_remains_deferred(self):
        result = self.assess(self.coverage_missing)["result"]
        self.assertIn("INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED", result["reason_codes"])
        self.assertFalse(result["provenance"]["inherited_native_coverage_supported"])
        self.assertEqual(result["provenance"]["native_continuity_review_status"], "UNRESOLVED")
        self.assertTrue(result["training_calibration"]["eligible"])
        self.assertFalse(result["eligible_for_study_design"])

    def test_different_export_continuity_source_cannot_silently_override_policy(self):
        with self.assertRaisesRegex(ValueError, "continuity source conflicts"):
            self.assess(self.conflicting_continuity)

    def test_explicit_new_method_ignores_old_forbidden_quote_chain_but_keeps_old_defer(self):
        result = self.assess(self.old_forbidden_chain)["result"]
        old = next(row for row in self.old_forbidden_chain["original"]["cases"] if row["case_id"] == "forbidden-holdout-cost-evidence")
        self.assertEqual(old["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertEqual(result["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertFalse(result["provenance"]["old_policy_quote_chains_used"])
        self.assertFalse(result["existing_gate_override"])

    def test_original_gate_and_records_are_preserved_and_raw_corpus_not_duplicated(self):
        before = [event.to_bytes() for event in self.complete["events"]]
        result = self.assess()
        self.assertEqual(before, [event.to_bytes() for event in self.complete["events"]])
        self.assertFalse(result["result"]["provenance"]["old_policy_quote_chains_used"])
        self.assertFalse(any(path.startswith(("unit-segmented/", "source/", "source_evidence/")) for path in result["evidence"]))
        raw_hashes = {ref["sha256"] for event in self.complete["segment_events"] for ref in event.evidence if ref["path"].startswith("unit-segmented/")}
        self.assertFalse(raw_hashes & {sha256_bytes(raw) for raw in result["evidence"].values()})

    def test_every_native_segment_replays_before_aggregate_extrema_are_used(self):
        original = self.complete["segment_events"][0]
        changed = original.to_dict(); changed["payload"]["result"]["symbols"][0]["max_spread_bps"] = "0"
        forged = JournalEvent.from_mapping(changed)
        events = tuple(forged if event.event_id == original.event_id else event for event in self.complete["events"])
        with self.assertRaisesRegex(ValueError, "replay"):
            self.assess({**self.complete, "events": events})

    def test_forged_aggregate_summary_cannot_pass_checked_fields_alone(self):
        original = self.complete["aggregate_export_event"]
        changed = original.to_dict(); changed["payload"]["result"]["folds"][0]["training_spread_profile"][0]["max_spread_bps"] = "0"
        forged = JournalEvent.from_mapping(changed)
        events = tuple(forged if event.event_id == original.event_id else event for event in self.complete["events"])
        with self.assertRaisesRegex(ValueError, "replay"):
            self.assess({**self.complete, "events": events})

    def test_cutoff_cannot_exclude_binding_or_export(self):
        value = self.complete["request"].to_dict(); value["data_cutoff_at"] = "2025-04-05T09:59:59Z"
        with self.assertRaisesRegex(ValueError, "cutoff"):
            self.assess(request=SegmentedEvidenceQualificationRequest.from_mapping(value))

    def test_binding_cannot_precede_source_freezes(self):
        value = self.complete["binding"].to_dict(); value["recorded_at"] = "2025-04-02T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "cannot precede"):
            engine.binding_context(value, tuple(event for event in self.complete["events"] if event.event_type != BINDING_TYPE), self.complete["blobs"])

    def test_binding_cannot_select_another_original_hypothesis_plan(self):
        value = self.complete["binding"].to_dict()
        other = next(row for row in self.complete["original"]["cases"] if row["case_id"] == "inactive-proposed-design")
        value["qualification_policy_event_id"] = other["policy_event"].event_id
        with self.assertRaisesRegex(ValueError, "exact original"):
            engine.binding_context(value, tuple(event for event in self.complete["events"] if event.event_type != BINDING_TYPE), self.complete["blobs"])

    def test_original_continuity_and_uncertainty_are_identical_to_frozen_methods(self):
        result = self.assess()["result"]
        old = next(row for row in self.complete["original"]["cases"] if row["case_id"] == "clean-declared-design")["result"]
        self.assertEqual(result["continuity"], old["continuity"])
        self.assertEqual(result["uncertainty_protocol"], self.complete["policy"].uncertainty_protocol)

    def test_training_split_availability_failure_propagates_without_scoring(self):
        original = engine.plan_chronological_splits
        def invalid(plan, dataset):
            value = original(plan, dataset)
            value["availability_failures"].append({"fold_id": plan.protocol["folds"][0]["fold_id"], "session_id": dataset.sessions[0]["session_id"], "reason_code": "FEATURE_AVAILABLE_AFTER_VALIDATION_START"})
            return value
        with patch.object(engine, "plan_chronological_splits", side_effect=invalid):
            result = self.assess()["result"]
        self.assertIn("TRAINING_CHRONOLOGICAL_AVAILABILITY_INVALID", result["reason_codes"])
        self.assertIsNone(result["training_calibration"]["folds"][0]["cost_model"])

    def test_declared_cost_stresses_and_daily_proxy_arithmetic_are_exact(self):
        fold = self.assess()["result"]["training_calibration"]["folds"][0]
        for stress in fold["cost_stress_assessment"]:
            for key, value in fold["cost_model"].items():
                self.assertEqual(Decimal(stress["declared_cost_model"][key]), Decimal(value) * Decimal(stress["multiplier"]))
        for row in fold["capacity_proxy"]:
            self.assertEqual(Decimal(row["daily_quantity_research_proxy"]), Decimal(row["minimum_training_daily_volume"]) * Decimal(row["reviewed_daily_volume_participation_fraction"]))

    def test_decimal_host_context_does_not_change_result(self):
        before = self.assess()["result"]
        with localcontext() as context:
            context.prec = 7; context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(before, self.assess()["result"])

    def test_binding_and_request_roundtrip_strictness_and_disabled_authority(self):
        for document in (self.complete["binding"], self.complete["request"]):
            self.assertEqual(type(document).from_bytes(document.to_bytes()).to_bytes(), document.to_bytes())
            for mutate in (lambda value: value.update(extra=True), lambda value: value.update(auto_trading_enabled=1),
                           lambda value: value["authority"].update(execution_enabled=True)):
                with self.subTest(document=document, mutate=mutate):
                    value = document.to_dict(); mutate(value)
                    with self.assertRaises(ContractValidationError): type(document).from_mapping(value)

    def test_result_nested_contract_rejects_missing_flags_unknown_fields_and_objects(self):
        original = self.assess()["result"]
        for mutate in (lambda value: value["training_calibration"].pop("auto_trading_enabled"),
                       lambda value: value["training_calibration"].update(extra=True),
                       lambda value: value.update(reason_codes=[{}]),
                       lambda value: value["training_calibration"]["folds"][0]["cost_stress_assessment"][0].update(within_existing_component_bounds=1),
                       lambda value: value["training_calibration"]["folds"][0].update(missing_symbol_sessions=[{}])):
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(original); mutate(value)
                with self.assertRaises(ContractValidationError): validate_result(value)

    def test_result_contract_never_allows_execution_performance_or_uncertainty_claims(self):
        original = self.assess()["result"]
        for field, value in (("execution_status", "EXECUTED"), ("realized_trade_pnl", "100"), ("uncertainty_computed", True),
                             ("economic_hypothesis_supported", True), ("existing_gate_override", True)):
            with self.subTest(field=field):
                changed = copy.deepcopy(original); changed[field] = value
                with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_exact_retry_and_output_alias_independence(self):
        first, second = self.assess(), self.assess()
        self.assertEqual(first["result"], second["result"])
        first["result"]["training_calibration"]["folds"].clear(); first["evidence"].clear()
        self.assertEqual(second["result"], self.assess()["result"])

    def test_appended_assessment_preserves_exact_retry_and_linked_supersession(self):
        first = qualification_material(self.complete["request"], self.complete["events"], self.complete["blobs"])
        events = self.complete["events"] + (first["event"],)
        blobs = {**self.complete["blobs"], **{sha256_bytes(raw): raw for raw in first["evidence"].values()}}
        again = qualification_material(self.complete["request"], events, blobs)
        self.assertEqual(first["event"].to_bytes(), again["event"].to_bytes())
        value = self.complete["request"].to_dict()
        value.update(qualification_id="unit-later-segmented-qualification", recorded_at="2025-04-05T14:00:00Z", data_cutoff_at="2025-04-05T13:00:00Z", supersedes_event_id=first["event"].event_id)
        second = qualification_material(value, events, blobs)
        self.assertEqual(second["event"].payload["prior_qualification_event_ids"], [first["event"].event_id])
        events += (second["event"],)
        branched = {**value, "qualification_id": "unit-branch-attempt", "recorded_at": "2025-04-05T16:00:00Z", "data_cutoff_at": "2025-04-05T15:00:00Z"}
        with self.assertRaisesRegex(ValueError, "unsuperseded"):
            engine.qualify_segmented_evidence(branched, events, blobs)

    def test_supersession_cutoff_and_record_clocks_cannot_move_backwards(self):
        first = qualification_material(self.complete["request"], self.complete["events"], self.complete["blobs"])
        events = self.complete["events"] + (first["event"],)
        for changes in ({"recorded_at": "2025-04-05T11:30:00Z"}, {"recorded_at": "2025-04-05T14:00:00Z", "data_cutoff_at": "2025-04-05T10:30:00Z"}):
            value = self.complete["request"].to_dict(); value.update(qualification_id="unit-backdated-attempt", supersedes_event_id=first["event"].event_id, **changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                engine.qualify_segmented_evidence(value, events, self.complete["blobs"])

    def test_binding_supersession_is_append_only_and_cannot_fork(self):
        binding = self.complete["binding"].to_dict()
        binding.update(binding_id="unit-next-binding", recorded_at="2025-04-05T13:00:00Z", supersedes_binding_event_id=self.complete["binding_event"].event_id)
        second = binding_material(binding, self.complete["events"], self.complete["blobs"])
        events = self.complete["events"] + (second["event"],)
        binding.update(binding_id="unit-fork-binding", recorded_at="2025-04-05T15:00:00Z")
        with self.assertRaisesRegex(ValueError, "unsuperseded"):
            engine.binding_context(binding, events, self.complete["blobs"])


if __name__ == "__main__":
    unittest.main()
