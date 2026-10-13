"""Strict declarations for shadow studies and retained gate evidence."""
import copy
import unittest
from decimal import localcontext

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_shadow_research import (
    PriceContinuityEvidence, PriceContinuitySource, TradingCostEvidence, TradingCostSource,
    TradingShadowStudy, validate_shadow_cost_model,
)
from test_trading_research_contracts import authority, ref


def study_mapping():
    return {
        "schema_version": "blackpod.trading_shadow_study.v1", "study_id": "shadow-contract-study",
        "experiment_id": "shadow-contract-experiment", "registered_at": "2026-01-20T00:00:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
        "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "base_plan_evidence": ref("research/base-plan.v2.json"),
        "price_continuity_evidence": ref("review/price-continuity.json"),
        "cost_evidence": ref("review/costs.json"),
        "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "200"},
        "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"},
        "cost_stress_multipliers": ["1", "2", "4"],
        "trial_registry": {"trial_id": "shadow-trial-001", "prior_trial_ids": []},
        "auto_trading_enabled": False, "authority": authority(),
    }


def cost_model():
    return {"spread_bps": "10", "slippage_bps": "5", "fee_bps": "1", "fee_per_fill": "0.10"}


def _review_mapping(cost):
    row = {
        "schema_version": "blackpod.trading_cost_evidence.v1" if cost else "blackpod.price_continuity_evidence.v1",
        "evidence_id": "cost-review-001" if cost else "continuity-review-001",
        "recorded_at": "2026-01-19T00:00:00Z", "dataset_evidence": ref("history/dataset.v2.json"),
        "coverage_start_session_id": "session-00", "coverage_end_session_id": "session-15",
        "universe": ["SYNTHA", "SYNTHB"], "basis": "SYNTHETIC_FIXTURE",
        "status": "SUPPORTED" if cost else "CONTINUITY_SUPPORTED",
        "source_evidence": [ref("review/cost-source.json" if cost else "review/continuity-source.json")],
        "reviewer_id": "fixture-reviewer", "review_notes": "Constructed fixture declarations require separate source checks.",
        "limitations": ["SYNTHETIC_TEST_EVIDENCE_NOT_REAL_MARKET_SUPPORT", "NO_EXECUTION_AUTHORITY"],
        "auto_trading_enabled": False, "authority": authority(),
    }
    if cost:
        row["cost_model"] = cost_model()
    return row


def price_review_mapping():
    return _review_mapping(False)


def cost_review_mapping():
    return _review_mapping(True)


def _source_mapping(cost):
    row = {
        "schema_version": "blackpod.trading_cost_source.v1" if cost else "blackpod.trading_price_continuity_source.v1",
        "source_id": "cost-source-001" if cost else "continuity-source-001",
        "recorded_at": "2026-01-18T00:00:00Z", "basis": "SYNTHETIC_FIXTURE",
        "dataset_evidence": ref("history/dataset.v2.json"), "universe": ["SYNTHA", "SYNTHB"],
        "coverage_start_session_id": "session-00", "coverage_end_session_id": "session-15",
        "coverage_complete": True, "origin_evidence": [ref("source/cost-origin.raw" if cost else "source/continuity-origin.raw")],
        "limitations": ["LOCAL_REVIEW_NOT_PROVIDER_AUTHENTICATION", "NO_HISTORICAL_POINT_IN_TIME_ATTESTATION"],
        "auto_trading_enabled": False, "authority": authority(),
    }
    if cost:
        row["sampling_policy"] = "DECLARED_REVIEW_BOUNDS_NOT_EXECUTABLE_QUOTES"
        row["observations"] = [{"symbol": symbol, **cost_model()} for symbol in row["universe"]]
    else:
        row["price_policy"] = "RAW_NO_SPLITS_DISTRIBUTIONS_OR_SYMBOL_CHANGES"
        row["events"] = []
    return row


def price_source_mapping():
    return _source_mapping(False)


def cost_source_mapping():
    return _source_mapping(True)


DOCUMENTS = (
    (TradingShadowStudy, study_mapping), (PriceContinuityEvidence, price_review_mapping),
    (TradingCostEvidence, cost_review_mapping), (PriceContinuitySource, price_source_mapping),
    (TradingCostSource, cost_source_mapping),
)


class TradingShadowContractTests(unittest.TestCase):
    def test_study_identifier_reserves_derived_intent_suffix(self):
        value = study_mapping()
        value["study_id"] = "a" * 110
        self.assertEqual(TradingShadowStudy.from_mapping(value).study_id, value["study_id"])
        for length in (111, 128):
            value["study_id"] = "a" * length
            with self.assertRaisesRegex(ValueError, "maximum 110"):
                TradingShadowStudy.from_mapping(value)

    def assert_rejects(self, cls, factory, mutate):
        row = factory()
        mutate(row)
        with self.assertRaises(ContractValidationError):
            cls.from_mapping(row)

    def test_all_five_documents_canonical_roundtrip(self):
        for cls, factory in DOCUMENTS:
            with self.subTest(cls=cls.__name__):
                document = cls.from_mapping(factory())
                self.assertEqual(cls.from_bytes(document.to_bytes()).to_bytes(), document.to_bytes())
                self.assertEqual(document.to_mapping(), document.to_dict())

    def test_nested_values_cannot_mutate_retained_bytes(self):
        for cls, factory in DOCUMENTS:
            with self.subTest(cls=cls.__name__):
                row = factory()
                document = cls.from_mapping(row)
                before = document.to_bytes()
                row["authority"].clear()
                document.authority.clear()
                document.to_dict().clear()
                self.assertEqual(document.to_bytes(), before)

    def test_unknown_missing_and_nonstring_fields_reject(self):
        for cls, factory in DOCUMENTS:
            for mutation in (lambda row: row.update(execute=True), lambda row: row.pop("schema_version"),
                             lambda row: row.update({1: "bad"})):
                with self.subTest(cls=cls.__name__):
                    self.assert_rejects(cls, factory, mutation)

    def test_versions_are_closed(self):
        for cls, factory in DOCUMENTS:
            with self.subTest(cls=cls.__name__):
                self.assert_rejects(cls, factory, lambda row: row.update(schema_version="blackpod.unknown.v2"))

    def test_all_authority_flags_and_auto_trading_are_strictly_false(self):
        for cls, factory in DOCUMENTS:
            for value in (True, 0, "false", None):
                for flag in authority():
                    with self.subTest(cls=cls.__name__, flag=flag, value=value):
                        self.assert_rejects(cls, factory, lambda row: row["authority"].update({flag: value}))
                with self.subTest(cls=cls.__name__, flag="auto_trading_enabled", value=value):
                    self.assert_rejects(cls, factory, lambda row: row.update(auto_trading_enabled=value))

    def test_authority_missing_and_additional_flags_reject(self):
        for cls, factory in DOCUMENTS:
            for mutation in (lambda row: row["authority"].pop("execution_enabled"),
                             lambda row: row["authority"].update(orders_enabled=False)):
                self.assert_rejects(cls, factory, mutation)

    def test_study_requires_trading_development_shadow_boundary(self):
        for field, value in (("domain", "INVESTMENT"), ("domain", "CAPITAL_ALLOCATION"), ("mode", "PAPER"),
                             ("mode", "LIVE"), ("mode", "SHADOW"), ("scope", "FINAL_HOLDOUT")):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row.update({field: value}))

    def test_evidence_scope_is_explicit_and_closed(self):
        row = study_mapping()
        row["evidence_scope"] = "RETAINED_HISTORY_RESEARCH"
        self.assertEqual(TradingShadowStudy.from_mapping(row).evidence_scope, "RETAINED_HISTORY_RESEARCH")
        for value in (None, "PAPER", "REAL_MARKET_VERIFIED", "SYNTHETIC_FIXTURE"):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row.update(evidence_scope=value))

    def test_study_gate_refs_are_nullable_without_claiming_eligibility(self):
        row = study_mapping()
        row["price_continuity_evidence"] = row["cost_evidence"] = None
        document = TradingShadowStudy.from_mapping(row)
        self.assertIsNone(document.price_continuity_evidence)
        self.assertIsNone(document.cost_evidence)

    def test_study_base_plan_is_not_nullable(self):
        self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row.update(base_plan_evidence=None))

    def test_study_evidence_paths_must_be_distinct(self):
        self.assert_rejects(TradingShadowStudy, study_mapping,
                            lambda row: row.update(cost_evidence=row["price_continuity_evidence"]))
        self.assert_rejects(TradingShadowStudy, study_mapping,
                            lambda row: row.update(price_continuity_evidence=row["base_plan_evidence"]))

    def test_evidence_refs_require_safe_paths_bounded_sizes_and_full_hashes(self):
        for field, value in (("path", "../secret"), ("path", "/tmp/source"), ("sha256", "x"),
                             ("sha256", "A" * 64), ("size_bytes", True), ("size_bytes", -1), ("size_bytes", 67108865)):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row["base_plan_evidence"].update({field: value}))

    def test_study_sizing_method_cannot_request_live_rules(self):
        for value in ("GALACTICA", "KELLY", "NEXT_OPEN", "DESK_BUDGET_PERCENT"):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row["sizing"].update(method=value))

    def test_study_sizing_is_positive_bounded_decimal_string(self):
        for value in ("0", "-1", "1e2", 200, 1.5, True, "NaN", "Infinity", "100000000000000000001"):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row["sizing"].update(per_symbol_notional=value))
        for value in ("0.000000000001", "200", "99999999999999999999"):
            row = study_mapping()
            row["sizing"]["per_symbol_notional"] = value
            self.assertEqual(TradingShadowStudy.from_mapping(row).sizing["per_symbol_notional"], value)

    def test_matched_benchmark_definition_is_closed(self):
        for value in ("CASH", "BUY_AND_HOLD", "MATCHED_EXPOSURE", None):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row["benchmark"].update(kind=value))

    def test_cost_stress_levels_cannot_be_tuned_reordered_or_cast(self):
        for value in ([], [1, 2, 4], ["1", "4", "2"], ["1", "2"], ["1", "2", "8"], ("1", "2", "4")):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row.update(cost_stress_multipliers=value))

    def test_trial_registry_rejects_duplicates_current_identity_or_excess_count(self):
        for value in (["old", "old"], ["shadow-trial-001"], ["prior-%05d" % index for index in range(10001)], None):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row["trial_registry"].update(prior_trial_ids=value))

    def test_prior_trial_order_is_preserved_not_repaired(self):
        row = study_mapping()
        row["trial_registry"]["prior_trial_ids"] = ["prior-b", "prior-a"]
        self.assertEqual(TradingShadowStudy.from_mapping(row).trial_registry["prior_trial_ids"], ["prior-b", "prior-a"])

    def test_unknown_nested_study_fields_reject(self):
        for field in ("sizing", "benchmark", "trial_registry", "base_plan_evidence", "price_continuity_evidence", "cost_evidence"):
            self.assert_rejects(TradingShadowStudy, study_mapping, lambda row: row[field].update(approved=True))

    def test_review_basis_and_status_are_explicit_closed_declarations(self):
        for cls, factory, retained, supported in (
            (PriceContinuityEvidence, price_review_mapping, "RETAINED_CORPORATE_ACTION_REVIEW", "CONTINUITY_SUPPORTED"),
            (TradingCostEvidence, cost_review_mapping, "RETAINED_COST_REVIEW", "SUPPORTED"),
        ):
            row = factory()
            row["basis"], row["status"] = retained, "UNRESOLVED"
            self.assertEqual(cls.from_mapping(row).status, "UNRESOLVED")
            for field, value in (("basis", "LLM_INFERENCE"), ("basis", "BROKER_AUTHENTICATED"),
                                 ("status", "EXECUTION_AUTHORIZED"), ("status", True)):
                self.assert_rejects(cls, factory, lambda row: row.update({field: value}))
            self.assertEqual(cls.from_mapping(factory()).status, supported)

    def test_unresolved_costs_can_remain_missing(self):
        row = cost_review_mapping()
        row["status"], row["cost_model"] = "UNRESOLVED", None
        self.assertIsNone(TradingCostEvidence.from_mapping(row).cost_model)

    def test_supported_costs_cannot_be_missing(self):
        self.assert_rejects(TradingCostEvidence, cost_review_mapping, lambda row: row.update(cost_model=None))

    def test_supported_review_does_not_establish_source_eligibility(self):
        # Parsing a review only records its claim; gate verification checks the
        # referenced source bytes and coverage in a separate pure operation.
        document = PriceContinuityEvidence.from_mapping(price_review_mapping())
        self.assertEqual(document.status, "CONTINUITY_SUPPORTED")
        self.assertNotIn("eligible", document.to_dict())
        self.assertNotIn("provider_authenticated", document.to_dict())

    def test_gate_cost_fields_are_exact_nonnegative_and_bounded(self):
        for field in ("spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"):
            for value in ("-1", "1e1", 1, None, True, "NaN"):
                self.assert_rejects(TradingCostEvidence, cost_review_mapping, lambda row: row["cost_model"].update({field: value}))
        for field in ("spread_bps", "slippage_bps", "fee_bps"):
            self.assert_rejects(TradingCostEvidence, cost_review_mapping, lambda row: row["cost_model"].update({field: "1000.000000000001"}))
        self.assert_rejects(TradingCostEvidence, cost_review_mapping, lambda row: row["cost_model"].update(commission="1"))

    def test_zero_cost_declarations_are_structurally_explicit_not_evidence(self):
        model = {field: "0" for field in cost_model()}
        self.assertEqual(validate_shadow_cost_model(model), model)

    def test_cost_validation_is_independent_of_ambient_decimal_context(self):
        model = {"spread_bps": "999.999999999999", "slippage_bps": "1.000000000001", "fee_bps": "0", "fee_per_fill": "0.01"}
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(validate_shadow_cost_model(model), model)

    def test_source_completeness_false_remains_valid_deferred_evidence(self):
        for cls, factory in ((PriceContinuitySource, price_source_mapping), (TradingCostSource, cost_source_mapping)):
            row = factory()
            row["coverage_complete"] = False
            self.assertIs(cls.from_mapping(row).coverage_complete, False)

    def test_source_completeness_is_strict_boolean(self):
        for cls, factory in ((PriceContinuitySource, price_source_mapping), (TradingCostSource, cost_source_mapping)):
            for value in (0, 1, "true", None):
                self.assert_rejects(cls, factory, lambda row: row.update(coverage_complete=value))

    def test_source_bases_do_not_claim_provider_or_live_authentication(self):
        for cls, factory in ((PriceContinuitySource, price_source_mapping), (TradingCostSource, cost_source_mapping)):
            row = factory()
            row["basis"] = "RETAINED_REVIEW_SOURCE"
            self.assertEqual(cls.from_mapping(row).basis, "RETAINED_REVIEW_SOURCE")
            for value in ("LIVE_EXECUTION", "PROVIDER_AUTHENTICATED", "LLM_DERIVED", None):
                self.assert_rejects(cls, factory, lambda row: row.update(basis=value))

    def test_source_price_policy_and_cost_sampling_policy_are_closed(self):
        self.assert_rejects(PriceContinuitySource, price_source_mapping, lambda row: row.update(price_policy="ADJUSTED_TOTAL_RETURN"))
        self.assert_rejects(TradingCostSource, cost_source_mapping, lambda row: row.update(sampling_policy="EXECUTABLE_QUOTES"))

    def test_source_cost_observations_cover_exact_sorted_universe(self):
        for mutation in (lambda row: row.update(observations=[]), lambda row: row["observations"].reverse(),
                         lambda row: row["observations"].pop(),
                         lambda row: row["observations"].append(copy.deepcopy(row["observations"][0])),
                         lambda row: row["observations"][0].update(symbol="UNDECLARED")):
            self.assert_rejects(TradingCostSource, cost_source_mapping, mutation)

    def test_source_cost_observations_are_strict_parameter_objects(self):
        for mutation in (lambda row: row["observations"][0].update(price="100"),
                         lambda row: row["observations"][0].pop("fee_per_fill"),
                         lambda row: row["observations"][0].update(slippage_bps="-1"),
                         lambda row: row["observations"][0].update(spread_bps="1001")):
            self.assert_rejects(TradingCostSource, cost_source_mapping, mutation)

    def test_continuity_source_can_record_discontinuities_without_authorizing_them(self):
        row = price_source_mapping()
        row["events"] = [{"event_id": "event-001", "symbol": "SYNTHA", "effective_session_id": "session-04", "kind": "SPLIT"}]
        self.assertEqual(PriceContinuitySource.from_mapping(row).events[0]["kind"], "SPLIT")

    def test_continuity_event_kinds_are_closed(self):
        for kind in ("SPLIT", "CASH_DISTRIBUTION", "STOCK_DISTRIBUTION", "SYMBOL_CHANGE", "MERGER", "OTHER_PRICE_DISCONTINUITY"):
            row = price_source_mapping()
            row["events"] = [{"event_id": "event-001", "symbol": "SYNTHA", "effective_session_id": "session-04", "kind": kind}]
            self.assertEqual(PriceContinuitySource.from_mapping(row).events[0]["kind"], kind)
        row["events"][0]["kind"] = "NOT_RELEVANT"
        with self.assertRaises(ContractValidationError):
            PriceContinuitySource.from_mapping(row)

    def test_continuity_event_order_and_identities_are_strict(self):
        event = {"event_id": "event-002", "symbol": "SYNTHA", "effective_session_id": "session-04", "kind": "SPLIT"}
        for events in ([event, copy.deepcopy(event)], [event, {**event, "event_id": "event-001"}]):
            row = price_source_mapping()
            row["events"] = events
            with self.assertRaises(ContractValidationError):
                PriceContinuitySource.from_mapping(row)

    def test_continuity_event_symbol_and_fields_are_strict(self):
        event = {"event_id": "event-001", "symbol": "SYNTHA", "effective_session_id": "session-04", "kind": "SPLIT"}
        for mutation in (lambda row: row.update(symbol="UNDECLARED"), lambda row: row.update(symbol="synth"),
                         lambda row: row.update(ignored=True), lambda row: row.pop("effective_session_id")):
            row = price_source_mapping()
            row["events"] = [copy.deepcopy(event)]
            mutation(row["events"][0])
            with self.assertRaises(ContractValidationError):
                PriceContinuitySource.from_mapping(row)

    def test_universe_order_uniqueness_symbols_and_bounds_are_preserved(self):
        for cls, factory in DOCUMENTS[1:]:
            for value in ([], ["SYNTHB", "SYNTHA"], ["SYNTHA", "SYNTHA"], ["synth"], ["../SYNTH"],
                          ["SYMBOL%d" % index for index in range(9)]):
                self.assert_rejects(cls, factory, lambda row: row.update(universe=value))

    def test_source_and_review_refs_are_nonempty_distinct_and_bounded(self):
        for cls, factory in DOCUMENTS[1:]:
            key = "origin_evidence" if cls in (PriceContinuitySource, TradingCostSource) else "source_evidence"
            for value in ([], None, [ref("same.raw"), ref("same.raw")], [ref("source-%03d.raw" % index) for index in range(129)]):
                self.assert_rejects(cls, factory, lambda row: row.update({key: value}))

    def test_dataset_path_cannot_be_reused_as_gate_origin_or_source(self):
        for cls, factory in DOCUMENTS[1:]:
            key = "origin_evidence" if cls in (PriceContinuitySource, TradingCostSource) else "source_evidence"
            self.assert_rejects(cls, factory, lambda row: row.update({key: [row["dataset_evidence"]]}))

    def test_review_notes_and_limitations_require_explicit_bounded_text(self):
        for cls, factory in DOCUMENTS[1:]:
            for value in ([], ["same", "same"], [" "], ["a" * 10001], ["item-%02d" % index for index in range(33)]):
                self.assert_rejects(cls, factory, lambda row: row.update(limitations=value))
        for cls, factory in DOCUMENTS[1:3]:
            for value in (None, " ", " leading", "bad\nline"):
                self.assert_rejects(cls, factory, lambda row: row.update(review_notes=value))

    def test_coverage_identities_are_not_inferred_or_repaired(self):
        for cls, factory in DOCUMENTS[1:]:
            for field in ("coverage_start_session_id", "coverage_end_session_id"):
                for value in (None, "", "../session"):
                    self.assert_rejects(cls, factory, lambda row: row.update({field: value}))

    def test_timestamps_require_real_rfc3339_supported_precision(self):
        for cls, factory in DOCUMENTS:
            key = "registered_at" if cls is TradingShadowStudy else "recorded_at"
            for value in ("2026-02-30T00:00:00Z", "2026-01-20", "2026-01-20T00:00:00.1234567Z", None):
                self.assert_rejects(cls, factory, lambda row: row.update({key: value}))

    def test_timestamp_offset_normalizes_without_backdating(self):
        row = study_mapping()
        row["registered_at"] = "2026-01-19T19:00:00-05:00"
        self.assertEqual(TradingShadowStudy.from_mapping(row).registered_at, "2026-01-20T00:00:00Z")

    def test_malformed_json_duplicates_nonfinite_nonobject_and_utf8_reject(self):
        for cls, _ in DOCUMENTS:
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'null', b'\xff'):
                with self.subTest(cls=cls.__name__, raw=raw), self.assertRaises(ContractValidationError):
                    cls.from_bytes(raw)

    def test_deep_json_parser_overflow_is_bounded(self):
        for cls, _ in DOCUMENTS:
            with self.assertRaises(ContractValidationError):
                cls.from_bytes(b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}')


if __name__ == "__main__":
    unittest.main()
