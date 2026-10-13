"""Deterministic raw history coverage, chronology and replay adversaries."""
import copy
from decimal import Decimal, localcontext
import json
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.historical_intake import HistoricalIntakeExport
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_historical_intake import (
    build_historical_intake, parse_historical_json, validate_historical_dataset, verify_historical_intake,
)
from test_trading_historical_intake_contracts import source_material, refresh


class HistoricalIntakeProjectionTests(unittest.TestCase):
    def project(self, mutate=None):
        request, values, blobs = source_material()
        if mutate:
            mutate(request, values); request, values, blobs = refresh(request, values)
        return build_historical_intake(request, blobs)

    def assert_rejects(self, mutate):
        with self.assertRaises(ContractValidationError): self.project(mutate)

    def test_source_projection_preserves_native_decimals_and_raw_bytes(self):
        material = self.project(); dataset = material["dataset"]
        self.assertEqual(dataset.sessions[0]["bars"][0]["open"], "100")
        self.assertEqual(dataset.sessions[0]["bars"][0]["volume"], "10000")
        request, _, blobs = source_material()
        for ref in request["sources"].values():
            self.assertEqual(material["evidence"][ref["path"]], blobs[ref["sha256"]])

    def test_actual_extended_session_not_regular_close_sets_assumed_availability(self):
        material = self.project(); session = material["dataset"].sessions[0]
        self.assertEqual(session["close_at"], "2026-01-05T21:00:00Z")
        self.assertEqual(session["available_at"], "2026-01-06T01:01:00Z")
        self.assertFalse(material["dataset"].provenance["historical_point_in_time_verified"])
        self.assertFalse(material["dataset"].provenance["availability_assumption"]["assumption_verified"])

    def test_latest_assumed_unavailable_session_is_explicitly_excluded(self):
        material = self.project()
        self.assertEqual(material["export"].coverage["included_session_count"], 12)
        self.assertEqual(material["export"].coverage["calendar_sessions_in_window"], 13)
        self.assertEqual(material["export"].coverage["excluded_unavailable_sessions"], ["2026-01-22"])
        self.assertNotIn("alpaca-session-2026-01-22", [row["session_id"] for row in material["dataset"].sessions])

    def test_stricter_calendar_capture_is_the_availability_bound(self):
        material = self.project(lambda request, values: values["calendar_receipt_evidence"].update(captured_at="2026-01-21T23:00:00Z"))
        self.assertEqual(material["export"].coverage["excluded_unavailable_sessions"], ["2026-01-21", "2026-01-22"])

    def test_returned_dates_alone_determine_sessions_not_weekday_guessing(self):
        material = self.project()
        ids = [row["session_id"] for row in material["dataset"].sessions]
        self.assertNotIn("alpaca-session-2026-01-19", ids)
        self.assertEqual(len(ids), 12)

    def test_dst_and_early_close_come_from_returned_calendar(self):
        request, values, _ = source_material(["2026-10-30", "2026-11-02", "2026-11-03"])
        values["calendar_evidence"][1]["close"] = "13:00"
        request, values, blobs = refresh(request, values)
        material = build_historical_intake(request, blobs)
        sessions = material["dataset"].sessions
        self.assertEqual(sessions[0]["open_at"], "2026-10-30T13:30:00Z")
        self.assertEqual(sessions[1]["open_at"], "2026-11-02T14:30:00Z")
        self.assertEqual(sessions[1]["close_at"], "2026-11-02T18:00:00Z")

    def test_exact_replay_idempotence_and_stable_identity(self):
        material = self.project(); replay = verify_historical_intake(material["export"], material["blobs"])
        self.assertEqual(replay["export"].to_bytes(), material["export"].to_bytes())
        self.assertEqual(replay["dataset"].to_bytes(), material["dataset"].to_bytes())
        self.assertEqual(validate_historical_dataset(material["dataset"], material["blobs"])["dataset"].to_bytes(), material["dataset"].to_bytes())
        self.assertEqual(self.project()["export"].intake_id, material["export"].intake_id)

    def test_declared_delay_is_in_identity_and_not_optimized(self):
        original = self.project(); changed = self.project(lambda request, values: request["availability_assumption"].update(delay_seconds=3600))
        self.assertNotEqual(original["export"].intake_id, changed["export"].intake_id)
        self.assertEqual(changed["dataset"].sessions[0]["available_at"], "2026-01-06T02:00:00Z")

    def test_hash_size_and_missing_source_reject_before_projection(self):
        request, _, blobs = source_material()
        for corruption in (b"{}", b"garbage"):
            altered = dict(blobs); altered[request["sources"]["bars_evidence"]["sha256"]] = corruption
            with self.assertRaises(ContractValidationError): build_historical_intake(request, altered)
        altered = dict(blobs); altered.pop(request["sources"]["calendar_evidence"]["sha256"])
        with self.assertRaises(ContractValidationError): build_historical_intake(request, altered)

    def test_receipt_hash_binding_and_capture_clock_reject(self):
        request, values, blobs = source_material()
        receipt = values["bars_receipt_evidence"]; receipt["body_sha256"] = "1" * 64
        raw = canonical_json_bytes(receipt); ref = request["sources"]["bars_receipt_evidence"]
        ref.update(sha256=sha256_bytes(raw), size_bytes=len(raw)); blobs[sha256_bytes(raw)] = raw
        with self.assertRaises(ContractValidationError): build_historical_intake(request, blobs)
        self.assert_rejects(lambda request, values: values["bars_receipt_evidence"].update(captured_at="2026-01-23T00:00:00Z"))

    def test_raw_pagination_never_silently_truncates(self):
        self.assert_rejects(lambda request, values: values["bars_evidence"].update(next_page_token="next"))

    def test_feed_adjustment_and_source_query_universe_mismatch_reject(self):
        for changes in ({"feed": "sip"}, {"adjustment": "split"}, {"symbols": "SYNTHB,SYNTHA"}, {"symbols": "SYNTHA"}):
            self.assert_rejects(lambda request, values: values["bars_receipt_evidence"]["query"].update(changes))

    def test_source_schema_extra_missing_or_hidden_symbol_reject(self):
        for mutation in (lambda request, values: values["bars_evidence"].update(metadata={}),
                         lambda request, values: values["bars_evidence"]["bars"].pop("SYNTHB"),
                         lambda request, values: values["bars_evidence"]["bars"].update(OTHER=[]),
                         lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"][0].pop("vw")):
            self.assert_rejects(mutation)

    def test_raw_duplicate_json_keys_nonfinite_and_number_precision(self):
        for raw in (b'{"bars":{},"bars":{}}', b'[NaN]', b'[Infinity]', b'\xff',
                    b'[1e999999999]', b'[1e-999999999]', b'[' + b'9' * 200 + b']'):
            with self.assertRaises(ContractValidationError): parse_historical_json(raw)
        self.assertEqual(parse_historical_json(b'[0.123456789012345678]'), [Decimal("0.123456789012345678")])

    def test_missing_calendar_eligible_symbol_bar_and_empty_bars_reject(self):
        for mutation in (lambda request, values: values["calendar_evidence"].pop(0),
                         lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"].pop(0),
                         lambda request, values: values["bars_evidence"]["bars"].update(SYNTHB=[])):
            self.assert_rejects(mutation)

    def test_mixed_symbol_missing_session_cannot_be_intersected_away(self):
        self.assert_rejects(lambda request, values: values["bars_evidence"]["bars"]["SYNTHB"].pop(3))

    def test_out_of_window_bars_and_insufficient_query_interval_reject(self):
        self.assert_rejects(lambda request, values: request["date_range"].update(start="2026-01-06"))
        self.assert_rejects(lambda request, values: values["bars_receipt_evidence"]["query"].update(start="2026-01-06T00:00:00Z"))
        self.assert_rejects(lambda request, values: values["calendar_receipt_evidence"]["query"].update(end="2026-01-21"))

    def test_calendar_exact_fields_clocks_order_and_bounds_reject(self):
        for mutation in (lambda request, values: values["calendar_evidence"][0].pop("session_close"),
                         lambda request, values: values["calendar_evidence"][0].update(close="2000"),
                         lambda request, values: values["calendar_evidence"][0].update(session_close="2500"),
                         lambda request, values: values["calendar_evidence"][0].update(session_close="1500"),
                         lambda request, values: values["calendar_evidence"].reverse(),
                         lambda request, values: values["calendar_evidence"].append(values["calendar_evidence"][-1])):
            self.assert_rejects(mutation)

    def test_daily_bar_timestamp_must_be_new_york_midnight_not_an_event_close(self):
        for stamp in ("2026-01-05T00:00:00Z", "2026-01-05T21:00:00Z", "2026-01-05T05:00:00.000001Z"):
            self.assert_rejects(lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"][0].update(t=stamp))

    def test_daily_bar_order_duplicates_and_non_session_date_reject(self):
        for mutation in (lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"].reverse(),
                         lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"].append(values["bars_evidence"]["bars"]["SYNTHA"][0]),
                         lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"][0].update(t="2026-01-04T05:00:00Z")):
            self.assert_rejects(mutation)

    def test_native_numeric_boolean_string_fractional_count_negative_volume_reject(self):
        for field, value in (("o", True), ("c", "101"), ("n", 0.5), ("v", -1), ("v", 1.5), ("vw", 0)):
            self.assert_rejects(lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"][0].update({field: value}))

    def test_ohlc_inconsistent_ranges_reject(self):
        for changes in ({"l": 103}, {"h": 98}, {"c": 104}, {"o": 0}):
            self.assert_rejects(lambda request, values: values["bars_evidence"]["bars"]["SYNTHA"][0].update(changes))

    def test_no_eligible_completed_sessions_reject_instead_of_fabricating_history(self):
        self.assert_rejects(lambda request, values: values["bars_receipt_evidence"].update(captured_at="2026-01-05T22:00:00Z"))

    def test_declared_limit_cannot_be_bypassed_by_retained_response(self):
        self.assert_rejects(lambda request, values: values["bars_receipt_evidence"]["query"].update(limit=1))

    def test_reserved_request_dataset_paths_cannot_shadow_raw_source(self):
        request, _, blobs = source_material()
        for path in ("historical-intake/request.v1.json", "historical-intake/dataset.v2.json"):
            value = copy.deepcopy(request); value["sources"]["bars_evidence"]["path"] = path
            with self.assertRaises(ContractValidationError): build_historical_intake(value, blobs)

    def test_dataset_and_manifest_tampering_cannot_pass_replay(self):
        material = self.project(); value = material["dataset"].to_dict()
        value["sessions"][0]["bars"][0]["close"] = "100"
        with self.assertRaises(ContractValidationError): validate_historical_dataset(value, material["blobs"])
        value = material["export"].to_dict(); value["coverage"]["included_start_session"] = "2026-01-06"
        with self.assertRaises(ContractValidationError): verify_historical_intake(value, material["blobs"])

    def test_export_authority_or_missing_limitations_cannot_be_promoted(self):
        material = self.project()
        for mutation in (lambda row: row.update(auto_trading_enabled=True), lambda row: row["authority"].update(execution_enabled=True),
                         lambda row: row["limitations"].pop(), lambda row: row.update(schema_version="blackpod.historical_intake_export.v2")):
            value = material["export"].to_dict(); mutation(value)
            with self.assertRaises(ContractValidationError): HistoricalIntakeExport.from_mapping(value)

    def test_no_socket_subprocess_broker_or_ambient_decimal_dependence(self):
        original = self.project()["export"].to_bytes()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("producer forbidden")), localcontext() as context:
            context.prec = 2
            material = self.project()
        self.assertEqual(original, material["export"].to_bytes())


if __name__ == "__main__": unittest.main()
