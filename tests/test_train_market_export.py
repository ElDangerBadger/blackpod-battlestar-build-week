"""Offline segmented TRAIN exports preserve full native chains and old research."""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Inexact, Rounded, localcontext
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import format_rfc3339, parse_rfc3339
from blackpod_build_week.contracts.train_market_evidence import TrainMarketCapturePlan
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.train_market_export import aggregate_training_segments, project_training_segment
from blackpod_build_week.trading_shadow_review_example import fixture_material


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


class TrainingExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture_material()
        cls.base = cls.original["base_studies"][0]
        cls.plan = prepare_capture_plan(cls.original["events"], cls.original["blobs"], capture_id="fixture-segmented-training",
            created_at="2025-04-03T00:00:00Z", base_plan_event_id=cls.base["plan_event"].event_id)

    def setUp(self):
        self.blobs = dict(self.original["blobs"])
        self.dataset = self.original["dataset"]
        self.segment = self.plan.segments[0]
        self.exported_at = "2025-04-04T00:00:00Z"
        for target in ("socket.socket", "subprocess.run"):
            mocked = patch(target, side_effect=AssertionError("network and producers forbidden"))
            mocked.start()
            self.addCleanup(mocked.stop)

    def row(self, segment=None, *, fraction="000000001", **changes):
        segment = segment or self.segment
        clock = parse_rfc3339(segment["query"]["start"], "returned open") + timedelta(seconds=1)
        stamp = format_rfc3339(clock).removesuffix("Z") + "." + fraction + "Z"
        return {"t": stamp, "bp": 100, "ap": 101, "bs": 10, "as": 20, "bx": "V", "ax": "V", "c": ["R"], "z": "C", **changes}

    def page(self, segment=None, *, quotes=None, token=None, request_token=None, status=200, captured_at=None, query_changes=None, label="first"):
        segment = segment or self.segment
        quotes = quotes if quotes is not None else {symbol: [self.row(segment)] for symbol in self.dataset.universe}
        raw = canonical_json_bytes({"quotes": quotes, "next_page_token": token})
        prefix = "segmented-fixture/" + segment["segment_id"] + "/" + label
        body = ref(prefix + ".raw", raw)
        query = copy.deepcopy(segment["query"])
        if query_changes:
            query.update(query_changes)
        if request_token is not None:
            query["page_token"] = request_token
        receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
            "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": query,
            "captured_at": captured_at or "2025-04-03T01:00:00Z", "status": status,
            "body_sha256": body["sha256"], "size_bytes": body["size_bytes"]}
        receipt_raw = canonical_json_bytes(receipt)
        receipt_ref = ref(prefix + ".receipt.json", receipt_raw)
        self.blobs[body["sha256"]], self.blobs[receipt_ref["sha256"]] = raw, receipt_raw
        return {"body_evidence": body, "receipt_evidence": receipt_ref}

    def project(self, pages=None, *, segment=None, plan=None, failure=None, exported_at=None):
        return project_training_segment(plan or self.plan, segment or self.segment,
            [self.page(segment)] if pages is None else pages, self.blobs,
            exported_at=exported_at or self.exported_at, failure=failure)

    def aggregate(self, summaries, *, plan=None):
        return aggregate_training_segments(plan or self.plan, self.base["plan"], self.dataset, summaries)

    def all_summaries(self):
        return [self.project([self.page(segment)], segment=segment)["summary"] for segment in self.plan.segments]

    def test_one_complete_native_segment_retains_exact_body_and_receipt(self):
        page = self.page()
        projected = self.project([page])
        result = projected["summary"]
        self.assertEqual(result["status"], "CAPTURE_COMPLETE")
        self.assertTrue(result["capture_complete"])
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["raw_quote_count"], len(self.dataset.universe))
        self.assertEqual(result["retained_source_bytes"], sum(ref["size_bytes"] for ref in page.values()))
        for reference in page.values():
            self.assertEqual(projected["evidence"][reference["path"]], self.blobs[reference["sha256"]])

    def test_all_planned_sessions_capture_complete_without_sampling(self):
        result = self.aggregate(self.all_summaries())
        self.assertEqual(result["status"], "CAPTURE_COMPLETE")
        self.assertTrue(result["capture_complete"])
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["counts"]["planned_segments"], len(self.plan.segments))
        self.assertEqual(result["counts"]["covered_symbol_sessions"], len(self.plan.segments) * len(self.dataset.universe))
        self.assertEqual(result["counts"]["missing_symbol_sessions"], 0)
        self.assertIsNotNone(result["folds"][0]["training_spread_profile"])

    def test_missing_segments_retain_every_original_symbol_session_gap(self):
        result = self.aggregate([])
        self.assertEqual(result["status"], "CAPTURE_INCOMPLETE")
        self.assertFalse(result["capture_complete"])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["counts"]["missing_segments"], len(self.plan.segments))
        self.assertEqual(result["counts"]["missing_symbol_sessions"], len(self.plan.segments) * len(self.dataset.universe))
        self.assertEqual(len(result["segments"]), len(self.plan.segments))
        self.assertIsNone(result["folds"][0]["training_spread_profile"])

    def test_partial_plan_capture_never_extrapolates_full_train_profile(self):
        summary = self.project()["summary"]
        result = self.aggregate([summary])
        self.assertFalse(result["capture_complete"])
        self.assertEqual(result["counts"]["provided_segments"], 1)
        self.assertEqual(result["counts"]["missing_segments"], len(self.plan.segments) - 1)
        self.assertIsNone(result["folds"][0]["training_spread_profile"])

    def test_empty_pages_are_not_started_not_an_invented_empty_complete_response(self):
        summary = self.project([])["summary"]
        self.assertFalse(summary["capture_complete"])
        self.assertFalse(summary["coverage_complete"])
        self.assertIn("SEGMENT_NOT_STARTED", summary["reason_codes"])
        self.assertEqual(summary["missing_symbols"], self.dataset.universe)
        self.assertTrue(all(row["max_spread_bps"] is None for row in summary["symbols"]))

    def test_terminal_empty_response_capture_complete_but_coverage_incomplete(self):
        summary = self.project([self.page(quotes={})])["summary"]
        self.assertTrue(summary["capture_complete"])
        self.assertFalse(summary["coverage_complete"])
        self.assertEqual(summary["missing_symbols"], self.dataset.universe)

    def test_unavailable_http_body_retained_without_native_quote_invention(self):
        page = self.page(status=403)
        projected = self.project([page])
        self.assertFalse(projected["summary"]["capture_complete"])
        self.assertEqual(projected["summary"]["raw_quote_count"], 0)
        self.assertIn("TRAINING_QUOTE_RESPONSE_UNAVAILABLE", projected["summary"]["reason_codes"])
        self.assertEqual(projected["evidence"][page["body_evidence"]["path"]], self.blobs[page["body_evidence"]["sha256"]])

    def test_pending_token_does_not_become_complete_when_both_symbols_present(self):
        summary = self.project([self.page(token="next")])["summary"]
        self.assertFalse(summary["capture_complete"])
        self.assertFalse(summary["coverage_complete"])
        self.assertEqual(summary["missing_symbols"], [])
        self.assertIn("TRAINING_QUOTE_PAGINATION_INCOMPLETE", summary["reason_codes"])

    def test_valid_pagination_keeps_every_row_and_forward_token(self):
        first = self.page(quotes={self.dataset.universe[0]: [self.row()]}, token="next")
        second = self.page(quotes={self.dataset.universe[1]: [self.row(fraction="000000002")]}, request_token="next", label="second")
        summary = self.project([first, second])["summary"]
        self.assertTrue(summary["capture_complete"])
        self.assertEqual(summary["page_count"], 2)
        self.assertEqual(summary["raw_quote_count"], 2)
        self.assertEqual(summary["pages"], [first, second])

    def test_distinct_same_nanosecond_updates_retained_across_page_boundary(self):
        symbol = self.dataset.universe[0]
        first = self.page(quotes={symbol: [self.row()]}, token="next")
        second = self.page(quotes={symbol: [self.row(ap=102)], self.dataset.universe[1]: [self.row()]}, request_token="next", label="second")
        summary = self.project([first, second])["summary"]
        self.assertEqual(summary["raw_quote_count"], 3)
        self.assertEqual(summary["symbols"][0]["eligible_quote_count"], 2)

    def test_identical_duplicate_update_rejected_across_page_boundary(self):
        first = self.page(quotes={self.dataset.universe[0]: [self.row()]}, token="next")
        second = self.page(quotes={self.dataset.universe[0]: [self.row()]}, request_token="next", label="second")
        with self.assertRaises(ValueError):
            self.project([first, second])

    def test_cycle_or_broken_forward_token_rejected(self):
        first = self.page(quotes={self.dataset.universe[0]: [self.row()]}, token="next")
        second = self.page(quotes={self.dataset.universe[1]: [self.row()]}, request_token="wrong", label="second")
        with self.assertRaises(ValueError):
            self.project([first, second])

    def test_new_session_starts_independent_pagination_without_legacy_query_relabel(self):
        summaries = [self.project([self.page(segment)], segment=segment)["summary"] for segment in self.plan.segments[:2]]
        result = self.aggregate(summaries)
        self.assertEqual(result["counts"]["capture_complete_segments"], 2)
        self.assertEqual(result["consumer_v18"], "INCOMPATIBLE_SEGMENTED_INPUT")
        self.assertNotEqual(summaries[0]["query"], summaries[1]["query"])

    def test_unfinished_chain_symbol_counts_not_used_as_aggregate_coverage(self):
        summaries = self.all_summaries()
        summaries[0] = self.project([self.page(token="next")])["summary"]
        result = self.aggregate(summaries)
        self.assertFalse(result["capture_complete"])
        self.assertEqual(result["counts"]["missing_symbol_sessions"], len(self.dataset.universe))
        self.assertIsNone(result["folds"][0]["training_spread_profile"])

    def test_spread_extreme_and_minimum_native_size_retained_without_clipping(self):
        summaries = self.all_summaries()
        segment = self.plan.segments[-1]
        quotes = {symbol: [self.row(segment, bp=1, ap=100, bs=1)] for symbol in self.dataset.universe}
        summaries[-1] = self.project([self.page(segment, quotes=quotes)], segment=segment)["summary"]
        result = self.aggregate(summaries)
        for symbol in result["folds"][0]["training_spread_profile"]:
            self.assertGreater(float(symbol["max_spread_bps"]), 1000)
            self.assertEqual(symbol["min_reported_side_size_native_units"], "1")

    def test_spread_rounds_up_eighteen_places_and_preserves_native_timestamps(self):
        summary = self.project()["summary"]
        self.assertEqual(summary["symbols"][0]["max_spread_bps"], "99.502487562189054727")
        self.assertTrue(summary["symbols"][0]["first_native_timestamp"].endswith(".000000001Z"))

    def test_rejected_conditions_crossed_quotes_and_zero_sizes_retained(self):
        rows = [self.row(fraction="000000001", c=["Y"]), self.row(fraction="000000002", bp=102, ap=101), self.row(fraction="000000003", bs=0)]
        summary = self.project([self.page(quotes={symbol: rows for symbol in self.dataset.universe})])["summary"]
        self.assertTrue(summary["capture_complete"])
        self.assertFalse(summary["coverage_complete"])
        self.assertEqual(summary["raw_quote_count"], 6)
        self.assertEqual(summary["eligible_quote_count"], 0)
        self.assertTrue(all(row["rejected_quote_count"] == 3 for row in summary["symbols"]))

    def test_declared_failure_kept_and_never_promotes_partial_capture(self):
        failure = {"code": "REQUEST_BUDGET_EXHAUSTED", "http_status": None}
        summary = self.project([self.page(token="next")], failure=failure)["summary"]
        self.assertEqual(summary["failure"], failure)
        self.assertFalse(summary["capture_complete"])
        self.assertIn("DECLARED_CAPTURE_FAILURE", summary["reason_codes"])

    def test_failed_attempt_without_response_does_not_claim_not_started(self):
        failure = {"code": "NETWORK_TIMEOUT", "http_status": None}
        summary = self.project([], failure=failure)["summary"]
        self.assertIn("NO_RETAINED_CAPTURE_RESPONSE", summary["reason_codes"])
        self.assertNotIn("SEGMENT_NOT_STARTED", summary["reason_codes"])
        self.assertFalse(summary["capture_complete"])

    def test_capture_receipts_must_follow_plan_freeze(self):
        with self.assertRaises(ValueError):
            self.project([self.page(captured_at="2025-04-02T00:00:00Z")])

    def test_page_capture_clocks_cannot_go_backwards(self):
        first = self.page(quotes={self.dataset.universe[0]: [self.row()]}, token="next", captured_at="2025-04-03T02:00:00Z")
        second = self.page(quotes={self.dataset.universe[1]: [self.row()]}, request_token="next", captured_at="2025-04-03T01:00:00Z", label="second")
        with self.assertRaises(ValueError):
            self.project([first, second])

    def test_page_after_export_clock_rejected(self):
        with self.assertRaises(ValueError):
            self.project([self.page(captured_at="2025-04-05T00:00:00Z")])

    def test_changed_body_hash_rejected(self):
        page = self.page()
        self.blobs[page["body_evidence"]["sha256"]] = b"{}"
        with self.assertRaises(ValueError):
            self.project([page])

    def test_exact_frozen_query_required_even_other_train_session(self):
        next_segment = self.plan.segments[1]
        with self.assertRaises(ValueError):
            self.project([self.page(query_changes={"start": next_segment["query"]["start"], "end": next_segment["query"]["end"]})])

    def test_outside_query_row_rejected_not_silently_removed(self):
        stamp = format_rfc3339(parse_rfc3339(self.segment["query"]["end"], "end") + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            self.project([self.page(quotes={self.dataset.universe[0]: [self.row(t=stamp)]})])

    def test_unknown_symbol_rejected_not_ignored(self):
        with self.assertRaises(ValueError):
            self.project([self.page(quotes={"UNKNOWN": [self.row()]})])

    def test_segment_identity_or_window_changed_rejected(self):
        value = copy.deepcopy(self.segment)
        value["session_index"] += 1
        with self.assertRaises(ValueError):
            self.project(segment=value)

    def test_subsampled_capture_plan_cannot_claim_full_train(self):
        value = self.plan.to_dict()
        value["segments"] = value["segments"][:1]
        with self.assertRaises(ValueError):
            self.project(plan=TrainMarketCapturePlan.from_mapping(value))

    def test_holdout_target_plan_rejected_before_consuming_native_pages(self):
        value = self.plan.to_dict()
        target = self.base["plan"].protocol["final_holdout"]["start_index"]
        value["segments"][0]["session_index"] = target
        value["segments"][0]["session_id"] = self.dataset.sessions[target]["session_id"]
        with self.assertRaises(ValueError):
            self.project(plan=TrainMarketCapturePlan.from_mapping(value))

    def limited_plan(self, **limits):
        value = self.plan.to_dict()
        value["limits"].update(limits)
        return TrainMarketCapturePlan.from_mapping(value)

    def test_segment_frozen_response_byte_limit_not_only_native_legacy_cap(self):
        with self.assertRaises(ValueError):
            self.project(plan=self.limited_plan(max_response_bytes=1))

    def test_segment_frozen_row_limit_not_only_native_legacy_cap(self):
        with self.assertRaises(ValueError):
            self.project(plan=self.limited_plan(max_rows_per_segment=1))

    def test_segment_frozen_page_and_combined_source_byte_limits(self):
        first = self.page(quotes={self.dataset.universe[0]: [self.row()]}, token="next")
        second = self.page(quotes={self.dataset.universe[1]: [self.row()]}, request_token="next", label="second")
        with self.assertRaises(ValueError):
            self.project([first, second], plan=self.limited_plan(max_pages_per_segment=1))
        body_size = first["body_evidence"]["size_bytes"]
        with self.assertRaises(ValueError):
            self.project([first], plan=self.limited_plan(max_response_bytes=body_size, max_segment_bytes=body_size))

    def test_aggregate_lifetime_request_limit_checked(self):
        summaries = self.all_summaries()
        plan = self.limited_plan(max_total_requests=1, max_requests_per_invocation=1)
        with self.assertRaises(ValueError):
            self.aggregate(summaries, plan=plan)

    def test_aggregate_lifetime_bytes_not_only_individual_segment_cap(self):
        summaries = self.all_summaries()
        single_max = max(summary["retained_source_bytes"] for summary in summaries)
        body_max = max(page["body_evidence"]["size_bytes"] for summary in summaries for page in summary["pages"])
        plan = self.limited_plan(max_response_bytes=body_max, max_segment_bytes=single_max, max_capture_bytes=single_max + 1)
        with self.assertRaises(ValueError):
            self.aggregate(summaries, plan=plan)

    def test_duplicate_summary_or_wrong_capture_plan_rejected(self):
        summary = self.project()["summary"]
        with self.assertRaises(ValueError):
            self.aggregate([summary, summary])
        altered = copy.deepcopy(summary)
        altered["capture_id"] = "other-capture"
        with self.assertRaises(ValueError):
            self.aggregate([altered])

    def test_forged_coverage_cannot_hide_missing_symbol(self):
        summary = self.project([self.page(quotes={self.dataset.universe[0]: [self.row()]})])["summary"]
        summary["coverage_complete"] = True
        with self.assertRaises(ValueError):
            self.aggregate([summary])

    def test_mismatched_symbol_counts_or_page_bytes_rejected(self):
        summary = self.project()["summary"]
        for field in ("raw_quote_count", "page_count", "retained_source_bytes"):
            altered = copy.deepcopy(summary)
            altered[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.aggregate([altered])

    def test_malformed_or_impossible_native_extrema_fail_closed(self):
        summary = self.project()["summary"]
        for field, value in (("max_spread_bps", "NaN"), ("max_spread_bps", "broken"),
                             ("min_reported_side_size_native_units", "0"), ("min_reported_side_size_native_units", "0.5")):
            altered = copy.deepcopy(summary)
            altered["symbols"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.aggregate([altered])

    def test_aggregate_source_profiles_never_supply_pnl_fees_or_authority(self):
        result = self.aggregate(self.all_summaries())
        for field in ("auto_trading_enabled", "economic_hypothesis_supported", "uncertainty_computed", "existing_gate_override", "source_authentication_verified", "historical_point_in_time_verified", "slippage_estimated", "fees_estimated", "opening_execution_capacity_verified"):
            self.assertIs(result[field], False)
        self.assertTrue(all(value is False for value in result["authority"].values()))
        self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertEqual(result["consumer_v18"], "INCOMPATIBLE_SEGMENTED_INPUT")
        self.assertNotIn("simulated_pnl", result)
        self.assertNotIn("cost_model", result)

    def test_pure_repeatable_preserves_old_inputs_and_native_bytes(self):
        pages = [self.page()]
        before = (self.plan.to_bytes(), self.base["plan"].to_bytes(), self.dataset.to_bytes(), dict(self.blobs))
        first, second = self.project(pages), self.project(pages)
        self.assertEqual(first, second)
        self.assertEqual(before, (self.plan.to_bytes(), self.base["plan"].to_bytes(), self.dataset.to_bytes(), dict(self.blobs)))

    def test_decimal_context_does_not_change_segment_or_aggregate_bounds(self):
        summaries = self.all_summaries()
        before = self.aggregate(summaries)
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(self.project()["summary"]["symbols"][0]["max_spread_bps"], summaries[0]["symbols"][0]["max_spread_bps"])
            self.assertEqual(self.aggregate(summaries), before)


if __name__ == "__main__":
    unittest.main()
