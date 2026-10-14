"""Offline operator workflow tests with a synthetic returned calendar."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from datetime import datetime
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import shadow_experiment_cli as cli
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_experiment import HYPOTHESIS_PATH, CALENDAR_PATH, read_experiment_view
from blackpod_build_week.shadow_experiment_capture import URLS, ExperimentCaptureError
from test_shadow_experiment import fixture, snapshot


class ExperimentCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root, self.runtime = self.base / "experiment", self.base / "runtime"
        self.protocol, self.evidence = fixture()
        inputs = self.base / "inputs"
        inputs.mkdir()
        self.hypothesis = inputs / "hypothesis.json"
        self.hypothesis.write_bytes(self.evidence[HYPOTHESIS_PATH])
        self.credentials = self.base / "credentials" / "paper.env"
        self.credentials.parent.mkdir()
        self.credentials.write_text("ALPACA_KEY_ID_PAPER=fixture-pilot-key\nALPACA_SECRET_KEY_PAPER=fixture-pilot-secret\nALPACA_BASE_URL_PAPER=https://paper-api.alpaca.markets/v2\n")
        self.clock = "2026-10-02T14:01:00Z"
        self.calls = []

    def transport(self, kind, query, credentials):
        self.calls.append((kind, dict(query)))
        if kind == "calendar":
            rows = json.loads(self.evidence[CALENDAR_PATH])
            raw = canonical_json_bytes([row for row in rows if query["start"] <= row["date"] <= query["end"]])
        else:
            rows = json.loads(snapshot(self.protocol, self.evidence, self.clock)["bars_raw"])
            lower, upper = (datetime.fromisoformat(query[field].replace("Z", "+00:00")) for field in ("start", "end"))
            raw = canonical_json_bytes({"bars": {symbol: [row for row in values
                if lower <= datetime.fromisoformat(row["t"]) <= upper] for symbol, values in rows["bars"].items()}, "next_page_token": None})
        receipt = {"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET", "url": URLS[kind],
            "query": query, "captured_at": self.clock, "status": 200, "body_sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        return raw, canonical_json_bytes(receipt)

    def run_cli(self, command, *extra, root=None):
        args = [command, "--experiment-root", str(root or self.root)]
        if command in {"freeze", "collect"}:
            args += ["--runtime-root", str(self.runtime), "--credentials-file", str(self.credentials), "--credential-format", "PAPER_ENV"]
        if command == "freeze":
            args += ["--experiment-id", "cli-fixture", "--first-signal-session", "2026-10-02", "--hypothesis-file", str(self.hypothesis)]
        args += extra
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(cli, "market_get", side_effect=self.transport), patch.object(cli, "utc_now", side_effect=lambda: self.clock):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_freeze_collect_inspect_and_verify_without_any_worker(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        self.assertEqual(len(self.calls), 1)
        self.clock = "2026-10-02T14:02:00Z"
        self.assertEqual(self.run_cli("collect")[0], 0)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(read_experiment_view(self.root)["summary"]["recorded_prediction_count"], 0)
        self.clock = "2026-10-03T01:00:00Z"
        self.assertEqual(self.run_cli("collect")[0], 0)
        view = json.loads(self.run_cli("status")[1])
        self.assertEqual(view["summary"]["recorded_prediction_count"], 2)
        self.assertEqual(view["summary"]["candidate_count"], 1)
        self.assertEqual(json.loads(self.run_cli("verify")[1])["verification"]["event_count"], 3)
        self.assertFalse(self.runtime.exists())
        self.assertNotIn("fixture-pilot-secret", json.dumps(view))

    def test_immutable_freeze_retry_does_not_read_credentials_or_fetch(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        self.credentials.unlink()
        result = self.run_cli("freeze")
        self.assertEqual(result[0], 0)
        self.assertFalse(json.loads(result[1])["written"])
        self.assertEqual(len(self.calls), 1)

    def test_conflicting_retry_rejected_before_network(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        result = self.run_cli("freeze", "--experiment-id", "conflict")
        self.assertEqual(result[0], 2)
        self.assertEqual(len(self.calls), 1)

    def test_clock_override_is_not_a_cli_argument(self):
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            self.run_cli("collect", "--recorded-at", "2026-10-01T00:00:00Z")

    def test_no_backdated_freeze(self):
        self.clock = "2026-10-05T10:00:00Z"
        self.assertEqual(self.run_cli("freeze")[0], 2)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_selected_runtime_must_be_off_before_provider_read(self):
        with patch.object(cli, "_off", side_effect=ValueError("runtime not OFF")):
            result = self.run_cli("freeze")
        self.assertEqual(result[0], 2)
        self.assertEqual(self.calls, [])

    def test_source_and_credential_storage_not_valid_output_roots(self):
        for root in (self.credentials.parent / "journal", self.base / "missions" / "journal"):
            with self.subTest(root=root):
                self.assertEqual(self.run_cli("freeze", root=root)[0], 2)
                self.assertEqual(self.calls, [])

    def test_changed_journal_refused_before_network(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        entry = self.root / "entries" / "00000001.json"
        entry.chmod(0o600)
        entry.write_bytes(b"{}")
        self.assertEqual(self.run_cli("collect")[0], 2)
        self.assertEqual(len(self.calls), 1)

    def test_collection_queries_use_entire_frozen_calendar_and_only_completed_bars(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        self.clock = "2026-10-02T14:02:00Z"
        self.assertEqual(self.run_cli("collect")[0], 0)
        view = read_experiment_view(self.root)
        context = view["protocol"]["context_sessions"]
        self.assertEqual(self.calls[1], ("calendar", {"start": context[0]["date"], "end": context[-1]["date"]}))
        self.assertEqual(self.calls[2][1]["end"], "2026-10-02T03:59:59Z")
        self.assertEqual(self.calls[2][1]["symbols"], "QQQ,SPY")

    def test_provider_failure_is_sanitized_and_creates_no_journal(self):
        with patch.object(cli, "_credentials", side_effect=ExperimentCaptureError("HTTP_ERROR", 401)):
            code, out, err = self.run_cli("freeze")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["http_status"], 401)
        self.assertFalse(self.root.exists())

    def test_completed_pilot_with_pending_outcomes_can_collect_later(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        view = read_experiment_view(self.root)
        view["summary"].update(conclusion="INCONCLUSIVE_MISSING_EVIDENCE", pending_prediction_count=0, pending_outcome_count=1)
        self.clock = "2026-11-20T02:00:00Z"
        with patch("blackpod_build_week.shadow_experiment.read_experiment_view", return_value=view), patch("blackpod_build_week.shadow_experiment.collect_observation", return_value={}) as collect:
            self.assertEqual(self.run_cli("collect")[0], 0)
            collect.assert_called_once()
        self.assertEqual(len(self.calls), 3)

    def test_complete_pilot_without_pending_rows_stops_provider_reads(self):
        self.assertEqual(self.run_cli("freeze")[0], 0)
        view = read_experiment_view(self.root)
        view["summary"].update(conclusion="DESCRIPTIVE_POSITIVE_PROXY_ONLY", pending_prediction_count=0, pending_outcome_count=0)
        with patch("blackpod_build_week.shadow_experiment.read_experiment_view", return_value=view):
            self.assertEqual(self.run_cli("collect")[0], 0)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
