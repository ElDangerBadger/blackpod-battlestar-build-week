"""Strict local retained-capture declarations; no credentials or network."""
import copy
from datetime import datetime, time, timezone
import json
import unittest
from zoneinfo import ZoneInfo

from blackpod_build_week.contracts.historical_intake import (
    HistoricalIntakeRequest, HistoricalIntakeExport, validate_historical_capture,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


def authority():
    return {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def source_material(days=None):
    days = days or ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12",
                    "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-20", "2026-01-21", "2026-01-22"]
    calendar = [{"date": day, "open": "09:30", "close": "16:00", "session_open": "0400", "session_close": "2000",
                 "settlement_date": day} for day in days]
    bars = {symbol: [{"t": datetime.combine(datetime.fromisoformat(day).date(), time(), ZoneInfo("America/New_York"))
                     .astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "o": 100 + index, "h": 102 + index, "l": 99 + index, "c": 101 + index,
                    "v": 10000, "n": 500, "vw": 100.125 + index} for index, day in enumerate(days)] for symbol in ["SYNTHA", "SYNTHB"]}
    captured = days[-1] + "T23:00:00Z"
    values = {"bars_evidence": {"bars": bars, "next_page_token": None}, "calendar_evidence": calendar}
    values["bars_receipt_evidence"] = {"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://data.alpaca.markets/v2/stocks/bars", "query": {"symbols": "SYNTHA,SYNTHB", "timeframe": "1Day",
        "start": days[0] + "T00:00:00Z", "end": captured, "feed": "iex", "adjustment": "raw", "sort": "asc", "limit": 10000},
        "captured_at": captured, "status": 200, "body_sha256": "0" * 64, "size_bytes": 1}
    values["calendar_receipt_evidence"] = {"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://paper-api.alpaca.markets/v2/calendar", "query": {"start": days[0], "end": days[-1]},
        "captured_at": captured, "status": 200, "body_sha256": "0" * 64, "size_bytes": 1}
    request = {"schema_version": "blackpod.trading_historical_intake_request.v1", "run_id": "synthetic-history-intake",
        "recorded_at": days[-1] + "T23:01:00Z", "domain": "TRADING", "mode": "OFFLINE_RESEARCH",
        "scope": "RETAINED_DAILY_RESEARCH_INTAKE_ONLY", "universe": ["SYNTHA", "SYNTHB"],
        "date_range": {"start": days[0], "end": days[-1]}, "feed": "IEX", "adjustment": "RAW",
        "availability_assumption": {"policy": "RETURNED_SESSION_END_PLUS_DECLARED_DELAY", "delay_seconds": 60,
            "declared_by": "synthetic-research-author", "rationale": "Fixture delay demonstrates a declared unverified experimental assumption."},
        "sources": {}, "auto_trading_enabled": False, "authority": authority()}
    return refresh(request, values)


def refresh(request, values):
    """Rebind synthetic sources after deliberate semantic corruption."""
    request, values = copy.deepcopy(request), copy.deepcopy(values)
    paths = {"bars_evidence": "source/bars.raw", "calendar_evidence": "source/calendar.raw",
             "bars_receipt_evidence": "source/bars-receipt.json", "calendar_receipt_evidence": "source/calendar-receipt.json"}
    for body, receipt in (("bars_evidence", "bars_receipt_evidence"), ("calendar_evidence", "calendar_receipt_evidence")):
        raw = canonical_json_bytes(values[body])
        values[receipt]["body_sha256"], values[receipt]["size_bytes"] = sha256_bytes(raw), len(raw)
    blobs = {}
    for field, value in values.items():
        raw = canonical_json_bytes(value)
        request["sources"][field] = {"path": paths[field], "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        blobs[sha256_bytes(raw)] = raw
    return request, values, blobs


class HistoricalIntakeContractTests(unittest.TestCase):
    def assert_request_rejects(self, mutate):
        value, _, _ = source_material(); mutate(value)
        with self.assertRaises(ContractValidationError): HistoricalIntakeRequest.from_mapping(value)

    def test_request_roundtrip_and_immutability(self):
        value, _, _ = source_material(); request = HistoricalIntakeRequest.from_mapping(value)
        original = request.to_bytes(); value["universe"].clear(); request.sources.clear()
        self.assertEqual(HistoricalIntakeRequest.from_bytes(original).to_bytes(), original)
        self.assertEqual(request.to_bytes(), original)

    def test_unknown_and_missing_fields_reject(self):
        for mutation in (lambda row: row.update(policy=True), lambda row: row.pop("date_range"),
                         lambda row: row["availability_assumption"].update(confidence="1"),
                         lambda row: row["sources"].update(broker_key="secret")):
            self.assert_request_rejects(mutation)

    def test_no_execution_modes_or_investment_authority(self):
        for field, value in (("mode", "LIVE"), ("mode", "PAPER"), ("domain", "INVESTMENT"),
                             ("scope", "EXECUTION_ONLY"), ("auto_trading_enabled", True), ("auto_trading_enabled", 0)):
            self.assert_request_rejects(lambda row: row.update({field: value}))

    def test_all_authority_flags_are_strictly_false(self):
        for flag in authority():
            for value in (True, 0, "false"):
                self.assert_request_rejects(lambda row: row["authority"].update({flag: value}))

    def test_assumption_must_be_explicit_not_point_in_time_claim(self):
        for mutation in (lambda row: row["availability_assumption"].update(policy="POINT_IN_TIME_VERIFIED"),
                         lambda row: row["availability_assumption"].update(declared_by=""),
                         lambda row: row["availability_assumption"].update(rationale=" ")):
            self.assert_request_rejects(mutation)

    def test_delay_is_bounded_integer_without_boolean_alias(self):
        for delay in (-1, True, 1.0, "60", 604801):
            self.assert_request_rejects(lambda row: row["availability_assumption"].update(delay_seconds=delay))
        for delay in (0, 604800):
            value, _, _ = source_material(); value["availability_assumption"]["delay_seconds"] = delay
            self.assertEqual(HistoricalIntakeRequest.from_mapping(value).availability_assumption["delay_seconds"], delay)

    def test_dates_validate_real_calendar_and_order(self):
        for day in ("2026-02-30", "2026-1-05", "2026-01-05T00:00:00Z", None):
            self.assert_request_rejects(lambda row: row["date_range"].update(start=day))
        self.assert_request_rejects(lambda row: row["date_range"].update(start="2026-01-23"))

    def test_universe_cannot_sort_repair_or_assume_symbols(self):
        for symbols in ([], ["SYNTHB", "SYNTHA"], ["spy"], ["SYNTHA", "SYNTHA"], ["../SPY"]):
            self.assert_request_rejects(lambda row: row.update(universe=symbols))

    def test_feed_and_adjustment_are_fixed_not_mixable(self):
        self.assert_request_rejects(lambda row: row.update(feed="SIP"))
        self.assert_request_rejects(lambda row: row.update(adjustment="SPLIT"))

    def test_source_refs_distinct_bounded_hash_and_paths(self):
        for field, value in (("path", "../source"), ("sha256", "bad"), ("size_bytes", True)):
            self.assert_request_rejects(lambda row: row["sources"]["bars_evidence"].update({field: value}))
        self.assert_request_rejects(lambda row: row["sources"].update(calendar_evidence=row["sources"]["bars_evidence"]))

    def test_duplicate_json_nonfinite_and_nonobject_reject(self):
        for cls in (HistoricalIntakeRequest, HistoricalIntakeExport):
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff'):
                with self.assertRaises(ContractValidationError): cls.from_bytes(raw)

    def test_capture_http_get_and_status_are_exact(self):
        _, values, _ = source_material()
        for field, value in (("method", "POST"), ("status", True), ("status", 401), ("status", "200")):
            row = copy.deepcopy(values["bars_receipt_evidence"]); row[field] = value
            with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")

    def test_capture_url_must_be_known_data_endpoint_without_credentials(self):
        _, values, _ = source_material()
        for url in ("https://api.alpaca.markets/v2/orders", "https://secret@data.alpaca.markets/v2/stocks/bars", "http://data.alpaca.markets/v2/stocks/bars"):
            row = copy.deepcopy(values["bars_receipt_evidence"]); row["url"] = url
            with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")

    def test_capture_query_semantics_and_unknown_fields_are_exact(self):
        _, values, _ = source_material()
        for field, value in (("feed", "sip"), ("adjustment", "split"), ("timeframe", "1Min"), ("sort", "desc"), ("limit", True)):
            row = copy.deepcopy(values["bars_receipt_evidence"]); row["query"][field] = value
            with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")
        row["query"]["limit"] = 10000; row["query"]["page_token"] = "x"
        with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")

    def test_capture_query_clocks_and_dates_are_chronological(self):
        _, values, _ = source_material()
        row = values["bars_receipt_evidence"]; row["query"]["end"] = row["query"]["start"]
        with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")
        row = values["calendar_receipt_evidence"]; row["query"]["start"] = "2026-02-01"
        with self.assertRaises(ContractValidationError): validate_historical_capture(row, "calendar")

    def test_existing_calendar_capture_version_is_supported_exactly(self):
        _, values, _ = source_material(); row = values["calendar_receipt_evidence"]
        row["schema_version"] = "blackpod.read_only_calendar_capture.v1"
        self.assertEqual(validate_historical_capture(row, "calendar")["method"], "GET")
        with self.assertRaises(ContractValidationError): validate_historical_capture(row, "bars")


if __name__ == "__main__": unittest.main()
