"""Closed capture receipts and additive reviewed-study declaration boundaries."""
import copy
import unittest

from blackpod_build_week.contracts.trading_evidence_capture import CaptureReceipt
from blackpod_build_week.contracts.trading_shadow_review import ReviewedShadowStudy
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_review_example import fixture_material


def receipt():
    return {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
        "url": "https://data.alpaca.markets/v1/corporate-actions", "query": {"symbols": "QQQ,SPY", "limit": 1000},
        "captured_at": "2026-10-13T03:55:20Z", "status": 200, "body_sha256": sha256_bytes(b"{}"), "size_bytes": 2}


class EvidenceCaptureTests(unittest.TestCase):
    def test_canonical_roundtrip_and_immutable_nested_query(self):
        doc = CaptureReceipt.from_mapping(receipt()); before = doc.to_bytes()
        doc.to_dict()["query"]["symbols"] = "OTHER"
        self.assertEqual(doc.to_bytes(), before)
        self.assertEqual(CaptureReceipt.from_bytes(before).to_bytes(), before)

    def test_unknown_missing_and_duplicate_json_fields_reject(self):
        for change in ({"extra": "x"}, {"size_bytes": None}):
            with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), **change})
        value = receipt(); value.pop("query")
        with self.assertRaises(ValueError): CaptureReceipt.from_mapping(value)
        with self.assertRaises(ValueError): CaptureReceipt.from_bytes(b'{"schema_version":"x","schema_version":"x"}')

    def test_no_broker_account_or_order_endpoints_or_non_get_methods(self):
        for url in ("https://paper-api.alpaca.markets/v2/orders", "https://paper-api.alpaca.markets/v2/account", "http://data.alpaca.markets/v2/stocks/quotes", [], None):
            with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), "url": url})
        with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), "method": "POST"})

    def test_strict_status_and_size_types_and_bounds(self):
        for field, values in (("status", [True, "200", 199, 600]), ("size_bytes", [False, "2", -1, 64 * 1024 * 1024 + 1])):
            for value in values:
                with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), field: value})

    def test_non_success_status_is_preserved_as_evidence_not_approval(self):
        for status in (401, 403, 429, 500):
            self.assertEqual(CaptureReceipt.from_mapping({**receipt(), "status": status}).status, status)

    def test_query_only_bounded_explicit_strings_or_integers(self):
        for query in ({}, {"limit": True}, {"symbols": ["QQQ"]}, {1: "x"}, {"page_token": " "}, {str(i): "x" for i in range(17)}):
            with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), "query": query})

    def test_hash_and_clock_validation(self):
        for change in ({"body_sha256": "invalid"}, {"captured_at": "2026-10-13"}):
            with self.assertRaises(ValueError): CaptureReceipt.from_mapping({**receipt(), **change})


class ReviewedStudyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.value = fixture_material()["studies"][0]["study"].to_dict()

    def test_roundtrip_and_original_version_remains_v2(self):
        doc = ReviewedShadowStudy.from_mapping(self.value)
        self.assertEqual(doc.schema_version, "blackpod.trading_shadow_study.v2")
        self.assertEqual(doc.to_bytes(), ReviewedShadowStudy.from_bytes(doc.to_bytes()).to_bytes())

    def test_risk_review_is_mandatory_and_intakes_nullable(self):
        value = copy.deepcopy(self.value)
        value["cost_intake_evidence"] = value["continuity_intake_evidence"] = None
        self.assertIsNone(ReviewedShadowStudy.from_mapping(value).cost_intake_evidence)
        value["risk_review_evidence"] = None
        with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping(value)

    def test_source_path_collisions_are_rejected(self):
        value = copy.deepcopy(self.value); value["risk_review_evidence"] = value["base_plan_evidence"]
        with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping(value)

    def test_execution_capital_and_policy_authority_cannot_be_enabled(self):
        for field in self.value["authority"]:
            value = copy.deepcopy(self.value); value["authority"][field] = True
            with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping(value)
        value = copy.deepcopy(self.value); value["auto_trading_enabled"] = True
        with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping(value)

    def test_legacy_gate_fields_or_unknown_versions_cannot_be_imported(self):
        for change in ({"schema_version": "blackpod.trading_shadow_study.v1"}, {"price_continuity_evidence": None}, {"untrusted": "order"}):
            with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping({**self.value, **change})

    def test_identifier_suffix_bound_is_retained(self):
        value = copy.deepcopy(self.value); value["study_id"] = "a" * 111
        with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping(value)

    def test_recording_clock_and_scope_remain_strict(self):
        for change in ({"registered_at": "not-a-time"}, {"domain": "INVESTMENT"}, {"scope": "EXECUTION"}, {"sizing": {"method": "AUTO", "per_symbol_notional": "100"}}):
            with self.assertRaises(ValueError): ReviewedShadowStudy.from_mapping({**self.value, **change})


if __name__ == "__main__": unittest.main()
