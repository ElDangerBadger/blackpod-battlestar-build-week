"""Strict inactive forecast contracts reject ambiguity and executable authority."""
from __future__ import annotations

import copy
import unittest

from blackpod_build_week.contracts.forecast_intake import (
    ForecastIntake, validate_forecast_provenance, validate_forecast_result,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from test_forecast_intake_engine import ForecastIntakeFixture


class ForecastIntakeContractTests(unittest.TestCase):
    def setUp(self): self.fx = ForecastIntakeFixture()
    def reject(self, value):
        with self.assertRaises(ContractValidationError): ForecastIntake.from_mapping(value)
    def reject_provenance(self, value):
        with self.assertRaises(ContractValidationError): validate_forecast_provenance(value)
    def reject_result(self, value):
        with self.assertRaises(ContractValidationError): validate_forecast_result(value, self.fx.document)

    def test_round_trip_and_nested_immutability(self):
        value = self.fx.document.to_mapping()
        value["sources"][0]["source_id"] = "changed"
        self.assertEqual(self.fx.document.sources[0]["source_id"], "fixture-spy")
        self.assertEqual(ForecastIntake.from_bytes(self.fx.document.to_bytes()).to_bytes(), self.fx.document.to_bytes())

    def test_unknown_or_missing_fields_rejected(self):
        value = self.fx.document.to_mapping(); value["confidence_probability"] = "0.9"; self.reject(value)
        value = self.fx.document.to_mapping(); del value["domain"]; self.reject(value)

    def test_only_two_decision_horizons_and_shadow_mode(self):
        for field, values in (("domain", ["CAPITAL_ALLOCATION", "UNCLASSIFIED", "trading"]), ("mode", ["PAPER", "LIVE"]),
                              ("scope", ["AUTHORIZE_FORECAST", "EXECUTION"]), ("schema_version", ["old", 1])):
            for candidate in values:
                with self.subTest(field=field, candidate=candidate):
                    value = self.fx.document.to_mapping(); value[field] = candidate; self.reject(value)

    def test_all_authority_fields_must_remain_false(self):
        for field in self.fx.document.authority:
            value = self.fx.document.to_mapping(); value["authority"][field] = True; self.reject(value)
            value = self.fx.document.to_mapping(); value["authority"][field] = 0; self.reject(value)

    def test_recorded_time_cannot_precede_shadow_time(self):
        value = self.fx.document.to_mapping(); value["recorded_at"] = "2026-10-12T20:59:59Z"; self.reject(value)

    def test_microsecond_precision_not_silently_lost(self):
        value = self.fx.document.to_mapping(); value["shadow_as_of"] = "2026-10-12T21:00:00.0000001Z"; self.reject(value)

    def test_naive_or_missing_timezone_rejected(self):
        value = self.fx.document.to_mapping(); value["recorded_at"] = "2026-10-12T21:00:00"; self.reject(value)

    def test_fixed_policy_cannot_be_loosened(self):
        for field, candidate in (("max_forecast_age_seconds", 86401), ("max_feature_age_seconds", True),
            ("max_training_age_seconds", "86400"), ("allowed_horizon_sessions", [1, 2, 3, 4, 6]), ("interface_version", "RETURNS_V1")):
            value = self.fx.document.to_mapping(); value["policy"][field] = candidate; self.reject(value)

    def test_bool_horizons_not_integer_aliases(self):
        value = self.fx.document.to_mapping(); value["policy"]["allowed_horizon_sessions"][0] = True; self.reject(value)

    def test_duplicate_source_identity_or_hash_rejected(self):
        value = self.fx.document.to_mapping(); value["sources"].append(copy.deepcopy(value["sources"][0])); self.reject(value)
        value["sources"][1]["source_id"] = "different"; self.reject(value)

    def test_unknown_source_format_rejected(self):
        value = self.fx.document.to_mapping(); value["sources"][0]["format"] = "PICKLE_MODEL"; self.reject(value)

    def test_path_traversal_or_reserved_input_rejected(self):
        for path in ("../forecast.csv", "/forecast.csv", "forecast-intake/input.v1.json"):
            value = self.fx.document.to_mapping(); value["sources"][0]["evidence"]["path"] = path; self.reject(value)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(ContractValidationError):
            ForecastIntake.from_bytes(b'{"schema_version":"one","schema_version":"two"}')

    def test_provenance_quantile_probability_alias_not_supported(self):
        value = copy.deepcopy(self.fx.manifest); value["confidence_probability"] = "0.8"; self.reject_provenance(value)

    def test_metadata_units_returns_and_percents_rejected(self):
        for invalid in ("RETURN_PERCENT", "PROBABILITY", "USD", "PRICE"):
            value = copy.deepcopy(self.fx.manifest); value["rows"][0]["units"] = invalid; self.reject_provenance(value)

    def test_horizon_requires_trading_sessions_explicitly(self):
        value = copy.deepcopy(self.fx.manifest); value["rows"][0]["horizon_unit"] = "CALENDAR_DAY"; self.reject_provenance(value)
        value = copy.deepcopy(self.fx.manifest); value["rows"][0]["horizon_count"] = True; self.reject_provenance(value)

    def test_provenance_rows_cannot_duplicate_source_numbers(self):
        value = copy.deepcopy(self.fx.manifest); value["rows"].append(copy.deepcopy(value["rows"][0])); self.reject_provenance(value)

    def test_reference_price_requires_timestamp_and_finite_positive_decimal(self):
        value = copy.deepcopy(self.fx.manifest); value["rows"][0]["reference_at"] = None; self.reject_provenance(value)
        for invalid in (100.0, True, "NaN", "0", "-1"):
            value = copy.deepcopy(self.fx.manifest); value["rows"][0]["reference_price"] = invalid; self.reject_provenance(value)

    def test_optional_unknown_metadata_null_is_preserved(self):
        value = copy.deepcopy(self.fx.manifest)
        value["reviewed_by"] = value["reviewed_at"] = None
        value["model"] = {key: None for key in value["model"]}
        for row in value["rows"]:
            for key in set(row) - {"symbol", "source_row_number"}: row[key] = None
        parsed = validate_forecast_provenance(value)
        self.assertIsNone(parsed["rows"][0]["issued_at"])

    def test_result_authority_or_auto_switch_cannot_be_on(self):
        value = self.fx.result(); value["auto_trading_enabled"] = True; self.reject_result(value)
        value = self.fx.result(); value["authority"]["execution_enabled"] = True; self.reject_result(value)

    def test_result_cannot_fabricate_realized_outcome_or_evaluation(self):
        for field in ("realized_outcome", "evaluation"):
            value = self.fx.result(); value["rows"][0][field] = {"pnl": "1"}; self.reject_result(value)

    def test_result_counts_must_bind_projected_sources(self):
        value = self.fx.result(); value["admitted_count"] = 0; self.reject_result(value)
        value = self.fx.result(); value["source_summaries"][0]["admitted_count"] -= 1
        value["source_summaries"][0]["deferred_count"] += 1; self.reject_result(value)

    def test_result_unique_source_row_and_evidence_required(self):
        value = self.fx.result(); value["rows"][1]["source_row_number"] = 1; self.reject_result(value)
        value = self.fx.result(); value["rows"][0]["source_evidence"]["sha256"] = "0" * 64; self.reject_result(value)

    def test_admitted_row_cannot_have_missing_model_or_deferral_reason(self):
        value = self.fx.result(); value["rows"][0]["model_id"] = None; self.reject_result(value)
        value = self.fx.result(); value["rows"][0]["reason_codes"] = ["STALE_FORECAST"]; self.reject_result(value)

    def test_deferred_row_requires_reason(self):
        value = self.fx.result(); value["rows"][0]["gate"] = "DEFER"; self.reject_result(value)

    def test_result_rejects_executable_orders_or_calibrated_probability_fields(self):
        for field in ("order", "authorization", "confidence_probability"):
            value = self.fx.result(); value["rows"][0][field] = "BUY"; self.reject_result(value)


if __name__ == "__main__": unittest.main()
