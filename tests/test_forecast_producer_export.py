"""Deterministic export/calendar tests; producer-fit replay cases are source-bound."""
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.forecast_producer_export import (
    build_forecast_producer_export, validate_forecast_producer_export_bundle, validate_raw_calendar,
)
from blackpod_build_week.contracts.forecast_producer import ForecastProducerRequest
from blackpod_build_week.forecast_intake import _proof_observations
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_quantitative_producer import capture_quantitative_sources


def calendar_material(rows=None):
    if rows is None:
        rows = [{"date": "2026-10-12", "open": "09:30", "close": "16:00"},
            {"date": "2026-11-02", "open": "09:30", "close": "16:00"},
            {"date": "2026-11-27", "open": "09:30", "close": "13:00"}]
    raw = canonical_json_bytes(rows)
    receipt = {"schema_version": "blackpod.read_only_calendar_capture.v1", "url": "https://paper-api.alpaca.markets/v2/calendar",
        "query": {"start": "2026-10-01", "end": "2026-11-30"}, "captured_at": "2026-10-12T21:00:00Z",
        "method": "GET", "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)}
    return raw, receipt


class SourceCalendarProjectionTests(unittest.TestCase):
    def test_explicit_dates_preserve_dst_and_early_close(self):
        raw, receipt = calendar_material(); value = validate_raw_calendar(raw, receipt)
        self.assertEqual(value, {"captured_at": receipt["captured_at"], "sessions": [
            {"date": "2026-10-12", "opens_at": "2026-10-12T13:30:00Z", "closes_at": "2026-10-12T20:00:00Z"},
            {"date": "2026-11-02", "opens_at": "2026-11-02T14:30:00Z", "closes_at": "2026-11-02T21:00:00Z"},
            {"date": "2026-11-27", "opens_at": "2026-11-27T14:30:00Z", "closes_at": "2026-11-27T18:00:00Z"}]})

    def test_missing_dates_are_not_synthesized(self):
        raw, receipt = calendar_material([{ "date": "2026-10-12", "open": "09:30", "close": "16:00"},
            {"date": "2026-10-15", "open": "09:30", "close": "16:00"}])
        self.assertEqual([row["date"] for row in validate_raw_calendar(raw, receipt)["sessions"]], ["2026-10-12", "2026-10-15"])

    def test_response_hash_and_size_are_source_bound(self):
        for field, item in (("body_sha256", "0" * 64), ("size_bytes", 0), ("size_bytes", True)):
            raw, receipt = calendar_material(); receipt[field] = item
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_no_broker_mutation_or_wrong_endpoint_claim(self):
        for field, item in (("url", "https://api.alpaca.markets/v2/calendar"), ("url", "https://paper-api.alpaca.markets/v2/orders"),
                            ("method", "POST"), ("status", 401), ("status", True), ("schema_version", "v2")):
            raw, receipt = calendar_material(); receipt[field] = item
            with self.subTest(field=field), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_invalid_or_inferred_times_rejected(self):
        for value in (None, "0930", "09:30-04:00", "25:00", "00:00Z", "09:30:00.123"):
            rows = [{"date": "2026-10-12", "open": value, "close": "16:00"}]
            raw, receipt = calendar_material(rows)
            with self.subTest(value=value), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_overnight_or_reverse_session_rejected(self):
        for opened, closed in (("16:00", "09:30"), ("16:00", "16:00"), ("23:00", "01:00")):
            raw, receipt = calendar_material([{ "date": "2026-10-12", "open": opened, "close": closed}])
            with self.subTest(opened=opened), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_duplicate_reverse_out_of_query_dates_rejected(self):
        for dates in (("2026-10-12", "2026-10-12"), ("2026-10-13", "2026-10-12"), ("2026-12-01",), ("2026-02-30",)):
            raw, receipt = calendar_material([{ "date": day, "open": "09:30", "close": "16:00"} for day in dates])
            with self.subTest(dates=dates), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_no_unrecognized_input_fields(self):
        raw, receipt = calendar_material(); receipt["api_key"] = "fictional"
        with self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)
        raw, receipt = calendar_material([{ "date": "2026-10-12", "open": "09:30", "close": "16:00", "guessed": True}])
        with self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_provider_extended_metadata_retained_without_using_it_as_regular_hours(self):
        raw, receipt = calendar_material([{ "date": "2026-10-12", "open": "09:30", "close": "16:00",
            "session_open": "04:00", "session_close": "20:00", "settlement_date": "2026-10-13"}])
        self.assertEqual(validate_raw_calendar(raw, receipt)["sessions"][0]["closes_at"], "2026-10-12T20:00:00Z")

    def test_actual_provider_hhmm_aux_fields_supported_with_numeric_bounds(self):
        raw, receipt = calendar_material([{ "date": "2026-10-12", "open": "09:30", "close": "16:00",
            "session_open": "0400", "session_close": "2000"}])
        self.assertEqual(validate_raw_calendar(raw, receipt)["sessions"][0]["closes_at"], "2026-10-12T20:00:00Z")
        for value in ("2400", "0460", "040", "04000", "ab00", True):
            raw, receipt = calendar_material([{ "date": "2026-10-12", "open": "09:30", "close": "16:00", "session_open": value}])
            with self.subTest(value=value), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_duplicate_json_keys_nonfinite_or_wrong_root_rejected(self):
        for raw in (b'[{"date":"2026-10-12","date":"2026-10-13","open":"09:30","close":"16:00"}]',
                    b'[NaN]', b'{}', b'[]', b'\xff'):
            _, receipt = calendar_material(); receipt.update(body_sha256=sha256_bytes(raw), size_bytes=len(raw))
            with self.subTest(raw=raw), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_high_precision_capture_time_rejected(self):
        raw, receipt = calendar_material(); receipt["captured_at"] = "2026-10-12T21:00:00.1234567Z"
        with self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)

    def test_ambiguous_or_nonexistent_eastern_time_is_not_guessed(self):
        for day, opened, closed in (("2026-11-01", "01:30", "03:30"), ("2026-03-08", "02:30", "04:00")):
            raw, receipt = calendar_material([{ "date": day, "open": opened, "close": closed}])
            receipt["query"] = {"start": "2026-01-01", "end": "2026-12-31"}
            with self.subTest(day=day), self.assertRaises(ContractValidationError): validate_raw_calendar(raw, receipt)


class NativeObservationPrecisionTests(unittest.TestCase):
    def proof(self, version, number, kind="FEATURES"):
        row = {"observed_at": "2026-10-12T20:00:00Z", "values": {"native_return": number}}
        if kind == "TRAINING": row["target_observed_at"] = "2026-10-13T20:00:00Z"
        raw = canonical_json_bytes({"schema_version": "blackpod.forecast_observation_evidence." + version,
            "kind": kind, "symbol": "SPY", "observations": [row]})
        reference = {"path": "proof.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        return reference, {reference["sha256"]: raw}

    def test_v1_numeric_precision_remains_unchanged(self):
        reference, blobs = self.proof("v1", "0.000000012345678901234567")
        latest, reason = _proof_observations(blobs, reference, "FEATURES", "SPY", {})
        self.assertIsNone(latest); self.assertEqual(reason, "UNSUPPORTED_FEATURES_OBSERVATION_PROOF")

    def test_v2_retains_actual_native_precision_without_rounding(self):
        number = "0.000000012345678901234567"
        reference, blobs = self.proof("v2", number)
        latest, reason = _proof_observations(blobs, reference, "FEATURES", "SPY", {})
        self.assertIsNone(reason); self.assertEqual(latest.isoformat(), "2026-10-12T20:00:00+00:00")
        self.assertEqual(json.loads(blobs[reference["sha256"]])["observations"][0]["values"]["native_return"], number)

    def test_v2_training_cutoff_is_actual_label_availability(self):
        reference, blobs = self.proof("v2", "0.000000012345678901234567", "TRAINING")
        latest, reason = _proof_observations(blobs, reference, "TRAINING", "SPY", {})
        self.assertIsNone(reason); self.assertEqual(latest.isoformat(), "2026-10-13T20:00:00+00:00")

    def test_v2_does_not_remove_numeric_bounds(self):
        for number in ("NaN", "Infinity", "1e-24", "0." + "0" * 80 + "1", True):
            reference, blobs = self.proof("v2", number)
            with self.subTest(number=number):
                self.assertEqual(_proof_observations(blobs, reference, "FEATURES", "SPY", {})[1], "UNSUPPORTED_FEATURES_OBSERVATION_PROOF")

    def test_v2_cannot_remove_or_backdate_label_availability(self):
        reference, blobs = self.proof("v2", "0.000000012345678901234567", "TRAINING")
        document = json.loads(blobs[reference["sha256"]]); document["observations"][0]["target_observed_at"] = "2026-10-11T20:00:00Z"
        raw = canonical_json_bytes(document); reference.update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        self.assertEqual(_proof_observations({reference["sha256"]: raw}, reference, "TRAINING", "SPY", {})[1], "TRAINING_LABEL_BEFORE_FEATURE_OBSERVATION")


class MultiHorizonTrainingProofTests(unittest.TestCase):
    def material(self, changes=None):
        packet = {"schema_version": "blackpod.forecast_observation_evidence.v3", "kind": "TRAINING", "symbol": "SPY",
            "datasets": [{"horizon_count": h, "observations": [{"observed_at": "2026-10-08T20:00:00Z",
                "target_observed_at": "2026-10-%02dT20:00:00Z" % (8 + h),
                "values": {"actual_feature": "0.000000012345678901234567", "target_close": str(100 + h)}}]} for h in (1, 2)]}
        if changes is not None: changes(packet)
        raw = canonical_json_bytes(packet); ref = {"path": "training-family.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        return packet, ref, {ref["sha256"]: raw}

    def test_each_horizon_binds_its_own_actual_labels(self):
        _, ref, blobs = self.material(); cache = {}
        for h, day in ((1, 9), (2, 10)):
            latest, reason = _proof_observations(blobs, ref, "TRAINING", "SPY", cache, h)
            self.assertIsNone(reason); self.assertEqual(latest.isoformat(), "2026-10-%02dT20:00:00+00:00" % day)

    def test_missing_horizon_cannot_reuse_h1_proof(self):
        _, ref, blobs = self.material()
        self.assertEqual(_proof_observations(blobs, ref, "TRAINING", "SPY", {}, 3)[1], "MISSING_TRAINING_HORIZON_DATASET")

    def test_horizon_datasets_sorted_unique_integer_bounded(self):
        for change in (lambda v: v["datasets"].reverse(), lambda v: v["datasets"][1].update(horizon_count=1),
                       lambda v: v["datasets"][0].update(horizon_count=True), lambda v: v["datasets"][0].update(horizon_count=6)):
            _, ref, blobs = self.material(change)
            with self.subTest(change=change): self.assertIsNotNone(_proof_observations(blobs, ref, "TRAINING", "SPY", {}, 1)[1])

    def test_v3_cannot_claim_feature_proof_or_omit_training_targets(self):
        _, ref, blobs = self.material()
        self.assertEqual(_proof_observations(blobs, ref, "FEATURES", "SPY", {}, 1)[1], "UNSUPPORTED_FEATURES_OBSERVATION_PROOF")
        _, ref, blobs = self.material(lambda v: v["datasets"][1]["observations"][0].update(target_observed_at=None))
        self.assertEqual(_proof_observations(blobs, ref, "TRAINING", "SPY", {}, 1)[1], "MISSING_TRAINING_LABEL_AVAILABILITY")

    def test_all_datasets_are_validated_even_if_current_row_uses_h1(self):
        _, ref, blobs = self.material(lambda v: v["datasets"][1]["observations"][0]["values"].update(target_close="NaN"))
        self.assertEqual(_proof_observations(blobs, ref, "TRAINING", "SPY", {}, 1)[1], "UNSUPPORTED_TRAINING_OBSERVATION_PROOF")


def fitted_export_material():
    """Wrap actual fitted synthetic observations in passive capture fixtures.

The fixture fit is real; the symbol, prices, calendar, HTTP receipt and clocks
are declared synthetic test inputs, never a current provider observation.
Only document-envelope history hashes change; native rows/models stay exact.
    """
    from test_shadow_quantitative_producer import fitted_quantitative_fixture, FIXTURES
    original_history, calendar, result = fitted_quantitative_fixture()
    result = copy.deepcopy(result)
    evidence, blobs = {}, {}
    def keep(path, value):
        raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
        evidence[path], blobs[sha256_bytes(raw)] = raw, raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
    captured = original_history["captured_at"]
    snapshots = {"SYNTHETIC": {"latestQuote": {"bp": 100, "ap": 100.01, "t": captured},
        "latestTrade": {"p": 100, "t": captured}}}
    history = {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": captured, "feed": "IEX", "adjustment": "RAW",
        "snapshots": snapshots, "bars": original_history["bars"], "source_evidence": [keep("market/synthetic-snapshots.json", snapshots),
            keep("market/synthetic-bars.json", {"bars": original_history["bars"], "next_page_token": None})]}
    market_ref = keep("market/synthetic-packet.json", history)
    zone = ZoneInfo("America/New_York")
    calendar_rows = [{"date": row["date"], **{field: datetime.fromisoformat(row[key].replace("Z", "+00:00")).astimezone(zone).strftime("%H:%M")
        for field, key in (("open", "opens_at"), ("close", "closes_at"))}} for row in calendar["sessions"]]
    calendar_ref = keep("calendar/synthetic-response.json", calendar_rows)
    receipt = {"schema_version": "blackpod.read_only_calendar_capture.v1", "url": "https://paper-api.alpaca.markets/v2/calendar",
        "query": {"start": calendar_rows[0]["date"], "end": calendar_rows[-1]["date"]}, "captured_at": calendar["captured_at"],
        "method": "GET", "status": 200, "body_sha256": calendar_ref["sha256"], "size_bytes": calendar_ref["size_bytes"]}
    receipt_ref = keep("calendar/synthetic-receipt.json", receipt)
    source_refs = [keep("native_forecast_code/" + path, raw) for path, raw in capture_quantitative_sources(FIXTURES).items()]
    result["history_sha256"] = sha256_bytes(canonical_json_bytes(history))
    request = ForecastProducerRequest.from_mapping({"schema_version": "blackpod.forecast_producer_request.v1", "run_id": "synthetic-actual-fit-export",
        "recorded_at": captured, "domain": "TRADING", "mode": "SHADOW", "scope": "SHADOW_FORECAST_PRODUCTION_ONLY",
        "symbols": ["SYNTHETIC"], "horizons": [1, 2, 3, 4, 5], "sources": {"market_evidence": market_ref,
            "calendar_evidence": calendar_ref, "calendar_receipt_evidence": receipt_ref, "native_source_evidence": source_refs},
        "authority": result["authority"]})
    day = result["issued_at"][:10]
    return request, result, blobs, {"started_at": day + "T20:05:01Z", "completed_at": day + "T20:09:59Z", "issued_at": result["issued_at"]}


class ActualFittedExportReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, cls.native_result, cls.blobs, cls.clocks = fitted_export_material()
        cls.material = build_forecast_producer_export(cls.request, cls.native_result, cls.blobs, **cls.clocks)

    def test_actual_native_fit_source_replays_without_fit_pickle_or_providers(self):
        with patch("pickle.loads", side_effect=AssertionError("no pickle")), patch("builtins.__import__", wraps=__import__) as imports:
            replay = validate_forecast_producer_export_bundle(self.material["export"], self.material["blobs"])
        self.assertEqual(replay["export"], self.material["export"])
        self.assertFalse(any(call.args and call.args[0].startswith("sklearn") for call in imports.mock_calls))

    def test_one_symbol_family_origin_preserves_all_fifteen_distinct_models(self):
        self.assertEqual(len(self.material["intake"].sources), 1)
        rows = self.material["intake_result"]["rows"]
        signatures = {(row["source_id"], row["model_id"], row["model_version"], row["issued_at"], row["feature_cutoff"], row["training_cutoff"]) for row in rows}
        self.assertEqual(len(signatures), 1)
        models = [json.loads(raw) for path, raw in self.material["evidence"].items() if path.endswith("/models.json")]
        self.assertEqual(sum(len(row["models"]) for row in models), 15)
        self.assertEqual(len({identifier for row in models for identifier in row["model_ids"].values()}), 15)

    def test_raw_crossings_are_deferred_and_native_sorted_output_remains_separate(self):
        rows = self.material["intake_result"]["rows"]
        from decimal import Decimal
        crossing = [row for row in rows if [Decimal(row[key]) for key in ("q10", "q50", "q90")] != sorted(Decimal(row[key]) for key in ("q10", "q50", "q90"))]
        self.assertEqual([row["horizon_count"] for row in crossing], [1, 4, 5])
        self.assertTrue(all(row["gate"] == "DEFER" and "CROSSED_QUANTILES" in row["reason_codes"] for row in crossing))
        self.assertEqual(self.material["intake_result"]["admitted_count"], 2)
        self.assertEqual(self.material["intake_result"]["deferred_count"], 3)
        for horizon in self.native_result["symbols"][0]["horizons"]:
            row = next(row for row in rows if row["horizon_count"] == horizon["horizon_count"])
            self.assertEqual({key: row[key] for key in ("q10", "q50", "q90")}, horizon["raw_quantiles"])

    def test_training_family_retains_actual_sample_count_and_target_dates_each_horizon(self):
        proof = next(json.loads(raw) for path, raw in self.material["evidence"].items() if path.endswith("multi-horizon-training.json"))
        for dataset, horizon in zip(proof["datasets"], self.native_result["symbols"][0]["horizons"]):
            self.assertEqual(dataset["observations"], horizon["training_observations"])
            self.assertEqual(dataset["horizon_count"], horizon["horizon_count"])
        self.assertEqual([len(row["observations"]) for row in proof["datasets"]], [70, 69, 68, 67, 66])

    def test_machine_validation_is_explicit_and_calibration_remains_missing(self):
        provenance = next(json.loads(raw) for path, raw in self.material["evidence"].items() if path.endswith("/provenance.json"))
        self.assertEqual(provenance["reviewed_by"], "machine-source-bound-producer-export-v1")
        self.assertIsNone(provenance["model"]["calibration_evidence"])
        self.assertFalse(self.material["export"]["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in self.material["export"]["authority"].values()))
        self.assertTrue(all(row["realized_outcome"] is None and row["evaluation"] is None for row in self.material["intake_result"]["rows"]))

    def test_native_source_changed_or_missing_is_rejected(self):
        blobs = dict(self.blobs); reference = self.request.sources["native_source_evidence"][0]; blobs[reference["sha256"]] += b"\n"
        with self.assertRaises(ValueError): build_forecast_producer_export(self.request, self.native_result, blobs, **self.clocks)

    def test_rehashed_prediction_and_model_edits_fail_native_replay(self):
        for field in ("raw_quantiles", "model_artifacts"):
            value = copy.deepcopy(self.native_result)
            if field == "raw_quantiles": value["symbols"][0]["horizons"][0][field]["q50"] = "999"
            else: value["symbols"][0]["horizons"][0][field]["q50"]["intercept"] = "999"
            with self.subTest(field=field), self.assertRaises(ValueError): build_forecast_producer_export(self.request, value, self.blobs, **self.clocks)

    def test_issue_clock_cannot_precede_generation_or_differ_from_native(self):
        for field, value in (("completed_at", self.clocks["issued_at"].replace("20:10", "20:11")), ("issued_at", self.clocks["issued_at"].replace("20:10", "20:11"))):
            clocks = dict(self.clocks, **{field: value})
            with self.subTest(field=field), self.assertRaises(ValueError): build_forecast_producer_export(self.request, self.native_result, self.blobs, **clocks)

    def test_export_immutable_reference_corruption_is_rejected(self):
        value = copy.deepcopy(self.material["export"]); value["symbol_results"][0]["horizon_results"][0]["native_output_evidence"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError): validate_forecast_producer_export_bundle(value, self.material["blobs"])

    def test_raw_source_calendar_history_and_code_retained_in_export(self):
        paths = set(self.material["evidence"])
        self.assertTrue({"market/synthetic-packet.json", "market/synthetic-snapshots.json", "market/synthetic-bars.json",
            "calendar/synthetic-response.json", "calendar/synthetic-receipt.json", "native_forecast_code/phase2_forecast_engine.py",
            "native_forecast_code/models/model_library.py"} <= paths)


if __name__ == "__main__": unittest.main()
