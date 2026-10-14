"""Offline action-intake contracts, immutable masks and conservative overlays."""
from copy import deepcopy
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.reconciled_action_intake import (
    ReconciledActionIntakePolicy, ReconciledActionIntakeRequest, POLICY_CONSTANTS,
    REQUEST_CONSTANTS, AUTHORITY, FALSE_FIELDS, ACTION_TYPES, validate_result,
    evidence_references,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_action_intake import inspect_policy_sources, build_reconciled_action_intake
from blackpod_build_week.trading_continuity_intake import build_continuity_intake
from blackpod_build_week.trading_historical_intake import build_historical_intake
from test_effective_date_reconciliation import fixture_material, independent_row, ref
from test_trading_continuity_intake import native_action
from test_trading_historical_intake_contracts import source_material, refresh
from test_qqq_distribution_inventory import material as qqq_material, row as qqq_row


EVENT = "journal-event-" + "1" * 64


def frozen_fixture(rows=None, *, groups=None):
    fixture = fixture_material(rows, groups=groups)
    # A source-bound original fragment; the journal tests bind a full frozen v22
    # qualification. This unit fixture does not invent a qualification upgrade.
    masks = {"status": "DEFER", "coverage_supported": False, "opportunities": [{"symbol": "SYNTHA", "combined_eligible": False, "reason_codes": ["COVERAGE_UNVERIFIED"]}]}
    return policy_fixture(fixture["native"], fixture["blobs"], [fixture["request"].independent_inventories[0]], masks)


def policy_fixture(native, blobs, inventories, masks):
    blobs = dict(blobs)
    export_raw = native["export"].to_bytes(); export_ref = ref("reconciled/native-export.json", export_raw)
    masks_raw = canonical_json_bytes(masks); masks_ref = ref("reconciled/original-masks.json", masks_raw)
    blobs.update({export_ref["sha256"]: export_raw, masks_ref["sha256"]: masks_raw})
    policy = ReconciledActionIntakePolicy.from_mapping({**POLICY_CONSTANTS, "policy_id": "unit-frozen-action-policy", "recorded_at": "2026-10-14T04:00:00Z",
        "anchor_review_event_id": EVENT, "dataset_evidence": native["export"].dataset_evidence, "native_continuity_export_evidence": export_ref,
        "original_native_masks_evidence": masks_ref, "independent_inventories": inventories, "evidence_scope": native["export"].evidence_scope,
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    policy_raw = policy.to_bytes(); policy_ref = ref("reconciled/policy.json", policy_raw); blobs[policy_ref["sha256"]] = policy_raw
    request = ReconciledActionIntakeRequest.from_mapping({**REQUEST_CONSTANTS, "intake_id": "unit-reconciled-action-intake", "recorded_at": "2026-10-14T06:00:00Z", "data_cutoff_at": "2026-10-14T05:00:00Z",
        "policy_event_id": "journal-event-" + "2" * 64, "policy_evidence": policy_ref, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    return {"policy": policy, "request": request, "blobs": blobs, "native": native, "masks": deepcopy(masks)}


def change_policy(fixture, **changes):
    value = fixture["policy"].to_dict(); value.update(changes)
    fixture["policy"] = ReconciledActionIntakePolicy.from_mapping(value)
    raw = fixture["policy"].to_bytes(); reference = ref("reconciled/changed-policy.json", raw)
    fixture["blobs"][reference["sha256"]] = raw
    value = fixture["request"].to_dict(); value["policy_evidence"] = reference
    fixture["request"] = ReconciledActionIntakeRequest.from_mapping(value)


def add_inventory(fixture, *, same_body=False, **changes):
    reference = fixture["policy"].independent_inventories[0]
    value = json.loads(fixture["blobs"][reference["sha256"]]); value.update({"inventory_id": "second-inventory", **changes})
    if not same_body:
        raw = canonical_json_bytes({"schema_version": "blackpod.authored_effective_date_actions.v1", "label": "AUTHORED_UNVERIFIED", "actions": []})
        body_ref = ref("reconciled/empty-independent.json", raw); fixture["blobs"][body_ref["sha256"]] = raw; value["body_evidence"] = body_ref
    raw = canonical_json_bytes(value); new_ref = ref("reconciled/second-inventory.json", raw); fixture["blobs"][new_ref["sha256"]] = raw
    change_policy(fixture, independent_inventories=[reference, new_ref])


def qqq_fixture(raw=None):
    # A separately authored QQQ calendar/bar scenario. No old frozen dataset or
    # original quote body is modified to obtain a favorable reconciliation.
    request, values, _ = source_material(days=["2023-12-15", "2023-12-18", "2023-12-19", "2023-12-20"])
    request["universe"] = ["QQQ"]
    values["bars_evidence"]["bars"] = {"QQQ": values["bars_evidence"]["bars"]["SYNTHA"]}
    values["bars_receipt_evidence"]["query"]["symbols"] = "QQQ"
    request, _, blobs = refresh(request, values)
    history = build_historical_intake(request, blobs); blobs.update(history["blobs"])
    dataset_ref = ref("historical-intake/dataset.v2.json", history["dataset"].to_bytes())
    body = canonical_json_bytes({"corporate_actions": {}, "next_page_token": None}); body_ref = ref("qqq-native/actions.raw", body)
    receipt = canonical_json_bytes({"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": "https://data.alpaca.markets/v1/corporate-actions",
        "query": {"symbols": "QQQ", "start": "2023-12-15", "end": "2023-12-20", "limit": 1000, "sort": "asc"}, "captured_at": "2026-10-13T23:58:00Z", "status": 200, "body_sha256": body_ref["sha256"], "size_bytes": len(body)})
    receipt_ref = ref("qqq-native/receipt.json", receipt); blobs.update({sha256_bytes(body): body, sha256_bytes(receipt): receipt})
    native = build_continuity_intake({"schema_version": "blackpod.trading_continuity_intake_request.v1", "run_id": "authored-qqq-intake-unit", "recorded_at": "2026-10-13T23:59:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "RETAINED_CORPORATE_ACTION_INTAKE_ONLY", "dataset_evidence": dataset_ref, "universe": ["QQQ"], "process_date_range": {"start": "2023-12-15", "end": "2023-12-20"},
        "pages": [{"response_evidence": body_ref, "capture_receipt_evidence": receipt_ref}], "coverage_basis": "EX_DATE_COVERAGE_UNVERIFIED", "evidence_scope": "RETAINED_HISTORY_RESEARCH", "coverage_review_evidence": None,
        "reviewer_id": "authored-fixture-only", "review_notes": "Independent authored fixture, no real completeness claim.", "auto_trading_enabled": False, "authority": dict(AUTHORITY)}, blobs)
    blobs.update(native["blobs"])
    # The old native contract reserves SYNTHETIC_FIXTURE_ONLY for SYNTH*
    # symbols. These are authored structural fixtures for its retained-history
    # profile; they are not claims of an authenticated real acquisition.
    inventory, source_blobs = qqq_material(raw, scope="RETAINED_HISTORY_RESEARCH"); blobs.update(source_blobs)
    inventory_raw = canonical_json_bytes(inventory); inventory_ref = ref("qqq/inventory.json", inventory_raw); blobs[inventory_ref["sha256"]] = inventory_raw
    return policy_fixture(native, blobs, [inventory_ref], {"status": "DEFER", "coverage_supported": False, "opportunities": []})


class ReconciledActionIntakeTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def assess(self, fixture):
        return build_reconciled_action_intake(fixture["policy"], fixture["request"], fixture["blobs"])

    def test_closed_immutable_policy_and_request_roundtrip(self):
        fixture = frozen_fixture()
        for key, klass in (("policy", ReconciledActionIntakePolicy), ("request", ReconciledActionIntakeRequest)):
            typed = fixture[key]; value = typed.to_dict(); value["authority"]["execution_enabled"] = True
            self.assertFalse(typed.authority["execution_enabled"])
            self.assertEqual(klass.from_bytes(typed.to_bytes()).to_bytes(), typed.to_bytes())
            bad = typed.to_dict(); bad["unrecognized"] = False
            with self.assertRaises(ContractValidationError): klass.from_mapping(bad)

    def test_policy_constants_and_false_authority_are_enforced(self):
        fixture = frozen_fixture()
        for key in POLICY_CONSTANTS:
            value = fixture["policy"].to_dict(); value[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ContractValidationError): ReconciledActionIntakePolicy.from_mapping(value)
        for field in ("auto_trading_enabled", *AUTHORITY):
            for unsafe in (True, 0):
                value = fixture["policy"].to_dict()
                if field in AUTHORITY: value["authority"][field] = unsafe
                else: value[field] = unsafe
                with self.subTest(field=field, unsafe=unsafe), self.assertRaises(ContractValidationError): ReconciledActionIntakePolicy.from_mapping(value)

    def test_inspection_verifies_sources_without_computing_overlay(self):
        fixture = frozen_fixture()
        with patch("blackpod_build_week.reconciled_action_intake._boundary", side_effect=AssertionError("premature overlay")):
            material = inspect_policy_sources(fixture["policy"], fixture["blobs"])
        self.assertEqual(material["original_masks"], fixture["masks"])
        self.assertEqual(len(material["inventories"]), 1)
        self.assertEqual(material["native_material"]["export"].to_bytes(), fixture["native"]["export"].to_bytes())

    def test_exact_match_preserves_masks_original_export_and_legacy_events(self):
        fixture = frozen_fixture(); before = deepcopy(fixture["blobs"])
        result = self.assess(fixture)["result"]
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["original_native_masks"]["assessment"], fixture["masks"])
        self.assertEqual(result["original_native_export"], fixture["native"]["export"].to_dict())
        self.assertEqual(result["original_native_events"], fixture["native"]["source"].events)
        self.assertEqual(fixture["blobs"], before)
        self.assertEqual(result["status"], "SHADOW_CANDIDATE_NOT_ELIGIBLE")

    def test_all_twenty_six_cells_unresolved_even_declared_complete(self):
        result = self.assess(frozen_fixture())["result"]
        self.assertEqual(len(result["coverage_matrix"]), 26)
        self.assertTrue(all(cell["status"] == "UNRESOLVED" and not cell["eligible"] and not cell["coverage_complete"] for cell in result["coverage_matrix"]))
        self.assertTrue(all(result[key] is False for key in FALSE_FIELDS))
        self.assertEqual(result["authority"], AUTHORITY); self.assertIsNone(result["realized_trade_pnl"])

    def test_new_issuer_date_retained_without_new_native_event(self):
        fixture = frozen_fixture([independent_row(effective_date="2026-01-12")], groups={})
        result = self.assess(fixture)["result"]
        self.assertEqual(result["original_native_events"], [])
        self.assertEqual(len(result["issuer_only"]), 1)
        boundary = result["candidate_overlay"]["boundaries"][0]
        self.assertEqual(boundary["origin"], "ISSUER_DECLARATION"); self.assertTrue(boundary["boundary_flag"])
        self.assertFalse(boundary["confirmed_payment"]); self.assertFalse(boundary["eligible"])

    def test_unknown_native_date_never_becomes_known_first_session_boundary(self):
        fixture = frozen_fixture([independent_row(effective_date=None)], groups={"worthless_removals": [native_action("worthless_removals")]})
        result = self.assess(fixture)["result"]
        self.assertEqual(result["original_native_events"][0]["effective_session_id"], fixture["native"]["dataset"].sessions[0]["session_id"])
        native = result["candidate_overlay"]["boundaries"][0]
        self.assertTrue(native["legacy_placeholder_retained"]); self.assertIsNone(native["mapped_session_id"])
        self.assertIsNone(native["mapped_session_index"]); self.assertFalse(native["boundary_flag"])
        self.assertEqual(len(result["candidate_overlay"]["unknown_date_scope"]), 2)

    def test_holiday_maps_to_next_returned_session_without_changing_declared_day(self):
        result = self.assess(frozen_fixture([independent_row(effective_date="2026-01-10")]))["result"]
        boundary = result["candidate_overlay"]["boundaries"][-1]
        self.assertEqual(boundary["declared_effective_date"], "2026-01-10")
        self.assertEqual(boundary["mapping"], "NEXT_RETURNED_DATE")
        self.assertEqual(boundary["mapped_session_id"], "alpaca-session-2026-01-12")

    def test_outside_span_rows_retained_without_invented_sessions(self):
        rows = [independent_row("before", effective_date="2025-12-31"), independent_row("after", effective_date="2026-02-01")]
        result = self.assess(frozen_fixture(rows))["result"]
        self.assertEqual(len(result["issuer_observations"]), 2)
        for boundary in result["candidate_overlay"]["boundaries"][-2:]:
            self.assertIsNone(boundary["mapped_session_id"]); self.assertFalse(boundary["boundary_flag"])
        self.assertEqual([row["dataset_disposition"] for row in result["issuer_observations"]], ["BEFORE_DATASET", "AFTER_DATASET"])

    def test_every_status_retained_cancellation_does_not_activate_boundary(self):
        statuses = ["EFFECTIVE", "SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN"]
        rows = [independent_row("status-" + status.lower(), status=status) for status in statuses]
        result = self.assess(frozen_fixture(rows))["result"]
        self.assertEqual([row["status"] for row in result["issuer_observations"]], statuses)
        boundaries = result["candidate_overlay"]["boundaries"][1:]
        self.assertEqual([row["boundary_flag"] for row in boundaries], [True, True, False, True, True])
        self.assertEqual(len(result["ambiguous"]), 1); self.assertFalse(result["coverage_complete"])

    def test_duplicate_same_key_rows_stay_distinct_and_ambiguous(self):
        result = self.assess(frozen_fixture([independent_row("first"), independent_row("second")]))["result"]
        self.assertEqual(len(result["issuer_observations"]), 2); self.assertEqual(result["matches"], [])
        self.assertEqual(len(result["ambiguous"]), 1); self.assertEqual(result["ambiguous"], result["duplicate_groups"])
        self.assertEqual(len(result["candidate_overlay"]["boundaries"]), 3)

    def test_full_alias_sets_not_silently_reduced(self):
        result = self.assess(frozen_fixture([independent_row(native_type="unit_splits")], groups={"unit_splits": [native_action("unit_splits")]}))["result"]
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["original_native_export"]["native_actions"][0]["affected_symbols"], ["ALTERNATE", "OTHER", "SYNTHA"])
        self.assertEqual(result["candidate_overlay"]["boundaries"][0]["affected_symbols"], ["ALTERNATE", "OTHER", "SYNTHA"])
        self.assertTrue(result["conflicts"])

    def test_exact_full_alias_set_can_match_without_symbol_translation(self):
        row = independent_row(native_type="unit_splits", affected_symbols=["ALTERNATE", "OTHER", "SYNTHA"])
        result = self.assess(frozen_fixture([row], groups={"unit_splits": [native_action("unit_splits")]}))["result"]
        self.assertEqual(len(result["matches"]), 1)

    def test_revised_replacement_link_retained_without_deleting_original(self):
        rows = [independent_row("old"), independent_row("new", status="REVISED", replaces_source_action_id="old", effective_date="2026-01-12")]
        result = self.assess(frozen_fixture(rows))["result"]
        self.assertEqual(len(result["issuer_observations"]), 2)
        self.assertEqual(result["issuer_observations"][1]["replaces_source_action_id"], "old")
        self.assertTrue(any(row["kind"] == "REPLACEMENT_LINK_UNRESOLVED" for row in result["conflicts"]))

    def test_same_source_body_under_two_manifests_retained_and_flagged(self):
        fixture = frozen_fixture(); add_inventory(fixture, same_body=True)
        result = self.assess(fixture)["result"]
        self.assertEqual(len(result["source_inventories"]), 2); self.assertEqual(len(result["issuer_observations"]), 2)
        self.assertTrue(any(row["kind"] == "DUPLICATE_SOURCE_BODY" for row in result["conflicts"]))

    def test_empty_inventory_and_gaps_never_mean_action_absence(self):
        result = self.assess(frozen_fixture([]))["result"]
        self.assertEqual(result["issuer_observations"], []); self.assertEqual(len(result["native_only"]), 1)
        self.assertEqual(result["coverage_matrix"][0]["unresolved_interval"], result["effective_span"])
        self.assertFalse(result["coverage_supported"])

    def test_source_clock_after_policy_and_policy_after_cutoff_rejected(self):
        fixture = frozen_fixture(); change_policy(fixture, recorded_at="2026-01-23T00:00:00Z")
        with self.assertRaises(ContractValidationError): self.assess(fixture)
        fixture = frozen_fixture(); change_policy(fixture, recorded_at="2026-10-14T05:30:00Z")
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_later_intake_cutoff_reuses_same_frozen_policy_without_rewriting_it(self):
        fixture = frozen_fixture(); before = fixture["policy"].to_bytes()
        value = fixture["request"].to_dict(); value.update(recorded_at="2026-10-15T06:00:00Z", data_cutoff_at="2026-10-15T05:00:00Z")
        fixture["request"] = ReconciledActionIntakeRequest.from_mapping(value)
        result = self.assess(fixture)["result"]
        self.assertEqual(before, fixture["policy"].to_bytes()); self.assertFalse(result["historical_point_in_time_verified"])

    def test_request_invalid_clocks_policy_event_and_authority_rejected(self):
        fixture = frozen_fixture()
        for changes in ({"data_cutoff_at": "2026-10-15T00:00:00Z"}, {"policy_event_id": "fake"}, {"supersedes_event_id": "fake"}, {"auto_trading_enabled": 0}):
            value = fixture["request"].to_dict(); value.update(changes)
            with self.assertRaises(ContractValidationError): ReconciledActionIntakeRequest.from_mapping(value)

    def test_tampered_missing_and_size_mismatched_direct_evidence_reject(self):
        for key in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence"):
            fixture = frozen_fixture(); ref_value = getattr(fixture["policy"], key)
            fixture["blobs"][ref_value["sha256"]] += b" "
            with self.subTest(key=key), self.assertRaises(ContractValidationError): self.assess(fixture)
        fixture = frozen_fixture(); fixture["blobs"].pop(fixture["policy"].independent_inventories[0]["sha256"])
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_supporting_evidence_hashes_are_checked(self):
        fixture = frozen_fixture(); reference = fixture["policy"].independent_inventories[0]
        value = json.loads(fixture["blobs"][reference["sha256"]]); support = ref("extra/support.raw", b"required source support")
        value["supporting_evidence"] = [support]
        raw = canonical_json_bytes(value); changed_ref = ref("changed/inventory.json", raw); fixture["blobs"][changed_ref["sha256"]] = raw
        change_policy(fixture, independent_inventories=[changed_ref])
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_rebinding_dataset_scope_or_universe_rejected(self):
        fixture = frozen_fixture(); change_policy(fixture, evidence_scope="RETAINED_HISTORY_RESEARCH")
        with self.assertRaises(ContractValidationError): self.assess(fixture)
        fixture = frozen_fixture(); reference = fixture["policy"].dataset_evidence; value = json.loads(fixture["blobs"][reference["sha256"]]); value["dataset_id"] = "unrelated-dataset"
        raw = canonical_json_bytes(value); changed = ref("changed/dataset.json", raw); fixture["blobs"][changed["sha256"]] = raw
        change_policy(fixture, dataset_evidence=changed)
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_noncanonical_masks_and_different_policy_bytes_rejected(self):
        fixture = frozen_fixture(); raw = json.dumps(fixture["masks"], indent=4).encode(); reference = ref("changed/masks.json", raw)
        fixture["blobs"][reference["sha256"]] = raw; change_policy(fixture, original_native_masks_evidence=reference)
        with self.assertRaises(ContractValidationError): self.assess(fixture)
        fixture = frozen_fixture(); raw = json.dumps(fixture["policy"].to_dict(), indent=4).encode(); reference = ref("changed/pretty-policy.json", raw)
        fixture["blobs"][reference["sha256"]] = raw; value = fixture["request"].to_dict(); value["policy_evidence"] = reference
        fixture["request"] = ReconciledActionIntakeRequest.from_mapping(value)
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_source_file_and_byte_bounds_fail_without_truncating_rows(self):
        fixture = frozen_fixture()
        with patch("blackpod_build_week.reconciled_action_intake.MAX_SOURCE_BYTES", 10):
            with self.assertRaises(ContractValidationError): self.assess(fixture)
        with patch("blackpod_build_week.reconciled_action_intake.MAX_FILES", 1):
            with self.assertRaises(ContractValidationError): self.assess(fixture)
        with patch("blackpod_build_week.reconciled_action_intake.MAX_OBSERVATIONS", 0):
            with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_exact_native_source_and_inventory_id_reuse_rejected(self):
        fixture = frozen_fixture(); add_inventory(fixture, same_body=True, inventory_id="unit-independent-actions", publisher="conflicting-reused-identity")
        with self.assertRaises(ContractValidationError): self.assess(fixture)

    def test_qqq_parser_to_intake_preserves_exponent_zero_trailing_zeros(self):
        raw = canonical_json_bytes({"cusip": "46090E103", "currencyCode": "USD", "distributions": [qqq_row()]})
        raw = raw.replace(b"0.80826", b"8.082600e-1").replace(b'"shortTermCapitalGainsDistribution": 0', b'"shortTermCapitalGainsDistribution": 0.00000')
        fixture = qqq_fixture(raw); result = self.assess(fixture)["result"]
        row = result["issuer_observations"][0]
        self.assertEqual(row["amount_lexemes"]["dividend"], "8.082600e-1")
        self.assertEqual(row["amount_lexemes"]["short_term_capital_gain"], "0.00000")
        self.assertEqual(row["provenance"]["native_row"]["longTermCapitalGainsDistribution"], "0")
        self.assertEqual(validate_result(result), result)
        self.assertEqual(len(result["coverage_matrix"]), 13)

    def test_qqq_special_total_not_recharacterized_as_ordinary_income(self):
        raw = canonical_json_bytes({"cusip": "46090E103", "currencyCode": "USD", "distributions": [qqq_row(exDate="2023-12-27", distributionAmountPerUnit=0.21584, ordinaryIncomeDistribution=0)]})
        result = self.assess(qqq_fixture(raw))["result"]; row = result["issuer_observations"][0]
        self.assertEqual(row["amount_lexemes"]["dividend"], "0.21584")
        self.assertEqual(row["provenance"]["native_row"]["ordinaryIncomeDistribution"], "0")
        self.assertFalse(result["economic_truth_verified"]); self.assertFalse(result["confirmed_payment"])

    def test_qqq_duplicate_rows_remain_distinct_source_pointer_observations(self):
        raw = canonical_json_bytes({"cusip": "46090E103", "currencyCode": "USD", "distributions": [qqq_row(), qqq_row()]})
        result = self.assess(qqq_fixture(raw))["result"]
        self.assertEqual(len(result["issuer_observations"]), 2); self.assertEqual(len(result["ambiguous"]), 1)
        self.assertNotEqual(*[item["provenance"]["value_pointer"] for item in result["issuer_observations"]])

    def test_result_unknown_keys_false_authority_and_coverage_promotion_rejected(self):
        result = self.assess(frozen_fixture())["result"]
        for field in FALSE_FIELDS:
            for unsafe in (True, 0):
                value = deepcopy(result); value[field] = unsafe
                with self.subTest(field=field, unsafe=unsafe), self.assertRaises(ContractValidationError): validate_result(value)
        value = deepcopy(result); value["extra"] = "forged"
        with self.assertRaises(ContractValidationError): validate_result(value)
        value = deepcopy(result); value["coverage_matrix"][0]["eligible"] = True
        with self.assertRaises(ContractValidationError): validate_result(value)

    def test_result_unknown_date_mapping_missing_cell_and_mask_rewrite_rejected(self):
        result = self.assess(frozen_fixture(groups={"worthless_removals": [native_action("worthless_removals")]}))["result"]
        value = deepcopy(result); value["candidate_overlay"]["boundaries"][0]["mapped_session_id"] = "2026-01-05"
        with self.assertRaises(ContractValidationError): validate_result(value)
        value = deepcopy(result); value["coverage_matrix"].pop()
        with self.assertRaises(ContractValidationError): validate_result(value)
        value = deepcopy(result); value["original_native_masks"]["assessment"]["status"] = "READY"
        with self.assertRaises(ContractValidationError): validate_result(value)

    def test_malformed_nested_source_inventory_rejected_as_contract_error(self):
        result = self.assess(frozen_fixture())["result"]
        for invalid in (None, [], "inventory"):
            value = deepcopy(result); value["source_inventories"][0]["inventory"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ContractValidationError): validate_result(value)

    def test_result_cannot_rebind_boundaries_drop_known_keys_or_change_counts(self):
        result = self.assess(frozen_fixture())["result"]
        changes = [lambda value: value["candidate_overlay"]["boundaries"][0].update(affected_symbols=["SYNTHB"]),
            lambda value: value["candidate_overlay"]["boundaries"][1].update(source_status="CANCELLED", boundary_flag=False),
            lambda value: value["candidate_overlay"]["boundaries"][0].update(boundary_id="forged-boundary"),
            lambda value: value["matches"].clear(),
            lambda value: value["source_inventories"][0].update(observed_action_count=0),
            lambda value: value["coverage_matrix"][0].update(observed_native_count=0),
            lambda value: value["original_native_events"][0].update(symbol="SYNTHB")]
        for change in changes:
            value = deepcopy(result); change(value)
            with self.subTest(change=change), self.assertRaises(ContractValidationError): validate_result(value)

    def test_unknown_scope_cannot_be_hidden_or_doubled_under_another_identity(self):
        fixture = frozen_fixture(groups={"worthless_removals": [native_action("worthless_removals")]})
        result = self.assess(fixture)["result"]
        value = deepcopy(result); value["candidate_overlay"]["unknown_date_scope"] = []
        with self.assertRaises(ContractValidationError): validate_result(value)
        value = deepcopy(result); value["candidate_overlay"]["boundaries"][1] = deepcopy(value["candidate_overlay"]["boundaries"][0]); value["candidate_overlay"]["boundaries"][1]["boundary_id"] = "different-label"
        with self.assertRaises(ContractValidationError): validate_result(value)

    def test_source_capture_and_manifest_clocks_checked_before_freeze(self):
        fixture = frozen_fixture(); reference = fixture["policy"].independent_inventories[0]
        value = json.loads(fixture["blobs"][reference["sha256"]]); value.update(captured_at="2026-10-14T04:01:00Z", recorded_at="2026-10-14T04:02:00Z")
        raw = canonical_json_bytes(value); new_ref = ref("reconciled/future-inventory.json", raw); fixture["blobs"][new_ref["sha256"]] = raw
        change_policy(fixture, independent_inventories=[new_ref])
        with self.assertRaises(ContractValidationError): inspect_policy_sources(fixture["policy"], fixture["blobs"])

    def test_conflict_comparison_and_result_byte_caps_fail_closed(self):
        fixture = frozen_fixture([independent_row(effective_date="2026-01-12")])
        with patch("blackpod_build_week.reconciled_action_intake.MAX_CONFLICT_COMPARISONS", 0):
            with self.assertRaises(ContractValidationError): self.assess(fixture)
        result = self.assess(fixture)["result"]
        with patch("blackpod_build_week.contracts.reconciled_action_intake.MAX_RESULT_BYTES", 10):
            with self.assertRaises(ContractValidationError): validate_result(result)

    def test_replay_evidence_is_complete_and_deterministic(self):
        fixture = frozen_fixture(); material = self.assess(fixture)
        retained = {sha256_bytes(value): value for value in material["evidence"].values()}
        self.assertEqual(build_reconciled_action_intake(fixture["policy"], fixture["request"], retained), material)
        self.assertEqual(len(evidence_references(fixture["policy"], fixture["request"])), 5)


if __name__ == "__main__": unittest.main()
