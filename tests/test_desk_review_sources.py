"""Offline checks that research projections retain exact raw source bindings."""
from copy import deepcopy
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.desk_review_sources import validate_market_packet, validate_issuer_packet
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_desk_candidate_review_engine import DeskReviewFixture


class SourceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.f = DeskReviewFixture()
    @classmethod
    def tearDownClass(cls): cls.f.close()
    def setUp(self): self.blobs = dict(self.f.blobs)

    def reference(self, path, value):
        raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
        digest = sha256_bytes(raw)
        self.blobs[digest] = raw
        return {"path": path, "sha256": digest, "size_bytes": len(raw)}


class MarketBindingTests(SourceFixtureTests):
    def setUp(self):
        super().setUp()
        self.packet = deepcopy(self.f.market)

    def validate(self): return validate_market_packet(self.packet, self.blobs)

    def test_raw_maps_reproduce_every_normalized_snapshot_and_bar(self):
        self.assertEqual(self.validate(), self.packet)

    def test_wrapped_snapshot_response_is_also_bound(self):
        self.packet["source_evidence"][0] = self.reference("wrapped-snapshots.json", {"snapshots": self.packet["snapshots"]})
        self.validate()

    def test_changed_normalized_quote_or_bar_fails(self):
        for field in ("snapshots", "bars"):
            with self.subTest(field=field):
                self.packet = deepcopy(self.f.market)
                if field == "snapshots": self.packet[field]["SPY"]["latestTrade"]["p"] = 1
                else: self.packet[field]["SPY"][0]["c"] = 1
                with self.assertRaisesRegex(ValueError, "retained provider maps"): self.validate()

    def test_missing_changed_or_wrong_size_retained_source_fails(self):
        for change in ("missing", "bytes", "size"):
            with self.subTest(change=change):
                self.packet, self.blobs = deepcopy(self.f.market), dict(self.f.blobs)
                reference = self.packet["source_evidence"][0]
                if change == "missing": self.blobs.pop(reference["sha256"])
                elif change == "bytes": self.blobs[reference["sha256"]] += b" "
                else: reference["size_bytes"] += 1
                with self.assertRaises(ValueError): self.validate()

    def test_missing_empty_or_duplicate_source_paths_fail(self):
        for refs in ([], None, [self.f.market["source_evidence"][0]] * 2):
            self.packet["source_evidence"] = deepcopy(refs)
            with self.assertRaises(ValueError): self.validate()

    def test_ambiguous_multiple_snapshot_or_bar_sources_fail(self):
        for payload in ({"snapshots": self.packet["snapshots"]}, {"bars": self.packet["bars"], "next_page_token": None}):
            self.packet = deepcopy(self.f.market)
            self.packet["source_evidence"].append(self.reference("duplicate-source.json", payload))
            with self.assertRaises(ValueError): self.validate()

    def test_open_pagination_cannot_be_claimed_complete(self):
        self.packet["source_evidence"][1] = self.reference("partial-bars.json", {"bars": self.packet["bars"], "next_page_token": "page-two"})
        with self.assertRaisesRegex(ValueError, "continuation token"): self.validate()

    def test_changed_universe_or_invalid_symbol_fails(self):
        self.packet["bars"].pop("SPY")
        with self.assertRaises(ValueError): self.validate()
        self.packet = deepcopy(self.f.market)
        self.packet["snapshots"]["../../secret"] = self.packet["snapshots"].pop("SPY")
        self.packet["bars"]["../../secret"] = self.packet["bars"].pop("SPY")
        with self.assertRaises(ValueError): self.validate()

    def test_unknown_fields_or_feed_adjustment_versions_fail(self):
        for field, value in (("new", True), ("feed", "SIP"), ("adjustment", "ALL"), ("schema_version", "v999")):
            self.packet = deepcopy(self.f.market)
            self.packet[field] = value
            with self.assertRaises(ValueError): self.validate()

    def test_array_or_duplicate_json_key_cannot_hide_raw_source(self):
        for raw in (b"[]", b'{"snapshots":{},"snapshots":{}}'):
            self.packet = deepcopy(self.f.market)
            self.packet["source_evidence"][0] = self.reference("malformed-snapshots.json", raw)
            with self.assertRaises(ValueError): self.validate()

    def test_source_roles_cannot_be_substituted_with_unrelated_object(self):
        self.packet["source_evidence"][0] = self.reference("unrelated.json", {"predicted_return": 50})
        with self.assertRaises(ValueError): self.validate()

    def test_bounded_history_and_symbol_count_required(self):
        self.packet["bars"]["SPY"] = [self.packet["bars"]["SPY"][0]] * 10001
        with self.assertRaises(ValueError): self.validate()

    def test_binding_does_not_rewrite_input_or_call_provider(self):
        before = deepcopy(self.packet)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")):
            self.validate()
        self.assertEqual(self.packet, before)


class IssuerBindingTests(SourceFixtureTests):
    def setUp(self):
        super().setUp()
        self.packet = deepcopy(self.f.issuer)

    def validate(self): return validate_issuer_packet(self.packet, self.blobs)

    def replace_source(self, **changes):
        fact = self.packet["facts"][0]
        source = {"schema_version": "blackpod.public_issuer_source.v1", "source_url": fact["source_url"],
            "retrieved_at": self.packet["captured_at"], "content": fact["source_excerpt"]}
        source.update(changes)
        reference = self.reference("replacement-issuer.json", source)
        old = fact["source_evidence"]
        self.packet["source_evidence"] = [reference if ref == old else ref for ref in self.packet["source_evidence"]]
        fact["source_evidence"] = reference

    def test_exact_primary_source_excerpt_and_timestamp_bound(self):
        self.assertEqual(self.validate(), self.packet)

    def test_declared_mandate_does_not_become_provider_attestation(self):
        self.packet["facts"][0]["mandate"] = "An explicitly declared reviewed interpretation"
        self.validate()
        self.assertNotIn("provider_verified", self.packet)

    def test_changed_excerpt_or_missing_text_fails(self):
        self.packet["facts"][0]["source_excerpt"] = "An invented issuer quotation"
        with self.assertRaises(ValueError): self.validate()
        self.packet = deepcopy(self.f.issuer)
        self.replace_source(content=123)
        with self.assertRaises(ValueError): self.validate()

    def test_url_identity_schema_and_source_time_must_match(self):
        for changes in ({"source_url": "https://www.ssga.com/other"}, {"schema_version": "other"},
                        {"retrieved_at": "2026-10-16T00:00:00Z"}):
            self.packet = deepcopy(self.f.issuer)
            self.replace_source(**changes)
            with self.assertRaises(ValueError): self.validate()

    def test_primary_https_origin_required_without_embedded_credentials(self):
        for url in ("http://www.ssga.com/fund", "https://issuer.invalid/fund", "https://user:password@www.ssga.com/fund",
                    "https://www.ssga.com:444/fund", "https://www.ssga.com.evil.invalid/fund"):
            self.packet = deepcopy(self.f.issuer)
            self.packet["facts"][0]["source_url"] = url
            with self.assertRaises(ValueError): self.validate()

    def test_future_invalid_or_unspecified_factual_date_fails(self):
        for stamp in ("2026-10-16", "2026-02-31", None, "yesterday"):
            self.packet = deepcopy(self.f.issuer)
            self.packet["facts"][0]["as_of"] = stamp
            with self.assertRaises(ValueError): self.validate()

    def test_fact_source_must_be_retained_by_same_packet(self):
        self.packet["facts"][0]["source_evidence"] = self.reference("unbound-issuer.json", {"content": "unbound"})
        with self.assertRaises(ValueError): self.validate()

    def test_unknown_exposure_structure_or_implicit_action_flag_fails(self):
        for field, value in (("asset_class", "OPTIONS"), ("structure", "UNKNOWN"), ("corporate_action_before_horizon", "false")):
            self.packet = deepcopy(self.f.issuer)
            self.packet["facts"][0][field] = value
            with self.assertRaises(ValueError): self.validate()

    def test_empty_duplicate_or_unknown_fact_fields_fail(self):
        for change in ("empty", "duplicate", "extra"):
            self.packet = deepcopy(self.f.issuer)
            if change == "empty": self.packet["facts"] = []
            elif change == "duplicate": self.packet["facts"].append(deepcopy(self.packet["facts"][0]))
            else: self.packet["facts"][0]["recommended_allocation"] = 1
            with self.assertRaises(ValueError): self.validate()

    def test_invalid_source_hash_or_duplicate_paths_fail(self):
        self.packet["source_evidence"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError): self.validate()
        self.packet = deepcopy(self.f.issuer)
        self.packet["source_evidence"].append(self.packet["source_evidence"][0])
        with self.assertRaises(ValueError): self.validate()

    def test_source_validation_uses_no_network_and_keeps_original_content(self):
        before = deepcopy(self.packet)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")):
            self.validate()
        self.assertEqual(self.packet, before)


if __name__ == "__main__": unittest.main()
