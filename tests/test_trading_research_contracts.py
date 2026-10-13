"""Adversarial strictness and structural-binding checks for offline research."""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_research import (
    TradingResearchDataset, TradingResearchIntents, TradingResearchPlan,
    research_symbol, validate_research_inputs,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


def authority():
    return {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def ref(path, raw=b"retained synthetic source"):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def dataset_mapping():
    sessions = []
    for index in range(14):
        day = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        stamp = lambda hour: day.replace(hour=hour).isoformat().replace("+00:00", "Z")
        sessions.append({"session_id": "session-%02d" % index, "open_at": stamp(14), "close_at": stamp(20),
                         "available_at": stamp(21), "bars": [{"symbol": "SYNTH", "open": "100", "high": "104",
                                                               "low": "98", "close": "102", "volume": "1000"}]})
    return {"schema_version": "blackpod.trading_research_dataset.v1", "dataset_id": "dataset-contract-test",
            "recorded_at": "2026-01-16T00:00:00Z", "universe": ["SYNTH"],
            "provenance": {"source_kind": "SYNTHETIC_FIXTURE", "source_evidence": [ref("source.json")],
                           "timestamp_policy": "SYNTHETIC_DECLARED", "historical_point_in_time_verified": False},
            "sessions": sessions, "authority": authority()}


def intents_mapping():
    return {"schema_version": "blackpod.trading_research_intents.v1", "intent_set_id": "intent-contract-test",
            "plan_id": "plan-contract-test", "created_at": "2026-01-17T00:00:00Z",
            "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [
                {"decision_id": "decision-buy", "fold_id": "fold-001", "source_session_id": "session-07",
                 "decision_at": "2026-01-09T13:00:00Z", "action": "BUY", "symbol": "SYNTH", "qty": "2"},
                {"decision_id": "decision-sell", "fold_id": "fold-001", "source_session_id": "session-08",
                 "decision_at": "2026-01-10T13:00:00Z", "action": "SELL", "symbol": "SYNTH", "qty": "1"}],
            "authority": authority()}


def plan_mapping():
    return {"schema_version": "blackpod.trading_research_plan.v1", "plan_id": "plan-contract-test",
            "experiment_id": "experiment-contract-test", "registered_at": "2026-01-18T00:00:00Z",
            "domain": "TRADING", "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
            "strategy": {"strategy_id": "new-independent-specification", "version": "1.0",
                         "hypothesis": "Synthetic externally authored quantities exercise the evaluator.",
                         "expected_edge": "No economic edge is claimed for this fixture.",
                         "falsification_conditions": ["Accounting does not replay exactly."],
                         "ancestry": "INDEPENDENT_NEW_RESEARCH_SPECIFICATION", "implementation_status": "EXTERNAL_INTENTS_ONLY"},
            "universe": ["SYNTH"], "horizon": {"kind": "SWING", "max_holding_sessions": 5, "label_horizon_sessions": 1},
            "dataset_evidence": ref("dataset.json", canonical_json_bytes(dataset_mapping())),
            "intents_evidence": ref("intents.json", canonical_json_bytes(intents_mapping())),
            "protocol": {"folds": [{"fold_id": "fold-001", "train": {"start_index": 0, "end_index": 2},
                                    "validation": {"start_index": 4, "end_index": 5}, "test": {"start_index": 7, "end_index": 10}}],
                         "embargo_sessions": 1, "final_holdout": {"start_index": 12, "end_index": 13}},
            "cost_model": {"spread_bps": "2", "slippage_bps": "1", "fee_bps": "1", "fee_per_fill": "0.10"},
            "risk": {"initial_cash": "1000", "max_order_notional": "500", "max_position_fraction": "0.5",
                     "max_gross_exposure_fraction": "0.8", "max_volume_participation_fraction": "0.01", "max_staleness_seconds": 86400},
            "benchmark": {"kind": "CASH"}, "trial_registry": {"trial_id": "trial-contract-test", "prior_trial_ids": []},
            "auto_trading_enabled": False, "authority": authority()}


class TradingResearchContractTests(unittest.TestCase):
    def assert_plan_rejects(self, mutate):
        value = plan_mapping(); mutate(value)
        with self.assertRaises(ContractValidationError): TradingResearchPlan.from_mapping(value)

    def assert_dataset_rejects(self, mutate):
        value = dataset_mapping(); mutate(value)
        with self.assertRaises(ContractValidationError): TradingResearchDataset.from_mapping(value)

    def assert_intents_rejects(self, mutate):
        value = intents_mapping(); mutate(value)
        with self.assertRaises(ContractValidationError): TradingResearchIntents.from_mapping(value)

    def test_all_three_contracts_round_trip_canonical_bytes(self):
        for cls, factory in ((TradingResearchPlan, plan_mapping), (TradingResearchDataset, dataset_mapping),
                             (TradingResearchIntents, intents_mapping)):
            with self.subTest(cls=cls.__name__):
                document = cls.from_mapping(factory())
                self.assertEqual(cls.from_bytes(document.to_bytes()).to_dict(), document.to_dict())
                self.assertEqual(cls.from_bytes(document.to_bytes()).to_bytes(), document.to_bytes())

    def test_documents_and_nested_getters_are_immutable(self):
        for cls, factory, key in ((TradingResearchPlan, plan_mapping, "strategy"),
                                  (TradingResearchDataset, dataset_mapping, "sessions"),
                                  (TradingResearchIntents, intents_mapping, "decisions")):
            with self.subTest(cls=cls.__name__):
                value = factory(); document = cls.from_mapping(value); original = document.to_bytes()
                value[key].clear(); getattr(document, key).clear(); document.to_dict().clear()
                self.assertEqual(document.to_bytes(), original)

    def test_unknown_and_missing_top_level_fields_reject(self):
        for cls, factory in ((TradingResearchPlan, plan_mapping), (TradingResearchDataset, dataset_mapping), (TradingResearchIntents, intents_mapping)):
            for mutation in (lambda row: row.update(execute=True), lambda row: row.pop("schema_version")):
                value = factory(); mutation(value)
                with self.subTest(cls=cls.__name__), self.assertRaises(ContractValidationError): cls.from_mapping(value)

    def test_unknown_nested_fields_reject(self):
        for field in ("strategy", "horizon", "protocol", "cost_model", "risk", "benchmark", "trial_registry", "dataset_evidence"):
            with self.subTest(field=field): self.assert_plan_rejects(lambda row: row[field].update(legacy_rule=True))
        self.assert_dataset_rejects(lambda row: row["provenance"].update(verified=True))
        self.assert_dataset_rejects(lambda row: row["sessions"][0].update(decision=True))
        self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"][0].update(signal="BUY"))
        self.assert_intents_rejects(lambda row: row["decisions"][0].update(approved=True))

    def test_contract_versions_reject_unknown_successors(self):
        for cls, factory in ((TradingResearchPlan, plan_mapping), (TradingResearchDataset, dataset_mapping), (TradingResearchIntents, intents_mapping)):
            value = factory(); value["schema_version"] = value["schema_version"].replace(".v1", ".v2")
            with self.subTest(cls=cls.__name__), self.assertRaises(ContractValidationError): cls.from_mapping(value)

    def test_live_paper_and_investment_modes_cannot_be_requested(self):
        for field, value in (("mode", "LIVE"), ("mode", "PAPER"), ("mode", "SHADOW"), ("domain", "INVESTMENT"),
                             ("scope", "EXECUTION_ONLY"), ("auto_trading_enabled", True), ("auto_trading_enabled", 0)):
            with self.subTest(field=field, value=value): self.assert_plan_rejects(lambda row: row.update({field: value}))

    def test_each_authority_flag_is_disabled_in_every_contract(self):
        for cls, factory in ((TradingResearchPlan, plan_mapping), (TradingResearchDataset, dataset_mapping), (TradingResearchIntents, intents_mapping)):
            for field in authority():
                for value in (True, 0, "false"):
                    row = factory(); row["authority"][field] = value
                    with self.subTest(cls=cls.__name__, field=field, value=value), self.assertRaises(ContractValidationError): cls.from_mapping(row)

    def test_identity_fields_reject_blank_and_path_injection(self):
        for field in ("plan_id", "experiment_id"):
            self.assert_plan_rejects(lambda row: row.update({field: "../other"}))
        self.assert_dataset_rejects(lambda row: row.update(dataset_id=""))
        self.assert_intents_rejects(lambda row: row["decisions"][0].update(decision_id="../order"))

    def test_research_symbol_validation_is_independent_and_path_safe(self):
        for symbol in ("spy", "../SPY", "A..B", "BTC/USD", "", "-SPY", "A" * 33, 123, True):
            with self.subTest(symbol=symbol), self.assertRaises(ContractValidationError): research_symbol(symbol)
        for symbol in ("SPY", "BRK.B", "SYNTH-1"):
            self.assertEqual(research_symbol(symbol), symbol)

    def test_universe_rejects_duplicate_unsorted_empty_and_oversize(self):
        for value in ([], ["SYNTH", "SYNTH"], ["ZZZ", "AAA"], ["spy"], ["S%02d" % index for index in range(9)]):
            with self.subTest(value=value):
                self.assert_plan_rejects(lambda row: row.update(universe=value))
                self.assert_dataset_rejects(lambda row: row.update(universe=value))

    def test_no_legacy_strategy_ancestry_or_implemented_rules_claim(self):
        self.assert_plan_rejects(lambda row: row["strategy"].update(ancestry="GALACTICA"))
        self.assert_plan_rejects(lambda row: row["strategy"].update(implementation_status="IMPLEMENTED"))
        self.assert_intents_rejects(lambda row: row.update(origin="NAVIGATOR_ORDER"))

    def test_hypothesis_expected_edge_and_falsification_must_be_explicit(self):
        for field in ("hypothesis", "expected_edge", "version"):
            self.assert_plan_rejects(lambda row: row["strategy"].update({field: " "}))
        for conditions in ([], [""], ["same", "same"], ["condition-%02d" % index for index in range(33)]):
            with self.subTest(conditions=conditions): self.assert_plan_rejects(lambda row: row["strategy"].update(falsification_conditions=conditions))

    def test_horizon_counts_are_bounded_true_integers(self):
        for field in ("max_holding_sessions", "label_horizon_sessions"):
            for value in (0, 21, True, "1", 1.0):
                with self.subTest(field=field, value=value): self.assert_plan_rejects(lambda row: row["horizon"].update({field: value}))
        self.assert_plan_rejects(lambda row: row["horizon"].update(kind="INVESTMENT"))

    def test_day_is_declared_but_not_granted_execution_authority(self):
        value = plan_mapping(); value["horizon"]["kind"] = "DAY"
        document = TradingResearchPlan.from_mapping(value)
        self.assertEqual(document.horizon["kind"], "DAY")
        self.assertFalse(any(document.authority.values()))

    def test_evidence_paths_hashes_sizes_and_collisions_are_strict(self):
        for field, value in (("path", "../dataset.json"), ("sha256", "not-a-hash"), ("size_bytes", True), ("size_bytes", -1)):
            with self.subTest(field=field): self.assert_plan_rejects(lambda row: row["dataset_evidence"].update({field: value}))
        self.assert_plan_rejects(lambda row: row.update(intents_evidence=row["dataset_evidence"]))

    def test_indices_are_inclusive_nonempty_bounded_integers(self):
        for value in (-1, 10000, True, 0.0, "0"):
            with self.subTest(value=value): self.assert_plan_rejects(lambda row: row["protocol"]["folds"][0]["train"].update(start_index=value))
        self.assert_plan_rejects(lambda row: row["protocol"]["folds"][0]["train"].update(start_index=3))
        value = plan_mapping(); value["protocol"]["folds"][0]["train"]["end_index"] = 0
        self.assertEqual(TradingResearchPlan.from_mapping(value).protocol["folds"][0]["train"]["end_index"], 0)

    def test_every_fold_is_chronological_and_embargoed(self):
        for mutate in (lambda row: row["protocol"]["folds"][0]["validation"].update(start_index=2),
                       lambda row: row["protocol"]["folds"][0]["validation"].update(start_index=3),
                       lambda row: row["protocol"]["folds"][0]["test"].update(start_index=5),
                       lambda row: row["protocol"].update(embargo_sessions=2)):
            self.assert_plan_rejects(mutate)

    def test_folds_must_be_nonempty_distinct_bounded(self):
        self.assert_plan_rejects(lambda row: row["protocol"].update(folds=[]))
        self.assert_plan_rejects(lambda row: row["protocol"]["folds"].append(copy.deepcopy(row["protocol"]["folds"][0])))
        self.assert_plan_rejects(lambda row: row["protocol"]["folds"][0].update(extra=True))

    def test_multiple_fold_tests_are_disjoint_and_ordered(self):
        value = plan_mapping(); fold = copy.deepcopy(value["protocol"]["folds"][0]); fold["fold_id"] = "fold-002"
        value["protocol"]["folds"].append(fold)
        with self.assertRaises(ContractValidationError): TradingResearchPlan.from_mapping(value)
        fold["test"] = {"start_index": 11, "end_index": 11}
        self.assertEqual(len(TradingResearchPlan.from_mapping(value).protocol["folds"]), 2)

    def test_final_holdout_follows_all_test_ranges(self):
        self.assert_plan_rejects(lambda row: row["protocol"]["final_holdout"].update(start_index=10))
        self.assert_plan_rejects(lambda row: row["protocol"]["final_holdout"].update(start_index=14))

    def test_embargo_has_no_boolean_or_negative_alias(self):
        for value in (-1, 101, True, "1"):
            with self.subTest(value=value): self.assert_plan_rejects(lambda row: row["protocol"].update(embargo_sessions=value))

    def test_costs_are_exact_nonnegative_decimal_strings(self):
        for field in ("spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"):
            for value in (-1, True, 0.1, "-0.1", "1e-2", "NaN", "Infinity", "00.1", "0.0000000000000000001"):
                with self.subTest(field=field, value=value): self.assert_plan_rejects(lambda row: row["cost_model"].update({field: value}))
        for field in ("spread_bps", "slippage_bps", "fee_bps"):
            self.assert_plan_rejects(lambda row: row["cost_model"].update({field: "1000.0001"}))

    def test_zero_cost_assumption_is_explicit_and_supported(self):
        value = plan_mapping(); value["cost_model"] = {field: "0" for field in value["cost_model"]}
        self.assertEqual(TradingResearchPlan.from_mapping(value).cost_model, value["cost_model"])

    def test_risk_cash_notional_and_fractions_are_bounded(self):
        for field in ("initial_cash", "max_order_notional", "max_position_fraction", "max_gross_exposure_fraction", "max_volume_participation_fraction"):
            for value in ("0", "-1", 100, True):
                with self.subTest(field=field, value=value): self.assert_plan_rejects(lambda row: row["risk"].update({field: value}))
        for field in ("max_position_fraction", "max_gross_exposure_fraction", "max_volume_participation_fraction"):
            self.assert_plan_rejects(lambda row: row["risk"].update({field: "1.0000001"}))

    def test_staleness_requires_positive_bounded_integer_seconds(self):
        for value in (0, -1, True, "86400", 366 * 86400 + 1):
            with self.subTest(value=value): self.assert_plan_rejects(lambda row: row["risk"].update(max_staleness_seconds=value))

    def test_cash_is_only_implemented_benchmark(self):
        self.assert_plan_rejects(lambda row: row["benchmark"].update(kind="GALACTICA"))
        self.assert_plan_rejects(lambda row: row["benchmark"].update(kind="SPY_BUY_AND_HOLD"))

    def test_prior_trials_are_declared_unique_and_cannot_include_current(self):
        for prior in (["old", "old"], ["trial-contract-test"], ["../old"]):
            with self.subTest(prior=prior): self.assert_plan_rejects(lambda row: row["trial_registry"].update(prior_trial_ids=prior))
        value = plan_mapping(); value["trial_registry"]["prior_trial_ids"] = ["failed-prior-trial"]
        self.assertEqual(TradingResearchPlan.from_mapping(value).trial_registry["prior_trial_ids"], ["failed-prior-trial"])

    def test_timestamp_normalization_and_precision_are_consistent(self):
        value = plan_mapping(); value["registered_at"] = "2026-01-18T01:00:00+01:00"
        self.assertEqual(TradingResearchPlan.from_mapping(value).registered_at, "2026-01-18T00:00:00Z")
        for timestamp in ("2026-01-18", "2026-01-18T00:00:00", "2026-01-18T00:00:00.1234567Z"):
            self.assert_plan_rejects(lambda row: row.update(registered_at=timestamp))

    def test_dataset_completed_clocks_cannot_be_backdated(self):
        for field, value in (("close_at", "2026-01-01T14:00:00Z"), ("available_at", "2026-01-01T19:59:59Z"),
                             ("available_at", "2026-01-17T00:00:00Z")):
            with self.subTest(field=field): self.assert_dataset_rejects(lambda row: row["sessions"][0].update({field: value}))

    def test_session_order_overlap_duplicates_and_empty_reject(self):
        self.assert_dataset_rejects(lambda row: row.update(sessions=[]))
        self.assert_dataset_rejects(lambda row: row["sessions"].reverse())
        self.assert_dataset_rejects(lambda row: row["sessions"][1].update(session_id=row["sessions"][0]["session_id"]))
        self.assert_dataset_rejects(lambda row: row["sessions"][1].update(open_at=row["sessions"][0]["close_at"]))

    def test_bars_require_complete_rectangular_sorted_universe(self):
        self.assert_dataset_rejects(lambda row: row["sessions"][0].update(bars=[]))
        self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"].append(copy.deepcopy(row["sessions"][0]["bars"][0])))
        self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"][0].update(symbol="OTHER"))
        self.assert_dataset_rejects(lambda row: row.update(universe=["SYNTH", "ZZZ"]))

    def test_ohlc_prices_and_volume_require_exact_valid_numbers(self):
        for field in ("open", "high", "low", "close"):
            for value in ("0", "-1", "NaN", 100.0, True):
                with self.subTest(field=field, value=value): self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"][0].update({field: value}))
        self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"][0].update(volume="-1"))

    def test_ohlc_internal_range_consistency_rejects_impossible_bars(self):
        for field, value in (("low", "105"), ("high", "99"), ("open", "105"), ("close", "97")):
            with self.subTest(field=field): self.assert_dataset_rejects(lambda row: row["sessions"][0]["bars"][0].update({field: value}))

    def test_zero_volume_is_explicit_evidence_not_missing_data(self):
        value = dataset_mapping(); value["sessions"][0]["bars"][0]["volume"] = "0"
        self.assertEqual(TradingResearchDataset.from_mapping(value).sessions[0]["bars"][0]["volume"], "0")

    def test_source_kind_requires_its_corresponding_timestamp_policy(self):
        self.assert_dataset_rejects(lambda row: row["provenance"].update(source_kind="ALPACA_LIVE"))
        self.assert_dataset_rejects(lambda row: row["provenance"].update(source_kind="RETAINED_MARKET_CAPTURE"))
        value = dataset_mapping(); value["provenance"].update(source_kind="RETAINED_MARKET_CAPTURE", timestamp_policy="RETAINED_RECEIPT_AVAILABILITY")
        self.assertEqual(TradingResearchDataset.from_mapping(value).provenance["source_kind"], "RETAINED_MARKET_CAPTURE")

    def test_point_in_time_authentication_is_never_claimed(self):
        for value in (True, 0, None):
            with self.subTest(value=value): self.assert_dataset_rejects(lambda row: row["provenance"].update(historical_point_in_time_verified=value))

    def test_source_evidence_must_be_nonempty_distinct_and_valid(self):
        self.assert_dataset_rejects(lambda row: row["provenance"].update(source_evidence=[]))
        self.assert_dataset_rejects(lambda row: row["provenance"]["source_evidence"].append(row["provenance"]["source_evidence"][0]))
        self.assert_dataset_rejects(lambda row: row["provenance"]["source_evidence"][0].update(path="/absolute/source"))

    def test_retrospective_capture_time_is_retained_not_invented_at_close(self):
        value = dataset_mapping(); value["provenance"].update(source_kind="RETAINED_MARKET_CAPTURE", timestamp_policy="RETAINED_RECEIPT_AVAILABILITY")
        for session in value["sessions"]: session["available_at"] = value["recorded_at"]
        document = TradingResearchDataset.from_mapping(value)
        self.assertEqual({row["available_at"] for row in document.sessions}, {value["recorded_at"]})
        self.assertFalse(document.provenance["historical_point_in_time_verified"])

    def test_intent_actions_preserve_research_only_semantics(self):
        for action in ("STRONG BUY", "buy", "EXIT", "AUTHORIZE", "EXECUTE"):
            with self.subTest(action=action): self.assert_intents_rejects(lambda row: row["decisions"][0].update(action=action))

    def test_buy_sell_whole_quantities_have_no_float_boolean_or_fraction_alias(self):
        for value in (0, True, "0", "-1", "1.0", "0.5", "01", "1e2", "9" * 21):
            with self.subTest(value=value): self.assert_intents_rejects(lambda row: row["decisions"][0].update(qty=value))

    def test_hold_requires_exact_zero_and_empty_intents_are_permitted(self):
        value = intents_mapping(); value["decisions"][0].update(action="HOLD", qty="0")
        self.assertEqual(TradingResearchIntents.from_mapping(value).decisions[0]["qty"], "0")
        for qty in (0, "0.0", "1", True):
            self.assert_intents_rejects(lambda row: row["decisions"][0].update(action="HOLD", qty=qty))
        value["decisions"] = []
        self.assertEqual(TradingResearchIntents.from_mapping(value).decisions, [])

    def test_duplicate_decision_identifiers_reject(self):
        self.assert_intents_rejects(lambda row: row["decisions"][1].update(decision_id=row["decisions"][0]["decision_id"]))

    def test_strict_json_rejects_duplicate_fields_nonfinite_and_nonobject(self):
        for cls in (TradingResearchPlan, TradingResearchDataset, TradingResearchIntents):
            for raw in (b'{"schema_version":"x","schema_version":"y"}', b'{"v":NaN}', b'{"v":Infinity}', b'[]', b'null', b'\xff'):
                with self.subTest(cls=cls.__name__, raw=raw), self.assertRaises(ContractValidationError): cls.from_bytes(raw)

    def test_crossbinding_returns_typed_immutable_documents(self):
        plan, dataset, intents = validate_research_inputs(plan_mapping(), dataset_mapping(), intents_mapping())
        self.assertIsInstance(plan, TradingResearchPlan)
        self.assertIsInstance(dataset, TradingResearchDataset)
        self.assertIsInstance(intents, TradingResearchIntents)

    def test_crossbinding_refuses_different_plan_and_universe(self):
        intents = intents_mapping(); intents["plan_id"] = "other-plan"
        with self.assertRaises(ContractValidationError): validate_research_inputs(plan_mapping(), dataset_mapping(), intents)
        plan = plan_mapping(); plan["universe"] = ["OTHER"]
        with self.assertRaises(ContractValidationError): validate_research_inputs(plan, dataset_mapping(), intents_mapping())

    def test_crossbinding_refuses_partition_outside_retained_session_count(self):
        plan = plan_mapping(); plan["protocol"]["final_holdout"]["end_index"] = 14
        with self.assertRaises(ContractValidationError): validate_research_inputs(plan, dataset_mapping(), intents_mapping())

    def test_crossbinding_refuses_unknown_structural_decision_references(self):
        for field, value in (("fold_id", "unknown-fold"), ("source_session_id", "unknown-session"), ("symbol", "OTHER")):
            intents = intents_mapping(); intents["decisions"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_research_inputs(plan_mapping(), dataset_mapping(), intents)

    def test_economically_invalid_intents_remain_recordable_for_explicit_rejection(self):
        for changes in ({"qty": "9999999999"}, {"decision_at": "2025-01-01T00:00:00Z"},
                        {"source_session_id": "session-13", "decision_at": "2026-01-15T00:00:00Z"}):
            intents = intents_mapping(); intents["decisions"][0].update(changes)
            with self.subTest(changes=changes):
                validated = validate_research_inputs(plan_mapping(), dataset_mapping(), intents)
                self.assertEqual(validated[2].decisions[0], intents["decisions"][0])


if __name__ == "__main__": unittest.main()
