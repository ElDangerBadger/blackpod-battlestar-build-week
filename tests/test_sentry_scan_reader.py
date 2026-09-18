"""Synthetic transport checks; no market acquisition or scientific experiments."""
import copy
from datetime import datetime, timezone
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

from blackpod_build_week import sentry_scan_reader as module
from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader, main


def seal(value, field, prefix):
    value[field] = prefix + module._digest({k: v for k, v in value.items() if k != field})
    return value


def fixture_receipt():
    """Small synthetic wire receipt, deliberately not scientific test evidence."""
    h = "a" * 64
    session, timestamp = "2026-09-17", "2026-09-18T05:00:00+00:00"
    rows, windows = [], []
    for name, profile in (("AAPL", "GENERAL_EQUITY"), ("SPY", "ETF")):
        rows.append(dict(symbol=name, status="OBSERVED", reasons=[], profile=profile, metadata_fingerprint=h,
            history=dict(file_name=name + ".csv", sha256=h, byte_size=2000, provider="synthetic", captured_at=timestamp,
                source_receipt_id="synthetic-capture", first_session="2026-01-01", last_session=session, row_count=200),
            failure_evidence=None, history_validation=dict(report_id="synthetic-history", structurally_valid=True,
                research_usable=True, errors=[], warnings=["SYNTHETIC_FIXTURE"]), observation_ids={}))
    for lookback in (20, 60):
        sensors, assessments, selected, excluded = [], [], [], []
        for row in rows:
            name, profile = row["symbol"], row["profile"]
            sensor = dict(symbol=name, instrument_class="ETF" if profile == "ETF" else "EQUITY", profile=profile,
                as_of=timestamp, state="RESEARCH_OBSERVATION", direction="UNKNOWN", calibration_status="UNCALIBRATED",
                measurements=[], measurement_context=[["lookback", str(lookback)], ["observed_session", session], ["metadata_fingerprint", h]],
                provenance=[], quality_flags=[], missing_information=[], reasons=[], legacy_classification=None,
                legacy_scores=[], legacy_event_id=None, method_version="sentry.daily.v1", observation_only=True,
                order_submission_enabled=False, schema_version="sentry.sensor_result.v1")
            seal(sensor, "result_id", "sentry-sensor-"); sensors.append(sensor)
            row["observation_ids"][str(lookback)] = sensor["result_id"]
            eligible = name == "AAPL"
            assessment = dict(symbol=name, profile=profile, session_date=session, sensor_result_id=sensor["result_id"],
                calibration_id="synthetic-reference", metric_name="relative_volume", percentile=.99 if eligible else None,
                tail_exceeded=eligible, eligible=eligible, training_end="2022-12-31", exclusion_reasons=[] if eligible else ["METRIC_UNAVAILABLE_OR_INCOMPATIBLE"],
                quality_flags=[], observed_value=8.0 if eligible else None, threshold=2.0, reference_count=200,
                tail="HIGH", research_only=True, observation_only=True, order_submission_enabled=False,
                schema_version="sentry.anomaly_assessment.v1")
            seal(assessment, "assessment_id", "sentry-assessment-"); assessments.append(assessment)
            entry = dict(symbol=name, profile=profile, sensor_result_id=sensor["result_id"], assessment_ids=[assessment["assessment_id"]],
                percentile=.99 if eligible else None, metric_name="relative_volume" if eligible else None,
                winning_assessment_id=assessment["assessment_id"] if eligible else None,
                calibration_id="synthetic-reference" if eligible else None, reasons=["SELECTED"] if eligible else ["NO_ELIGIBLE_TAIL_METRIC"],
                assessment_exclusions=[] if eligible else [[assessment["assessment_id"], ["METRIC_UNAVAILABLE_OR_INCOMPATIBLE"]]], quality_flags=[])
            (selected if eligible else excluded).append(entry)
        policy = dict(policy_version="sentry.attention.max_eligible_percentile.v1", capacity=6,
            per_profile_capacity=[["ETF", 4], ["GENERAL_EQUITY", 4]], minimum_percentile=.95)
        attention = dict(schema_version="sentry.attention_selection.v1", **policy, session_date=session,
            selected=selected, excluded=excluded, input_assessment_ids=sorted(a["assessment_id"] for a in assessments),
            input_count=2, unique_assessment_count=2, duplicate_count=0, candidate_count=2,
            eligible_candidate_count=1, capacity_remaining=5, research_only=True, observation_only=True,
            order_submission_enabled=False, policy_id="sentry-attention-policy-" + module._digest(policy))
        seal(attention, "selection_id", "sentry-attention-")
        windows.append(dict(lookback=lookback, sensors=sensors, assessments=assessments, attention=attention))
    rows.insert(1, dict(symbol="IWM", status="EXCLUDED", reasons=["CAPTURE_CONFLICT"], profile=None,
        metadata_fingerprint=None, history=None, failure_evidence=dict(file_name="failure.json", sha256=h,
            byte_size=1000, receipt_id="synthetic-failure", status="CONFLICT"), history_validation=None, observation_ids=None))
    receipt = dict(schema_version="sentry.operational_scan.v1", scan_kind="OFFLINE_RESEARCH_SNAPSHOT", session_date=session,
        as_of=timestamp, manifest_sha256=h, reference_manifest_id="synthetic-references", validation_protocol_id="synthetic-protocol",
        calibration_ids=["synthetic-reference"], source_files=[dict(role=role, file_name=role + ".json", sha256=h, byte_size=1000) for role in ("protocol", "references")],
        configuration=dict(windows=[20, 60], minimum_history_sessions=66, capacity=6, minimum_percentile=.95,
            per_profile_capacity={"GENERAL_EQUITY": 4, "ETF": 4}),
        population=dict(requested=["AAPL", "IWM", "SPY"], observed=["AAPL", "SPY"], failed=["IWM"], requested_count=3, observed_count=2, failed_count=1),
        symbol_receipts=rows, windows=windows, limitations=["SYNTHETIC_TRANSPORT_FIXTURE_NOT_MARKET_EVIDENCE"],
        profile_statuses={"GENERAL_EQUITY": "RESEARCH_ONLY", "ETF": "RESEARCH_ONLY"}, research_only=True,
        production_ready=False, observation_only=True, order_submission_enabled=False, current_attention_published=False)
    return seal(receipt, "scan_id", "sentry-operational-scan-")


class SentryScanReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.archive = self.root / "scan.json"
        self.receipt = fixture_receipt(); self.write()
        clock = patch.object(module, "datetime", wraps=datetime); self.clock = clock.start(); self.addCleanup(clock.stop)
        self.clock.now.return_value = datetime(2026, 9, 18, 6, tzinfo=timezone.utc)

    def write(self):
        self.archive.write_text(json.dumps(self.receipt), encoding="utf-8")

    def read(self):
        return module.SentryScanReader(self.archive).current()

    def unavailable(self):
        result = self.read()
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertIsNone(result["source"]); self.assertIsNone(result["scan"])
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_no_default_discovery(self):
        with patch.object(module, "_read_regular") as read:
            result = module.SentryScanReader().current()
        read.assert_not_called(); self.assertEqual(result["status"], "NOT_CONFIGURED")

    def test_projection_preserves_failed_symbol_and_canonical_order(self):
        before = self.archive.read_bytes()
        with patch.object(module, "_read_regular", wraps=module._read_regular) as read:
            result = self.read()
        self.assertEqual(result["status"], "READY")
        read.assert_called_once_with(self.archive, module.MAX_SOURCE_BYTES)
        scan = result["scan"]
        self.assertEqual(scan["population"], self.receipt["population"])
        self.assertEqual(scan["symbols"][1]["reasons"], ["CAPTURE_CONFLICT"])
        self.assertEqual([w["selected"][0]["symbol"] for w in scan["windows"]], ["AAPL", "AAPL"])
        self.assertEqual(scan["windows"][0]["excluded"][0]["symbol"], "SPY")
        self.assertNotEqual(scan["as_of"], result["checked_at"])
        self.assertFalse(result["source"]["declared_evidence_reverified"])
        self.assertNotIn("sensors", scan["windows"][0]); self.assertNotIn("assessments", scan["windows"][0])
        self.assertLess(len(json.dumps(result)), module.MAX_FEED_BYTES)
        self.assertEqual(self.archive.read_bytes(), before)

    def test_missing_malformed_oversized_duplicate_keys_and_wrong_hash(self):
        for raw in (b"{}", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * (module.MAX_SOURCE_BYTES + 1)):
            with self.subTest(raw=raw[:40]):
                self.archive.write_bytes(raw); self.unavailable()
        self.receipt["population"]["observed_count"] = 3; self.write(); self.unavailable()
        self.archive.unlink(); self.unavailable()

    def test_symlink_file_parent_and_nonregular_refused(self):
        self.archive.unlink(); self.archive.symlink_to(self.root / "target"); self.unavailable(); self.archive.unlink()
        self.archive.mkdir(); self.unavailable(); self.archive.rmdir()
        os.mkfifo(self.archive); self.unavailable(); self.archive.unlink(); self.write()
        alias = self.root / "alias"; alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(module.SentryScanReader(alias / "scan.json").current()["status"], "UNAVAILABLE")

    def test_changed_during_read_refused(self):
        original = os.read; changed = False
        def mutate(fd, n):
            nonlocal changed
            data = original(fd, n)
            if not changed:
                changed = True; self.archive.write_bytes(self.archive.read_bytes() + b" ")
            return data
        with patch("blackpod_build_week.sentry_reader.os.read", side_effect=mutate): self.unavailable()

    def test_semantic_safety_population_dates_links_and_caps_rejected_even_if_resealed(self):
        mutations = [
            lambda r: r.update(order_submission_enabled=True), lambda r: r.update(research_only=False),
            lambda r: r.update(production_ready=True), lambda r: r.update(current_attention_published=True),
            lambda r: r.update(as_of="2099-01-01T00:00:00Z"), lambda r: r.update(session_date="2026-09-18"),
            lambda r: r["population"].update(failed=[]), lambda r: r["population"].update(observed_count=True),
            lambda r: r["profile_statuses"].update(ETF="PRODUCTION_CANDIDATE"),
            lambda r: r["configuration"].update(minimum_percentile=.90),
            lambda r: r["symbol_receipts"][0].update(reasons=["UNEXPECTED_REASON"]),
            lambda r: r["symbol_receipts"][1].update(reasons=[]),
            lambda r: r["symbol_receipts"][0]["history"].update(captured_at="2026-09-17T20:00:00Z"),
            lambda r: r["symbol_receipts"][0]["history"].update(source_receipt_id="/private/key"),
            lambda r: r["symbol_receipts"][0]["history_validation"].update(warnings=["/private/key"]),
            lambda r: r["symbol_receipts"][0]["history"].update(last_session="2026-09-16"),
            lambda r: r["symbol_receipts"][0]["observation_ids"].update({"20": "wrong"}),
            lambda r: r["windows"][0]["sensors"][0].update(order_submission_enabled=True),
            lambda r: r["windows"][0]["assessments"][0].update(research_only=False),
            lambda r: r["windows"][0]["attention"]["selected"][0].update(symbol="IWM"),
            lambda r: r["windows"][0]["attention"].update(capacity_remaining=6),
            lambda r: r["windows"][0]["attention"].update(eligible_candidate_count=True),
            lambda r: r["windows"][0]["attention"].update(current_attention_published=True),
            lambda r: r["windows"][0]["attention"]["selected"].append(copy.deepcopy(r["windows"][0]["attention"]["selected"][0])),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(mutation=i):
                self.receipt = fixture_receipt(); mutate(self.receipt)
                for window in self.receipt["windows"]:
                    for sensor in window["sensors"]: seal(sensor, "result_id", "sentry-sensor-")
                    for a in window["assessments"]: seal(a, "assessment_id", "sentry-assessment-")
                    seal(window["attention"], "selection_id", "sentry-attention-")
                seal(self.receipt, "scan_id", "sentry-operational-scan-"); self.write(); self.unavailable()

    def test_excluded_malformed_dates_do_not_block_healthy_symbols(self):
        row = self.receipt["symbol_receipts"][1]
        row["history"] = copy.deepcopy(self.receipt["symbol_receipts"][0]["history"])
        row["history"].update(first_session=None, last_session=None, row_count=0)
        row["failure_evidence"] = None; row["reasons"] = ["HISTORY_INVALID_OR_INSUFFICIENT"]
        row["history_validation"] = dict(report_id="synthetic-invalid", structurally_valid=False, research_usable=False, errors=["NO_HISTORY_ROWS"], warnings=[])
        seal(self.receipt, "scan_id", "sentry-operational-scan-"); self.write()
        self.assertEqual(self.read()["status"], "READY")

    def test_all_failed_is_valid_empty_selection_not_global_error(self):
        self.receipt["symbol_receipts"] = [self.receipt["symbol_receipts"][1]]
        self.receipt["population"] = dict(requested=["IWM"], observed=[], failed=["IWM"], requested_count=1, observed_count=0, failed_count=1)
        for w in self.receipt["windows"]:
            w.update(sensors=[], assessments=[])
            w["attention"].update(selected=[], excluded=[], input_assessment_ids=[], input_count=0, unique_assessment_count=0,
                candidate_count=0, eligible_candidate_count=0, capacity_remaining=6)
            seal(w["attention"], "selection_id", "sentry-attention-")
        seal(self.receipt, "scan_id", "sentry-operational-scan-"); self.write()
        self.assertEqual(self.read()["status"], "READY")

    def test_projection_bound_and_normalized_config(self):
        with patch.object(module, "MAX_FEED_BYTES", 1): self.unavailable()
        for path in (self.root / "../scan.json", self.root / "bad\nname", self.root / "bad\\name"):
            with self.subTest(path=path), self.assertRaises(ValueError): module.SentryScanReader(path)

    def test_large_failed_population_keeps_all_symbols_and_caps_only_display_diagnostics(self):
        rows = []
        for n in range(128):
            name = f"SYM{n:03d}"
            row = copy.deepcopy(self.receipt["symbol_receipts"][1])
            row.update(symbol=name, failure_evidence=None, reasons=["HISTORY_INVALID_OR_INSUFFICIENT"])
            row["history"] = copy.deepcopy(self.receipt["symbol_receipts"][0]["history"])
            row["history"].update(file_name=name + ".csv", first_session=None, last_session=None, row_count=128)
            row["history_validation"] = dict(report_id="synthetic-history-" + name, structurally_valid=False,
                research_usable=False, errors=[f"ROW_{i}_SESSION_AFTER_DECLARED_AVAILABILITY_UTC_DATE" for i in range(128)],
                warnings=[f"SYNTHETIC_WARNING_{i}" for i in range(128)])
            rows.append(row)
        names = [r["symbol"] for r in rows]
        self.receipt["symbol_receipts"] = rows
        self.receipt["population"] = dict(requested=names, observed=[], failed=names, requested_count=128, observed_count=0, failed_count=128)
        for window in self.receipt["windows"]:
            window.update(sensors=[], assessments=[])
            window["attention"].update(selected=[], excluded=[], input_assessment_ids=[], input_count=0, unique_assessment_count=0,
                candidate_count=0, eligible_candidate_count=0, capacity_remaining=6)
            seal(window["attention"], "selection_id", "sentry-attention-")
        seal(self.receipt, "scan_id", "sentry-operational-scan-"); self.write()
        original = self.archive.read_bytes()
        result = self.read()
        self.assertEqual(result["status"], "READY")
        self.assertLessEqual(len(module.canonical_json_bytes(result)), module.MAX_FEED_BYTES)
        self.assertEqual(result["scan"]["population"]["failed"], names)
        self.assertEqual(len(result["scan"]["symbols"]), 128)
        for supplied, displayed in zip(rows, result["scan"]["symbols"]):
            self.assertEqual(displayed["history"]["sha256"], supplied["history"]["sha256"])
            self.assertEqual(displayed["history_validation"]["report_id"], supplied["history_validation"]["report_id"])
            for key in ("errors", "warnings"):
                self.assertEqual(displayed["history_validation"][key][:8], supplied["history_validation"][key][:8])
                self.assertEqual(displayed["history_validation"][key][8], "ADDITIONAL_DIAGNOSTICS_OMITTED:120")
                self.assertEqual(len(displayed["history_validation"][key]), 9)
        self.assertEqual(self.archive.read_bytes(), original)


class SentryScanHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.server = CabinHTTPServer(CabinReader(), self.root, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self, path="/live/sentry/scan.json", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse(); result = response.status, dict(response.getheaders()), response.read()
        connection.close(); return result

    def test_optional_endpoint_is_independent_and_no_store(self):
        with patch.object(self.server.reader, "current") as mission, patch.object(self.server.sentry_reader, "current") as legacy, patch.object(self.server.sentry_research_reader, "current") as research:
            status, headers, raw = self.request()
        mission.assert_not_called(); legacy.assert_not_called(); research.assert_not_called()
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw)["status"], "NOT_CONFIGURED")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(self.request(method="HEAD")[2], b"")

    def test_request_guards_preserved(self):
        with patch.object(self.server.sentry_scan_reader, "current") as read:
            for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
                self.assertEqual(self.request(headers=headers)[0], 403)
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                self.assertEqual(self.request(method=method)[0], 405)
            for path in ("/live/sentry/scan.json?path=/private", "/live/sentry/../scan.json", "/live/sentry/%2e%2e/scan.json", "/live/sentry/scan.json/extra"):
                self.assertEqual(self.request(path)[0], 404)
        read.assert_not_called()

    def test_cli_option_independent_of_research_and_microcap(self):
        instance = Mock(); instance.server_port = 5174; instance.serve_forever.side_effect = KeyboardInterrupt
        with patch("blackpod_build_week.cabin_reader.CabinHTTPServer", return_value=instance) as server:
            self.assertEqual(main(["--sentry-scan-archive", "/explicit/scan.json"]), 0)
        self.assertEqual(server.call_args.kwargs["sentry_scan_reader"].archive, Path("/explicit/scan.json"))

    def test_cli_rejects_unsafe_path_before_start(self):
        with patch("blackpod_build_week.cabin_reader.CabinHTTPServer") as server, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): main(["--sentry-scan-archive", "/explicit/../scan.json"])
        server.assert_not_called()
