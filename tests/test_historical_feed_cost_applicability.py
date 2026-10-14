"""Deterministic declared-scope tests; fixture assertions establish no costs."""
import copy
from datetime import timedelta
from decimal import localcontext, Inexact, Rounded
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import historical_feed_cost_applicability as engine
from blackpod_build_week.contracts.historical_feed_cost_applicability import (
    HistoricalFeedCostContext, HistoricalFeedCostApplicabilityPacket, CATEGORIES,
    CONTEXT_VERSION, PACKET_VERSION, DERIVED_NULL_FIELDS, FALSE_FIELDS, evidence_references, validate_result,
)
from blackpod_build_week.contracts.mission_request import parse_rfc3339, format_rfc3339
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.trading_shadow_review_example import fixture_material


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def applicability_fixture():
    """Use original fictional bars and new explicit, fictional document claims."""
    original = fixture_material(); blobs = dict(original["blobs"])
    base = original["base_studies"][0]
    capture = prepare_capture_plan(original["events"], blobs, capture_id="applicability-fixture-capture",
        created_at="2025-04-03T00:00:00Z", base_plan_event_id=base["plan_event"].event_id)
    plan_ref = ref("applicability-fixture/capture.json", capture.to_bytes()); blobs[plan_ref["sha256"]] = capture.to_bytes()
    receipts, clocks = [], []
    for index, segment in enumerate(capture.segments):
        clock = format_rfc3339(parse_rfc3339("2025-04-04T00:00:00Z", "clock") + timedelta(seconds=index))
        receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
            "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": segment["query"],
            "captured_at": clock, "status": 200, "body_sha256": "c" * 64, "size_bytes": 100}
        raw = canonical_json_bytes(receipt); receipt_ref = ref("applicability-fixture/receipt-%03d.json" % index, raw)
        receipts.append(receipt_ref); clocks.append(clock); blobs[receipt_ref["sha256"]] = raw
    account_raw = b"Fictional redacted paper profile; no real account or authenticated authority.\n"
    account = ref("applicability-fixture/account.raw", account_raw); blobs[account["sha256"]] = account_raw
    bars_receipt = next(row for row in original["dataset"].provenance["source_evidence"] if "bars-receipt" in row["path"])
    context = HistoricalFeedCostContext.from_mapping({"schema_version": CONTEXT_VERSION, "context_id": "applicability-fixture-context",
        "recorded_at": "2025-04-05T00:00:00Z", "capture_plan_event_id": "journal-event-" + "a" * 64,
        "aggregate_export_event_id": "journal-event-" + "b" * 64, "base_plan_event_id": capture.base_plan_event_id,
        "dataset_evidence": capture.dataset_evidence, "bars_receipt_evidence": bars_receipt, "capture_plan_evidence": plan_ref,
        "quote_receipt_evidence": receipts, "provider": "ALPACA", "endpoint": "https://data.alpaca.markets/v2/stocks/quotes",
        "feed": "iex", "universe": original["dataset"].universe, "currency": "USD",
        "market_event_interval": {"start_at": capture.segments[0]["query"]["start"], "end_at": capture.segments[-1]["query"]["end"]},
        "delivery_interval": {"start_at": clocks[0], "end_at": clocks[-1]}, "collection_mode": "MARKET_DATA_GET_ONLY",
        "declared_evaluation_mode": "PAPER_SIMULATION", "account_evidence": account,
        "auto_trading_enabled": False, "authority": engine.AUTHORITY})
    context_ref = ref("applicability-fixture/context.json", context.to_bytes()); blobs[context_ref["sha256"]] = context.to_bytes()
    raw = b"Entirely fictional source document for interface tests, not a real provider or economic fact.\n"
    document_ref = ref("applicability-fixture/document.raw", raw); blobs[document_ref["sha256"]] = raw
    document = {"document_id": "fictional-document", "evidence": document_ref, "source_url": "https://example.invalid/fictional-source",
        "publisher": "Fictional software fixture author", "document_version": "fictional-v1", "published_at": "2025-01-01T00:00:00Z",
        "observed_at": "2025-04-04T12:00:00Z", "document_kind": "RAW_PRIMARY_DOCUMENT"}
    scope = {key: context.to_dict()[key] for key in ("provider", "endpoint", "feed", "universe", "currency", "collection_mode",
        "declared_evaluation_mode", "account_evidence", "market_event_interval", "delivery_interval")}
    scope["effective_time_basis"] = "BOTH"
    categories = [{"category": category, "assertions": [{"assertion_id": "assertion-" + category.lower().replace("_", "-"),
        "document_id": document["document_id"], "claim_key": "claim-" + category.lower().replace("_", "-"),
        "claim_value": "fictional-source-claim", "numeric_assertion": {"value": "1e2", "unit": "fictional-native-units"},
        "fee_formula_shape": "CONSTANT_BPS_PLUS_PER_FILL" if category == "FEE_SCHEDULE" else "UNRESOLVED", "scope": copy.deepcopy(scope)}]}
        for category in CATEGORIES]
    packet = HistoricalFeedCostApplicabilityPacket.from_mapping({"schema_version": PACKET_VERSION,
        "packet_id": "applicability-fixture-packet", "recorded_at": "2025-04-06T00:00:00Z", "data_cutoff_at": "2025-04-05T23:00:00Z",
        "context_evidence": context_ref, "reviewer_id": "fictional-author", "review_notes": "Authored interface fixture only; never a fee, unit, slippage or fill assumption.",
        "source_documents": [document], "categories": categories, "auto_trading_enabled": False, "authority": engine.AUTHORITY})
    return {"context": context, "packet": packet, "blobs": blobs, "original": original, "capture": capture}


class HistoricalApplicabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            cls.material = applicability_fixture()

    def setUp(self):
        self.packet = self.material["packet"].to_dict(); self.context = self.material["context"].to_dict(); self.blobs = dict(self.material["blobs"])
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("inference forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))

    def assess(self):
        return engine.assess_historical_applicability(self.packet, self.context, self.blobs)

    def rebind_context(self):
        context = HistoricalFeedCostContext.from_mapping(self.context)
        raw = context.to_bytes(); reference = ref(self.packet["context_evidence"]["path"], raw)
        self.blobs[reference["sha256"]] = raw; self.packet["context_evidence"] = reference

    def claim(self, index=0):
        return self.packet["categories"][index]["assertions"][0]

    def test_matched_declared_fixture_never_establishes_applicability_parameters_or_authority(self):
        result = self.assess()["result"]
        self.assertTrue(all(row["status"] == "DECLARED_SCOPE_MATCHED_NOT_VERIFIED" for row in result["category_results"]))
        for key in DERIVED_NULL_FIELDS: self.assertIsNone(result[key])
        for key in FALSE_FIELDS: self.assertIs(result[key], False)
        self.assertEqual(result["evidence_scope"], "SYNTHETIC_FIXTURE_ONLY")

    def test_exact_numeric_lexemes_retained_without_unit_or_rate_assignment(self):
        result = self.assess()["result"]
        self.assertEqual(result["category_results"][1]["assertion_results"][0]["numeric_assertion"], {"value": "1e2", "unit": "fictional-native-units"})
        self.assertIsNone(result["derived_unit_multiplier"])

    def test_sip_scope_cannot_resolve_original_iex_data(self):
        self.claim(1)["scope"]["feed"] = "sip"
        row = self.assess()["result"]["category_results"][1]
        self.assertEqual(row["status"], "SCOPE_MISMATCH")
        self.assertEqual(row["assertion_results"][0]["mismatched_fields"], ["feed"])

    def test_delivery_only_unit_document_cannot_establish_historical_cross_time_semantics(self):
        self.claim(1)["scope"].update(effective_time_basis="DELIVERY_TIME", market_event_interval=None)
        row = self.assess()["result"]["category_results"][1]
        self.assertEqual(row["status"], "UNRESOLVED")
        self.assertIn("CROSS_TIME_APPLICABILITY_UNRESOLVED", row["reason_codes"])

    def test_partial_interval_has_exact_open_and_closed_gap_boundaries(self):
        original = self.claim()["scope"]["market_event_interval"]
        self.claim()["scope"]["market_event_interval"] = {"start_at": "2025-01-03T14:30:00Z", "end_at": "2025-01-06T14:31:00Z"}
        row = self.assess()["result"]["category_results"][0]["assertion_results"][0]
        self.assertEqual(len(row["interval_gaps"]), 2)
        self.assertEqual(row["interval_gaps"][0]["start_at"], original["start_at"])
        self.assertFalse(row["interval_gaps"][0]["end_inclusive"])
        self.assertFalse(row["interval_gaps"][1]["start_inclusive"])

    def test_unresolved_basis_and_missing_intervals_are_explicit(self):
        self.claim()["scope"].update(effective_time_basis="UNRESOLVED", market_event_interval=None, delivery_interval=None)
        self.assertIn("EFFECTIVE_TIME_BASIS_UNRESOLVED", self.assess()["result"]["reason_codes"])
        self.claim()["scope"]["effective_time_basis"] = "BOTH"
        row = self.assess()["result"]["category_results"][0]["assertion_results"][0]
        self.assertEqual(len(row["interval_gaps"]), 2)

    def test_missing_account_does_not_invent_paper_fee_or_capacity_applicability(self):
        self.context["account_evidence"] = None; self.rebind_context()
        for row in self.packet["categories"]: row["assertions"][0]["scope"]["account_evidence"] = None
        result = self.assess()["result"]
        for row in result["category_results"][2:]:
            self.assertEqual(row["status"], "UNRESOLVED"); self.assertIn("ACCOUNT_SCOPE_UNRESOLVED", row["reason_codes"])

    def test_paper_mode_document_cannot_apply_to_live_target(self):
        self.context["declared_evaluation_mode"] = "LIVE_BROKERAGE"; self.rebind_context()
        self.assertEqual(self.assess()["result"]["category_results"][2]["status"], "SCOPE_MISMATCH")

    def test_author_notes_remain_distinct_from_raw_primary_documents(self):
        self.packet["source_documents"][0]["document_kind"] = "AUTHORED_REVIEW_NOTE"
        self.assertIn("AUTHORED_REVIEW_NOTE_NOT_RAW_PRIMARY_DOCUMENT", self.assess()["result"]["reason_codes"])

    def test_missing_publication_version_and_source_claim_remain_unresolved(self):
        self.packet["source_documents"][0].update(published_at=None, document_version=None)
        self.claim().update(claim_value=None, numeric_assertion=None)
        reasons = self.assess()["result"]["reason_codes"]
        for reason in ("PUBLICATION_TIME_UNRESOLVED", "DOCUMENT_VERSION_UNRESOLVED", "CLAIM_VALUE_UNRESOLVED"): self.assertIn(reason, reasons)

    def test_conflicting_same_scope_claims_are_preserved_without_winner_selection(self):
        second = copy.deepcopy(self.claim(1)); second.update(assertion_id="conflicting-unit-claim", claim_value="different-source-unit-claim")
        self.packet["categories"][1]["assertions"].append(second)
        row = self.assess()["result"]["category_results"][1]
        self.assertEqual(row["status"], "CONFLICTING_SOURCES")
        self.assertEqual(row["conflicts"][0]["assertion_ids"], sorted([self.claim(1)["assertion_id"], second["assertion_id"]]))

    def test_equivalent_numeric_tokens_are_not_false_conflicts(self):
        second = copy.deepcopy(self.claim(1)); second.update(assertion_id="equivalent-number-claim", numeric_assertion={"value": "100", "unit": "fictional-native-units"})
        self.packet["categories"][1]["assertions"].append(second)
        self.assertEqual(self.assess()["result"]["category_results"][1]["conflicts"], [])

    def test_disjoint_feed_scopes_and_nonoverlapping_dates_do_not_create_false_conflicts(self):
        for scope_change in ({"feed": "sip"}, {"market_event_interval": {"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-02-01T00:00:00Z"}}):
            second = copy.deepcopy(self.claim(1)); second.update(assertion_id="disjoint-claim", claim_value="different-unit")
            second["scope"].update(scope_change); self.packet["categories"][1]["assertions"] = [self.claim(1), second]
            self.assertEqual(self.assess()["result"]["category_results"][1]["conflicts"], [])

    def test_richer_fee_formula_does_not_become_old_three_parameter_cost_model(self):
        self.claim(2)["fee_formula_shape"] = "SIDE_PER_SHARE_CAP_ROUNDING"
        result = self.assess()["result"]
        self.assertIn("OLD_COST_MODEL_EXPRESSIVITY_UNVERIFIED", result["reason_codes"])
        self.assertIsNone(result["derived_fee_rates"]); self.assertFalse(result["old_assumptions_populated"])

    def test_empty_categories_are_first_class_unresolved_and_no_documents_required(self):
        for row in self.packet["categories"]: row["assertions"] = []
        self.packet["source_documents"] = []
        self.assertTrue(all(row["status"] == "UNRESOLVED" for row in self.assess()["result"]["category_results"]))

    def test_metadata_only_no_quote_or_bar_bodies_read(self):
        for source in self.material["original"]["dataset"].provenance["source_evidence"]:
            if source["path"].endswith(".raw"): self.blobs.pop(source["sha256"], None)
        self.assertNotIn("c" * 64, self.blobs)
        self.assess()

    def test_receipt_feed_query_membership_and_delivery_clock_tampering_rejected(self):
        for change in ({"feed": "sip"}, {"start": "2024-01-01T00:00:00Z"}):
            blobs = dict(self.blobs); original = self.context["quote_receipt_evidence"][0]
            value = json.loads(blobs[original["sha256"]]); value["query"].update(change)
            raw = canonical_json_bytes(value); replacement = ref(original["path"], raw)
            self.context["quote_receipt_evidence"][0] = replacement; self.blobs[replacement["sha256"]] = raw; self.rebind_context()
            with self.assertRaises(ValueError): self.assess()
            self.context["quote_receipt_evidence"][0] = original; self.blobs = blobs; self.rebind_context()
        self.context["delivery_interval"]["end_at"] = "2025-04-04T23:00:00Z"; self.rebind_context()
        with self.assertRaises(ValueError): self.assess()

    def test_reduced_market_interval_cannot_hide_original_planned_windows(self):
        self.context["market_event_interval"]["end_at"] = self.context["market_event_interval"]["start_at"]; self.rebind_context()
        with self.assertRaises(ValueError): self.assess()

    def test_unrelated_bars_receipt_and_context_dataset_bindings_rejected(self):
        self.context["bars_receipt_evidence"] = self.context["quote_receipt_evidence"][0]; self.rebind_context()
        with self.assertRaises(ValueError): self.assess()

    def test_missing_hash_or_size_mismatch_or_context_identity_rejected(self):
        for kind in ("missing", "tamper", "size"):
            blobs = dict(self.blobs); reference = self.packet["source_documents"][0]["evidence"]
            if kind == "missing": self.blobs.pop(reference["sha256"])
            elif kind == "tamper": self.blobs[reference["sha256"]] = b"different bytes"
            else: reference["size_bytes"] += 1
            with self.assertRaises(ValueError): self.assess()
            self.blobs = blobs; self.packet = self.material["packet"].to_dict()
        self.context["context_id"] = "different-context"
        with self.assertRaises(ValueError): self.assess()

    def test_cutoff_excludes_future_context_or_publication_and_observation_clock(self):
        self.packet["data_cutoff_at"] = "2025-04-04T23:59:59Z"
        with self.assertRaises(ValueError): self.assess()
        self.packet = self.material["packet"].to_dict(); self.packet["source_documents"][0]["published_at"] = "2025-04-05T00:00:00Z"
        with self.assertRaises(ValueError): self.assess()
        self.packet = self.material["packet"].to_dict(); self.packet["source_documents"][0]["observed_at"] = "2025-04-06T00:00:00Z"
        with self.assertRaises(ValueError): self.assess()

    def test_closed_nested_fields_duplicate_category_assertion_and_document_ids_rejected(self):
        for target in (self.packet, self.packet["source_documents"][0], self.claim(), self.claim()["scope"], self.claim()["numeric_assertion"]):
            target["extra"] = True
            with self.assertRaises(ValueError): HistoricalFeedCostApplicabilityPacket.from_mapping(self.packet)
            del target["extra"]
        self.packet["categories"][1]["assertions"].append(copy.deepcopy(self.claim(1)))
        with self.assertRaises(ValueError): self.assess()

    def test_numeric_claim_types_nonfinite_and_huge_exponents_rejected(self):
        for value in (True, 1.0, "NaN", "1e999999999", '"100"'):
            self.claim()["numeric_assertion"]["value"] = value
            with self.assertRaises(ValueError): self.assess()

    def test_urls_cannot_contain_credentials_fragments_or_nonhttps_schemes(self):
        for url in ("https://user:pass@example.invalid/document", "file:///tmp/document", "http://example.invalid/document", "https://example.invalid/doc#fragment"):
            self.packet["source_documents"][0]["source_url"] = url
            with self.assertRaises(ValueError): self.assess()

    def test_safety_booleans_and_derived_values_cannot_be_promoted(self):
        result = self.assess()["result"]
        for key in FALSE_FIELDS:
            value = copy.deepcopy(result); value[key] = 1
            with self.assertRaises(ValueError): validate_result(value)
        for key in DERIVED_NULL_FIELDS:
            value = copy.deepcopy(result); value[key] = "0"
            with self.assertRaises(ValueError): validate_result(value)
        self.context["auto_trading_enabled"] = 0
        with self.assertRaises(ValueError): HistoricalFeedCostContext.from_mapping(self.context)

    def test_deterministic_context_independent_of_decimal_precision_and_input_mutation(self):
        before_packet, before_context, before_blobs = copy.deepcopy(self.packet), copy.deepcopy(self.context), dict(self.blobs)
        normal = self.assess()
        with localcontext() as context:
            context.prec = 3; context.traps[Inexact] = True; context.traps[Rounded] = True
            hostile = self.assess()
        self.assertEqual(normal, hostile)
        self.assertEqual((self.packet, self.context, self.blobs), (before_packet, before_context, before_blobs))
        normal["result"]["source_documents"][0]["publisher"] = "changed return only"
        self.assertEqual(self.packet, before_packet)

    def test_source_leaf_traversal_and_raw_evidence_retention(self):
        references = evidence_references(self.packet, self.context)
        self.assertIn(self.packet["context_evidence"], references)
        for reference in self.context["quote_receipt_evidence"]: self.assertIn(reference, references)
        result = self.assess()
        reference = self.packet["source_documents"][0]["evidence"]
        self.assertEqual(result["evidence"]["historical-applicability/support/" + reference["sha256"] + ".raw"], self.blobs[reference["sha256"]])

    def test_result_scope_and_category_dispositions_cannot_hide_gaps(self):
        self.claim(1)["scope"]["feed"] = "sip"
        result = self.assess()["result"]
        for pointer in (("category_results", 1, "status"), ("category_results", 1, "assertion_results", 0, "scope_status")):
            value = copy.deepcopy(result); target = value
            for key in pointer[:-1]: target = target[key]
            target[pointer[-1]] = "DECLARED_SCOPE_MATCHED_NOT_VERIFIED"
            with self.assertRaises(ValueError): validate_result(value)
        value = copy.deepcopy(result); value["category_results"][1]["reason_codes"] = []
        with self.assertRaises(ValueError): validate_result(value)

    def test_missing_category_assertions_cannot_receive_matched_status(self):
        self.packet["categories"][0]["assertions"] = []
        value = self.assess()["result"]; value["category_results"][0]["status"] = "DECLARED_SCOPE_MATCHED_NOT_VERIFIED"
        with self.assertRaises(ValueError): validate_result(value)

    def test_conflict_metadata_must_match_retained_assertion_keys_and_dispositions(self):
        second = copy.deepcopy(self.claim(1)); second.update(assertion_id="conflicting-result", claim_value="conflicting-value")
        self.packet["categories"][1]["assertions"].append(second)
        result = self.assess()["result"]
        for kind in ("wrong_key", "hidden_status", "duplicate"):
            value = copy.deepcopy(result); category = value["category_results"][1]
            if kind == "wrong_key": category["conflicts"][0]["claim_key"] = "unrelated-key"
            elif kind == "hidden_status": category["status"] = "UNRESOLVED"
            else: category["conflicts"].append(copy.deepcopy(category["conflicts"][0]))
            with self.assertRaises(ValueError): validate_result(value)


if __name__ == "__main__": unittest.main()
