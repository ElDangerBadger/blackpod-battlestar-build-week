import copy
import unittest

from blackpod_build_week.contracts.forecast_producer import (
    FORECAST_PRODUCER_LIMITATIONS, ForecastProducerRequest, validate_forecast_producer_export,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import sha256_bytes


def ref(path, raw=b"source"):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def request_mapping():
    return {"schema_version": "blackpod.forecast_producer_request.v1", "run_id": "producer-test-001",
        "recorded_at": "2026-10-12T21:00:00Z", "domain": "TRADING", "mode": "SHADOW",
        "scope": "SHADOW_FORECAST_PRODUCTION_ONLY", "symbols": ["SPY"], "horizons": [1, 2, 3, 4, 5],
        "sources": {"market_evidence": ref("market.json"), "calendar_evidence": ref("calendar.json"),
            "calendar_receipt_evidence": ref("receipt.json"), "native_source_evidence": [ref("native/producer.py")]},
        "authority": {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}}


def export_mapping():
    request = ForecastProducerRequest.from_mapping(request_mapping())
    result = {"schema_version": "blackpod.forecast_producer_export.v1", "run_id": request.run_id,
        "request_evidence": ref("producer-request.json", request.to_bytes()),
        "started_at": "2026-10-12T21:01:00Z", "completed_at": "2026-10-12T21:02:00Z", "issued_at": "2026-10-12T21:02:01Z",
        "status": "PRODUCED", "runtime_fingerprint": {name: "version" for name in ("python", "pandas", "numpy", "scikit-learn", "scipy")},
        "native_config_evidence": ref("native/config.json"), "model_kind": "QUANTILE_LINEAR",
        "symbol_results": [{"symbol": "SPY", "status": "PRODUCED", "reason_codes": [],
            "feature_cutoff": "2026-10-12T20:00:00Z", "reference_price": "100", "reference_at": "2026-10-12T20:00:00Z",
            "feature_evidence": ref("SPY/features.json"), "horizon_results": [{
                "horizon_count": horizon, "status": "PRODUCED", "reason_codes": [], "training_cutoff": "2026-10-12T20:00:00Z",
                **{field: ref("SPY/h%d/%s.json" % (horizon, field)) for field in (
                    "training_evidence", "model_artifact_evidence", "native_output_evidence", "forecast_evidence",
                    "provenance_evidence", "target_session_evidence")}} for horizon in request.horizons]}],
        "source_evidence": [ref("native/producer.py")], "limitations": list(FORECAST_PRODUCER_LIMITATIONS),
        "auto_trading_enabled": False, "authority": request.authority}
    return result, request


class ForecastProducerContractTests(unittest.TestCase):
    def test_request_round_trip_is_immutable(self):
        value = request_mapping(); request = ForecastProducerRequest.from_mapping(value)
        value["symbols"].append("ZZZ")
        self.assertEqual(request.symbols, ["SPY"])
        self.assertEqual(ForecastProducerRequest.from_bytes(request.to_bytes()), request)

    def test_unknown_fields_and_versions_rejected(self):
        for field, value in (("schema_version", "v2"), ("domain", "INVESTMENT"), ("mode", "PAPER"), ("scope", "EXECUTE"), ("unrecognized", False)):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                mapping = request_mapping(); mapping[field] = value; ForecastProducerRequest.from_mapping(mapping)

    def test_every_authority_flag_fails_closed(self):
        for field in request_mapping()["authority"]:
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                mapping = request_mapping(); mapping["authority"][field] = True; ForecastProducerRequest.from_mapping(mapping)

    def test_symbols_are_explicit_sorted_unique_path_safe(self):
        for symbols in ([], ["spy"], ["SPY", "SPY"], ["XLF", "SPY"], ["../SPY"], ["BTC/USD"], ["A..B"]):
            with self.subTest(symbols=symbols), self.assertRaises(ContractValidationError):
                mapping = request_mapping(); mapping["symbols"] = symbols; ForecastProducerRequest.from_mapping(mapping)

    def test_horizon_counts_preserve_integer_trading_sessions(self):
        for horizons in ([], [True], [0], [6], [1, 1], [2, 1], ["1D"]):
            with self.subTest(horizons=horizons), self.assertRaises(ContractValidationError):
                mapping = request_mapping(); mapping["horizons"] = horizons; ForecastProducerRequest.from_mapping(mapping)

    def test_unrecordable_source_universe_rejected_before_model_work(self):
        mapping = request_mapping(); mapping["symbols"] = ["SYNTH%02d" % index for index in range(9)]
        with self.assertRaises(ContractValidationError): ForecastProducerRequest.from_mapping(mapping)

    def test_evidence_paths_cannot_collide(self):
        mapping = request_mapping(); mapping["sources"]["calendar_evidence"] = mapping["sources"]["market_evidence"]
        with self.assertRaises(ContractValidationError): ForecastProducerRequest.from_mapping(mapping)

    def test_produced_export_validates(self):
        value, request = export_mapping()
        self.assertEqual(validate_forecast_producer_export(value, request), value)

    def test_no_execution_or_model_switch(self):
        for field, item in (("auto_trading_enabled", True), ("model_kind", "GBM_QUANTILE"), ("status", "AUTHORIZED")):
            value, request = export_mapping(); value[field] = item
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_forecast_producer_export(value, request)

    def test_actual_generation_clocks_cannot_be_reversed(self):
        for field, item in (("started_at", "2026-10-12T20:59:59Z"), ("completed_at", "2026-10-12T21:00:00Z"),
                            ("issued_at", "2026-10-12T21:01:59Z")):
            value, request = export_mapping(); value[field] = item
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_forecast_producer_export(value, request)

    def test_complete_symbol_horizon_coverage_required(self):
        for mutation in (lambda value: value["symbol_results"].clear(),
                         lambda value: value["symbol_results"][0]["horizon_results"].pop(),
                         lambda value: value["symbol_results"][0].update(symbol="QQQ")):
            value, request = export_mapping(); mutation(value)
            with self.assertRaises(ContractValidationError): validate_forecast_producer_export(value, request)

    def test_produced_horizon_cannot_omit_or_claim_deferral(self):
        for field, item in (("model_artifact_evidence", None), ("training_cutoff", None), ("reason_codes", ["MISSING"]), ("horizon_count", True)):
            value, request = export_mapping(); value["symbol_results"][0]["horizon_results"][0][field] = item
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_forecast_producer_export(value, request)

    def test_deferred_horizons_require_reason_and_cannot_create_produced_export(self):
        value, request = export_mapping()
        value["status"] = "DEFERRED"; row = value["symbol_results"][0]; row["status"] = "DEFERRED"; row["reason_codes"] = ["INSUFFICIENT_TRAINING_ROWS"]
        for horizon in row["horizon_results"]:
            horizon.update(status="DEFERRED", reason_codes=["INSUFFICIENT_TRAINING_ROWS"])
            for field in ("training_cutoff", "training_evidence", "model_artifact_evidence", "native_output_evidence",
                          "forecast_evidence", "provenance_evidence", "target_session_evidence"): horizon[field] = None
        validate_forecast_producer_export(value, request)
        invalid = copy.deepcopy(value); invalid["symbol_results"][0]["horizon_results"][0]["reason_codes"] = []
        with self.assertRaises(ContractValidationError): validate_forecast_producer_export(invalid, request)

    def test_limitations_are_versioned(self):
        value, request = export_mapping(); value["limitations"] = []
        with self.assertRaises(ContractValidationError): validate_forecast_producer_export(value, request)


if __name__ == "__main__": unittest.main()
