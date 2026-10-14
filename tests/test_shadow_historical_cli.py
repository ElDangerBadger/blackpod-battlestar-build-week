"""Offline historical capture, publication, exact replay and source boundaries."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import date, timedelta
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch

from blackpod_build_week import shadow_historical_baseline_cli as cli
from blackpod_build_week import shadow_historical_calendar as capture
from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.shadow_experiment import freeze_experiment
from blackpod_build_week.shadow_experiment_capture import ExperimentCaptureError
from blackpod_build_week.shadow_historical_presentation import render_historical_baseline
from test_shadow_experiment import fixture as protocol_fixture
from test_shadow_experiment_capture import Response
from test_shadow_historical_baseline import fixture, calculate
from test_trading_research_contracts import plan_mapping


def protected_fixture():
    day = date(2026, 3, 5)
    before = []
    while len(before) < 11:
        if day.weekday() < 5:
            before.append(day.isoformat())
        day -= timedelta(days=1)
    days = list(reversed(before))
    day = date(2026, 3, 6)
    while len(days) < 14:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    raw = canonical_json_bytes([{"date": value, "open": "09:30", "close": "16:00", "session_open": "0400",
        "session_close": "2000", "settlement_date": value} for value in days])
    receipt = canonical_json_bytes({"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": capture.URL, "query": {"start": days[0], "end": days[-1]}, "captured_at": "2026-10-14T16:00:00Z",
        "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)})
    plan = plan_mapping()
    plan["universe"] = ["QQQ", "SPY"]
    return {"sources/protected-plan.json": TradingResearchPlan.from_mapping(plan).to_bytes(),
            "sources/protected-calendar.json": raw, "sources/protected-calendar.receipt.json": receipt}


class CalendarCaptureTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.credentials = PaperCredentials("fixture-historical-key", "fixture-historical-secret")
        self.raw = canonical_json_bytes([{"date": "1998-01-02", "open": "09:30", "close": "16:00",
            "session_open": "0400", "session_close": "2000", "settlement_date": "1998-01-06"}])

    def test_one_fixed_calendar_get_exact_receipt(self):
        requests = []
        def open_request(request, timeout):
            requests.append(request)
            return Response(request.full_url, self.raw)
        with patch.object(capture, "build_opener", return_value=Mock(open=open_request)):
            raw, receipt = capture.calendar_get("1998-01-01", "2026-03-05", self.credentials)
        self.assertEqual(raw, self.raw)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].get_method(), "GET")
        self.assertTrue(requests[0].full_url.startswith(capture.URL + "?"))
        self.assertEqual(json.loads(receipt)["body_sha256"], sha256_bytes(raw))
        self.assertNotIn(b"fixture-historical-secret", receipt)

    def test_scope_escapes_holdout_future_and_other_endpoints_refused(self):
        for start, end in (("1997-01-01", "2026-03-05"), ("1998-01-01", "2026-03-06"),
                           ("https://host", "2026-03-05"), ("2026-03-05", "1998-01-01")):
            with self.subTest(start=start), patch.object(capture, "build_opener") as factory:
                with self.assertRaises(ExperimentCaptureError):
                    capture.calendar_get(start, end, self.credentials)
                factory.assert_not_called()

    def test_redirect_invalid_body_and_credential_echo_refused(self):
        for body, url in ((self.raw, "https://example.com"), (b"not json", None),
                          (b'[{"secret":"fixture-historical-secr\\u0065t"}]', None)):
            with self.subTest(body=body):
                def open_request(request, timeout):
                    return Response(url or request.full_url, body)
                with patch.object(capture, "build_opener", return_value=Mock(open=open_request)):
                    with self.assertRaises(ExperimentCaptureError):
                        capture.calendar_get("1998-01-01", "2026-03-05", self.credentials)

    def test_oversized_response_refused_without_retention(self):
        with patch.object(capture, "build_opener") as factory:
            factory.return_value.open.side_effect = lambda request, timeout: Response(request.full_url, b"x" * (capture.MAX_BYTES + 1))
            with self.assertRaisesRegex(ExperimentCaptureError, "RESPONSE_TOO_LARGE"):
                capture.calendar_get("1998-01-01", "2026-03-05", self.credentials)


class HistoricalBundleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        arguments, _ = fixture()
        self.arguments = arguments
        self.root = self.base / "baseline"
        self.history = self.base / "history"
        self.history.mkdir()
        for symbol, raw in arguments["source_blobs"].items():
            (self.history / (symbol + ".csv")).write_bytes(raw)
        material = calculate(arguments)
        self.manifest = self.history / "backfill.json"
        self.manifest.write_bytes(canonical_json_bytes({"provider": "yfinance", "interval": "1d",
            "generated_at": "2026-07-16T23:30:11Z", "series": [{"symbol": row["symbol"],
                "row_count": row["source_row_count"], "first_date": row["source_first_date"],
                "last_date": row["source_last_date"]} for row in material["report"]["source_coverage"]]}))
        self.calendar = self.base / "calendar"
        self.calendar.mkdir()
        (self.calendar / "calendar.json").write_bytes(arguments["calendar_raw"])
        (self.calendar / "calendar.receipt.json").write_bytes(arguments["calendar_receipt_raw"])
        self.protected = self.base / "protected"
        source_paths = {"protected-plan.json": "trading-research/registered-plan.v2.json",
                        "protected-calendar.json": "source/calendar.raw",
                        "protected-calendar.receipt.json": "source/calendar.receipt.v1.json"}
        for name, raw in protected_fixture().items():
            target = self.protected / source_paths[Path(name).name]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.pilot = self.base / "pilot"
        protocol, evidence = protocol_fixture()
        freeze_experiment(self.pilot, protocol, evidence)
        self.before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.pilot.rglob("*") if path.is_file()}
        self.args = argparse.Namespace(output_root=self.root, experiment_root=self.pilot, history_root=self.history,
            backfill_manifest=self.manifest, calendar_root=self.calendar, protected_study_root=self.protected,
            runtime_root=self.base / "runtime")

    def test_build_verify_retry_leave_live_journal_and_runtime_unchanged(self):
        self.assertTrue(cli.build_bundle(self.args)["written"])
        before = {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertTrue(cli.verify_bundle(self.root)["valid"])
        self.assertFalse(cli.build_bundle(self.args)["written"])
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertEqual(self.before, {str(path): (path.read_bytes(), path.stat().st_mtime_ns) for path in self.pilot.rglob("*") if path.is_file()})
        self.assertFalse(self.args.runtime_root.exists())

    def test_interrupted_publication_and_postcommit_retry_recover_exactly(self):
        actual_write = cli._write
        for target, after_write in (("rows.json", False), ("bundle-manifest.json", True)):
            with self.subTest(target=target):
                self.args.output_root = self.base / ("recovery-" + target.replace(".", "-"))
                def interrupted(path, raw, sources):
                    if Path(path).name == target:
                        if after_write:
                            actual_write(path, raw, sources)
                        raise OSError("authored interruption")
                    actual_write(path, raw, sources)
                with patch.object(cli, "_write", side_effect=interrupted), self.assertRaises(OSError):
                    cli.build_bundle(self.args)
                retry = cli.build_bundle(self.args)
                self.assertEqual(retry["written"], not after_write)
                self.assertTrue(cli.verify_bundle(self.args.output_root)["valid"])

    def test_declared_provenance_cannot_upgrade_unknown_cost_or_feed(self):
        cli.build_bundle(self.args)
        report = json.loads((self.root / "report.json").read_bytes())
        evidence = {ref["path"]: (self.root / ref["path"]).read_bytes()
                    for ref in json.loads((self.root / "bundle-manifest.json").read_bytes())["files"]}
        manifest = report["source_manifest"]
        manifest["data_semantics"]["net_costs_available"] = True
        with self.assertRaisesRegex(ValueError, "verified semantics"):
            cli.validate_provenance({"report": report}, manifest, evidence)

    def test_protected_scope_derived_from_plan_and_calendar(self):
        scope, evidence = cli.protected_scope(self.protected)
        self.assertEqual(scope["maximum_scored_date"], "2026-03-05")
        self.assertEqual(scope, cli.protected_scope_from_bytes(evidence))
        changed = dict(evidence)
        changed["sources/protected-calendar.json"] += b" "
        with self.assertRaises(ValueError):
            cli.protected_scope_from_bytes(changed)

    def test_changed_input_conflicts_without_overwriting_first_report(self):
        cli.build_bundle(self.args)
        report = (self.root / "report.json").read_bytes()
        source = self.history / "QQQ.csv"
        source.write_bytes(source.read_bytes().replace(b",200,99,", b",201,99,", 1))
        with self.assertRaises(ValueError):
            cli.build_bundle(self.args)
        self.assertEqual(report, (self.root / "report.json").read_bytes())

    def test_retained_source_and_report_tampering_fails(self):
        cli.build_bundle(self.args)
        path = self.root / "rows.json"
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            cli.verify_bundle(self.root)

    def test_rehashed_forged_protected_provenance_still_fails_semantic_replay(self):
        cli.build_bundle(self.args)
        path = self.root / "sources/protected-plan.json"
        plan = json.loads(path.read_bytes())
        plan["protocol"]["folds"][0]["test"]["end_index"] = 9
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(plan))
        bundle_path = self.root / "bundle-manifest.json"
        bundle = json.loads(bundle_path.read_bytes())
        for ref in bundle["files"]:
            if ref["path"] == "sources/protected-plan.json":
                ref.update(sha256=sha256_bytes(path.read_bytes()), size_bytes=path.stat().st_size)
        bundle_path.chmod(0o600)
        bundle_path.write_bytes(canonical_json_bytes(bundle))
        with self.assertRaises(ValueError):
            cli.verify_bundle(self.root)

    def test_rehashed_other_hypothesis_rejected_before_calculation(self):
        from blackpod_build_week.trading_hypotheses import catalog_hypotheses, catalog_documents
        cli.build_bundle(self.args)
        other = next(doc for doc in catalog_documents(catalog_hypotheses("2026-10-01T12:00:00Z", "fixture-author"))
                     if doc.hypothesis_id == "five-session-continuation-v1").to_bytes()
        hypothesis = self.root / "sources/hypothesis.json"
        hypothesis.chmod(0o600)
        hypothesis.write_bytes(other)
        path = self.root / "sources/protocol.json"
        protocol = json.loads(path.read_bytes())
        protocol["hypothesis_evidence"].update(sha256=sha256_bytes(other), size_bytes=len(other))
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(protocol))
        bundle_path = self.root / "bundle-manifest.json"
        bundle = json.loads(bundle_path.read_bytes())
        for ref in bundle["files"]:
            if ref["path"] in {"sources/protocol.json", "sources/hypothesis.json"}:
                raw = (self.root / ref["path"]).read_bytes()
                ref.update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        bundle_path.chmod(0o600)
        bundle_path.write_bytes(canonical_json_bytes(bundle))
        with patch("blackpod_build_week.shadow_historical_baseline.build_historical_baseline", side_effect=AssertionError("calculation must not run")):
            with self.assertRaisesRegex(ValueError, "source hypothesis differs"):
                cli.verify_bundle(self.root)

    def test_render_escapes_source_text_and_labels_historical_quantiles(self):
        material = calculate(self.arguments)
        material["report"]["report_id"] = "<script>unsafe()</script>"
        html = render_historical_baseline(material)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("not confidence intervals", html)
        self.assertIn("auto-trading OFF", html)

    def test_no_writes_inside_prospective_journal_or_source_storage(self):
        for root in (self.pilot / "nested", self.history / "nested", self.base / "missions" / "nested"):
            with self.subTest(root=root):
                self.args.output_root = root
                with self.assertRaises((ValueError, RuntimeError)):
                    cli.build_bundle(self.args)

    def test_capture_retry_uses_existing_receipt_without_credentials_or_provider(self):
        out, err = StringIO(), StringIO()
        with patch.object(cli, "calendar_get", side_effect=AssertionError("no GET")), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["capture-calendar", "--output-root", str(self.calendar),
                "--runtime-root", str(self.args.runtime_root), "--credentials-file", str(self.base / "missing.env"), "--credential-format", "PAPER_ENV"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["provider_calls"], 0)


if __name__ == "__main__":
    unittest.main()
