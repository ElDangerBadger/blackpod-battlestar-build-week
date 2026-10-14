"""Offline retained-primary QQQ profile, with synthetic software fixtures."""
from copy import deepcopy
from decimal import localcontext, Inexact, InvalidOperation
from html import escape, unescape
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.qqq_distribution_inventory import (
    QQQDistributionInventory, VERSION, PROFILE, URL, RESOURCE_TEMPLATE, AUTHORITY,
    MAX_BODY_BYTES, MAX_DISCOVERY_BYTES, evidence_references,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.qqq_distribution_inventory import (
    parse_qqq_distribution_inventory, NUMBER_ENCODING, HASH_BASIS,
)

CAPTURED_AT = "2026-10-14T02:05:08.383765Z"


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def row(**changes):
    return {"exDate": "2023-12-18", "recordDate": "2023-12-19", "payDate": "2023-12-29",
        "distributionAmountPerUnit": 0.80826, "ordinaryIncomeDistribution": 0.80826,
        "shortTermCapitalGainsDistribution": 0, "longTermCapitalGainsDistribution": 0,
        "returnOfCapitalDistribution": None, "liquidationDistribution": None, **changes}


def discovery(component=None):
    component = component or {"url": RESOURCE_TEMPLATE, "tableVariation": "distributions", "apiResponseKey": "distributions",
        "productMetaData": {"cusip": "46090E103", "locale": "en_US", "isin": "US46090E1038", "uniqueIdentifier": "cusip"}}
    return ('<div data-model="' + escape(json.dumps({"root": component}), quote=True) + '"></div>').encode()


def material(raw=None, *, receipt_changes=None, discovery_raw=None, scope="SYNTHETIC_FIXTURE_ONLY"):
    raw = raw if raw is not None else canonical_json_bytes({"cusip": "46090E103", "currencyCode": "USD", "distributions": [row()]})
    receipt = canonical_json_bytes({"schema_version": "blackpod.public_document_capture_receipt.v1", "method": "GET", "url": URL,
        "status": 200, "captured_at": CAPTURED_AT, "content_type": "application/json", "body_sha256": sha256_bytes(raw), "size_bytes": len(raw),
        "source_kind": "PUBLIC_PUBLISHER_DISTRIBUTION_HISTORY", "credentials_used": False, "redirects_followed": False, **(receipt_changes or {})})
    html = discovery_raw if discovery_raw is not None else discovery()
    manifest = {"schema_version": VERSION, "inventory_id": "synthetic-qqq-profile-unit", "recorded_at": "2026-10-14T03:00:00Z", "profile": PROFILE,
        "evidence_scope": scope, "publisher": "INVESCO", "source_url": URL, "captured_at": CAPTURED_AT,
        "body_evidence": ref("qqq/distributions.json", raw), "receipt_evidence": ref("qqq/receipt.json", receipt), "discovery_evidence": ref("qqq/discovery.html", html),
        "declared_coverage": {"symbols": ["QQQ"], "action_types": ["cash_dividends"], "effective_start": "2023-10-02", "effective_end": "2026-10-12", "completeness": "UNKNOWN"},
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)}
    return manifest, {sha256_bytes(value): value for value in (raw, receipt, html)}


class QQQDistributionInventoryTests(unittest.TestCase):
    def parse(self, raw=None, **kwargs):
        manifest, blobs = material(raw, **kwargs)
        return parse_qqq_distribution_inventory(manifest, blobs)

    def body(self, rows=None, **changes):
        return canonical_json_bytes({"cusip": "46090E103", "currencyCode": "USD", "distributions": [row()] if rows is None else rows, **changes})

    def test_literal_dates_amounts_and_exact_provenance(self):
        parsed = self.parse(); action = parsed["actions"][0]
        self.assertEqual(action["effective_date"], "2023-12-18")
        self.assertEqual(action["record_date"], "2023-12-19")
        self.assertEqual(action["payable_date"], "2023-12-29")
        self.assertEqual(action["amount_lexemes"], {"dividend": "0.80826", "short_term_capital_gain": "0", "long_term_capital_gain": "0"})
        provenance = action["provenance"]
        self.assertEqual(provenance["value_pointer"], "/distributions/0")
        self.assertEqual(provenance["native_row_number_encoding"], NUMBER_ENCODING)
        self.assertEqual(provenance["native_row_hash_basis"], HASH_BASIS)
        self.assertEqual(provenance["row_sha256"], sha256_bytes(canonical_json_bytes(provenance["native_row"])))
        self.assertEqual(action["status"], "LISTED_STATUS_UNSPECIFIED")
        self.assertEqual(action["cusip"], "46090E103")

    def test_exponent_trailing_zero_and_zero_lexemes_are_not_rounded(self):
        raw = self.body().replace(b'0.80826', b'8.082600e-1').replace(b'"shortTermCapitalGainsDistribution": 0', b'"shortTermCapitalGainsDistribution": 0.00000')
        parsed = self.parse(raw); action = parsed["actions"][0]
        self.assertEqual(action["amount_lexemes"]["dividend"], "8.082600e-1")
        self.assertEqual(action["amount_lexemes"]["short_term_capital_gain"], "0.00000")
        self.assertEqual(action["provenance"]["native_row"]["ordinaryIncomeDistribution"], "8.082600e-1")

    def test_all_rows_retained_even_outside_declared_span(self):
        parsed = self.parse(self.body([row(exDate="2003-12-24"), row(exDate="2023-12-18"), row(exDate="2026-12-28")]))
        self.assertEqual(parsed["rows_scanned"], 3)
        self.assertEqual([a["effective_date"] for a in parsed["actions"]], ["2003-12-24", "2023-12-18", "2026-12-28"])

    def test_duplicate_effective_rows_are_retained_and_visible_not_deduplicated(self):
        parsed = self.parse(self.body([row(), row()]))
        self.assertEqual(parsed["duplicate_effective_dates"], [{"effective_date": "2023-12-18", "row_indices": [0, 1]}])
        self.assertNotEqual(parsed["actions"][0]["source_action_id"], parsed["actions"][1]["source_action_id"])
        self.assertNotEqual(parsed["actions"][0]["provenance"]["value_pointer"], parsed["actions"][1]["provenance"]["value_pointer"])

    def test_empty_inventory_does_not_claim_coverage(self):
        result = self.parse(self.body([]))
        self.assertEqual(result["actions"], []); self.assertEqual(result["observed_action_types"], [])
        self.assertFalse(result["completeness_verified"])

    def test_status_characterizations_are_preserved_without_payment_inference(self):
        parsed = self.parse(self.body([row(exDate="2023-12-27", recordDate="2023-12-28", payDate="2024-01-15", distributionAmountPerUnit=0.21584, ordinaryIncomeDistribution=0)]))
        action = parsed["actions"][0]
        self.assertEqual(action["amount_lexemes"]["dividend"], "0.21584")
        self.assertEqual(action["provenance"]["native_row"]["ordinaryIncomeDistribution"], "0")
        self.assertEqual(action["status"], "LISTED_STATUS_UNSPECIFIED")

    def test_safety_and_scope_claims_remain_false(self):
        result = self.parse()
        for key in ("completeness_verified", "source_authentication_verified", "historical_point_in_time_verified", "auto_trading_enabled"):
            self.assertIs(result[key], False)
        self.assertEqual(result["authority"], AUTHORITY)
        self.assertEqual(result["source_scope"], "LISTED_INVESCO_QQQ_DISTRIBUTIONS_ONLY")

    def test_exact_original_source_bytes_and_manifest_roundtrip(self):
        raw = b' \n' + self.body() + b'\n'
        manifest, blobs = material(raw)
        typed = QQQDistributionInventory.from_mapping(manifest)
        self.assertEqual(QQQDistributionInventory.from_bytes(typed.to_bytes()).to_dict(), manifest)
        parsed = parse_qqq_distribution_inventory(typed, blobs)
        self.assertEqual(parsed["evidence"][manifest["body_evidence"]["path"]], raw)
        self.assertEqual(len(evidence_references(typed)), 3)

    def test_unknown_manifest_fields_and_source_profile_changes_reject(self):
        for key, value in (("unexpected", False), ("publisher", "OTHER"), ("source_url", URL + "&year=2023"), ("profile", "LATEST"), ("schema_version", "next")):
            manifest, _ = material(); manifest[key] = value
            with self.subTest(key=key), self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_manifest_cannot_claim_completeness_foreign_symbol_or_other_action_types(self):
        for key, value in (("completeness", "DECLARED_COMPLETE"), ("completeness", "PARTIAL"), ("symbols", ["QQQM"]), ("action_types", ["forward_splits"]), ("effective_end", "2000-01-01")):
            manifest, _ = material(); manifest["declared_coverage"][key] = value
            with self.subTest(key=key), self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_manifest_source_clocks_cannot_regress(self):
        manifest, _ = material(); manifest["recorded_at"] = "2026-10-14T01:00:00Z"
        with self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_authority_and_auto_flags_cannot_be_enabled(self):
        for key in AUTHORITY:
            manifest, _ = material(); manifest["authority"][key] = True
            with self.subTest(key=key), self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)
        manifest, _ = material(); manifest["auto_trading_enabled"] = True
        with self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_alias_conflicts_and_duplicate_source_leaves_reject(self):
        for key in ("receipt_evidence", "discovery_evidence"):
            manifest, _ = material(); manifest[key]["path"] = manifest["body_evidence"]["path"]
            with self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)
            manifest, _ = material(); manifest[key]["sha256"] = manifest["body_evidence"]["sha256"]
            with self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_missing_tampered_and_size_mismatched_leaves_reject(self):
        for key in ("body_evidence", "receipt_evidence", "discovery_evidence"):
            for damage in ("missing", "bytes", "size"):
                manifest, blobs = material(); digest = manifest[key]["sha256"]
                if damage == "missing": del blobs[digest]
                elif damage == "bytes": blobs[digest] = b'corrupt'
                else: manifest[key]["size_bytes"] += 1
                with self.subTest(key=key, damage=damage), self.assertRaises(ContractValidationError): parse_qqq_distribution_inventory(manifest, blobs)

    def test_manifest_byte_bounds_reject_before_parsing(self):
        for key, maximum in (("body_evidence", MAX_BODY_BYTES), ("discovery_evidence", MAX_DISCOVERY_BYTES), ("receipt_evidence", 16384)):
            manifest, _ = material(); manifest[key]["size_bytes"] = maximum + 1
            with self.subTest(key=key), self.assertRaises(ContractValidationError): QQQDistributionInventory.from_mapping(manifest)

    def test_http_and_capture_receipt_semantics_reject_false_source(self):
        changes = (("status", 403), ("status", "200"), ("method", "POST"), ("url", URL + "&latest=true"), ("body_sha256", "0" * 64),
            ("size_bytes", "1"), ("size_bytes", 1), ("credentials_used", True), ("redirects_followed", True), ("captured_at", "2026-10-14T02:05:09Z"), ("unknown", None))
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaises(ContractValidationError): self.parse(receipt_changes={key: value})

    def test_foreign_fund_currency_and_numeric_cusip_reject(self):
        for raw in (self.body(cusip="46090E202"), self.body(currencyCode="CAD"), self.body().replace(b'"46090E103"', b'46090E103')):
            with self.assertRaises(ContractValidationError): self.parse(raw)

    def test_root_and_row_unknown_or_missing_fields_reject(self):
        for value in ({"cusip": "46090E103", "currencyCode": "USD"}, {"cusip": "46090E103", "currencyCode": "USD", "distributions": [], "status": "approved"},
                {"cusip": "46090E103", "currencyCode": "USD", "distributions": [row(unexpected=None)]},
                {"cusip": "46090E103", "currencyCode": "USD", "distributions": [{key: value for key, value in row().items() if key != "payDate"}]}):
            with self.assertRaises(ContractValidationError): self.parse(canonical_json_bytes(value))

    def test_literal_calendar_dates_reject_ambiguous_unknown_or_impossible_dates(self):
        for value in ("12/18/2023", "2023-02-29", "2023-12-18T00:00:00Z", " 2023-12-18", None, 20231218):
            with self.subTest(value=value), self.assertRaises(ContractValidationError): self.parse(self.body([row(exDate=value)]))

    def test_amount_strings_bools_negative_oversized_and_missing_totals_reject(self):
        for value in ("0.80826", True, -0.1, 1e21, None):
            with self.subTest(value=value), self.assertRaises(ContractValidationError): self.parse(self.body([row(distributionAmountPerUnit=value)]))
        with self.assertRaises(ContractValidationError): self.parse(self.body([row(ordinaryIncomeDistribution="0.5")]))

    def test_duplicate_json_keys_at_root_and_row_reject(self):
        for raw in (self.body().replace(b'"cusip":', b'"cusip":"46090E103","cusip":'), self.body().replace(b'"exDate":', b'"exDate":"2023-12-18","exDate":')):
            with self.assertRaises(ContractValidationError): self.parse(raw)

    def test_nonfinite_unicode_and_malformed_json_reject(self):
        cases = [self.body().replace(b'0.80826', b'NaN', 1), self.body().replace(b'0.80826', b'Infinity', 1), b'\xff', b'[]', b'{', self.body().replace(b'"USD"', b'"\\ud800"')]
        for raw in cases:
            with self.subTest(raw=raw[:40]), self.assertRaises(ContractValidationError): self.parse(raw)

    def test_deep_json_is_rejected_before_decoder(self):
        raw = b'[' * 17 + b'0' + b']' * 17
        with self.assertRaises(ContractValidationError): self.parse(raw)

    def test_row_and_node_resource_limits(self):
        with patch("blackpod_build_week.qqq_distribution_inventory.MAX_ROWS", 1):
            with self.assertRaises(ContractValidationError): self.parse(self.body([row(), row()]))
        with self.assertRaises(ContractValidationError): self.parse(self.body(distributions=[[]] * 200001))

    def test_discovery_missing_foreign_or_duplicate_selected_component_reject(self):
        good = {"url": RESOURCE_TEMPLATE, "tableVariation": "distributions", "apiResponseKey": "distributions", "productMetaData": {"cusip": "46090E103", "locale": "en_US", "isin": "US46090E1038", "uniqueIdentifier": "cusip"}}
        cases = [b'<html>QQQ distribution</html>', discovery({**good, "tableVariation": "holdings"}), discovery({**good, "productMetaData": {**good["productMetaData"], "cusip": "OTHER"}}), discovery() + discovery()]
        selected_json = json.dumps(good).replace('"cusip":', '"cusip":"OTHER","cusip":')
        cases.append(('<div data-model="' + escape(selected_json, quote=True) + '"></div>').encode())
        for html in cases:
            with self.subTest(html=html[:60]), self.assertRaises(ContractValidationError): self.parse(discovery_raw=html)

    def test_discovery_unrelated_cms_duplicate_keys_never_hide_selected_ambiguity(self):
        selected = json.loads(unescape(discovery().decode().split('data-model="')[1].split('"')[0]))
        model = '{"unrelated":{"x":1,"x":2},"component":' + json.dumps(selected["root"]) + '}'
        html = ('<div data-model="' + escape(model, quote=True) + '"></div>').encode()
        self.assertEqual(self.parse(discovery_raw=html)["rows_scanned"], 1)

    def test_ambient_decimal_traps_do_not_round_or_mutate_lexemes(self):
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True; context.traps[InvalidOperation] = True
            parsed = self.parse()
        self.assertEqual(parsed["actions"][0]["amount_lexemes"]["dividend"], "0.80826")

    def test_actual_retained_primary_source_if_available(self):
        base = Path(__file__).resolve().parents[1] / "output/reconciled-action-intake-real-001/source"
        paths = [base / "invesco-qqq-distributions.json", base / "invesco-qqq-distributions.receipt.json", base / "invesco-qqq-product.html"]
        if not all(path.is_file() for path in paths): self.skipTest("local retained issuer source is not committed")
        raw, receipt, html = (path.read_bytes() for path in paths)
        self.assertEqual(sha256_bytes(raw), "8cac48440d684d73a51016d1b98323b2ffd85a378bd82f987c43c807f0ae1aa2")
        manifest, blobs = material(raw, discovery_raw=html, scope="RETAINED_HISTORY_RESEARCH")
        manifest["receipt_evidence"] = ref("qqq/actual.receipt.json", receipt); blobs[sha256_bytes(receipt)] = receipt
        result = parse_qqq_distribution_inventory(manifest, blobs)
        self.assertEqual(result["rows_scanned"], 89)
        self.assertEqual(result["actions"][0]["effective_date"], "2026-09-21")
        self.assertEqual(result["actions"][-1]["effective_date"], "2003-12-24")
        self.assertEqual(sum("2023-10-02" <= row["effective_date"] <= "2026-10-12" for row in result["actions"]), 13)
        december = [row for row in result["actions"] if row["effective_date"].startswith("2023-12")]
        self.assertEqual([row["effective_date"] for row in december], ["2023-12-27", "2023-12-18"])
        self.assertEqual([row["amount_lexemes"]["dividend"] for row in december], ["0.21584", "0.80826"])
        self.assertEqual(result["evidence"]["qqq/distributions.json"], raw)
        self.assertFalse(result["completeness_verified"])


if __name__ == "__main__":
    unittest.main()
