"""Synthetic-only offline forecast gate fixtures and adversarial source replay."""
from __future__ import annotations

import copy
import socket
import unittest
from decimal import localcontext
from unittest.mock import patch

from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.forecast_intake import assess_forecast_intake, evidence_for_forecast_intake
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes

NOW = "2026-10-12T21:00:00Z"


class ForecastIntakeFixture:
    """Explicit fake model/data evidence; never actual current model inference."""
    def __init__(self, *, domain="TRADING", horizons=(1, 2, 3)):
        self.blobs, self.paths = {}, {}
        self.source_rows = [dict(Date="2026-10-12", Symbol="SPY", Q10=str(98 + horizon), Q50=str(100 + horizon),
            Q90=str(102 + horizon), Pattern="LIVE", Timeframe="1D", Horizon=str(horizon) + "D") for horizon in horizons]
        self.source_format = "GALACTICA_PHASE2_CSV"
        self.source = self.reference("forecast/source.csv", self.csv_bytes())
        feature = {"schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "FEATURES", "symbol": "SPY",
            "observations": [{"observed_at": "2026-10-12T20:00:00Z", "values": {"close_lag": "100"}}]}
        training = {"schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "TRAINING", "symbol": "SPY",
            "observations": [{"observed_at": "2026-10-09T20:00:00Z", "target_observed_at": "2026-10-12T20:00:00Z",
                              "values": {"close_lag": "99", "target_close": "100"}}]}
        config = {"schema_version": "blackpod.forecast_model_config.v1", "model_kind": "QUANTILE_LINEAR",
            "quantile_levels": ["0.10", "0.50", "0.90"], "target": "FUTURE_CLOSE", "currency": "USD", "feature_names": ["close_lag"]}
        self.calendar = {"schema_version": "blackpod.forecast_session_calendar.v1", "symbol": "SPY",
            "anchor_at": "2026-10-12T20:00:00Z", "captured_at": "2026-10-12T20:00:00Z", "sessions": [
                {"opens_at": "2026-10-13T13:30:00Z", "closes_at": "2026-10-13T20:00:00Z"},
                {"opens_at": "2026-10-14T13:30:00Z", "closes_at": "2026-10-14T20:00:00Z"},
                {"opens_at": "2026-10-15T13:30:00Z", "closes_at": "2026-10-15T20:00:00Z"},
                {"opens_at": "2026-10-16T13:30:00Z", "closes_at": "2026-10-16T20:00:00Z"},
                {"opens_at": "2026-10-19T13:30:00Z", "closes_at": "2026-10-19T20:00:00Z"}]}
        calendar_reference = self.reference("forecast/calendar.json", canonical_json_bytes(self.calendar))
        self.manifest = {"schema_version": "blackpod.forecast_provenance.v1", "source_sha256": self.source["sha256"],
            "status": "REVIEWED_SOURCE_BOUND", "reviewed_by": "fixture-reviewer", "reviewed_at": "2026-10-12T20:30:00Z",
            "model": {"model_id": "synthetic-model-not-inferred", "model_version": "fixture-v1", "model_kind": "QUANTILE_LINEAR",
                "producer_evidence": self.reference("forecast/producer.py", b"# Synthetic test producer; not executed.\n"),
                "model_artifact_evidence": self.reference("forecast/model.bin", b"Synthetic model bytes; must never be loaded."),
                "config_evidence": self.reference("forecast/config.json", canonical_json_bytes(config)),
                "feature_evidence": self.reference("forecast/features.json", canonical_json_bytes(feature)),
                "training_evidence": self.reference("forecast/training.json", canonical_json_bytes(training)), "calibration_evidence": None},
            "rows": [{"source_row_number": number, "symbol": "SPY", "issued_at": "2026-10-12T20:05:00Z",
                "feature_cutoff": "2026-10-12T20:00:00Z", "training_cutoff": "2026-10-12T20:00:00Z", "horizon_count": horizon,
                "horizon_unit": "TRADING_SESSION", "target_at": self.calendar["sessions"][horizon - 1]["closes_at"],
                "target_session_evidence": calendar_reference, "units": "PRICE_USD", "value_semantics": "PREDICTED_CLOSE_LEVEL",
                "reference_price": "100", "reference_at": "2026-10-12T20:00:00Z"} for number, horizon in enumerate(horizons, 1)]}
        self.value = {"schema_version": "blackpod.forecast_intake.v1", "intake_id": "fixture-current-forecast", "recorded_at": NOW,
            "shadow_as_of": NOW, "domain": domain, "mode": "SHADOW", "scope": "SHADOW_FORECAST_INTAKE_ONLY",
            "policy": {"interface_version": "DAILY_USD_PRICE_V1", "max_forecast_age_seconds": 86400,
                "max_feature_age_seconds": 86400, "max_training_age_seconds": 86400, "allowed_horizon_sessions": [1, 2, 3, 4, 5]},
            "sources": [{"source_id": "fixture-spy", "evidence": self.source, "format": self.source_format,
                "provenance_evidence": None}], "authority": {field: False for field in (
                    "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}}
        self.refresh()

    def reference(self, path, raw):
        digest = sha256_bytes(raw)
        self.blobs[digest], self.paths[path] = raw, raw
        return {"path": path, "sha256": digest, "size_bytes": len(raw)}

    def csv_bytes(self):
        import csv
        import io
        out = io.StringIO(newline="")
        names = ["Date", "Symbol", "Q10", "Q50", "Q90", "Pattern", "Timeframe"]
        if self.source_format == "GALACTICA_PHASE2_CSV": names.append("Horizon")
        writer = csv.DictWriter(out, names, lineterminator="\n")
        writer.writeheader(); writer.writerows(self.source_rows)
        return out.getvalue().encode()

    def refresh(self, *, source=False):
        if source:
            self.source = self.reference("forecast/source.csv", self.csv_bytes())
            self.value["sources"][0]["evidence"] = self.source
            self.value["sources"][0]["format"] = self.source_format
            self.manifest["source_sha256"] = self.source["sha256"]
        self.value["sources"][0]["provenance_evidence"] = self.reference("forecast/provenance.json", canonical_json_bytes(self.manifest))
        self.document = ForecastIntake.from_mapping(self.value)
        return self

    def replace_proof(self, field, packet):
        path = self.manifest["model"][field]["path"]
        self.manifest["model"][field] = self.reference(path, canonical_json_bytes(packet))
        return self.refresh()

    def result(self): return assess_forecast_intake(self.document, self.blobs)
    def evidence(self): return evidence_for_forecast_intake(self.document, self.blobs)
    def close(self): pass

    def with_json(self):
        rows = []
        for raw, metadata in zip(self.source_rows, self.manifest["rows"]):
            row = {"symbol": raw["Symbol"], "source_date": raw["Date"], "q10": raw["Q10"], "q50": raw["Q50"], "q90": raw["Q90"], "timeframe": "1D"}
            row.update({field: metadata[field] for field in ("horizon_count", "horizon_unit", "units", "value_semantics", "issued_at",
                "feature_cutoff", "training_cutoff", "target_at", "reference_price", "reference_at")})
            row.update({field: self.manifest["model"][field] for field in ("model_id", "model_version")})
            rows.append(row)
        self.json_source = {"schema_version": "blackpod.daily_price_forecasts.v1", "rows": rows}
        self.source = self.reference("forecast/source.json", canonical_json_bytes(self.json_source))
        self.value["sources"][0].update(evidence=self.source, format="GOVERNED_PRICE_FORECAST_JSON")
        self.manifest["source_sha256"] = self.source["sha256"]
        return self.refresh()


class ForecastIntakeEngineTests(unittest.TestCase):
    def setUp(self): self.fx = ForecastIntakeFixture()
    def reasons(self): return self.fx.result()["rows"][0]["reason_codes"]

    def test_explicit_current_synthetic_source_admitted_without_authority(self):
        result = self.fx.result()
        self.assertEqual(result["admitted_count"], 3)
        self.assertEqual(result["deferred_count"], 0)
        self.assertFalse(result["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in result["authority"].values()))
        row = result["rows"][0]
        self.assertEqual(row["q50"], "101")
        self.assertEqual(row["units"], "PRICE_USD")
        self.assertIsNone(row["realized_outcome"])
        self.assertIsNone(row["evaluation"])

    def test_date_only_remains_date_only(self):
        row = self.fx.result()["rows"][0]
        self.assertEqual(row["source_date"], "2026-10-12")
        self.assertEqual(row["source_time_precision"], "DATE_ONLY")
        self.assertEqual(row["raw_source_row"], self.fx.source_rows[0])

    def test_unknown_model_metadata_never_invented(self):
        self.fx.value["sources"][0]["provenance_evidence"] = None
        self.fx.document = ForecastIntake.from_mapping(self.fx.value)
        row = self.fx.result()["rows"][0]
        for field in ("model_id", "model_version", "issued_at", "feature_cutoff", "training_cutoff", "target_at", "units", "horizon_unit"):
            self.assertIsNone(row[field])
        self.assertEqual(row["horizon_count"], 1)
        self.assertEqual(row["gate"], "DEFER")

    def test_historical_asof_and_future_dates_do_not_create_current_forecast(self):
        for row in self.fx.source_rows: row["Date"] = "2026-06-10"
        for row in self.fx.manifest["rows"]:
            row.update(issued_at="2026-06-10T20:05:00Z", feature_cutoff="2026-06-10T20:00:00Z", training_cutoff="2026-06-10T20:00:00Z")
        self.fx.refresh(source=True)
        self.assertIn("STALE_FORECAST", self.reasons())
        self.assertEqual(self.fx.result()["admitted_count"], 0)

    def test_source_hash_mismatch_rejected(self):
        self.fx.manifest["source_sha256"] = "0" * 64
        self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_source_blob_size_and_hash_checked(self):
        self.fx.blobs[self.fx.source["sha256"]] += b"x"
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_source_row_mismatch_rejected(self):
        self.fx.manifest["rows"][0]["symbol"] = "QQQ"
        self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_metadata_cannot_relabel_source_horizon(self):
        self.fx.manifest["rows"][0]["horizon_count"] = 2
        self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_erased_phase3_horizon_cannot_be_restored_by_manifest(self):
        for row in self.fx.source_rows: del row["Horizon"]
        self.fx.source_format = "GALACTICA_PHASE3_CSV"
        self.fx.refresh(source=True)
        result = self.fx.result()
        self.assertEqual(result["admitted_count"], 0)
        self.assertIn("HORIZON_NOT_RETAINED", result["rows"][0]["reason_codes"])
        self.assertIn("AMBIGUOUS_SOURCE_IDENTITY", result["rows"][0]["reason_codes"])
        self.assertIn("PROVENANCE_CANNOT_RESTORE_ERASED_HORIZON", result["rows"][0]["reason_codes"])

    def test_duplicate_identical_raw_rows_rejected(self):
        self.fx.source_rows.append(copy.deepcopy(self.fx.source_rows[0])); self.fx.refresh(source=True)
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_crossed_quantiles_preserved_and_deferred(self):
        self.fx.source_rows[0]["Q10"] = "104"; self.fx.refresh(source=True)
        row = self.fx.result()["rows"][0]
        self.assertEqual(row["q10"], "104")
        self.assertEqual(row["q50"], "101")
        self.assertIn("CROSSED_QUANTILES", row["reason_codes"])

    def test_nonfinite_scientific_and_zero_levels_do_not_pass(self):
        for invalid in ("NaN", "Infinity", "1e2", "0", "-1", "1." + "1" * 19):
            with self.subTest(invalid=invalid):
                self.fx.source_rows[0]["Q10"] = invalid; self.fx.refresh(source=True)
                self.assertEqual(self.fx.result()["rows"][0]["gate"], "DEFER")

    def test_feature_cutoff_lookahead_blocked(self):
        self.fx.manifest["rows"][0]["feature_cutoff"] = "2026-10-12T20:06:00Z"; self.fx.refresh()
        self.assertIn("FEATURE_CUTOFF_AFTER_ISSUE", self.reasons())

    def test_observed_feature_after_declared_cutoff_blocked(self):
        packet = copy.deepcopy(__import__("json").loads(self.fx.paths["forecast/features.json"]))
        packet["observations"][0]["observed_at"] = "2026-10-12T20:01:00Z"
        self.fx.replace_proof("feature_evidence", packet)
        self.assertIn("FEATURES_OBSERVATIONS_AFTER_CUTOFF", self.reasons())

    def test_training_target_label_lookahead_blocked(self):
        packet = copy.deepcopy(__import__("json").loads(self.fx.paths["forecast/training.json"]))
        packet["observations"][0]["target_observed_at"] = "2026-10-13T20:00:00Z"
        self.fx.replace_proof("training_evidence", packet)
        self.assertIn("TRAINING_OBSERVATIONS_AFTER_CUTOFF", self.reasons())

    def test_training_feature_date_does_not_prove_target_availability(self):
        packet = copy.deepcopy(__import__("json").loads(self.fx.paths["forecast/training.json"]))
        packet["observations"][0]["target_observed_at"] = None
        self.fx.replace_proof("training_evidence", packet)
        self.assertIn("MISSING_TRAINING_LABEL_AVAILABILITY", self.reasons())

    def test_training_target_before_feature_observation_blocked(self):
        packet = copy.deepcopy(__import__("json").loads(self.fx.paths["forecast/training.json"]))
        packet["observations"][0]["target_observed_at"] = "2026-10-08T20:00:00Z"
        self.fx.replace_proof("training_evidence", packet)
        self.assertIn("TRAINING_LABEL_BEFORE_FEATURE_OBSERVATION", self.reasons())

    def test_training_source_observations_must_be_unique_even_if_labels_differ(self):
        packet = __import__("json").loads(self.fx.paths["forecast/training.json"])
        first = copy.deepcopy(packet["observations"][0])
        first["target_observed_at"] = "2026-10-10T20:00:00Z"
        packet["observations"].insert(0, first)
        self.fx.replace_proof("training_evidence", packet)
        self.assertIn("UNORDERED_TRAINING_OBSERVATION_PROOF", self.reasons())

    def test_cutoff_must_match_latest_retained_observation(self):
        packet = copy.deepcopy(__import__("json").loads(self.fx.paths["forecast/features.json"]))
        packet["observations"][0]["observed_at"] = "2026-10-12T19:59:00Z"
        self.fx.replace_proof("feature_evidence", packet)
        self.assertIn("FEATURES_CUTOFF_NOT_OBSERVED", self.reasons())

    def test_malformed_or_unsupported_proof_deferred(self):
        for raw in (b"not JSON", b'{"schema_version":"old"}'):
            self.fx.manifest["model"]["feature_evidence"] = self.fx.reference("forecast/features.json", raw)
            self.fx.refresh()
            self.assertIn("UNSUPPORTED_FEATURES_OBSERVATION_PROOF", self.reasons())

    def test_unsupported_or_unreviewed_provenance_deferred(self):
        self.fx.manifest["status"] = "DECLARED_UNVERIFIED"; self.fx.refresh()
        self.assertIn("UNREVIEWED_PROVENANCE", self.reasons())

    def test_future_issue_or_future_review_blocked(self):
        self.fx.manifest["rows"][0]["issued_at"] = "2026-10-12T21:01:00Z"; self.fx.refresh()
        self.assertIn("ISSUED_AFTER_SHADOW_AS_OF", self.reasons())
        self.fx.manifest["reviewed_at"] = "2026-10-12T21:02:00Z"; self.fx.refresh()
        self.assertIn("REVIEW_AFTER_SHADOW_AS_OF", self.reasons())

    def test_elapsed_target_is_deferred(self):
        self.fx.manifest["rows"][0]["target_at"] = "2026-10-12T20:10:00Z"; self.fx.refresh()
        self.assertIn("TARGET_ALREADY_ELAPSED", self.reasons())

    def test_target_must_match_declared_nth_session_close(self):
        self.fx.manifest["rows"][0]["target_at"] = "2027-10-12T20:00:00Z"; self.fx.refresh()
        self.assertIn("TARGET_NOT_DECLARED_HORIZON_SESSION_CLOSE", self.reasons())

    def test_overlapping_session_calendar_deferred(self):
        self.fx.calendar["sessions"][1]["opens_at"] = self.fx.calendar["sessions"][0]["opens_at"]
        reference = self.fx.reference("forecast/calendar.json", canonical_json_bytes(self.fx.calendar))
        for row in self.fx.manifest["rows"]: row["target_session_evidence"] = reference
        self.fx.refresh()
        self.assertIn("UNORDERED_OR_OVERLAPPING_TARGET_SESSIONS", self.reasons())

    def test_calendar_capture_after_issue_blocked(self):
        self.fx.calendar["captured_at"] = "2026-10-12T21:00:00Z"
        reference = self.fx.reference("forecast/calendar.json", canonical_json_bytes(self.fx.calendar))
        for row in self.fx.manifest["rows"]: row["target_session_evidence"] = reference
        self.fx.refresh()
        self.assertIn("TARGET_CALENDAR_CAPTURE_AFTER_ISSUE", self.reasons())

    def test_investment_desk_does_not_use_daily_trading_horizon(self):
        self.fx.value["domain"] = "INVESTMENT"; self.fx.document = ForecastIntake.from_mapping(self.fx.value)
        self.assertIn("SHORT_HORIZON_NOT_INVESTMENT_EVIDENCE", self.reasons())
        self.assertEqual(self.fx.result()["admitted_count"], 0)

    def test_missing_model_artifact_blocks_gate(self):
        self.fx.manifest["model"]["model_artifact_evidence"] = None; self.fx.refresh()
        self.assertIn("MISSING_MODEL_ARTIFACT_EVIDENCE", self.reasons())

    def test_model_bytes_never_unpickled_and_provider_never_called(self):
        with patch("pickle.loads", side_effect=AssertionError("must never unpickle")), patch("socket.create_connection", side_effect=AssertionError("must remain offline")):
            self.assertEqual(self.fx.result()["admitted_count"], 3)

    def test_retained_evidence_complete_and_deterministic(self):
        self.assertEqual(self.fx.result(), self.fx.result())
        evidence = self.fx.evidence()
        self.assertEqual(evidence["forecast-intake/input.v1.json"], self.fx.document.to_bytes())
        self.assertEqual(evidence["forecast/source.csv"], self.fx.csv_bytes())
        self.assertEqual(len(evidence), 9)

    def test_empty_sources_explicit_no_current_forecasts(self):
        self.fx.value["sources"] = []; self.fx.document = ForecastIntake.from_mapping(self.fx.value)
        result = self.fx.result()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["reason_codes"], ["NO_CURRENT_GOVERNED_FORECASTS"])

    def test_governed_json_original_types_and_fields_preserved(self):
        self.fx.with_json()
        result = self.fx.result()
        self.assertEqual(result["admitted_count"], 3)
        self.assertEqual(result["rows"][0]["raw_source_row"], self.fx.json_source["rows"][0])
        self.assertIs(type(result["rows"][0]["raw_source_row"]["horizon_count"]), int)

    def test_json_declared_metadata_preserved_but_unproven_without_manifest(self):
        self.fx.with_json(); self.fx.value["sources"][0]["provenance_evidence"] = None
        self.fx.document = ForecastIntake.from_mapping(self.fx.value)
        row = self.fx.result()["rows"][0]
        self.assertEqual(row["units"], "PRICE_USD")
        self.assertEqual(row["issued_at"], "2026-10-12T20:05:00Z")
        self.assertEqual(row["model_id"], "synthetic-model-not-inferred")
        self.assertEqual(row["gate"], "DEFER")

    def test_json_source_provenance_metadata_disagreement_rejected(self):
        self.fx.with_json(); self.fx.manifest["rows"][0]["issued_at"] = "2026-10-12T20:06:00Z"; self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_json_cannot_introduce_return_units_or_executable_fields(self):
        self.fx.with_json(); self.fx.json_source["rows"][0]["order"] = "BUY"
        self.fx.source = self.fx.reference("forecast/source.json", canonical_json_bytes(self.fx.json_source))
        self.fx.value["sources"][0]["evidence"] = self.fx.source; self.fx.manifest["source_sha256"] = self.fx.source["sha256"]; self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_model_config_quantile_semantics_cannot_be_relabelled(self):
        packet = __import__("json").loads(self.fx.paths["forecast/config.json"])
        packet["quantile_levels"] = ["0.10", "0.90", "0.50"]
        self.fx.replace_proof("config_evidence", packet)
        self.assertIn("UNSUPPORTED_MODEL_CONFIG_PROOF", self.reasons())

    def test_source_date_does_not_override_explicit_feature_time(self):
        self.fx.source_rows[0]["Date"] = "2026-10-11"; self.fx.refresh(source=True)
        self.assertIn("SOURCE_DATE_FEATURE_CUTOFF_MISMATCH", self.reasons())

    def test_nonlive_pattern_and_nondaily_timeframe_deferred(self):
        self.fx.source_rows[0].update(Pattern="BACKTEST", Timeframe="1H"); self.fx.refresh(source=True)
        self.assertIn("NONLIVE_SOURCE_PATTERN", self.reasons())
        self.assertIn("UNSUPPORTED_TIMEFRAME", self.reasons())

    def test_missing_calendar_is_deferred(self):
        self.fx.manifest["rows"][0]["target_session_evidence"] = None; self.fx.refresh()
        self.assertIn("MISSING_TARGET_SESSION_PROOF", self.reasons())

    def test_duplicate_headers_and_extra_row_fields_rejected(self):
        for raw in (b"Date,Symbol,Q10,Q50,Q90,Pattern,Timeframe,Horizon,Horizon\n", self.fx.csv_bytes() + b"2026-10-12,SPY,1,2,3,LIVE,1D,1D,extra\n"):
            self.fx.value["sources"][0]["evidence"] = self.fx.reference("forecast/source.csv", raw)
            self.fx.document = ForecastIntake.from_mapping(self.fx.value)
            with self.assertRaises(ContractValidationError): self.fx.result()

    def test_conflicting_proof_path_or_reserved_input_collision_rejected(self):
        self.fx.manifest["model"]["config_evidence"]["path"] = "forecast/source.csv"; self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()
        self.fx.manifest["model"]["config_evidence"]["path"] = "forecast-intake/input.v1.json"; self.fx.refresh()
        with self.assertRaises(ContractValidationError): self.fx.result()

    def test_shared_proof_bytes_are_parsed_once_per_assessment(self):
        from blackpod_build_week import forecast_intake as engine
        raw, metadata = copy.deepcopy(self.fx.source_rows[0]), copy.deepcopy(self.fx.manifest["rows"][0])
        self.fx.source_rows, self.fx.manifest["rows"] = [], []
        for number in range(1, 301):
            self.fx.source_rows.append(dict(raw, Q50=str(100 + number)))
            self.fx.manifest["rows"].append(dict(metadata, source_row_number=number))
        self.fx.refresh(source=True)
        with patch.object(engine, "parse_strict_json_object_bytes", wraps=engine.parse_strict_json_object_bytes) as parser:
            result = self.fx.result()
        self.assertEqual(len(result["rows"]), 300)
        names = [call.kwargs.get("document_name") for call in parser.call_args_list]
        self.assertEqual(names.count("forecast observation proof"), 2)
        self.assertEqual(names.count("forecast model configuration proof"), 1)
        self.assertEqual(names.count("forecast session calendar"), 1)

    def test_proof_cache_does_not_survive_a_later_source_change(self):
        self.assertEqual(self.fx.result()["admitted_count"], 3)
        packet = __import__("json").loads(self.fx.paths["forecast/features.json"])
        packet["observations"][0]["observed_at"] = "2026-10-13T20:00:00Z"
        self.fx.replace_proof("feature_evidence", packet)
        self.assertEqual(self.fx.result()["admitted_count"], 0)
        self.assertIn("FEATURES_OBSERVATIONS_AFTER_CUTOFF", self.reasons())

    def test_mismatched_symbols_cannot_force_repeated_large_proof_parsing(self):
        from blackpod_build_week import forecast_intake as engine
        raw, metadata = copy.deepcopy(self.fx.source_rows[0]), copy.deepcopy(self.fx.manifest["rows"][0])
        self.fx.source_rows, self.fx.manifest["rows"] = [], []
        for number in range(1, 301):
            symbol = "SYNTH" + str(number)
            self.fx.source_rows.append(dict(raw, Symbol=symbol))
            self.fx.manifest["rows"].append(dict(metadata, source_row_number=number, symbol=symbol))
        self.fx.refresh(source=True)
        with patch.object(engine, "parse_strict_json_object_bytes", wraps=engine.parse_strict_json_object_bytes) as parser:
            result = self.fx.result()
        self.assertEqual(result["deferred_count"], 300)
        names = [call.kwargs.get("document_name") for call in parser.call_args_list]
        self.assertEqual(names.count("forecast observation proof"), 2)
        self.assertEqual(names.count("forecast session calendar"), 1)

    def test_tiny_ambient_decimal_context_does_not_change_gate(self):
        expected = self.fx.result()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.fx.result(), expected)


if __name__ == "__main__": unittest.main()
