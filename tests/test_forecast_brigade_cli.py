"""Explicit source-bound CLI workflows and output guards, without providers."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import brigade_shadow_cli, forecast_intake_cli
from blackpod_build_week.brigade_shadow_transport import make_transcript_bundle
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.forecast_intake import evidence_for_forecast_intake
from blackpod_build_week.forecast_journal import build_brigade_shadow_event, build_forecast_intake_event
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_brigade_analysis import evidence_for_shadow_brigade_analysis
from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture
from test_shadow_brigade_analysis import VALID_RESPONSE


class ForecastBrigadeCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("inference process forbidden")))
        self.enterContext(patch("blackpod_build_week.modeldock_client.ModelDockClient.generate_text", side_effect=AssertionError("implicit inference forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.journal, self.evidence = self.base / "journal", self.base / "evidence"
        self.fx = ForecastBrigadeJournalFixture()
        self.intake_path, self.request_path = self.base / "intake.json", self.base / "request.json"
        self.intake_path.write_bytes(self.fx.f.intake.to_bytes())
        self.request_path.write_bytes(self.fx.request.to_bytes())
        closure = evidence_for_shadow_brigade_analysis(self.fx.f.intake, self.fx.f.raw, self.fx.f.brigade, self.fx.f.decay, self.fx.blobs)
        for name, raw in closure.items():
            path = self.evidence / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def invoke(self, module, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main([str(arg) for arg in args])
        return code, json.loads(out.getvalue()) if code == 0 else None, err.getvalue()

    def forecast(self, command, *, journal=None, evidence=True):
        args = [command, "--journal-root", journal or self.journal, "--intake", self.intake_path]
        if evidence: args += ["--evidence-root", self.evidence]
        return self.invoke(forecast_intake_cli, *args)

    def brigade(self, command, *, evidence=True, request=None, extras=()):
        args = [command, "--journal-root", self.journal, "--request", request or self.request_path]
        if evidence: args += ["--evidence-root", self.evidence]
        return self.invoke(brigade_shadow_cli, *args, *extras)

    def seed(self):
        code, output, error = self.forecast("record")
        self.assertEqual(code, 0, error)
        return output

    def retained_request(self, response=VALID_RESPONSE, *, partial=False):
        packet = self.fx.f.build(text_generator=lambda _request: response, allow_generation=True)
        records = packet["response_transcripts"][:2] if partial else packet["response_transcripts"]
        bundle = make_transcript_bundle(self.fx.request, records)
        raw = canonical_json_bytes(bundle)
        relative = "brigade/declared-replay.json"
        path = self.evidence / relative
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        value = self.fx.request.to_dict()
        value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence={"path": relative, "sha256": sha256_bytes(raw), "size_bytes": len(raw)})
        request = BrigadeShadowRequest.from_mapping(value)
        self.request_path.write_bytes(request.to_bytes())
        return request

    def test_forecast_assess_is_readonly_offline_and_source_bound(self):
        code, output, error = self.forecast("assess")
        self.assertEqual(code, 0, error)
        self.assertEqual(output["result"]["admitted_count"], 5)
        self.assertFalse(output["result"]["auto_trading_enabled"])
        self.assertEqual(output["inference_calls"], 0)
        self.assertEqual(output["orders_submitted"], 0)
        self.assertFalse(self.journal.exists())

    def test_forecast_record_retry_show_and_retained_only_retry(self):
        first = self.seed()
        original = JournalStore(self.journal).verify().to_dict()
        code, retry, error = self.forecast("record")
        self.assertEqual(code, 0, error); self.assertFalse(retry["written"])
        self.assertEqual(retry["event_id"], first["event_id"])
        code, shown, error = self.invoke(forecast_intake_cli, "show", "--journal-root", self.journal, "--event-id", first["event_id"])
        self.assertEqual(code, 0, error)
        self.assertEqual(shown["payload"]["intake"], self.fx.f.intake.to_dict())
        shutil.rmtree(self.evidence)
        code, retained, error = self.forecast("record", evidence=False)
        self.assertEqual(code, 0, error); self.assertFalse(retained["written"])
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), original)

    def test_brigade_assess_is_readonly_and_has_no_native_executable_plan(self):
        self.seed()
        original = JournalStore(self.journal).verify().to_dict()
        code, output, error = self.brigade("assess")
        self.assertEqual(code, 0, error)
        packet = output["analysis"]
        self.assertEqual(packet["response_capture_status"], "INFERENCE_DISABLED")
        self.assertFalse(any(packet["authority"].values()))
        self.assertTrue(all(opinion["recommendation"] is None for opinion in packet["symbols"][0]["opinions"]))
        self.assertEqual(output["orders_submitted"], 0)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), original)

    def test_brigade_record_show_render_and_retained_only_retry(self):
        self.seed()
        code, output, error = self.brigade("record")
        self.assertEqual(code, 0, error)
        self.assertTrue(output["written"])
        code, shown, error = self.invoke(brigade_shadow_cli, "show", "--journal-root", self.journal, "--event-id", output["event_id"])
        self.assertEqual(code, 0, error)
        self.assertEqual(shown["source"]["kind"], "BRIGADE_SHADOW_ANALYSIS")
        report = self.base / "reports" / "report.html"
        code, rendered, error = self.invoke(brigade_shadow_cli, "render", "--journal-root", self.journal, "--event-id", output["event_id"], "--output", report)
        self.assertEqual(code, 0, error)
        self.assertEqual(rendered["sha256"], sha256_bytes(report.read_bytes()))
        self.assertIn("AUTOMATION AUTHORITY OFF", report.read_text())
        self.assertIn("admitted at the frozen intake clock", report.read_text())
        original = JournalStore(self.journal).verify().to_dict()
        shutil.rmtree(self.evidence)
        code, retry, error = self.brigade("record", evidence=False)
        self.assertEqual(code, 0, error); self.assertFalse(retry["written"])
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), original)

    def test_declared_response_replay_is_offline_and_partial_capture_remains_deferred(self):
        self.seed()
        self.retained_request(partial=True)
        code, output, error = self.brigade("record")
        self.assertEqual(code, 0, error)
        opinions = output["analysis"]["symbols"][0]["opinions"]
        self.assertEqual([opinion["recommendation"] for opinion in opinions], ["BUY", "BUY", None, None, None])
        self.assertFalse(output["auto_trading_changed"])

    def test_render_escapes_untrusted_agent_reasoning_and_has_no_actions(self):
        self.seed()
        self.retained_request(VALID_RESPONSE.replace("Synthetic governed fixture opinion; not live trading advice.", "<script>alert('x')</script> & fixture text"))
        code, output, error = self.brigade("record")
        self.assertEqual(code, 0, error)
        event = JournalStore(self.journal).events()[-1]
        html = brigade_shadow_cli.render_brigade_review(event)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<button", html)
        self.assertNotIn("<form", html)

    def test_render_preserves_historical_missing_units_and_horizon_as_unverified(self):
        raw = b"Date,Symbol,Q10,Q50,Q90,Pattern,Timeframe,Horizon\n2026-06-10,AAA,98,100,104,LIVE,1D,1D\n"
        value = self.fx.f.intake.to_dict()
        value["sources"][0].update(evidence=self.fx.reference("forecast/historical-AAA.csv", raw), provenance_evidence=None)
        intake = ForecastIntake.from_mapping(value)
        source_event = build_forecast_intake_event(intake, blobs=self.fx.blobs)
        request_value = self.fx.request.to_dict()
        request_value["forecast"].update(intake_event_id=source_event.event_id, intake_source_sha256=sha256_bytes(intake.to_bytes()),
            intake_evidence=self.fx.reference("brigade/forecast-intake.json", intake.to_bytes()))
        request = BrigadeShadowRequest.from_mapping(request_value)
        event = build_brigade_shadow_event(request, (source_event,), self.fx.blobs)
        row = event.payload["analysis"]["forecast_result"]["rows"][0]
        self.assertIsNone(row["units"])
        self.assertIsNone(row["horizon_unit"])
        html = brigade_shadow_cli.render_brigade_review(event)
        self.assertIn("2026-06-10", html)
        self.assertIn("DATE_ONLY", html)
        body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        self.assertIn("Units unverified", body)
        self.assertIn("unit unverified", body)
        self.assertNotIn("PRICE_USD", body)
        self.assertNotIn("1 sessions", body)
        self.assertNotIn("1D USD", body)

    def test_missing_predecessor_or_unknown_event_is_reported_as_cli_failure(self):
        code, _, error = self.brigade("record")
        self.assertEqual(code, 2)
        self.assertIn("preceding verified forecast", error)
        self.seed()
        for module in (forecast_intake_cli, brigade_shadow_cli):
            code, _, error = self.invoke(module, "show", "--journal-root", self.journal, "--event-id", "journal-event-" + "0" * 64)
            self.assertEqual(code, 2)
            self.assertIn("unknown verified", error)

    def test_changed_or_symlinked_bound_source_is_rejected(self):
        source = self.evidence / "brigade/decay.py"
        source.write_bytes(source.read_bytes() + b"\n# changed")
        self.seed()
        code, _, error = self.brigade("record")
        self.assertEqual(code, 2)
        self.assertIn("hash or size", error)
        source.unlink()
        outside = self.base / "outside-source.py"
        outside.write_bytes(self.fx.f.decay)
        source.symlink_to(outside)
        code, _, error = self.brigade("record")
        self.assertEqual(code, 2)

    def test_nested_journal_evidence_root_is_rejected_before_source_read(self):
        self.seed()
        code, _, error = self.invoke(brigade_shadow_cli, "assess", "--journal-root", self.journal,
            "--request", self.request_path, "--evidence-root", self.journal / "evidence")
        self.assertEqual(code, 2)
        self.assertIn("separate", error)

    def test_generate_requires_explicit_modeldock_shadow_flag(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                brigade_shadow_cli.main(["generate", "--journal-root", str(self.journal), "--request", str(self.request_path),
                    "--output-directory", str(self.base / "capture")])
        self.assertEqual(caught.exception.code, 2)

    def test_generate_explicit_flag_passes_only_shadow_capture_and_process_local_config(self):
        self.seed()
        result = {"orders_submitted": 0, "auto_trading_changed": False, "inference_calls": 0}
        with patch("blackpod_build_week.brigade_shadow_transport.capture_modeldock", return_value=result) as captured:
            code, output, error = self.brigade("generate", extras=("--output-directory", self.base / "capture", "--modeldock-shadow",
                "--modeldock-base-url", "http://127.0.0.1:8765", "--modeldock-timeout-seconds", "5", "--modeldock-delivery-grace-seconds", "0"))
        self.assertEqual(code, 0, error)
        self.assertEqual(captured.call_args.args[0].mode, "SHADOW")
        self.assertEqual(captured.call_args.kwargs["config"].base_url, "http://127.0.0.1:8765")
        self.assertFalse(captured.call_args.kwargs["recover"])
        self.assertFalse(output["auto_trading_changed"])

    def test_generate_cannot_write_inside_journal_or_evidence_root(self):
        self.seed()
        for target in (self.journal / "capture", self.evidence / "capture"):
            with self.subTest(target=target):
                code, _, error = self.brigade("generate", extras=("--output-directory", target, "--modeldock-shadow"))
                self.assertEqual(code, 2)
                self.assertIn("separate", error)
                self.assertFalse(target.exists())

    def test_render_cannot_write_inside_journal_runtime_or_source_storage(self):
        self.seed()
        code, output, error = self.brigade("record")
        self.assertEqual(code, 0, error)
        runtime = self.base / "installed-runtime"
        runtime.mkdir(); (runtime / "ledger.lock").write_bytes(b"")
        source = self.base / "source-checkout"
        source.mkdir(); (source / ".git").mkdir()
        for target in (self.journal / "report.html", runtime / "report.html", source / "report.html"):
            with self.subTest(target=target):
                code, _, error = self.invoke(brigade_shadow_cli, "render", "--journal-root", self.journal, "--event-id", output["event_id"], "--output", target)
                self.assertEqual(code, 2, error)
                self.assertFalse(target.exists())

    def test_recover_is_explicit_receipt_replay_without_provider_activation(self):
        self.seed()
        with patch("blackpod_build_week.brigade_shadow_transport.capture_modeldock", return_value={"inference_calls": 0}) as captured:
            code, _, error = self.brigade("recover", extras=("--output-directory", self.base / "capture"))
        self.assertEqual(code, 0, error)
        self.assertTrue(captured.call_args.kwargs["recover"])
        self.assertEqual(captured.call_args.args[0].inference_mode, "DISABLED")


if __name__ == "__main__": unittest.main()
