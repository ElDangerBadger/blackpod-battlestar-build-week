"""Pure shadow consumer tests; all data scenarios are explicitly authored."""
from copy import deepcopy
from datetime import timedelta
from decimal import localcontext, Inexact, Rounded
from functools import lru_cache
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.reconciled_shadow_qualification import (
    ReconciledShadowQualificationRequest, REQUEST_CONSTANTS, AUTHORITY, FALSE_FIELDS,
    ROLES, validate_result, evidence_references, risk_checks,
)
from blackpod_build_week.contracts.reconciled_action_intake import ReconciledActionIntakePolicy, ReconciledActionIntakeRequest
from blackpod_build_week.contracts.effective_date_reconciliation import IndependentActionInventory
from blackpod_build_week.contracts.mission_request import ContractValidationError, parse_rfc3339
from blackpod_build_week.contracts.trading_research import TradingResearchDataset
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_action_intake import build_reconciled_action_intake
from blackpod_build_week.reconciled_shadow_qualification import qualify_reconciled_overlay
from blackpod_build_week.trading_continuity_intake import build_continuity_intake


def ref(path, raw): return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


@lru_cache(maxsize=1)
def original_fixture():
    from blackpod_build_week.reconciled_action_intake_example import example_material
    return example_material()


def retained_request(intake, native, blobs, *, identity="authored-shadow-unit", intake_event_id=None):
    raw = canonical_json_bytes(intake); reference = ref("reconciled-actions/result.v1.json", raw); blobs = {**blobs, reference["sha256"]: raw}
    request = ReconciledShadowQualificationRequest.from_mapping({**REQUEST_CONSTANTS, "qualification_id": identity,
        "recorded_at": "2025-04-11T12:00:00Z", "data_cutoff_at": "2025-04-11T11:00:00Z", "intake_event_id": intake_event_id or "journal-event-" + "a" * 64,
        "intake_result_evidence": reference, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    return {"request": request, "intake": deepcopy(intake), "native": deepcopy(native), "blobs": blobs}


def source_day(dataset, index): return dataset.sessions[index]["open_at"][:10]


def action(identity, *, symbol="SYNTHA", day=None, status="EFFECTIVE", affected=None):
    return {"source_action_id": identity, "native_type": "cash_dividends", "affected_symbols": affected or [symbol], "effective_date": day,
        "record_date": None, "payable_date": None, "status": status, "cusip": None,
        "amount_lexemes": {"dividend": "0.5", "short_term_capital_gain": None, "long_term_capital_gain": None}, "replaces_source_action_id": None}


def authored_fixture(rows=(), mutate_native=None, *, native_unknown=False):
    """New pure-unit scenario, not a replacement of the frozen journal source.

    The genuine 42-event fixture stays untouched. Unit variants do not claim a
    valid replacement v23 registration or a historical policy precommitment.
    """
    original = original_fixture(); blobs = dict(original["blobs"])
    native = deepcopy(original["intake_event"].payload["anchor_snapshot"]["native_qualification_snapshot"])
    export_reference = original["policy"].native_continuity_export_evidence
    if native_unknown:
        export_value = original["result"]["original_native_export"]
        old_request = json.loads(blobs[export_value["request_evidence"]["sha256"]])
        old_receipt = json.loads(blobs[old_request["pages"][0]["capture_receipt_evidence"]["sha256"]])
        identity = "00000000-0000-0000-0000-000000000001"
        body = canonical_json_bytes({"corporate_actions": {"worthless_removals": [{"id": identity, "process_date": old_request["process_date_range"]["start"], "symbol": "SYNTHA", "cusip": "000000001"}]}, "next_page_token": None})
        body_ref = ref("authored-shadow/native-unknown.raw", body); blobs[body_ref["sha256"]] = body
        old_receipt.update(body_sha256=body_ref["sha256"], size_bytes=body_ref["size_bytes"])
        receipt_raw = canonical_json_bytes(old_receipt); receipt_ref = ref("authored-shadow/native-unknown-receipt.json", receipt_raw); blobs[receipt_ref["sha256"]] = receipt_raw
        old_request.update(run_id="authored-native-unknown-shadow-unit", pages=[{"response_evidence": body_ref, "capture_receipt_evidence": receipt_ref}], coverage_review_evidence=None, coverage_basis="EX_DATE_COVERAGE_UNVERIFIED")
        native_material = build_continuity_intake(old_request, blobs); blobs.update(native_material["blobs"])
        export_raw = native_material["export"].to_bytes(); export_reference = ref("authored-shadow/native-unknown-export.json", export_raw); blobs[export_reference["sha256"]] = export_raw
        defer_native(native, "AUTHORED_UNKNOWN_NATIVE_DATE")
        native["continuity"].update(native_action_audit=native_material["export"].native_actions, coverage_supported=False, native_continuity_review_status="UNRESOLVED")
        for row in native["continuity"]["opportunities"]:
            if row["symbol"] == "SYNTHA": row["candidate_action_ids"]["UNKNOWN"] = [identity]
            row["benchmark_action_ids"] = [identity]
    if mutate_native: mutate_native(native)
    masks_raw = canonical_json_bytes(native["continuity"]); masks_ref = ref("authored-shadow/native-masks.json", masks_raw); blobs[masks_ref["sha256"]] = masks_raw
    body = canonical_json_bytes({"schema_version": "blackpod.authored_effective_date_actions.v1", "label": "AUTHORED_UNVERIFIED", "actions": list(rows)})
    body_ref = ref("authored-shadow/issuer-actions.raw", body); blobs[body_ref["sha256"]] = body
    inventory = deepcopy(original["inventory"].to_dict()); inventory.update(inventory_id="authored-shadow-unit-inventory", body_evidence=body_ref)
    inventory = IndependentActionInventory.from_mapping(inventory)
    raw = inventory.to_bytes(); inventory_ref = ref("authored-shadow/issuer-inventory.json", raw); blobs[inventory_ref["sha256"]] = raw
    policy_value = original["policy"].to_dict(); policy_value.update(policy_id="authored-shadow-unit-policy", original_native_masks_evidence=masks_ref, native_continuity_export_evidence=export_reference, independent_inventories=[inventory_ref])
    policy = ReconciledActionIntakePolicy.from_mapping(policy_value)
    raw = policy.to_bytes(); policy_ref = ref("authored-shadow/policy.json", raw); blobs[policy_ref["sha256"]] = raw
    intake_request = original["request"].to_dict(); intake_request.update(intake_id="authored-shadow-unit-intake", policy_evidence=policy_ref)
    intake_request = ReconciledActionIntakeRequest.from_mapping(intake_request)
    material = build_reconciled_action_intake(policy, intake_request, blobs)
    blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
    return retained_request(material["result"], native, blobs)


def defer_native(native, reason="AUTHORED_NATIVE_ALREADY_DEFERRED", *, feature_lookback=None, holding=None):
    native.update(status="DEFER_EVIDENCE_QUALIFICATION", eligible_for_study_design=False, reason_codes=sorted(set(native["reason_codes"]) | {reason}))
    continuity = native["continuity"]
    for row in continuity["opportunities"]:
        row.update(candidate_eligible=False, benchmark_eligible=False, combined_eligible=False, window_status="DEFER")
        row["reason_codes"] = sorted(set(row["reason_codes"]) | {reason})
        if feature_lookback is not None:
            row["feature_start_index"] = row["source_session_index"] - feature_lookback
            row["source_clock_reasons"] = sorted(set(row["source_clock_reasons"]) | {"INSUFFICIENT_COMPLETED_FEATURE_LOOKBACK"})
            row["reason_codes"] = sorted(set(row["reason_codes"]) | {"INSUFFICIENT_COMPLETED_FEATURE_LOOKBACK"})
        if holding is not None:
            row["exit_session_index"] = row["entry_session_index"] + holding
            row["source_clock_reasons"] = sorted(set(row["source_clock_reasons"]) | {"DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST"})
            row["reason_codes"] = sorted(set(row["reason_codes"]) | {"DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST"})
    continuity.update(status="DEFER", counts={"opportunities": len(continuity["opportunities"]), "candidate_eligible": 0, "benchmark_eligible": 0, "combined_eligible": 0, "deferred": len(continuity["opportunities"])})
    native["risk"]["eligible"] = False; native["risk"]["reason_codes"] = sorted(set(native["risk"]["reason_codes"]) | {reason})
    for check in native["risk"]["capacity_checks"]: check.update(continuity_comparable=False, joint_eligible=False)


class ReconciledShadowQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = original_fixture()
        cls.dataset = TradingResearchDataset.from_bytes(cls.original["blobs"][cls.original["policy"].dataset_evidence["sha256"]])
        cls.first = cls.original["intake_event"].payload["anchor_snapshot"]["native_qualification_snapshot"]["continuity"]["opportunities"][0]

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("inference forbidden")))

    def assess(self, fixture): return qualify_reconciled_overlay(fixture["request"], fixture["intake"], fixture["native"], fixture["blobs"])

    def first_window(self, result, symbol="SYNTHA"):
        return next(row for row in result["opportunities"] if row["native_opportunity"]["source_session_index"] == self.first["source_session_index"] and row["native_opportunity"]["symbol"] == symbol)

    def test_request_is_closed_immutable_and_roundtrips(self):
        fixture = authored_fixture(); request = fixture["request"]
        self.assertEqual(ReconciledShadowQualificationRequest.from_bytes(request.to_bytes()).to_bytes(), request.to_bytes())
        value = request.to_dict(); value["authority"]["execution_enabled"] = True
        self.assertFalse(request.authority["execution_enabled"])
        for changes in ({"extra": False}, {"mode": "PAPER"}, {"domain": "INVESTMENT"}, {"intake_event_id": "latest"}, {"supersedes_event_id": "bad"}):
            value = request.to_dict(); value.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ContractValidationError): ReconciledShadowQualificationRequest.from_mapping(value)

    def test_request_false_flags_clock_and_evidence_bounds(self):
        fixture = authored_fixture()
        for value in (True, 0):
            request = fixture["request"].to_dict(); request["auto_trading_enabled"] = value
            with self.assertRaises(ContractValidationError): ReconciledShadowQualificationRequest.from_mapping(request)
        request = fixture["request"].to_dict(); request["data_cutoff_at"] = "2025-04-12T00:00:00Z"
        with self.assertRaises(ContractValidationError): ReconciledShadowQualificationRequest.from_mapping(request)
        request = fixture["request"].to_dict(); request["intake_result_evidence"]["size_bytes"] = 8 * 1024 * 1024 + 1
        with self.assertRaises(ContractValidationError): ReconciledShadowQualificationRequest.from_mapping(request)

    def test_frozen_shared_fixture_unknown_vetoes_all_controls_and_affected_candidates(self):
        original = self.original
        fixture = retained_request(original["result"], original["intake_event"].payload["anchor_snapshot"]["native_qualification_snapshot"], original["blobs"], intake_event_id=original["intake_event"].event_id)
        result = self.assess(fixture)["result"]
        unknown_ids = {item["boundary_id"] for item in result["boundary_catalog"]["boundaries"] if item["mapping"] == "UNKNOWN_EFFECTIVE_DATE"}
        self.assertEqual(len(unknown_ids), 1)
        for row in result["opportunities"]:
            self.assertEqual(set(row["overlay_benchmark_boundary_ids"]), unknown_ids)
            self.assertEqual(set(row["overlay_candidate_boundary_ids"]["UNKNOWN"]), unknown_ids if row["native_opportunity"]["symbol"] == "SYNTHB" else set())
        self.assertEqual(result["native_qualification_snapshot"], fixture["native"])
        self.assertEqual(result["coverage_matrix"], fixture["intake"]["coverage_matrix"])
        self.assertEqual(result["counts"]["risk_checks_matched"], result["counts"]["opportunities"])

    def test_ready_native_empty_overlay_still_defers_for_unresolved_coverage(self):
        fixture = authored_fixture(); result = self.assess(fixture)["result"]
        self.assertEqual(fixture["native"]["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertEqual(result["boundary_catalog"]["boundaries"], [])
        self.assertEqual(result["counts"]["additional_overlay_veto"], 0)
        self.assertEqual(result["counts"]["newly_ineligible_due_to_overlay"], 0)
        self.assertEqual(result["counts"]["overlay_clear"], result["counts"]["opportunities"])
        self.assertGreater(result["counts"]["newly_ineligible"], 0)
        self.assertEqual(result["counts"]["effective_combined_eligible"], 0)
        self.assertTrue(all(not row["overlay_candidate_eligible"] and not row["overlay_benchmark_eligible"] for row in result["opportunities"]))

    def test_feature_entry_holding_and_excluded_lower_edge(self):
        row = self.first
        for index, role in ((row["feature_start_index"], None), (row["source_session_index"], "FEATURE"), (row["entry_session_index"], "ENTRY"), (row["exit_session_index"], "HOLDING_EXIT"), (row["exit_session_index"]+1, None)):
            fixture = authored_fixture([action("edge", day=source_day(self.dataset, index))]); result = self.assess(fixture)["result"]
            window = self.first_window(result)
            actual = [name for name, ids in window["overlay_candidate_boundary_ids"].items() if ids]
            self.assertEqual(actual, [] if role is None else [role])
            self.assertEqual(window["overlay_benchmark_veto"], row["source_session_index"] < index <= row["exit_session_index"])

    def test_suspension_uses_full_alias_set_for_candidate_and_fixed_universe_control(self):
        day = source_day(self.dataset, self.first["entry_session_index"])
        fixture = authored_fixture([action("alias", day=day, affected=["EXTERNAL", "SYNTHB"])]); result = self.assess(fixture)["result"]
        left, right = self.first_window(result), self.first_window(result, "SYNTHB")
        self.assertFalse(left["overlay_candidate_veto"]); self.assertTrue(left["overlay_benchmark_veto"])
        self.assertTrue(right["overlay_candidate_veto"])
        self.assertEqual(result["boundary_catalog"]["boundaries"][0]["affected_symbols"], ["EXTERNAL", "SYNTHB"])

    def test_nontrading_effective_date_uses_exact_retained_next_session_mapping(self):
        # Friday Jan31 is feature anchor; SaturdayFeb1 maps MondayFeb3 SOURCE.
        friday = parse_rfc3339(self.dataset.sessions[self.first["feature_start_index"]]["open_at"], "authored clock").date()
        day = (friday + timedelta(days=1)).isoformat()
        fixture = authored_fixture([action("weekend", day=day)]); result = self.assess(fixture)["result"]
        boundary = result["boundary_catalog"]["boundaries"][0]
        self.assertEqual(boundary["mapping"], "NEXT_RETURNED_DATE")
        self.assertEqual(boundary["declared_effective_date"], day)
        self.assertTrue(self.first_window(result)["overlay_candidate_boundary_ids"]["FEATURE"])

    def test_unknown_non_cancelled_vetoes_every_affected_window_and_all_controls(self):
        result = self.assess(authored_fixture([action("unknown", symbol="SYNTHB", status="UNKNOWN")]))["result"]
        self.assertEqual(result["counts"]["benchmark_overlay_veto"], result["counts"]["opportunities"])
        self.assertEqual(result["counts"]["candidate_overlay_veto"], result["counts"]["opportunities"] // 2)
        self.assertTrue(all(row["mapped_session_id"] is None for row in result["boundary_catalog"]["boundaries"]))

    def test_native_unknown_first_session_placeholder_remains_unknown_for_consumer(self):
        fixture = authored_fixture(native_unknown=True); result = self.assess(fixture)["result"]
        original_audit = fixture["intake"]["original_native_export"]["native_actions"][0]
        self.assertEqual(original_audit["mapped_session_id"], self.dataset.sessions[0]["session_id"])
        boundary = result["boundary_catalog"]["boundaries"][0]
        self.assertTrue(boundary["legacy_placeholder_retained"])
        self.assertIsNone(boundary["mapped_session_id"]); self.assertIsNone(boundary["mapped_session_index"])
        self.assertEqual(result["counts"]["benchmark_overlay_veto"], result["counts"]["opportunities"])
        self.assertEqual(result["counts"]["newly_ineligible"], 0)
        self.assertTrue(self.first_window(result)["overlay_candidate_boundary_ids"]["UNKNOWN"])
        self.assertEqual(self.first_window(result)["overlay_candidate_boundary_ids"]["FEATURE"], [])

    def test_cancelled_unknown_and_known_declarations_are_retained_but_inactive(self):
        rows = [action("cancelled-unknown", status="CANCELLED"), action("cancelled-known", status="CANCELLED", day=source_day(self.dataset, self.first["entry_session_index"]))]
        result = self.assess(authored_fixture(rows))["result"]
        self.assertEqual(len(result["boundary_catalog"]["boundaries"]), 2)
        self.assertEqual(len(result["boundary_catalog"]["unknown_date_scope"]), 1)
        self.assertEqual(result["counts"]["additional_overlay_veto"], 0)
        self.assertEqual(result["counts"]["effective_combined_eligible"], 0)

    def test_before_after_span_observations_stay_inactive_and_retained(self):
        rows = [action("before", day="2024-12-01"), action("after", day="2026-01-01")]
        result = self.assess(authored_fixture(rows))["result"]
        self.assertEqual(len(result["boundary_catalog"]["boundaries"]), 2)
        self.assertEqual(result["counts"]["additional_overlay_veto"], 0)

    def test_duplicate_rows_produce_distinct_witnesses_without_collapsing(self):
        day = source_day(self.dataset, self.first["entry_session_index"])
        result = self.assess(authored_fixture([action("one", day=day), action("two", day=day)]))["result"]
        ids = self.first_window(result)["overlay_candidate_boundary_ids"]["ENTRY"]
        self.assertEqual(len(ids), 2); self.assertNotEqual(ids[0], ids[1])
        self.assertEqual(ids, sorted(ids))

    def test_already_deferred_native_windows_do_not_count_as_newly_ineligible(self):
        result = self.assess(authored_fixture([action("unknown", status="UNKNOWN")], defer_native))["result"]
        self.assertGreater(result["counts"]["additional_overlay_veto"], 0)
        self.assertEqual(result["counts"]["newly_ineligible"], 0)
        self.assertEqual(result["counts"]["newly_ineligible_due_to_overlay"], 0)

    def test_native_negative_features_and_unavailable_exits_are_not_dropped(self):
        fixture = authored_fixture(mutate_native=lambda native: defer_native(native, feature_lookback=50, holding=100))
        result = self.assess(fixture)["result"]
        self.assertEqual(len(result["opportunities"]), len(fixture["native"]["continuity"]["opportunities"]))
        self.assertTrue(all(row["native_opportunity"]["feature_start_index"] < 0 for row in result["opportunities"]))
        self.assertTrue(all(row["native_opportunity"]["exit_session_index"] >= len(self.dataset.sessions) for row in result["opportunities"]))
        self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")

    def test_original_failed_calibration_risk_and_uncertainty_are_preserved(self):
        fixture = authored_fixture(mutate_native=defer_native); native = fixture["native"]
        native["uncertainty_status"] = "MISSING"; native["uncertainty_protocol"] = None
        result = self.assess(fixture)["result"]
        self.assertEqual(result["native_qualification_snapshot"]["training_calibration"], native["training_calibration"])
        self.assertEqual(result["native_qualification_snapshot"]["risk"], native["risk"])
        self.assertEqual(result["native_qualification_snapshot"]["uncertainty_status"], "MISSING")
        self.assertTrue(set(native["reason_codes"]) <= set(result["reason_codes"]))

    def test_no_risk_checks_remain_null_and_cannot_gain_joint_eligibility(self):
        fixture = authored_fixture(); fixture["native"]["risk"] = {"eligible": False, "reason_codes": ["SIMULATION_RISK_REVIEW_MISSING"], "native_assessment": None, "capacity_checks": []}
        result = self.assess(fixture)["result"]
        self.assertEqual(result["counts"]["risk_checks_matched"], 0)
        self.assertTrue(all(row["risk_joint_eligible"] is None and not row["effective_joint_eligible"] for row in result["opportunities"]))

    def test_risk_checks_duplicate_omitted_unknown_key_and_false_boolean_rejected(self):
        for mutate in (lambda checks: checks.append(deepcopy(checks[0])), lambda checks: checks.pop(), lambda checks: checks[0].update(source_session_id="foreign"), lambda checks: checks[0].update(joint_eligible=0)):
            fixture = authored_fixture(); mutate(fixture["native"]["risk"]["capacity_checks"])
            with self.subTest(mutate=mutate), self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_malformed_capacity_identity_fields_raise_contract_errors_before_hashing(self):
        fixture = authored_fixture()
        for field in ("fold_id", "symbol", "source_session_id"):
            for invalid in ([], {}, None, 0, True, ""):
                native = deepcopy(fixture["native"]); native["risk"]["capacity_checks"][0][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ContractValidationError):
                    risk_checks(native, native["continuity"]["opportunities"])

    def test_malformed_risk_keys_reject_through_full_json_result_validation(self):
        result = self.assess(authored_fixture())["result"]
        for field in ("fold_id", "symbol", "source_session_id"):
            for invalid in ([], {}, None, 0, True):
                value = deepcopy(result); native = value["native_qualification_snapshot"]
                native["risk"]["capacity_checks"][0][field] = invalid
                value["input_bindings"]["native_snapshot_sha256"] = sha256_bytes(canonical_json_bytes(native))
                parsed = json.loads(canonical_json_bytes(value))
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ContractValidationError): validate_result(parsed)

    def test_malformed_native_risk_window_identity_fields_reject_before_hashing(self):
        fixture = authored_fixture()
        for field in ("fold_id", "symbol", "source_session_id"):
            windows = deepcopy(fixture["native"]["continuity"]["opportunities"]); windows[0][field] = []
            with self.subTest(field=field), self.assertRaises(ContractValidationError): risk_checks(fixture["native"], windows)

    def test_no_price_field_reads_after_existing_dataset_contract_validation(self):
        fixture = authored_fixture(); dataset = self.dataset
        class MetadataOnly(dict):
            def __getitem__(self, key):
                if key == "bars": raise AssertionError("price or volume value read")
                return super().__getitem__(key)
        class MetadataDataset:
            schema_version = dataset.schema_version
            universe = dataset.universe
            recorded_at = dataset.recorded_at
            sessions = [MetadataOnly({key: value for key, value in row.items() if key != "bars"}) for row in dataset.sessions]
            def to_bytes(self): return dataset.to_bytes()
        with patch("blackpod_build_week.reconciled_shadow_qualification.TradingResearchDataset.from_bytes", return_value=MetadataDataset()):
            self.assertEqual(self.assess(fixture)["result"]["counts"]["opportunities"], 18)

    def test_host_decimal_context_does_not_change_integer_overlay_projection(self):
        fixture = authored_fixture([action("unknown", status="UNKNOWN")]); expected = self.assess(fixture)
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True; context.traps[Rounded] = True
            self.assertEqual(self.assess(fixture), expected)

    def test_native_snapshot_different_mask_fragment_rejected(self):
        fixture = authored_fixture(); fixture["native"]["continuity"]["opportunities"].pop()
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_native_window_duplicate_omitted_symbol_and_invalid_indices_rejected(self):
        mutations = [lambda native: native["continuity"]["opportunities"].append(deepcopy(native["continuity"]["opportunities"][0])),
            lambda native: native["continuity"]["opportunities"].pop(0),
            lambda native: native["continuity"]["opportunities"][0].update(entry_session_index=0),
            lambda native: native["continuity"]["opportunities"][0].update(source_session_id="foreign"),
            lambda native: native["continuity"]["opportunities"][0].update(source_session_index=True)]
        for mutate in mutations:
            fixture = authored_fixture(mutate_native=mutate)
            with self.subTest(mutate=mutate), self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_wrong_boundary_mapping_or_source_identity_rejected(self):
        day = source_day(self.dataset, self.first["entry_session_index"])
        for change in ({"mapped_session_index": 0}, {"mapped_session_id": "foreign"}, {"source_id": "foreign"}):
            fixture = authored_fixture([action("mapped", day=day)])
            fixture["intake"]["candidate_overlay"]["boundaries"][0].update(change)
            raw = canonical_json_bytes(fixture["intake"]); reference = ref("changed/intake.json", raw); fixture["blobs"][reference["sha256"]] = raw
            value = fixture["request"].to_dict(); value["intake_result_evidence"] = reference; fixture["request"] = ReconciledShadowQualificationRequest.from_mapping(value)
            with self.subTest(change=change), self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_tampered_size_missing_and_noncanonical_intake_bytes_rejected(self):
        for damage in ("tamper", "missing", "pretty"):
            fixture = authored_fixture(); reference = fixture["request"].intake_result_evidence
            if damage == "tamper": fixture["blobs"][reference["sha256"]] += b" "
            elif damage == "missing": fixture["blobs"].pop(reference["sha256"])
            else:
                raw = json.dumps(fixture["intake"], indent=4).encode(); new_ref = ref("changed/pretty-intake.json", raw); fixture["blobs"][new_ref["sha256"]] = raw
                value = fixture["request"].to_dict(); value["intake_result_evidence"] = new_ref; fixture["request"] = ReconciledShadowQualificationRequest.from_mapping(value)
            with self.subTest(damage=damage), self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_reserved_request_path_cannot_overwrite_selected_source_evidence(self):
        fixture = authored_fixture(); value = fixture["request"].to_dict()
        value["intake_result_evidence"]["path"] = "reconciled-shadow/request.v1.json"
        fixture["request"] = ReconciledShadowQualificationRequest.from_mapping(value)
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_cutoff_before_policy_source_is_rejected_without_rewriting_clock(self):
        fixture = authored_fixture(); value = fixture["request"].to_dict(); value["data_cutoff_at"] = "2025-04-08T00:00:00Z"
        fixture["request"] = ReconciledShadowQualificationRequest.from_mapping(value)
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_pure_projection_is_immutable_and_replayable_from_retained_direct_sources(self):
        fixture = authored_fixture(); before = deepcopy(fixture); material = self.assess(fixture)
        self.assertEqual(fixture, before)
        retained = {sha256_bytes(raw): raw for raw in material["evidence"].values()}
        self.assertEqual(qualify_reconciled_overlay(fixture["request"], fixture["intake"], fixture["native"], retained), material)
        self.assertEqual(evidence_references(fixture["request"]), [fixture["request"].intake_result_evidence])

    def test_resource_comparison_and_result_size_bounds_fail_without_sampling(self):
        fixture = authored_fixture([action("unknown", status="UNKNOWN")])
        with patch("blackpod_build_week.contracts.reconciled_shadow_qualification.MAX_COMPARISONS", 1):
            with self.assertRaises(ContractValidationError): self.assess(fixture)
        result = self.assess(fixture)["result"]
        with patch("blackpod_build_week.contracts.reconciled_shadow_qualification.MAX_RESULT_BYTES", 1):
            with self.assertRaises(ContractValidationError): validate_result(result)

    def test_strict_result_rejects_missing_windows_changed_witnesses_or_counts(self):
        result = self.assess(authored_fixture([action("unknown", status="UNKNOWN")]))["result"]
        for mutate in (lambda value: value["opportunities"].pop(), lambda value: value["opportunities"][0]["overlay_candidate_boundary_ids"]["UNKNOWN"].clear(), lambda value: value["counts"].update(newly_ineligible=999), lambda value: value["final_holdout"].update(scoring_status="SCORED"), lambda value: value.update(extra=False), lambda value: value["reason_codes"].pop()):
            changed = deepcopy(result); mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ContractValidationError): validate_result(changed)

    def test_window_false_booleans_cannot_be_encoded_as_zero(self):
        result = self.assess(authored_fixture())["result"]
        for field in ("overlay_candidate_eligible", "overlay_benchmark_eligible", "effective_candidate_eligible", "effective_benchmark_eligible", "effective_combined_eligible", "effective_joint_eligible"):
            changed = deepcopy(result); changed["opportunities"][0][field] = 0
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_result(changed)

    def test_exact_holdout_boolean_cannot_be_encoded_as_zero(self):
        result = self.assess(authored_fixture())["result"]
        changed = deepcopy(result); changed["final_holdout"]["access_sealed"] = 0
        with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_unretained_native_action_identity_and_malformed_coverage_cell_rejected(self):
        fixture = authored_fixture(mutate_native=lambda native: native["continuity"]["opportunities"][0]["candidate_action_ids"]["FEATURE"].append("unretained-native-id"))
        with self.assertRaises(ContractValidationError): self.assess(fixture)
        result = self.assess(authored_fixture())["result"]
        changed = deepcopy(result); changed["coverage_matrix"][0]["symbol"] = []
        with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_all_top_safety_flags_and_authority_remain_strict_false(self):
        result = self.assess(authored_fixture())["result"]
        for field in FALSE_FIELDS:
            for bad in (True, 0):
                changed = deepcopy(result); changed[field] = bad
                with self.subTest(field=field, bad=bad), self.assertRaises(ContractValidationError): validate_result(changed)
        for field in AUTHORITY:
            changed = deepcopy(result); changed["authority"][field] = True
            with self.assertRaises(ContractValidationError): validate_result(changed)
        self.assertEqual(result["execution_status"], "NOT_EXECUTED"); self.assertIsNone(result["realized_trade_pnl"])


if __name__ == "__main__": unittest.main()
