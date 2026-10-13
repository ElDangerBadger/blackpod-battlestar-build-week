"""Offline source, completed-label and data-only coefficient replay gates."""
from __future__ import annotations

import copy
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.shadow_quantitative_producer import (
    SOURCE_PINS, QuantitativeDependencyUnavailable, ShadowQuantitativeProducerError,
    build_shadow_quantitative_forecasts, capture_quantitative_sources, main, native_quantitative_config,
    prepare_shadow_quantitative_features, validate_shadow_quantitative_forecasts,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/shadow_quantitative_producer"


def synthetic_quantitative_inputs():
    """Declared test sessions and OHLCV; no claim these are exchange records."""
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    days = []
    for index in range(220):
        when = start + timedelta(days=index)
        if when.weekday() < 5:
            days.append(when.date().isoformat())
    sessions = [{"date": day, "opens_at": day + "T13:30:00Z", "closes_at": day + "T20:00:00Z"} for day in days]
    bars = []
    rng = random.Random(8941)
    for index, day in enumerate(days[:120]):
        close = 100 + index * 0.04 + math.sin(index / 3) * 2 + math.cos(index / 7) + rng.uniform(-0.4, 0.4)
        opened = close + rng.uniform(-0.3, 0.3)
        bars.append({"t": day + "T12:00:00Z", "o": opened, "h": max(close, opened) + rng.uniform(0.1, 1),
                     "l": min(close, opened) - rng.uniform(0.1, 1), "c": close, "v": rng.randrange(10000, 70000)})
    cutoff = sessions[119]["closes_at"]
    captured_at = cutoff.replace("20:00:00", "20:05:00")
    return ({"captured_at": captured_at, "bars": {"SYNTHETIC": bars}},
            {"captured_at": captured_at, "sessions": sessions},
            cutoff.replace("20:00:00", "20:10:00"))


def fitted_quantitative_fixture():
    """Actual native fits on declared synthetic prices, captured with sklearn."""
    packet = json.loads((FIXTURES / "synthetic_fitted.v1.json").read_bytes())
    if packet["data_status"] != "ACTUAL_NATIVE_FIT_ON_SYNTHETIC_INPUTS":
        raise ValueError("fitted fixture data status differs")
    return packet["history"], packet["calendar"], packet["result"]


class QuantitativeProducerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = capture_quantitative_sources(FIXTURES)

    def inputs(self):
        history, calendar, issued = synthetic_quantitative_inputs()
        return history, calendar, issued

    def prepare(self, history=None, calendar=None, issued=None):
        h, c, i = self.inputs()
        return prepare_shadow_quantitative_features(history or h, calendar or c, self.sources,
            issued_at=issued or i, symbols=["SYNTHETIC"])

    def test_source_closure_exact(self):
        for path in SOURCE_PINS:
            bad = dict(self.sources, **{path: self.sources[path] + b"\n"})
            with self.assertRaises(ShadowQuantitativeProducerError):
                native_quantitative_config(bad)
        with self.assertRaises(ShadowQuantitativeProducerError):
            native_quantitative_config(dict(self.sources, extra=b"code"))

    def test_ambient_environment_does_not_change_native_defaults(self):
        with patch.dict("os.environ", {"PHASE2_MODEL_TYPE": "gbm_quantile"}):
            config = native_quantitative_config(self.sources)
        self.assertEqual(config["model"]["type"], "quantile_linear")
        self.assertEqual(config["model"]["window"], 252)
        self.assertEqual(config["horizons"], [1, 2, 3, 4, 5])
        self.assertTrue(config["persist"]["enabled"])

    def test_no_initialization_or_model_cache_functions_selected(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("os.getcwd", return_value=root), patch("builtins.print"):
                material = self.prepare()
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertEqual(len(material[0]["horizons"]), 5)

    def test_completed_labels_and_future_sessions_have_actual_clocks(self):
        rows = self.prepare()[0]
        self.assertEqual(rows["bar_count"], 120)
        self.assertEqual(rows["completed_bar_count"], 120)
        self.assertEqual(rows["excluded_incomplete_bar_count"], 0)
        self.assertEqual(len(rows["feature_observations"]), 71)
        for horizon in rows["horizons"]:
            self.assertEqual(horizon["training_cutoff"], rows["reference_at"])
            training = horizon["training_observations"]
            self.assertEqual(len(training), 71 - horizon["horizon_count"])
            self.assertIn("target_close", training[0]["values"])
            self.assertGreater(training[0]["target_observed_at"], training[0]["observed_at"])
            self.assertGreater(horizon["target_at"], rows["feature_cutoff"])
        self.assertLess(rows["reference_at"], rows["feature_cutoff"])
        self.assertTrue(rows["reference_at"].endswith("T20:00:00Z"))
        self.assertTrue(rows["feature_cutoff"].endswith("T20:05:00Z"))

    def test_same_day_bar_admitted_only_after_calendar_proven_close(self):
        history, calendar, issued = self.inputs()
        day = calendar["sessions"][119]["date"]
        history["captured_at"] = day + "T18:00:00Z"
        calendar["captured_at"] = history["captured_at"]
        rows = self.prepare(history, calendar, day + "T18:01:00Z")[0]
        self.assertEqual(rows["completed_bar_count"], 119)
        self.assertEqual(rows["excluded_incomplete_bar_count"], 1)
        self.assertEqual(rows["horizons"][0]["target_at"], day + "T20:00:00Z")

    def test_history_capture_after_issue_rejected(self):
        h, c, i = self.inputs()
        h["captured_at"] = i.replace("20:10", "20:11")
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, i)

    def test_calendar_capture_after_issue_rejected(self):
        h, c, i = self.inputs()
        c["captured_at"] = i.replace("20:10", "20:11")
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, i)

    def test_calendar_duplicate_date_and_overlapping_clock_rejected(self):
        h, c, i = self.inputs()
        for field in ("date", "opens_at"):
            bad = copy.deepcopy(c)
            bad["sessions"][1][field] = bad["sessions"][0][field]
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.prepare(h, bad, i)

    def test_missing_calendar_for_daily_bar_rejected(self):
        h, c, i = self.inputs()
        del c["sessions"][60]
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, i)

    def test_missing_interior_bar_refuses_feature_row_horizon(self):
        h, c, i = self.inputs()
        del h["bars"]["SYNTHETIC"][60]
        with self.assertRaisesRegex(ShadowQuantitativeProducerError, "missing exchange sessions"):
            self.prepare(h, c, i)

    def test_latest_unusable_features_do_not_anchor_an_older_row(self):
        h, c, i = self.inputs()
        h["bars"]["SYNTHETIC"][-1]["v"] = None
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, i)

    def test_duplicate_and_reversed_bar_dates_rejected(self):
        h, c, i = self.inputs()
        for bad_bars in ([h["bars"]["SYNTHETIC"][0]] * 120, list(reversed(h["bars"]["SYNTHETIC"]))):
            bad = copy.deepcopy(h); bad["bars"]["SYNTHETIC"] = bad_bars
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.prepare(bad, c, i)

    def test_malformed_boolean_nonfinite_and_ohlc_rejected(self):
        for field, value in (("c", True), ("c", float("nan")), ("v", -1), ("h", 1)):
            h, c, i = self.inputs(); h["bars"]["SYNTHETIC"][60][field] = value
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.prepare(h, c, i)

    def test_horizon_future_calendar_required(self):
        h, c, i = self.inputs(); c["sessions"] = c["sessions"][:124]
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, i)

    def test_forecast_cannot_already_have_reached_target(self):
        h, c, i = self.inputs()
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.prepare(h, c, c["sessions"][120]["closes_at"])

    def test_native_minimum_training_horizon_never_fabricated(self):
        h, c, i = self.inputs(); h["bars"]["SYNTHETIC"] = h["bars"]["SYNTHETIC"][:80]
        h["captured_at"] = c["captured_at"] = c["sessions"][79]["closes_at"].replace("20:00", "20:05")
        i = h["captured_at"].replace("20:05", "20:10")
        self.assertEqual([row["horizon_count"] for row in self.prepare(h, c, i)[0]["horizons"]], [1])

    def test_native_window_limited_after_feature_engineering(self):
        h, c, i = self.inputs()
        # Three-year native window tested with a longer wholly synthetic calendar.
        days, start = [], datetime(2024, 1, 2, tzinfo=timezone.utc)
        for index in range(600):
            day = (start + timedelta(days=index))
            if day.weekday() < 5:
                days.append(day.date().isoformat())
        sessions = [{"date": d, "opens_at": d + "T13:30:00Z", "closes_at": d + "T20:00:00Z"} for d in days]
        bars = []
        for index, day in enumerate(days[:350]):
            p = 100 + index * 0.02 + math.sin(index / 3)
            bars.append({"t": day + "T12:00:00Z", "o": p, "h": p + 1, "l": p - 1, "c": p, "v": 10000 + index})
        captured = sessions[349]["closes_at"].replace("20:00", "20:05")
        rows = self.prepare({"captured_at": captured, "bars": {"SYNTHETIC": bars}},
            {"captured_at": captured, "sessions": sessions}, captured.replace("20:05", "20:10"))[0]
        self.assertEqual(len(rows["feature_observations"]), 252)
        self.assertEqual(len(rows["horizons"][4]["training_observations"]), 247)

    def test_requested_symbols_unknown_duplicate_and_empty_rejected(self):
        h, c, i = self.inputs()
        for symbols in ([], ["SYNTHETIC", "SYNTHETIC"], ["UNKNOWN"]):
            with self.assertRaises(ShadowQuantitativeProducerError):
                prepare_shadow_quantitative_features(h, c, self.sources, issued_at=i, symbols=symbols)

    def test_native_source_closure_has_no_io_side_effects(self):
        with patch("pathlib.Path.mkdir", side_effect=AssertionError("no cache mkdir")), patch("builtins.open", side_effect=AssertionError("no cache file")):
            self.prepare()

    def test_missing_fit_dependency_never_installs_or_substitutes_model(self):
        import builtins
        original = builtins.__import__
        def deny_sklearn(name, *args, **kwargs):
            if name.startswith("sklearn"):
                raise ImportError("not available")
            return original(name, *args, **kwargs)
        h, c, i = self.inputs()
        with patch("builtins.__import__", side_effect=deny_sklearn):
            with self.assertRaises(QuantitativeDependencyUnavailable):
                build_shadow_quantitative_forecasts(h, c, self.sources, issued_at=i)

    def test_worker_existing_output_blocks_before_fit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / "source"; source.mkdir()
            out = root / "fit"; out.mkdir(); target = out / "result.json"; target.write_bytes(b"retained")
            with patch("blackpod_build_week.shadow_quantitative_producer.build_shadow_quantitative_forecasts", side_effect=AssertionError("fit retried")), patch("builtins.print"):
                code = main(["--history", str(source / "history.json"), "--calendar", str(source / "calendar.json"),
                    "--sources-root", str(FIXTURES), "--output", str(target), "--symbols", "SYNTHETIC"])
            self.assertEqual(code, 2)
            self.assertEqual(target.read_bytes(), b"retained")

    def test_worker_unsafe_output_blocks_before_fit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); source = root / "source"; source.mkdir()
            (source / "missions").mkdir()
            with patch("blackpod_build_week.shadow_quantitative_producer.build_shadow_quantitative_forecasts", side_effect=AssertionError("unsafe fit")), patch("builtins.print"):
                code = main(["--history", str(source / "history.json"), "--calendar", str(source / "calendar.json"),
                    "--sources-root", str(FIXTURES), "--output", str(source / "result.json"), "--symbols", "SYNTHETIC"])
            self.assertEqual(code, 2)
            self.assertFalse((source / "result.json").exists())


class QuantitativeFittedReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = capture_quantitative_sources(FIXTURES)
        cls.history, cls.calendar, cls.result = fitted_quantitative_fixture()

    def replay(self, result=None):
        return validate_shadow_quantitative_forecasts(result or self.result, self.history, self.calendar, self.sources)

    def test_actual_fitted_fixture_replays_without_sklearn_or_pickle(self):
        with patch("pickle.loads", side_effect=AssertionError("no pickle loading")):
            self.assertEqual(self.replay(), self.result)

    def test_all_raw_outputs_and_native_sort_preview_retained(self):
        for horizon in self.result["symbols"][0]["horizons"]:
            self.assertEqual(set(horizon["raw_quantiles"]), {"q10", "q50", "q90"})
            self.assertEqual(set(horizon["model_artifacts"]), {"q10", "q50", "q90"})
        self.assertEqual(len(self.result["symbols"][0]["horizons"]), 5)

    def test_actual_crossed_fits_are_preserved_without_label_reassignment(self):
        first = self.result["symbols"][0]["horizons"][0]
        self.assertGreater(float(first["raw_quantiles"]["q10"]), float(first["raw_quantiles"]["q90"]))
        self.assertLess(float(first["native_sorted_quantiles"]["q10"]), float(first["native_sorted_quantiles"]["q90"]))
        self.assertNotEqual(first["raw_quantiles"], first["native_sorted_quantiles"])
        self.replay()

    def test_raw_prediction_edit_rejected(self):
        result = copy.deepcopy(self.result); result["symbols"][0]["horizons"][0]["raw_quantiles"]["q50"] = "999"
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.replay(result)

    def test_model_coefficients_quantile_identity_and_training_hash_edits_rejected(self):
        for field, value in (("intercept", "999"), ("quantile", "0.9"), ("training_sha256", "0" * 64), ("params", {})):
            result = copy.deepcopy(self.result); result["symbols"][0]["horizons"][0]["model_artifacts"]["q50"][field] = value
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.replay(result)

    def test_target_availability_and_feature_edits_rejected(self):
        for kind in ("training", "features"):
            result = copy.deepcopy(self.result)
            if kind == "training":
                result["symbols"][0]["horizons"][0]["training_observations"][0]["target_observed_at"] = result["issued_at"]
            else:
                result["symbols"][0]["feature_observations"][0]["values"]["RSI"] = "100"
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.replay(result)

    def test_model_pickle_or_unknown_fields_rejected(self):
        result = copy.deepcopy(self.result)
        result["symbols"][0]["horizons"][0]["model_artifacts"]["q50"]["pickle"] = "unsafe"
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.replay(result)

    def test_malformed_model_and_coefficient_count_rejected(self):
        for value in ([], dict(self.result["symbols"][0]["horizons"][0]["model_artifacts"]["q50"], coefficients=[])):
            result = copy.deepcopy(self.result)
            result["symbols"][0]["horizons"][0]["model_artifacts"]["q50"] = value
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.replay(result)

    def test_authority_and_config_edits_rejected(self):
        for field in ("authority", "config"):
            result = copy.deepcopy(self.result)
            if field == "authority":
                result[field]["execution_enabled"] = True
            else:
                result[field]["model"]["window"] = 1
            with self.assertRaises(ShadowQuantitativeProducerError):
                self.replay(result)

    def test_source_binding_and_native_sorted_preview_edits_rejected(self):
        result = copy.deepcopy(self.result); result["history_sha256"] = "0" * 64
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.replay(result)
        result = copy.deepcopy(self.result); result["symbols"][0]["horizons"][0]["native_sorted_quantiles"]["q10"] = "99"
        with self.assertRaises(ShadowQuantitativeProducerError):
            self.replay(result)


if __name__ == "__main__":
    unittest.main()
