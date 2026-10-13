"""Deterministic pre-signal boundary masks; no prices or hypotheses repaired."""
from __future__ import annotations

import copy
from datetime import timedelta
from decimal import Inexact, Rounded, localcontext
import json
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_continuity_intake import ContinuityCoverageReview
from blackpod_build_week.contracts.mission_request import parse_rfc3339, format_rfc3339
from blackpod_build_week.contracts.trading_research import TradingResearchDataset
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_continuity_intake import build_continuity_intake, verify_continuity_intake
from blackpod_build_week.trading_continuity_qualification import POLICY, qualify_continuity_windows
from blackpod_build_week.trading_shadow_review_example import fixture_material


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def native_intake(original, actions=(), *, coverage=True, complete=True):
    """New authored action scenario against unchanged original raw prices."""
    old = original["continuity"]
    request = old["request"].to_dict()
    request["run_id"] = "new-qualification-action-scenario"
    evidence = dict(original["evidence"])
    groups = {}
    for number, (group, session_index, symbol) in enumerate(actions, 1):
        common = {"id": "00000000-0000-0000-0000-%012d" % number,
                  "process_date": original["dataset"].sessions[0]["open_at"][:10],
                  "symbol": symbol, "cusip": "000000001"}
        effective = session_index if isinstance(session_index, str) else (None if session_index is None else original["dataset"].sessions[session_index]["open_at"][:10])
        if group == "cash_dividends":
            common.update(rate=0.5, special=False, foreign=False,
                          ex_date=effective)
        elif group == "forward_splits":
            common.update(new_rate=2, old_rate=1,
                          ex_date=effective)
        elif group == "worthless_removals":
            pass
        else:
            raise ValueError("unsupported authored test scenario")
        groups.setdefault(group, []).append(common)
    raw = canonical_json_bytes({"corporate_actions": groups, "next_page_token": None if complete else "missing-next-page"})
    body_ref = ref("qualification-fixture/actions.raw", raw)
    receipt = json.loads(evidence[request["pages"][0]["capture_receipt_evidence"]["path"]])
    receipt.update(body_sha256=body_ref["sha256"], size_bytes=body_ref["size_bytes"])
    receipt_raw = canonical_json_bytes(receipt)
    receipt_ref = ref("qualification-fixture/actions-receipt.json", receipt_raw)
    evidence[body_ref["path"]], evidence[receipt_ref["path"]] = raw, receipt_raw
    request["pages"] = [{"response_evidence": body_ref, "capture_receipt_evidence": receipt_ref}]
    if coverage:
        # This new independent authored scenario declares its own complete
        # action inventory. The original no-action support is never rewritten
        # or reused as evidence that these newly authored actions did not exist.
        origin = canonical_json_bytes({"scope": "AUTHORED_FIXTURE_ONLY", "native_actions": groups,
            "statement": "All effective dates and action groups of this explicitly constructed fixture scenario are listed; no real-security coverage is claimed."})
        origin_ref = ref("qualification-fixture/independent-coverage.raw", origin)
        evidence[origin_ref["path"]] = origin
        coverage_value = original["coverage_review"].to_dict()
        coverage_value.update(review_id="new-qualification-fixture-coverage", source_evidence=[origin_ref],
            review_notes="Complete authored action-scenario inventory only; no real provider independence or completeness claim.")
        review_raw = ContinuityCoverageReview.from_mapping(coverage_value).to_bytes()
        review_ref = ref("qualification-fixture/coverage-review.json", review_raw)
        evidence[review_ref["path"]] = review_raw
        request.update(coverage_basis="REVIEWED_EX_DATE_COVERAGE", coverage_review_evidence=review_ref)
    else:
        request.update(coverage_basis="EX_DATE_COVERAGE_UNVERIFIED", coverage_review_evidence=None)
    blobs = {sha256_bytes(value): value for value in evidence.values()}
    material = build_continuity_intake(request, blobs)
    combined = {**blobs, **material["blobs"]}
    return verify_continuity_intake(material["export"], combined)


class ContinuityQualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = fixture_material()

    def setUp(self):
        self.base = next(row for row in self.original["base_studies"] if row["hypothesis"].signal["lookback_sessions"] == 5)
        self.plan = self.base["plan"]
        self.dataset = self.original["dataset"]
        self.hypothesis = self.base["hypothesis"]
        self.policy = {"continuity_policy": POLICY, "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
                       "recorded_at": "2025-04-02T14:00:00Z", "continuity_event_id": None}
        self.patches = [patch("socket.socket", side_effect=AssertionError("network forbidden")),
                        patch("subprocess.run", side_effect=AssertionError("producer process forbidden"))]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def qualify(self, material="original", **overrides):
        if material == "original":
            material = self.original["continuity"]
        return qualify_continuity_windows(overrides.get("policy", self.policy), overrides.get("plan", self.plan),
            overrides.get("dataset", self.dataset), overrides.get("hypothesis", self.hypothesis), material)

    def row(self, result, source_index=None, symbol=None):
        source_index = source_index if source_index is not None else self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        symbol = symbol or self.plan.universe[0]
        return next(row for row in result["opportunities"] if row["source_session_index"] == source_index and row["symbol"] == symbol)

    def test_original_no_action_fixture_enumerates_every_test_opportunity(self):
        result = self.qualify()
        expected = sum(fold["test"]["end_index"] - fold["test"]["start_index"] + 1 for fold in self.plan.protocol["folds"]) * len(self.plan.universe)
        self.assertEqual(result["counts"]["opportunities"], expected)
        self.assertEqual(len(result["opportunities"]), expected)
        self.assertTrue(result["coverage_supported"])
        self.assertEqual(result["native_continuity_review_status"], "CONTINUITY_SUPPORTED")
        self.assertEqual(result["status"], "ELIGIBLE_WINDOWS_ONLY")

    def test_terminal_rows_defer_original_exit_outside_test(self):
        result = self.qualify()
        last = self.plan.protocol["folds"][0]["test"]["end_index"] - 1
        row = self.row(result, last)
        self.assertFalse(row["combined_eligible"])
        self.assertIn("DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST", row["reason_codes"])
        self.assertEqual(result["counts"]["deferred"], self.hypothesis.horizon["holding_sessions"] * len(self.plan.universe))

    def test_one_session_hypothesis_uses_original_lookback_and_horizon(self):
        base = next(row for row in self.original["base_studies"] if row["hypothesis"].signal["lookback_sessions"] == 1)
        self.plan, self.hypothesis = base["plan"], base["hypothesis"]
        row = self.row(self.qualify())
        self.assertEqual(row["source_session_index"] - row["feature_start_index"], 1)
        self.assertEqual(row["exit_session_index"] - row["entry_session_index"], 1)

    def test_five_session_hypothesis_uses_original_lookback_and_horizon(self):
        row = self.row(self.qualify())
        self.assertEqual(row["source_session_index"] - row["feature_start_index"], 5)
        self.assertEqual(row["exit_session_index"] - row["entry_session_index"], 3)

    def test_missing_continuity_defer_every_row_and_preserve_calendar_indices(self):
        result = self.qualify(None)
        self.assertEqual(result["status"], "DEFER")
        self.assertEqual(result["counts"]["combined_eligible"], 0)
        self.assertFalse(result["coverage_supported"])
        self.assertEqual(result["reason_codes"], ["CONTINUITY_SOURCE_MISSING"])
        for row in result["opportunities"]:
            self.assertEqual(row["source_session_id"], self.dataset.sessions[row["source_session_index"]]["session_id"])

    def test_process_pagination_without_independent_coverage_never_qualifies(self):
        material = native_intake(self.original, coverage=False)
        result = self.qualify(material)
        self.assertTrue(material["export"].pagination_complete)
        self.assertFalse(result["coverage_supported"])
        self.assertEqual(result["counts"]["candidate_eligible"], 0)
        self.assertEqual(result["counts"]["benchmark_eligible"], 0)
        self.assertEqual(result["counts"]["combined_eligible"], 0)
        self.assertIn("INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED", result["reason_codes"])

    def test_incomplete_page_chain_defer_even_authored_coverage_review(self):
        material = native_intake(self.original, complete=False)
        result = self.qualify(material)
        self.assertEqual(result["status"], "DEFER")
        self.assertIn("CONTINUITY_CAPTURE_UNAVAILABLE_OR_INCOMPLETE", result["reason_codes"])
        self.assertEqual(result["counts"]["combined_eligible"], 0)

    def test_feature_boundary_suspends_comparison_but_oldest_anchor_does_not_cross(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        first = source - self.hypothesis.signal["lookback_sessions"]
        symbol = self.plan.universe[0]
        for boundary, expected in ((first, True), (first + 1, False), (source, False)):
            with self.subTest(boundary=boundary):
                material = native_intake(self.original, [("cash_dividends", boundary, symbol)])
                row = self.row(self.qualify(material))
                self.assertIs(row["candidate_eligible"], expected)
                if not expected:
                    self.assertEqual(len(row["candidate_action_ids"]["FEATURE"]), 1)
                else:
                    self.assertTrue(row["combined_eligible"])

    def test_action_at_next_entry_open_is_not_ignored(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        material = native_intake(self.original, [("forward_splits", source + 1, self.plan.universe[0])])
        row = self.row(self.qualify(material))
        self.assertFalse(row["candidate_eligible"])
        self.assertEqual(len(row["candidate_action_ids"]["ENTRY"]), 1)
        self.assertFalse(row["benchmark_eligible"])

    def test_action_at_holding_or_exit_open_suspends_original_raw_ledger(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        for boundary in (source + 2, source + 1 + self.hypothesis.horizon["holding_sessions"]):
            with self.subTest(boundary=boundary):
                material = native_intake(self.original, [("cash_dividends", boundary, self.plan.universe[0])])
                row = self.row(self.qualify(material))
                self.assertFalse(row["candidate_eligible"])
                self.assertEqual(len(row["candidate_action_ids"]["HOLDING_EXIT"]), 1)
                self.assertFalse(row["benchmark_eligible"])

    def test_action_after_exit_open_does_not_censor_that_window(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        boundary = source + 2 + self.hypothesis.horizon["holding_sessions"]
        material = native_intake(self.original, [("cash_dividends", boundary, self.plan.universe[0])])
        row = self.row(self.qualify(material))
        self.assertTrue(row["combined_eligible"])

    def test_control_constituent_action_blocks_benchmark_for_clean_candidate(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        candidate, other = self.plan.universe
        material = native_intake(self.original, [("cash_dividends", source + 2, other)])
        row = self.row(self.qualify(material), symbol=candidate)
        self.assertTrue(row["candidate_eligible"])
        self.assertFalse(row["benchmark_eligible"])
        self.assertFalse(row["combined_eligible"])
        self.assertFalse(any(row["candidate_action_ids"].values()))
        self.assertEqual(len(row["benchmark_action_ids"]), 1)

    def test_other_symbol_feature_action_does_not_invent_control_signal_dependency(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        candidate, other = self.plan.universe
        material = native_intake(self.original, [("cash_dividends", source - 1, other)])
        row = self.row(self.qualify(material), symbol=candidate)
        self.assertTrue(row["combined_eligible"])
        self.assertEqual(row["benchmark_action_ids"], [])

    def test_unknown_first_session_placeholder_blocks_all_affected_windows(self):
        affected, other = self.plan.universe
        material = native_intake(self.original, [("worthless_removals", None, affected)])
        self.assertEqual(material["source"].events[0]["effective_session_id"], self.dataset.sessions[0]["session_id"])
        result = self.qualify(material)
        for row in result["opportunities"]:
            self.assertFalse(row["benchmark_eligible"])
            self.assertFalse(row["combined_eligible"])
            if row["symbol"] == affected:
                self.assertFalse(row["candidate_eligible"])
                self.assertEqual(len(row["candidate_action_ids"]["UNKNOWN"]), 1)
        self.assertEqual(result["counts"]["combined_eligible"], 0)

    def test_known_actions_do_not_rewrite_old_v16_defer_status(self):
        material = native_intake(self.original, [("cash_dividends", 10, self.plan.universe[0])])
        original = material["review"].to_bytes()
        result = self.qualify(material)
        self.assertEqual(result["native_continuity_review_status"], "UNRESOLVED")
        self.assertGreater(result["counts"]["combined_eligible"], 0)
        self.assertEqual(material["review"].to_bytes(), original)

    def test_retains_native_action_ids_types_dates_and_full_audit(self):
        material = native_intake(self.original, [("cash_dividends", 10, self.plan.universe[0]), ("forward_splits", 20, self.plan.universe[1])])
        result = self.qualify(material)
        self.assertEqual(result["native_action_audit"], material["export"].native_actions)
        self.assertEqual([item["native_type"] for item in result["native_action_audit"]], ["cash_dividends", "forward_splits"])

    def test_before_after_dataset_actions_retained_without_censoring_windows(self):
        material = native_intake(self.original, [("cash_dividends", "2024-12-01", self.plan.universe[0]),
                                                ("cash_dividends", "2026-01-01", self.plan.universe[0])])
        result = self.qualify(material)
        self.assertEqual(result["opportunities"], self.qualify()["opportunities"])
        self.assertEqual([row["dataset_disposition"] for row in result["native_action_audit"]], ["BEFORE_DATASET", "AFTER_DATASET"])

    def test_weekend_effective_date_uses_next_returned_session_without_inference(self):
        material = native_intake(self.original, [("cash_dividends", "2025-02-08", self.plan.universe[0])])
        action = material["export"].native_actions[0]
        self.assertEqual(action["effective_date"], "2025-02-08")
        self.assertEqual(action["mapped_session_id"], "alpaca-session-2025-02-10")
        result = self.qualify(material)
        mapped = next(index for index, row in enumerate(self.dataset.sessions) if row["session_id"] == action["mapped_session_id"])
        crossing = [row for row in result["opportunities"] if row["symbol"] == self.plan.universe[0] and row["source_session_index"] < mapped <= row["exit_session_index"]]
        self.assertTrue(crossing)
        self.assertTrue(all(not row["combined_eligible"] for row in crossing))

    def test_final_holdout_withheld_not_a_new_partition_or_score(self):
        result = self.qualify()
        self.assertEqual({key: result["final_holdout"][key] for key in ("start_index", "end_index")}, self.plan.protocol["final_holdout"])
        self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertTrue(all(row["entry_session_index"] < self.plan.protocol["final_holdout"]["start_index"] for row in result["opportunities"]))
        self.assertNotIn("intents", result)
        self.assertNotIn("metrics", result)

    def test_masks_same_when_future_or_source_prices_change_preserving_calendar(self):
        # Compare masks directly against a new independent raw-price fixture,
        # never rewrite an old dataset. Root binding rejects using new prices
        # under old hashes; the qualification itself depends only on metadata.
        data = self.dataset.to_dict()
        for session in data["sessions"]:
            for bar in session["bars"]:
                for field in ("open", "high", "low", "close"):
                    bar[field] = str(int(bar[field]) * 10)
        raw = canonical_json_bytes(data)
        plan = self.plan.to_dict()
        plan["dataset_evidence"] = ref(plan["dataset_evidence"]["path"], raw)
        changed = self.qualify(None, plan=plan, dataset=data)
        original = self.qualify(None)
        self.assertEqual(changed["opportunities"], original["opportunities"])

    def test_preserves_original_prices_hypothesis_plan_and_evidence_bytes(self):
        before = (self.dataset.to_bytes(), self.plan.to_bytes(), self.hypothesis.to_bytes(), dict(self.original["evidence"]))
        self.qualify()
        after = (self.dataset.to_bytes(), self.plan.to_bytes(), self.hypothesis.to_bytes(), dict(self.original["evidence"]))
        self.assertEqual(before, after)

    def test_qualification_is_repeatable(self):
        self.assertEqual(self.qualify(), self.qualify())

    def changed_clock_context(self, index, value):
        data = self.dataset.to_dict()
        data["sessions"][index]["available_at"] = value
        typed = TradingResearchDataset.from_mapping(data)
        plan = self.plan.to_dict()
        plan["dataset_evidence"] = ref(plan["dataset_evidence"]["path"], typed.to_bytes())
        return typed, plan

    def test_entry_open_must_follow_source_availability(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        data, plan = self.changed_clock_context(source, self.dataset.sessions[source + 1]["open_at"])
        row = self.row(self.qualify(None, dataset=data, plan=plan))
        self.assertIn("ENTRY_OPEN_NOT_AFTER_SOURCE_AVAILABILITY", row["reason_codes"])

    def test_earlier_feature_input_cannot_be_unavailable_at_decision(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        value = format_rfc3339(parse_rfc3339(self.dataset.sessions[source]["available_at"], "clock") + timedelta(seconds=1))
        data, plan = self.changed_clock_context(source - 1, value)
        row = self.row(self.qualify(None, dataset=data, plan=plan))
        self.assertIn("FEATURE_INPUT_NOT_AVAILABLE_AT_DECISION", row["reason_codes"])

    def test_original_exit_open_requires_valid_exit_decision_clock(self):
        source = self.plan.protocol["folds"][0]["test"]["start_index"] - 1
        exit_at = source + 1 + self.hypothesis.horizon["holding_sessions"]
        data, plan = self.changed_clock_context(exit_at - 1, self.dataset.sessions[exit_at]["open_at"])
        row = self.row(self.qualify(None, dataset=data, plan=plan))
        self.assertIn("EXIT_OPEN_NOT_AFTER_SOURCE_AVAILABILITY", row["reason_codes"])

    def test_ambient_decimal_precision_and_traps_do_not_change_clock_masks(self):
        original = self.qualify()
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            self.assertEqual(self.qualify(), original)

    def test_untrusted_action_window_join_has_explicit_workload_bound(self):
        with patch("blackpod_build_week.trading_continuity_qualification.MAX_ACTION_WINDOW_COMPARISONS", 1):
            material = native_intake(self.original, [("cash_dividends", 24, self.plan.universe[0])])
            with self.assertRaises(ValueError):
                self.qualify(material)

    def test_rejects_policy_change(self):
        with self.assertRaises(ValueError):
            self.qualify(policy={**self.policy, "continuity_policy": "ADJUST_FOR_FAVORABLE_RETURNS"})

    def test_rejects_scope_mismatch(self):
        with self.assertRaises(ValueError):
            self.qualify(policy={**self.policy, "evidence_scope": "RETAINED_HISTORY_RESEARCH"})

    def test_rejects_policy_before_selected_evidence(self):
        with self.assertRaises(ValueError):
            self.qualify(policy={**self.policy, "recorded_at": "2025-03-01T00:00:00Z"})

    def test_rejects_changed_raw_dataset_under_original_reference(self):
        data = self.dataset.to_dict()
        data["sessions"][0]["bars"][0]["volume"] = str(int(data["sessions"][0]["bars"][0]["volume"]) + 1)
        with self.assertRaises(ValueError):
            self.qualify(dataset=data)

    def test_rejects_original_hypothesis_mismatch(self):
        with self.assertRaises(ValueError):
            other = next(row["hypothesis"] for row in self.original["base_studies"] if row["hypothesis"].signal["lookback_sessions"] == 1)
            self.qualify(hypothesis=other)

    def test_original_staleness_limit_applies_to_entry_and_exit(self):
        plan = self.plan.to_dict()
        plan["risk"]["max_staleness_seconds"] = 1
        result = self.qualify(plan=plan)
        self.assertEqual(result["counts"]["combined_eligible"], 0)
        self.assertTrue(any("ENTRY_SOURCE_STALE_AT_OPEN" in row["reason_codes"] for row in result["opportunities"]))
        self.assertTrue(any("EXIT_SOURCE_STALE_AT_OPEN" in row["reason_codes"] for row in result["opportunities"]))

    def test_all_suspended_and_eligible_windows_retained_in_counts(self):
        material = native_intake(self.original, [("cash_dividends", 24, self.plan.universe[0])])
        result = self.qualify(material)
        self.assertEqual(result["counts"]["opportunities"], result["counts"]["combined_eligible"] + result["counts"]["deferred"])
        self.assertGreater(result["counts"]["combined_eligible"], 0)
        self.assertGreater(result["counts"]["deferred"], 0)


if __name__ == "__main__":
    unittest.main()
