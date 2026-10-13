"""Strict research-only hypothesis declarations and frozen recipe boundaries."""
import copy
import json
import unittest

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_hypothesis import (
    HYPOTHESIS_FAMILIES, TradingHypothesis, TradingHypothesisCatalog,
)
from blackpod_build_week.trading_hypotheses import catalog_hypotheses


STAMP = "2026-10-13T00:00:00Z"


def catalog_mapping():
    return catalog_hypotheses(STAMP, "research-reviewer").to_dict()


def hypothesis_mapping(family="PREVIOUS_SESSION_REVERSAL"):
    return next(row for row in catalog_mapping()["hypotheses"] if row["signal"]["family"] == family)


class TradingHypothesisContractTests(unittest.TestCase):
    def reject_hypothesis(self, mutation):
        value = hypothesis_mapping()
        mutation(value)
        with self.assertRaises(ContractValidationError):
            TradingHypothesis.from_mapping(value)

    def reject_catalog(self, mutation):
        value = catalog_mapping()
        mutation(value)
        with self.assertRaises(ContractValidationError):
            TradingHypothesisCatalog.from_mapping(value)

    def test_catalog_and_both_documents_canonical_round_trip(self):
        catalog = TradingHypothesisCatalog.from_mapping(catalog_mapping())
        self.assertEqual(TradingHypothesisCatalog.from_bytes(catalog.to_bytes()).to_bytes(), catalog.to_bytes())
        for row in catalog.hypotheses:
            document = TradingHypothesis.from_mapping(row)
            self.assertEqual(TradingHypothesis.from_bytes(document.to_bytes()).to_dict(), row)

    def test_nested_input_and_output_mutations_do_not_change_documents(self):
        value = catalog_mapping()
        document = TradingHypothesisCatalog.from_mapping(value)
        raw = document.to_bytes()
        value["hypotheses"][0]["signal"].clear()
        document.hypotheses[0]["test_protocol"].clear()
        document.to_dict().clear()
        self.assertEqual(document.to_bytes(), raw)
        hypothesis = TradingHypothesis.from_mapping(hypothesis_mapping())
        raw = hypothesis.to_bytes()
        hypothesis.mechanism["assumptions"].clear()
        self.assertEqual(hypothesis.to_bytes(), raw)

    def test_missing_top_level_fields_reject(self):
        for cls, factory in ((TradingHypothesis, hypothesis_mapping), (TradingHypothesisCatalog, catalog_mapping)):
            for field in factory():
                value = factory(); value.pop(field)
                with self.subTest(document=cls.__name__, field=field), self.assertRaises(ContractValidationError):
                    cls.from_mapping(value)

    def test_unknown_fields_cannot_smuggle_legacy_or_execution_instructions(self):
        for field in ("galactica_rules", "brigade_votes", "executable_order", "investment_authorization", "auto_select"):
            with self.subTest(field=field):
                self.reject_hypothesis(lambda value: value.update({field: True}))
                self.reject_catalog(lambda value: value.update({field: True}))

    def test_unknown_nested_fields_reject(self):
        for field in ("mechanism", "signal", "horizon", "data_requirements", "exposure_policy", "test_protocol"):
            with self.subTest(field=field):
                self.reject_hypothesis(lambda value: value[field].update(legacy_threshold=1))
        self.reject_hypothesis(lambda value: value["alternatives"][0].update(decision="BUY"))
        self.reject_hypothesis(lambda value: value["test_protocol"]["benchmarks"][0].update(score="0.4"))

    def test_versions_and_unknown_families_reject(self):
        self.reject_hypothesis(lambda value: value.update(schema_version="blackpod.trading_hypothesis.v2"))
        self.reject_hypothesis(lambda value: value.update(specification_version="2"))
        self.reject_catalog(lambda value: value.update(schema_version="blackpod.trading_hypothesis_catalog.v2"))
        self.reject_hypothesis(lambda value: value["signal"].update(family="NAVIGATOR_TRAILING_STOP"))

    def test_all_contracts_keep_authority_and_auto_trading_disabled(self):
        for cls, factory in ((TradingHypothesis, hypothesis_mapping), (TradingHypothesisCatalog, catalog_mapping)):
            for field in factory()["authority"]:
                for forbidden in (True, 0, "false", None):
                    value = factory(); value["authority"][field] = forbidden
                    with self.subTest(document=cls.__name__, field=field, forbidden=forbidden), self.assertRaises(ContractValidationError):
                        cls.from_mapping(value)
            for forbidden in (True, 0, "false", None):
                value = factory(); value["auto_trading_enabled"] = forbidden
                with self.subTest(document=cls.__name__, auto=forbidden), self.assertRaises(ContractValidationError):
                    cls.from_mapping(value)

    def test_scope_cannot_become_paper_live_investment_or_capital_allocation(self):
        for field, forbidden in (("domain", "INVESTMENT"), ("domain", "CAPITAL_ALLOCATION"),
                                 ("mode", "PAPER"), ("mode", "LIVE"), ("scope", "EXECUTION"),
                                 ("status", "AUTHORIZED"), ("status", "VALIDATED_STRATEGY")):
            with self.subTest(field=field, value=forbidden):
                self.reject_hypothesis(lambda value: value.update({field: forbidden}))
                self.reject_catalog(lambda value: value.update({field: forbidden}))

    def test_no_legacy_ancestry_or_implemented_signal_claim(self):
        for field, forbidden in (("ancestry", "GALACTICA"), ("implementation_status", "STRATEGY_PRODUCER"),
                                 ("preregistration_claim", "HISTORICAL_PREREGISTERED")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value.update({field: forbidden}))

    def test_identity_fields_reject_paths_and_empty_strings(self):
        for field in ("hypothesis_id", "author_id"):
            for forbidden in ("", "../other", "author name"):
                with self.subTest(field=field, value=forbidden): self.reject_hypothesis(lambda value: value.update({field: forbidden}))
        for field in ("catalog_id", "author_id"):
            self.reject_catalog(lambda value: value.update({field: "../other"}))

    def test_timestamps_are_normalized_and_precision_is_not_discarded(self):
        value = hypothesis_mapping(); value["recorded_at"] = "2026-10-12T17:00:00-07:00"
        self.assertEqual(TradingHypothesis.from_mapping(value).recorded_at, STAMP)
        for forbidden in ("yesterday", "2026-10-13T00:00:00", "2026-10-13T00:00:00.0000001Z"):
            with self.subTest(value=forbidden): self.reject_hypothesis(lambda value: value.update(recorded_at=forbidden))

    def test_explicit_mechanism_and_assumptions_are_required(self):
        for field in ("statement", "proposed_causal_mechanism"):
            self.reject_hypothesis(lambda value: value["mechanism"].update({field: ""}))
        for forbidden in ([], [""], ["same", "same"], ["assumption-%d" % i for i in range(17)]):
            self.reject_hypothesis(lambda value: value["mechanism"].update(assumptions=forbidden))
        self.reject_hypothesis(lambda value: value["mechanism"].update(evidence_status="VALIDATED_EDGE"))

    def test_alternatives_are_explicit_distinct_and_bounded(self):
        self.reject_hypothesis(lambda value: value.update(alternatives=[]))
        self.reject_hypothesis(lambda value: value["alternatives"].append(copy.deepcopy(value["alternatives"][0])))
        for field in ("statement", "distinguishing_test"):
            self.reject_hypothesis(lambda value: value["alternatives"][0].update({field: ""}))
        self.reject_hypothesis(lambda value: value.update(alternatives=[{
            "alternative_id": "alternative-%d" % i, "statement": "Other explanation.", "distinguishing_test": "Compare outcomes."
        } for i in range(17)]))

    def test_recipe_lookback_formula_condition_and_identity_cannot_be_tuned(self):
        for field, forbidden in (("lookback_sessions", 2), ("lookback_sessions", True),
                                 ("formula", "EMA[t] / EMA[t-1] - 1"), ("candidate_condition", "RETURN_LT_NEGATIVE_ONE_PERCENT"),
                                 ("parameter_selection", "OPTIMIZED_ON_TEST_DATA")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["signal"].update({field: forbidden}))
        self.reject_hypothesis(lambda value: value.update(hypothesis_id="five-session-continuation-v1"))

    def test_signal_availability_no_imputation_and_zero_boundary_are_fixed(self):
        for field, forbidden in (("zero_return_behavior", "BUY"), ("input_field", "CURRENT_INCOMPLETE_CLOSE"),
                                 ("known_at_requirement", "ASSUME_DAY_START"), ("missing_input_behavior", "FORWARD_FILL")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["signal"].update({field: forbidden}))

    def test_horizon_is_a_true_integer_and_consistent_with_family(self):
        for field in ("holding_sessions", "label_horizon_sessions"):
            for forbidden in (0, 3, True, "1", 1.0):
                with self.subTest(field=field, value=forbidden): self.reject_hypothesis(lambda value: value["horizon"].update({field: forbidden}))
        for family in HYPOTHESIS_FAMILIES:
            document = TradingHypothesis.from_mapping(hypothesis_mapping(family))
            self.assertEqual(document.horizon["holding_sessions"], HYPOTHESIS_FAMILIES[family]["holding_sessions"])

    def test_entry_exit_and_nonoverlap_cannot_become_execution_rules(self):
        for field, forbidden in (("kind", "DAY"), ("entry_clock", "INTRABAR_LIMIT"),
                                 ("exit_clock", "NAVIGATOR_TRAILING_STOP"), ("overlap_policy", "PYRAMID")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["horizon"].update({field: forbidden}))

    def test_data_requirements_disallow_backdating_adjustment_guesses_and_survivorship_claims(self):
        for field, forbidden in (("bar_frequency", "INTRADAY"), ("corporate_actions", "ASSUME_NONE"),
                                 ("availability", "BAR_EVENT_TIME_IS_AVAILABILITY"), ("missing_sessions", "FILL"),
                                 ("survivorship", "MARKET_WIDE_UNBIASED"), ("universe_selection", "TOP_PERFORMERS_AFTER_TEST")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["data_requirements"].update({field: forbidden}))

    def test_exposure_cannot_activate_budgets_leverage_shorts_or_autosizing(self):
        for field, forbidden in (("capital_status", "ACTIVE"), ("leverage", "ENABLED"), ("shorts", "ENABLED"),
                                 ("size_source", "GALACTICA_POSITION_SIZE"), ("kind", "LONG_SHORT")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["exposure_policy"].update({field: forbidden}))

    def test_two_benchmarks_are_required_and_unsupported_control_is_honest(self):
        self.reject_hypothesis(lambda value: value["test_protocol"]["benchmarks"].pop())
        self.reject_hypothesis(lambda value: value["test_protocol"]["benchmarks"].reverse())
        self.reject_hypothesis(lambda value: value["test_protocol"]["benchmarks"][1].update(status="IMPLEMENTED"))
        self.reject_hypothesis(lambda value: value["test_protocol"]["benchmarks"][0].update(kind="GALACTICA_BASELINE"))

    def test_cost_stress_levels_are_frozen_and_no_missing_costs_are_invented(self):
        for forbidden in ([1, 2, 4], ["1", "1", "4"], ["1", "3"], []):
            with self.subTest(value=forbidden): self.reject_hypothesis(lambda value: value["test_protocol"].update(cost_stress_multipliers=forbidden))
        self.reject_hypothesis(lambda value: value["test_protocol"].update(cost_policy="ZERO_FEES"))

    def test_metrics_failure_rules_and_expected_tests_cannot_be_cherry_picked(self):
        for field in ("required_metrics", "failure_rules"):
            self.reject_hypothesis(lambda value: value["test_protocol"][field].pop())
            self.reject_hypothesis(lambda value: value["test_protocol"][field].append("OPTIONAL"))
        self.reject_hypothesis(lambda value: value["expected_tests"].pop())
        self.reject_hypothesis(lambda value: value.update(falsification_conditions=[]))

    def test_holdout_results_and_winner_selection_are_not_claimed(self):
        for field, forbidden in (("performance_status", "PASSED"), ("selection_policy", "PROMOTE_WINNER"),
                                 ("final_holdout", "SCORED"), ("missing_evidence_policy", "ASSUME_PASS"),
                                 ("partition_policy", "RANDOM_CROSS_VALIDATION")):
            with self.subTest(field=field): self.reject_hypothesis(lambda value: value["test_protocol"].update({field: forbidden}))
        self.reject_catalog(lambda value: value.update(selection_policy="BEST_SELECTED"))

    def test_catalog_requires_exact_two_hypotheses_without_duplicates_or_reordering(self):
        for mutate in (lambda value: value["hypotheses"].pop(), lambda value: value["hypotheses"].reverse(),
                       lambda value: value["hypotheses"].append(value["hypotheses"][0]), lambda value: value.update(hypotheses=[])):
            self.reject_catalog(mutate)

    def test_catalog_author_and_recording_clocks_bind_each_document(self):
        self.reject_catalog(lambda value: value["hypotheses"][0].update(author_id="other-author"))
        self.reject_catalog(lambda value: value["hypotheses"][0].update(recorded_at="2026-10-13T00:00:01Z"))
        value = catalog_mapping(); value["hypotheses"][0]["recorded_at"] = "2026-10-12T17:00:00-07:00"
        self.assertEqual(TradingHypothesisCatalog.from_mapping(value).hypotheses[0]["recorded_at"], STAMP)

    def test_strict_json_duplicate_keys_constants_and_non_objects_reject(self):
        for cls, factory in ((TradingHypothesis, hypothesis_mapping), (TradingHypothesisCatalog, catalog_mapping)):
            raw = json.dumps(factory()).encode()
            duplicate = raw.replace(b'{', b'{"schema_version":"smuggled",', 1)
            for forbidden in (duplicate, b'{"x": NaN}', b'{"x": Infinity}', b'[]', b'null'):
                with self.subTest(document=cls.__name__, raw=forbidden[:60]), self.assertRaises(ContractValidationError):
                    cls.from_bytes(forbidden)

    def test_frozen_family_metadata_cannot_be_mutated_by_callers(self):
        with self.assertRaises(TypeError): HYPOTHESIS_FAMILIES["OTHER"] = {}
        with self.assertRaises(TypeError): HYPOTHESIS_FAMILIES["PREVIOUS_SESSION_REVERSAL"]["lookback_sessions"] = 100


if __name__ == "__main__":
    unittest.main()
