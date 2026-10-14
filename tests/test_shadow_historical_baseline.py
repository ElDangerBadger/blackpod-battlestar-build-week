"""Synthetic retrospective price fixtures; no market requests or orders."""
from copy import deepcopy
import csv
from datetime import date, timedelta
from decimal import localcontext, ROUND_UP
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest import mock

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_historical_baseline import (
    build_historical_baseline, calculation_evidence, CSV_FIELDS, MAX_CUTOFF,
)
from blackpod_build_week.shadow_experiment import _ratio
from test_shadow_experiment import fixture as protocol_fixture


def fixture(count=65, *, mutate=None, first_qqq=0):
    protocol, _ = protocol_fixture()
    start = date(2025, 1, 2)
    days, offset = [], 0
    while len(days) < count:
        current = start + timedelta(days=offset)
        offset += 1
        if current.weekday() < 5:
            days.append(current.isoformat())
    records = {symbol: [] for symbol in ("QQQ", "SPY")}
    for index, day in enumerate(days):
        for symbol in records:
            if symbol == "QQQ" and index < first_qqq:
                continue
            records[symbol].append({"date": day, "open": str(100 + index) if symbol == "QQQ" else "100",
                "high": "1000", "low": "1", "close": str(200 - index) if symbol == "QQQ" else str(100 + index),
                "adj_close": "99", "volume": "10000"})
    if mutate:
        mutate(records, days)
    blobs = {}
    for symbol, rows in records.items():
        output = StringIO()
        writer = csv.DictWriter(output, CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        blobs[symbol] = output.getvalue().encode()
    manifest = {"schema_version": "blackpod.shadow_historical_source_manifest.v1", "source_price_basis": "UNKNOWN",
        "sources": {symbol: {"sha256": sha256_bytes(raw), "size_bytes": len(raw), "path": "sources/" + symbol + ".csv"}
                    for symbol, raw in blobs.items()}}
    calendar = canonical_json_bytes([{"date": day, "open": "09:30", "close": "16:00", "session_open": "0400",
        "session_close": "2000", "settlement_date": day} for day in days])
    receipt = canonical_json_bytes({"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://paper-api.alpaca.markets/v2/calendar", "query": {"start": "1998-01-01", "end": MAX_CUTOFF},
        "captured_at": "2026-10-14T16:00:00Z", "status": 200, "body_sha256": sha256_bytes(calendar), "size_bytes": len(calendar)})
    return {"protocol": protocol, "source_blobs": blobs, "calendar_raw": calendar,
            "calendar_receipt_raw": receipt, "source_manifest": manifest}, days


def calculate(arguments):
    return build_historical_baseline(**arguments)


def rebuild_source(arguments, symbol, raw):
    arguments["source_blobs"][symbol] = raw
    arguments["source_manifest"]["sources"][symbol].update(sha256=sha256_bytes(raw), size_bytes=len(raw))


class HistoricalBaselineTests(unittest.TestCase):
    def test_identical_frozen_signal_and_paired_arithmetic(self):
        arguments, days = fixture()
        material = calculate(arguments)
        qqq = next(row for row in material["rows"] if row["symbol"] == "QQQ" and row["signal_session"] == days[1])
        spy = next(row for row in material["rows"] if row["symbol"] == "SPY" and row["signal_session"] == days[1])
        self.assertEqual(qqq["status"], "OBSERVATIONAL_CANDIDATE")
        self.assertEqual(qqq["signal_return"], _ratio("199", "200"))
        self.assertEqual((qqq["entry_session"], qqq["exit_session"]), (days[2], days[3]))
        self.assertEqual(qqq["candidate_gross_return"], _ratio("103", "102"))
        self.assertTrue(qqq["pair_eligible"])
        self.assertEqual(spy["status"], "ABSTAIN_NONNEGATIVE_RETURN")
        self.assertEqual(material["report"]["summary"]["opportunity_count"], 130)

    def test_zero_change_abstains(self):
        arguments, days = fixture(mutate=lambda rows, _: rows["QQQ"][1].update(close="200"))
        row = calculate(arguments)["rows"][2]
        self.assertEqual(row["signal_session"], days[1])
        self.assertEqual(row["status"], "ABSTAIN_NONNEGATIVE_RETURN")
        self.assertEqual(row["signal_return"], "0")

    def test_future_prices_do_not_change_prior_signal(self):
        original, days = fixture()
        changed, _ = fixture(mutate=lambda rows, _: rows["QQQ"][3].update(open="500", close="500", volume="1"))
        before = calculate(original)["rows"][2]
        after = calculate(changed)["rows"][2]
        for field in ("status", "signal_return", "signal_close", "previous_close", "entry_session", "exit_session"):
            self.assertEqual(before[field], after[field], field)
        self.assertNotEqual(before["candidate_gross_return"], after["candidate_gross_return"])

    def test_missing_calendar_session_is_not_bridged_by_next_available_bar(self):
        arguments, days = fixture(mutate=lambda rows, _: rows["QQQ"].pop(2))
        material = calculate(arguments)
        by_date = {row["signal_session"]: row for row in material["rows"] if row["symbol"] == "QQQ"}
        self.assertEqual(by_date[days[2]]["status"], "DEFER_MISSING_INPUT")
        self.assertEqual(by_date[days[3]]["status"], "DEFER_MISSING_INPUT")
        self.assertIsNone(by_date[days[3]]["signal_return"])
        self.assertEqual(by_date[days[4]]["previous_session"], days[3])
        self.assertEqual(by_date[days[4]]["status"], "OBSERVATIONAL_CANDIDATE")

    def test_missing_control_keeps_candidate_but_excludes_paired_measurement(self):
        arguments, days = fixture(mutate=lambda rows, _: rows["SPY"].pop(3))
        material = calculate(arguments)
        row = material["rows"][2]
        self.assertEqual(row["status"], "OBSERVATIONAL_CANDIDATE")
        self.assertEqual(row["candidate_gross_return"], _ratio("103", "102"))
        self.assertFalse(row["pair_eligible"])
        self.assertIsNone(row["control_gross_return"])
        self.assertIsNone(row["cash_return"])
        self.assertGreater(material["report"]["summary"]["unpaired_candidate_count"], 2)

    def test_before_first_symbol_source_is_retained_without_fabricating_qqq(self):
        arguments, days = fixture(first_qqq=3)
        material = calculate(arguments)
        qqq = [row for row in material["rows"] if row["symbol"] == "QQQ"]
        self.assertEqual([row["status"] for row in qqq[:3]], ["SOURCE_NOT_YET_AVAILABLE"] * 3)
        self.assertEqual(qqq[3]["status"], "DEFER_MISSING_INPUT")
        self.assertEqual(material["report"]["cohort_anchor"], days[4])
        self.assertEqual(material["report"]["summary"]["opportunity_count"], 130)

    def test_last_two_candidate_horizons_remain_unmeasurable(self):
        arguments, days = fixture()
        material = calculate(arguments)
        qqq = [row for row in material["rows"] if row["symbol"] == "QQQ"]
        self.assertTrue(all(row["status"] == "OBSERVATIONAL_CANDIDATE" for row in qqq[-2:]))
        self.assertTrue(all(not row["pair_eligible"] for row in qqq[-2:]))
        self.assertTrue(all(row["candidate_gross_return"] is None for row in qqq[-2:]))
        self.assertEqual(material["report"]["summary"]["unpaired_candidate_count"], 2)

    def test_all_fixed_cohorts_including_last_partial_are_retained(self):
        arguments, days = fixture()
        material = calculate(arguments)
        self.assertEqual([row["signal_session_count"] for row in material["cohorts"]], [30, 30, 4])
        self.assertEqual([row["opportunity_count"] for row in material["cohorts"]], [60, 60, 8])
        self.assertEqual(material["cohorts"][0]["first_signal_session"], days[1])
        self.assertEqual(material["cohorts"][-1]["conclusion"], "INCONCLUSIVE_INCOMPLETE_COHORT")
        self.assertEqual(material["report"]["cohort_summary"]["cohort_count"], 3)
        self.assertEqual(material["report"]["cohort_summary"]["distribution_cohort_count"], 2)

    def test_missing_evidence_cohort_is_retained_not_positive(self):
        arguments, _ = fixture(mutate=lambda rows, _: rows["QQQ"].pop(10))
        material = calculate(arguments)
        self.assertEqual(material["cohorts"][0]["conclusion"], "INCONCLUSIVE_MISSING_EVIDENCE")
        self.assertEqual(material["report"]["cohort_summary"]["cohort_count"], 3)

    def test_zero_candidates_cohort_is_retained_too_few(self):
        def mutate(rows, _):
            for symbol in rows:
                for row in rows[symbol]:
                    row["close"] = "100"
        arguments, _ = fixture(mutate=mutate)
        material = calculate(arguments)
        self.assertEqual(material["cohorts"][0]["conclusion"], "INCONCLUSIVE_TOO_FEW_CANDIDATES")
        self.assertIsNone(material["report"]["summary"]["mean_gross_return"])
        self.assertEqual(material["report"]["summary"]["paired_candidate_count"], 0)

    def test_both_selected_symbols_average_to_equal_weight_control(self):
        def mutate(rows, _):
            for index, row in enumerate(rows["SPY"]):
                row["close"] = str(200 - index)
        arguments, _ = fixture(mutate=mutate)
        material = calculate(arguments)
        self.assertEqual(material["report"]["summary"]["mean_gross_excess_over_control"], "0")

    def test_no_net_return_pnl_or_economic_support_claim(self):
        arguments, _ = fixture()
        report = calculate(arguments)["report"]
        self.assertEqual(report["economic_support"], "NOT_EVALUABLE")
        self.assertEqual(report["summary"]["economic_support"], "NOT_EVALUABLE")
        self.assertIsNone(report["net_return"])
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertFalse(report["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertIn("RETROSPECTIVE_RECONSTRUCTION", report["scope"])

    def test_adj_close_never_rescales_opens_or_changes_results(self):
        arguments, _ = fixture()
        changed, _ = fixture(mutate=lambda rows, _: [row.update(adj_close="0.01") for row in rows["QQQ"]])
        self.assertEqual(calculate(arguments)["rows"], calculate(changed)["rows"])
        self.assertFalse(calculate(changed)["report"]["source_coverage"][0]["adjusted_close_used"])

    def test_decimal_ambient_context_cannot_change_results(self):
        arguments, _ = fixture()
        expected = calculate(arguments)
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_UP
            actual = calculate(arguments)
        self.assertEqual(actual, expected)

    def test_original_inputs_unchanged_and_no_network_calls(self):
        arguments, _ = fixture()
        before = deepcopy(arguments)
        with mock.patch("socket.socket", side_effect=AssertionError("no network")):
            calculate(arguments)
        self.assertEqual(arguments, before)

    def test_exact_source_hash_and_size_required(self):
        for field, value in (("sha256", "0" * 64), ("size_bytes", 1), ("size_bytes", True)):
            with self.subTest(field=field, value=value):
                arguments, _ = fixture()
                arguments["source_manifest"]["sources"]["QQQ"][field] = value
                with self.assertRaises(ValueError):
                    calculate(arguments)

    def test_exact_qqq_spy_universe_required(self):
        arguments, _ = fixture()
        arguments["source_blobs"]["DIA"] = arguments["source_blobs"].pop("QQQ")
        with self.assertRaises(ValueError):
            calculate(arguments)

    def test_calendar_receipt_hash_required(self):
        arguments, _ = fixture()
        receipt = json.loads(arguments["calendar_receipt_raw"])
        receipt["body_sha256"] = "0" * 64
        arguments["calendar_receipt_raw"] = canonical_json_bytes(receipt)
        with self.assertRaises(ValueError):
            calculate(arguments)

    def test_calendar_query_must_cover_1998(self):
        arguments, _ = fixture()
        receipt = json.loads(arguments["calendar_receipt_raw"])
        receipt["query"]["start"] = "2025-01-01"
        arguments["calendar_receipt_raw"] = canonical_json_bytes(receipt)
        with self.assertRaises(ValueError):
            calculate(arguments)

    def test_no_holdout_scoring_even_when_requested(self):
        arguments, _ = fixture()
        with self.assertRaisesRegex(ValueError, "withheld holdout"):
            build_historical_baseline(**arguments, cutoff="2026-03-11")

    def test_post_cutoff_source_prices_are_not_scored(self):
        arguments, _ = fixture()
        expected_rows = calculate(arguments)["rows"]
        for symbol in ("QQQ", "SPY"):
            raw = arguments["source_blobs"][symbol] + b"2026-03-11,INVALID,INVALID,INVALID,INVALID,INVALID,INVALID\n"
            rebuild_source(arguments, symbol, raw)
        result = calculate(arguments)
        self.assertEqual(result["rows"], expected_rows)
        self.assertTrue(all(row["signal_session"] <= MAX_CUTOFF for row in result["rows"]))
        self.assertTrue(all(row["exit_session"] is None or row["exit_session"] <= MAX_CUTOFF for row in result["rows"]))

    def test_csv_header_duplicate_order_and_noncalendar_dates_rejected(self):
        for mutation in (lambda raw: raw.replace(b"adj_close", b"adjusted_close", 1),
                         lambda raw: raw + raw.splitlines(keepends=True)[1],
                         lambda raw: raw.replace(b"2025-01-02", b"2025-01-04", 1)):
            with self.subTest(mutation=mutation):
                arguments, _ = fixture()
                rebuild_source(arguments, "QQQ", mutation(arguments["source_blobs"]["QQQ"]))
                with self.assertRaises(ValueError):
                    calculate(arguments)

    def test_nonfinite_negative_and_ohlc_invalid_values_rejected(self):
        for field, value in (("close", "NaN"), ("open", "Infinity"), ("close", "0"), ("close", "1e-999999"),
                             ("volume", "-1"), ("volume", "1.5"), ("open", "1001")):
            with self.subTest(field=field, value=value):
                arguments, _ = fixture(mutate=lambda rows, _: rows["QQQ"][1].update({field: value}))
                with self.assertRaises(ValueError):
                    calculate(arguments)

    def test_retained_provenance_and_exact_artifact_hashes(self):
        arguments, _ = fixture()
        arguments["source_manifest"]["declared_provenance"] = {"actions": False, "auto_adjust": False}
        material = calculate(arguments)
        report = material["report"]
        self.assertEqual(report["source_manifest"], arguments["source_manifest"])
        self.assertEqual(report["source_manifest_sha256"], sha256_bytes(canonical_json_bytes(arguments["source_manifest"])))
        self.assertEqual(report["protocol_sha256"], sha256_bytes(canonical_json_bytes(arguments["protocol"])))
        self.assertEqual(report["rows_evidence"]["sha256"], sha256_bytes(canonical_json_bytes(material["rows"])))
        self.assertEqual(report["cohorts_evidence"]["sha256"], sha256_bytes(canonical_json_bytes(material["cohorts"])))
        implementation = calculation_evidence()
        for reference in report["calculation_sources"]:
            self.assertEqual(reference["sha256"], sha256_bytes(implementation[reference["path"]]))


if __name__ == "__main__":
    unittest.main()
