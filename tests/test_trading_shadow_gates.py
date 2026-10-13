"""Retained gate declarations must replay before shadow research is eligible."""
import copy
from decimal import Inexact, Overflow, Rounded, ROUND_UP, Underflow, localcontext
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_shadow_research import (
    PriceContinuityEvidence, PriceContinuitySource, TradingCostEvidence, TradingCostSource, TradingShadowStudy,
)
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.trading_shadow_example import fixture_material
from blackpod_build_week.trading_shadow_gates import assess_shadow_gates, shadow_gate_material


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


class TradingShadowGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.row = self.material["studies"][0]

    def altered(self, *, price_source=None, price_review=None, cost_source=None, cost_review=None, study=None):
        mapping, blobs = self.row["study"].to_dict(), dict(self.material["blobs"])
        for kind, source_cls, review_cls, source_mutation, review_mutation in (
            ("price", PriceContinuitySource, PriceContinuityEvidence, price_source, price_review),
            ("cost", TradingCostSource, TradingCostEvidence, cost_source, cost_review),
        ):
            review = self.material[kind + "_review"].to_dict()
            if source_mutation is not None:
                source = self.material[kind + "_source"].to_dict()
                source_mutation(source)
                raw = source_cls.from_mapping(source).to_bytes()
                reference = _reference(review["source_evidence"][0]["path"], raw)
                review["source_evidence"] = [reference]
                blobs[reference["sha256"]] = raw
            if review_mutation is not None:
                review_mutation(review)
            raw = review_cls.from_mapping(review).to_bytes()
            key = "price_continuity_evidence" if kind == "price" else "cost_evidence"
            reference = _reference(mapping[key]["path"], raw)
            mapping[key] = reference
            blobs[reference["sha256"]] = raw
        if study is not None:
            study(mapping)
        return TradingShadowStudy.from_mapping(mapping), blobs

    def assessment(self, study=None, blobs=None):
        return assess_shadow_gates(study or self.row["study"], self.row["plan"], self.material["dataset"],
                                   self.material["blobs"] if blobs is None else blobs)

    def test_fixture_with_both_bound_gates_is_eligible_only_for_declared_research(self):
        result = self.assessment()
        self.assertTrue(result["eligible"])
        self.assertEqual(result["reason_codes"], [])
        self.assertEqual(result["cost_model"], self.material["cost_review"].cost_model)
        self.assertFalse(result["provenance"]["provider_authenticity_verified"])
        self.assertFalse(result["provenance"]["historical_point_in_time_verified"])
        self.assertEqual(result["provenance"]["costs_semantics"], "DECLARED_REVIEW_BOUNDS_NOT_OBSERVED_EXECUTION_COSTS")

    def test_both_missing_gates_defer_without_costs(self):
        study, blobs = self.altered(study=lambda row: row.update(price_continuity_evidence=None, cost_evidence=None))
        result = self.assessment(study, blobs)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_codes"], ["COST_EVIDENCE_MISSING", "PRICE_CONTINUITY_EVIDENCE_MISSING"])
        self.assertIsNone(result["cost_model"])

    def test_single_missing_gate_defer_is_explicit(self):
        for field, reason in (("price_continuity_evidence", "PRICE_CONTINUITY_EVIDENCE_MISSING"),
                              ("cost_evidence", "COST_EVIDENCE_MISSING")):
            study, blobs = self.altered(study=lambda row: row.update({field: None}))
            self.assertIn(reason, self.assessment(study, blobs)["reason_codes"])

    def test_synthetic_reviews_cannot_clear_retained_history_scope(self):
        study, blobs = self.altered(study=lambda row: row.update(evidence_scope="RETAINED_HISTORY_RESEARCH"))
        result = self.assessment(study, blobs)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason_codes"], ["COST_EVIDENCE_SCOPE_MISMATCH", "COST_SOURCE_SCOPE_MISMATCH",
                                                "PRICE_CONTINUITY_EVIDENCE_SCOPE_MISMATCH", "PRICE_CONTINUITY_SOURCE_SCOPE_MISMATCH"])

    def test_retained_review_labels_do_not_satisfy_fixture_scope(self):
        study, blobs = self.altered(price_review=lambda row: row.update(basis="RETAINED_CORPORATE_ACTION_REVIEW"),
                                   cost_review=lambda row: row.update(basis="RETAINED_COST_REVIEW"))
        result = self.assessment(study, blobs)
        self.assertFalse(result["eligible"])
        self.assertIn("PRICE_CONTINUITY_EVIDENCE_SCOPE_MISMATCH", result["reason_codes"])
        self.assertIn("COST_EVIDENCE_SCOPE_MISMATCH", result["reason_codes"])

    def test_retained_source_labels_do_not_satisfy_fixture_scope(self):
        study, blobs = self.altered(price_source=lambda row: row.update(basis="RETAINED_REVIEW_SOURCE"),
                                   cost_source=lambda row: row.update(basis="RETAINED_REVIEW_SOURCE"))
        result = self.assessment(study, blobs)
        self.assertIn("PRICE_CONTINUITY_SOURCE_SCOPE_MISMATCH", result["reason_codes"])
        self.assertIn("COST_SOURCE_SCOPE_MISMATCH", result["reason_codes"])

    def test_review_status_without_complete_source_coverage_cannot_clear_gate(self):
        study, blobs = self.altered(price_source=lambda row: row.update(coverage_complete=False),
                                   cost_source=lambda row: row.update(coverage_complete=False))
        result = self.assessment(study, blobs)
        self.assertFalse(result["eligible"])
        self.assertIn("PRICE_CONTINUITY_SOURCE_COVERAGE_INCOMPLETE", result["reason_codes"])
        self.assertIn("COST_SOURCE_COVERAGE_INCOMPLETE", result["reason_codes"])

    def test_partial_source_interval_cannot_clear_gate(self):
        study, blobs = self.altered(price_source=lambda row: row.update(coverage_start_session_id="2025-01-03"),
                                   cost_source=lambda row: row.update(coverage_end_session_id="2025-02-24"))
        result = self.assessment(study, blobs)
        self.assertIn("PRICE_CONTINUITY_SOURCE_COVERAGE_INCOMPLETE", result["reason_codes"])
        self.assertIn("COST_SOURCE_COVERAGE_INCOMPLETE", result["reason_codes"])

    def test_partial_review_interval_cannot_clear_gate(self):
        study, blobs = self.altered(price_review=lambda row: row.update(coverage_start_session_id="2025-01-03"),
                                   cost_review=lambda row: row.update(coverage_end_session_id="2025-02-24"))
        result = self.assessment(study, blobs)
        self.assertIn("PRICE_CONTINUITY_REVIEW_COVERAGE_INCOMPLETE", result["reason_codes"])
        self.assertIn("COST_REVIEW_COVERAGE_INCOMPLETE", result["reason_codes"])

    def test_unresolved_reviews_defer(self):
        study, blobs = self.altered(price_review=lambda row: row.update(status="UNRESOLVED"),
                                   cost_review=lambda row: row.update(status="UNRESOLVED", cost_model=None))
        result = self.assessment(study, blobs)
        self.assertIn("PRICE_CONTINUITY_REVIEW_UNRESOLVED", result["reason_codes"])
        self.assertIn("COST_REVIEW_UNRESOLVED", result["reason_codes"])
        self.assertIn("COST_MODEL_MISSING", result["reason_codes"])

    def test_any_declared_price_discontinuity_defers_entire_raw_dataset(self):
        first = self.material["dataset"].sessions[0]["session_id"]
        for kind in ("SPLIT", "CASH_DISTRIBUTION", "STOCK_DISTRIBUTION", "SYMBOL_CHANGE", "MERGER", "OTHER_PRICE_DISCONTINUITY"):
            study, blobs = self.altered(price_source=lambda row: row.update(events=[{
                "event_id": "fixture-event-001", "symbol": "SYNTHA", "effective_session_id": first, "kind": kind,
            }]))
            self.assertIn("PRICE_CONTINUITY_DISCONTINUITY_PRESENT", self.assessment(study, blobs)["reason_codes"])

    def test_unknown_effective_session_rejects_even_after_valid_rehash(self):
        study, blobs = self.altered(price_source=lambda row: row.update(events=[{
            "event_id": "fixture-event-001", "symbol": "SYNTHA", "effective_session_id": "unknown-session", "kind": "SPLIT",
        }]))
        with self.assertRaisesRegex(ValueError, "unknown dataset session"):
            self.assessment(study, blobs)

    def test_each_cost_component_must_cover_all_retained_bounds(self):
        for field in ("spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"):
            study, blobs = self.altered(cost_source=lambda row: row["observations"][1].update({field: "20"}))
            result = self.assessment(study, blobs)
            self.assertFalse(result["eligible"])
            self.assertIn("COST_MODEL_BELOW_RETAINED_REVIEW_BOUND", result["reason_codes"])

    def test_zero_friction_review_cannot_clear_gate(self):
        study, blobs = self.altered(cost_review=lambda row: row["cost_model"].update(spread_bps="0", slippage_bps="0"))
        self.assertIn("COST_ZERO_FRICTION_NOT_SUPPORTED", self.assessment(study, blobs)["reason_codes"])

    def test_stress_costs_must_fit_evaluator_bounds(self):
        study, blobs = self.altered(cost_review=lambda row: row["cost_model"].update(spread_bps="251"))
        self.assertIn("COST_STRESS_BOUND_EXCEEDS_SUPPORTED_RANGE", self.assessment(study, blobs)["reason_codes"])

    def test_fee_stress_boundary_rejects_21_digit_result(self):
        study, blobs = self.altered(cost_review=lambda row: row["cost_model"].update(fee_per_fill="25000000000000000000"))
        result = self.assessment(study, blobs)
        self.assertFalse(result["eligible"])
        self.assertIn("COST_STRESS_BOUND_EXCEEDS_SUPPORTED_RANGE", result["reason_codes"])

    def test_smallest_supported_spread_increment_above_stress_bound_defers(self):
        study, blobs = self.altered(cost_review=lambda row: row["cost_model"].update(spread_bps="250.000000000000000001"))
        self.assertIn("COST_STRESS_BOUND_EXCEEDS_SUPPORTED_RANGE", self.assessment(study, blobs)["reason_codes"])

    def test_unsupported_cost_precision_is_rejected_instead_of_rounded_to_bound(self):
        with self.assertRaises(ValueError):
            self.altered(cost_review=lambda row: row["cost_model"].update(spread_bps="250." + "0" * 80 + "1"))

    def test_gate_cost_stress_is_independent_of_hostile_decimal_context(self):
        study, blobs = self.altered(cost_review=lambda row: row["cost_model"].update(spread_bps="249.999999999999999999"))
        expected = self.assessment(study, blobs)
        self.assertTrue(expected["eligible"])
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_UP
            context.Emax, context.Emin = 2, -2
            for signal in (Inexact, Rounded, Overflow, Underflow):
                context.traps[signal] = True
            self.assertEqual(self.assessment(study, blobs), expected)

    def test_source_and_review_clocks_are_bound_to_capture_and_freeze(self):
        for keyword, timestamp in (("price_source", "2025-04-01T10:00:00Z"), ("cost_source", "2025-04-01T11:30:00Z"),
                                   ("price_review", "2025-04-01T10:00:00Z"), ("cost_review", "2025-04-01T12:01:00Z")):
            study, blobs = self.altered(**{keyword: lambda row: row.update(recorded_at=timestamp)})
            with self.assertRaisesRegex(ValueError, "clock|capture|freeze"):
                self.assessment(study, blobs)

    def test_rehashed_dataset_reference_mismatch_rejects(self):
        for keyword in ("price_source", "cost_source", "price_review", "cost_review"):
            study, blobs = self.altered(**{keyword: lambda row: row["dataset_evidence"].update(sha256="0" * 64)})
            with self.assertRaisesRegex(ValueError, "dataset or universe differs"):
                self.assessment(study, blobs)

    def test_missing_source_bytes_cannot_be_replaced_by_review_status(self):
        blobs = dict(self.material["blobs"])
        source_ref = self.material["price_review"].source_evidence[0]
        del blobs[source_ref["sha256"]]
        with self.assertRaisesRegex(ValueError, "hash or size"):
            self.assessment(blobs=blobs)

    def test_raw_origin_hash_or_size_tamper_rejects(self):
        for source in (self.material["price_source"], self.material["cost_source"]):
            blobs = dict(self.material["blobs"])
            origin_ref = source.origin_evidence[0]
            blobs[origin_ref["sha256"]] += b"tampered"
            with self.assertRaisesRegex(ValueError, "hash or size"):
                self.assessment(blobs=blobs)

    def test_missing_origin_is_not_inferred(self):
        blobs = dict(self.material["blobs"])
        del blobs[self.material["price_source"].origin_evidence[0]["sha256"]]
        with self.assertRaisesRegex(ValueError, "hash or size"):
            self.assessment(blobs=blobs)

    def test_original_plan_bytes_and_dataset_hash_are_checked(self):
        blobs = dict(self.material["blobs"])
        blobs[self.row["study"].base_plan_evidence["sha256"]] += b"\n"
        with self.assertRaisesRegex(ValueError, "hash or size"):
            self.assessment(blobs=blobs)

    def test_origin_bytes_are_retained_verbatim_and_never_executed(self):
        result = shadow_gate_material(self.row["study"], self.row["plan"], self.material["dataset"], self.material["blobs"])
        for source in (self.material["price_source"], self.material["cost_source"]):
            for reference in source.origin_evidence:
                self.assertEqual(result["evidence"][reference["path"]], self.material["blobs"][reference["sha256"]])
        self.assertEqual(len(result["evidence"]), 6)

    def test_gate_verification_is_pure_and_deterministic(self):
        before = copy.deepcopy(self.material["blobs"])
        self.assertEqual(self.assessment(), self.assessment())
        self.assertEqual(before, self.material["blobs"])


if __name__ == "__main__":
    unittest.main()
