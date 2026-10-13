"""One-shot local text capture tested with real client validation and fake HTTP."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.brigade_shadow_transport import capture_modeldock, validate_transcript_bundle
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.decision_journal_store import JournalUnsafePathError
from blackpod_build_week.desk_candidate_review_cli import load_evidence, _references
from blackpod_build_week.forecast_journal import assess_brigade_shadow, build_forecast_intake_event
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import HttpResponse, ModelDockClient
from blackpod_build_week.modeldock_config import ModelDockConfig
from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture
from test_shadow_brigade_analysis import VALID_RESPONSE

NOW = datetime(2026, 10, 12, 20, 1, 1, tzinfo=timezone.utc)


class CaptureHTTP:
    """In-memory HTTP transport; exercising ModelDockClient's actual validator."""
    def __init__(self, directory, *, modifier=None, interrupt_after=None):
        self.directory, self.modifier, self.interrupt_after = directory, modifier, interrupt_after
        self.calls = []

    def request(self, **kwargs):
        if self.interrupt_after is not None and len(self.calls) == self.interrupt_after:
            raise KeyboardInterrupt("injected uncertain delivery interruption")
        wire = json.loads(kwargs["body"])
        # No provider request may occur before both durable reservations exist.
        assert (self.directory / "generation-intent.json").is_file()
        assert (self.directory / f"call-intent-{len(self.calls)+1:04d}.json").is_file()
        self.calls.append(kwargs)
        action = "EXIT" if wire["messages"][-1]["content"].startswith("Assess risk profile") else "BUY"
        text = VALID_RESPONSE.replace("ACTION: BUY", "ACTION: " + action)
        envelope = {"status": "ok", "request_type": "text.generate", "profile": wire["profile"], "provider": "mlx",
            "model": "fixture-active-model", "content": json.dumps({"brigade_text": text}),
            "data": {"engine": "mlx-lm", "profile": wire["profile"], "model_path": "/private/fixture/model/revision-abc"},
            "metadata": {"blackpod_correlation": wire["metadata"]["blackpod_correlation"], "structured_output": {"mode": "json_schema", "validated": True},
                "requested_max_tokens": wire["max_tokens"], "effective_max_tokens": wire["max_tokens"], "generated_token_count": 25,
                "generated_token_count_source": "native", "stop_reason": "stop", "stop_reason_source": "native",
                "generation_options": {"temperature": 0.0},
                "private_field": "must-not-be-retained"}, "trace_id": "fixture-trace", "mocked": False}
        if self.modifier is not None:
            result = self.modifier(envelope)
            if isinstance(result, Exception): raise result
            if isinstance(result, HttpResponse): return result
        raw = canonical_json_bytes(envelope)
        return HttpResponse(200, {"Content-Length": str(len(raw))}, raw)


class BrigadeShadowTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("actual network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("inference process forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.out = self.base / "capture"
        self.fx = ForecastBrigadeJournalFixture()
        self.config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=5, delivery_grace_seconds=0)

    def capture(self, *, transport=None, now=None, monotonic=None, recover=False, request=None, config=None, directory=None):
        directory = directory or self.out
        transport = transport or CaptureHTTP(directory)
        now = now or (lambda: NOW)
        client_factory = lambda selected: ModelDockClient(selected, transport=transport, now=now, monotonic=lambda: 0)
        result = capture_modeldock(request or self.fx.request, (self.fx.forecast_event,), self.fx.blobs, directory,
            config=config or self.config, client_factory=client_factory, now=now, monotonic=monotonic or (lambda: 0), recover=recover)
        return result, transport

    def retained(self):
        request = BrigadeShadowRequest.from_bytes((self.out / "request.replay.json").read_bytes())
        blobs = load_evidence(self.out / "evidence", _references(request.to_dict()))
        bundle = json.loads(blobs[request.transcript_evidence["sha256"]])
        analysis = assess_brigade_shadow(request, (self.fx.forecast_event,), blobs)
        return request, bundle, analysis

    def test_real_client_validates_five_fake_http_responses_and_preserves_dissent(self):
        result, transport = self.capture()
        self.assertEqual(len(transport.calls), 5)
        self.assertEqual(result["inference_calls"], 5)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertFalse(result["auto_trading_changed"])
        self.assertFalse(result["automatic_retry_allowed"])
        request, bundle, analysis = self.retained()
        self.assertEqual(bundle["capture_kind"], "MODELDOCK_CAPTURE")
        self.assertFalse(any(request.authority.values()))
        self.assertEqual({row["recommendation"] for row in analysis["symbols"][0]["dissent"]}, {"BUY", "EXIT"})
        self.assertEqual(analysis, json.loads((self.out / "analysis.json").read_bytes()))

    def test_durable_intent_and_each_call_reservation_precede_every_post(self):
        result, transport = self.capture()
        intent = json.loads((self.out / "generation-intent.json").read_bytes())
        self.assertEqual(intent["request_sha256"], sha256_bytes(self.fx.request.to_bytes()))
        self.assertEqual(len(intent["planned_requests"]), 5)
        self.assertFalse(intent["automatic_retry_allowed"])
        self.assertEqual(len(transport.calls), 5)
        for index in range(1, 6):
            self.assertTrue((self.out / f"call-intent-{index:04d}.json").is_file())
            self.assertTrue((self.out / f"receipt-{index:04d}.json").is_file())

    def test_wire_keeps_native_prompts_but_appliance_owns_model_and_temperature(self):
        _, transport = self.capture()
        _, bundle, _ = self.retained()
        for raw_call, transcript in zip(transport.calls, bundle["transcripts"]):
            wire = json.loads(raw_call["body"])
            native = transcript["request"]
            self.assertEqual(raw_call["method"], "POST")
            self.assertTrue(raw_call["url"].endswith("/text/generate"))
            self.assertNotIn("model", wire)
            self.assertNotIn("temperature", wire)
            self.assertNotIn("generation_options", wire)
            self.assertEqual(wire["messages"][1]["content"], native["prompt"])
            self.assertTrue(wire["messages"][0]["content"].endswith(native["system"]))
            self.assertIn("future target horizons is not observed price history", wire["messages"][0]["content"])
            self.assertEqual(wire["response_format"]["schema"]["required"], ["brigade_text"])
            self.assertEqual(wire["max_tokens"], 500)
            self.assertEqual(native["temperature"], "0.7")

    def test_capture_sanitizes_private_provider_paths_and_extra_metadata(self):
        self.capture()
        _, bundle, _ = self.retained()
        text = canonical_json_bytes(bundle).decode()
        self.assertNotIn("/private/fixture", text)
        self.assertNotIn("must-not-be-retained", text)
        self.assertNotIn("model_path", text)
        for record in bundle["transport_records"]:
            self.assertEqual(record["provider"], "mlx")
            self.assertEqual(record["model"], "fixture-active-model")
            self.assertEqual(record["safe_response"]["metadata"]["structured_output"], {"mode": "json_schema", "validated": True})

    def test_replay_uses_only_retained_sources_and_no_modeldock_client(self):
        self.capture()
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("replay inference forbidden")):
            request, bundle, analysis = self.retained()
            validate_transcript_bundle(bundle, request)
        self.assertEqual(len(analysis["response_transcripts"]), 5)

    def test_completed_attempt_is_reused_without_provider_calls(self):
        self.capture()
        before = {path.relative_to(self.out): path.read_bytes() for path in self.out.rglob("*.json")}
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("retry inference forbidden")):
            result, transport = self.capture()
        self.assertTrue(result["reused_capture"])
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(transport.calls, [])
        self.assertEqual(before, {path.relative_to(self.out): path.read_bytes() for path in self.out.rglob("*.json")})

    def test_malformed_content_stops_after_one_failed_call_and_defers_every_member(self):
        def bad(envelope): envelope["content"] = json.dumps({"action": "BUY"})
        transport = CaptureHTTP(self.out, modifier=bad)
        self.capture(transport=transport)
        _, bundle, analysis = self.retained()
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(bundle["transport_records"][0]["status"], "FAILED")
        self.assertTrue(all(item["recommendation"] is None for item in analysis["symbols"][0]["opinions"]))

    def test_valid_provider_json_with_missing_native_labels_does_not_invent_votes(self):
        def unstructured(envelope): envelope["content"] = json.dumps({"brigade_text": "Synthetic unstructured commentary only."})
        self.capture(transport=CaptureHTTP(self.out, modifier=unstructured))
        _, bundle, analysis = self.retained()
        self.assertTrue(all(record["status"] == "VALIDATED" for record in bundle["transport_records"]))
        self.assertTrue(all(item["recommendation"] is None for item in analysis["symbols"][0]["opinions"]))
        self.assertTrue(all("RESPONSE_LABELS_MISSING_OR_DUPLICATED" in item["reason_codes"] for item in analysis["symbols"][0]["member_coverage"]))

    def test_truncation_wrong_correlation_mocked_or_missing_structured_ack_are_deferred(self):
        changes = (
            lambda envelope: envelope["metadata"].update(stop_reason="length"),
            lambda envelope: envelope["metadata"]["blackpod_correlation"].update(symbol="OTHER"),
            lambda envelope: envelope.update(mocked=True),
            lambda envelope: envelope["metadata"].pop("structured_output"),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                directory = self.base / f"failure-{index}"
                transport = CaptureHTTP(directory, modifier=change)
                result, _ = self.capture(transport=transport, directory=directory)
                self.assertEqual(result["inference_calls"], 1)
                bundle = json.loads((directory / "evidence/brigade-shadow/transcript-bundle.json").read_bytes())
                self.assertEqual(bundle["transcripts"][0]["error_code"], "SHADOW_GENERATION_FAILED")
                self.assertIsNone(bundle["transcripts"][0]["response_text"])

    def test_http_failure_never_retries_and_does_not_publish_body_secrets(self):
        def bad(_envelope): return HttpResponse(500, {}, b"private-provider-body-must-not-appear")
        transport = CaptureHTTP(self.out, modifier=bad)
        self.capture(transport=transport)
        _, bundle, _ = self.retained()
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("private-provider-body", canonical_json_bytes(bundle).decode())

    def test_consumed_interrupted_attempt_requires_recover_and_does_not_retry(self):
        transport = CaptureHTTP(self.out, interrupt_after=2)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        self.assertEqual(len(transport.calls), 2)
        self.assertFalse((self.out / "request.replay.json").exists())
        with self.assertRaisesRegex(ValueError, "consumed or interrupted"):
            self.capture()
        self.assertEqual(len(transport.calls), 2)

    def test_two_receipt_recovery_never_calls_provider_and_defers_missing_members(self):
        transport = CaptureHTTP(self.out, interrupt_after=2)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("recovery provider forbidden")):
            result, recovered_transport = self.capture(recover=True)
        self.assertEqual(recovered_transport.calls, [])
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(result["durable_call_intent_count"], 3)
        self.assertEqual(result["retained_receipt_count"], 2)
        self.assertEqual(result["unconfirmed_call_count"], 1)
        _, bundle, analysis = self.retained()
        self.assertEqual(len(bundle["transport_records"]), 2)
        self.assertEqual([item["recommendation"] for item in analysis["symbols"][0]["opinions"]], ["BUY", "EXIT", None, None, None])
        self.assertTrue(all(record["error_code"] == "RETAINED_RESPONSE_MISSING" for record in analysis["response_transcripts"][2:]))

    def test_zero_receipt_recovery_seals_deferred_capture_without_provider(self):
        transport = CaptureHTTP(self.out, interrupt_after=0)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        result, _ = self.capture(recover=True)
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(result["durable_call_intent_count"], 1)
        self.assertEqual(result["retained_receipt_count"], 0)
        self.assertEqual(result["unconfirmed_call_count"], 1)
        _, bundle, analysis = self.retained()
        self.assertEqual(bundle["transport_records"], [])
        self.assertTrue(all(item["recommendation"] is None for item in analysis["symbols"][0]["opinions"]))

    def test_recover_without_consumed_attempt_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no consumed generation attempt"):
            self.capture(recover=True)

    def test_missing_current_forecast_defers_without_loading_config_or_creating_client(self):
        value = self.fx.f.intake.to_dict()
        value["sources"][0]["provenance_evidence"] = None
        intake = ForecastIntake.from_mapping(value)
        event = build_forecast_intake_event(intake, blobs=self.fx.blobs)
        request_value = self.fx.request.to_dict()
        request_value["forecast"].update(intake_event_id=event.event_id, intake_source_sha256=sha256_bytes(intake.to_bytes()),
            intake_evidence=self.fx.reference("brigade/forecast-intake.json", intake.to_bytes()))
        request = BrigadeShadowRequest.from_mapping(request_value)
        with patch("blackpod_build_week.modeldock_config.load_modeldock_config", side_effect=AssertionError("configuration lookup forbidden")):
            result = capture_modeldock(request, (event,), self.fx.blobs, self.out,
                client_factory=lambda _config: (_ for _ in ()).throw(AssertionError("client construction forbidden")), now=lambda: NOW)
        self.assertEqual(result["status"], "DEFER_NO_CURRENT_ELIGIBLE_MEMBERS")
        self.assertEqual(result["inference_calls"], 0)
        self.assertFalse((self.out / "generation-intent.json").exists())

    def test_changed_request_cannot_reuse_consumed_identity(self):
        transport = CaptureHTTP(self.out, interrupt_after=0)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        value = self.fx.request.to_dict()
        value["analysis_id"] = "another-attempt"
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.capture(request=BrigadeShadowRequest.from_mapping(value), recover=True)

    def test_future_or_stale_generation_clock_does_not_consume_attempt(self):
        for index, now in enumerate((NOW - timedelta(minutes=2), NOW + timedelta(minutes=6))):
            with self.subTest(now=now):
                directory = self.base / f"clock-{index}"
                with self.assertRaisesRegex(ValueError, "within five minutes"):
                    self.capture(directory=directory, now=lambda: now)
                self.assertFalse((directory / "generation-intent.json").exists())

    def test_per_call_delivery_budget_above_300_seconds_is_rejected(self):
        config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=301, delivery_grace_seconds=0)
        with self.assertRaisesRegex(ValueError, "300-second"):
            self.capture(config=config)
        self.assertFalse((self.out / "generation-intent.json").exists())

    def test_attempt_budget_stops_after_two_calls_and_does_not_retry(self):
        ticks = iter((0, 0, 100, 400))
        result, transport = self.capture(monotonic=lambda: next(ticks))
        self.assertEqual(len(transport.calls), 2)
        _, bundle, analysis = self.retained()
        self.assertEqual(len(bundle["transcripts"]), 2)
        self.assertTrue(all(opinion["recommendation"] is None for opinion in analysis["symbols"][0]["opinions"][2:]))

    def test_target_expiry_while_prior_members_run_prevents_another_post(self):
        times = iter((NOW, NOW, NOW, NOW, NOW + timedelta(days=1), NOW + timedelta(days=1), NOW + timedelta(days=1)))
        last = [NOW]
        def clock():
            last[0] = next(times, last[0])
            return last[0]
        result, transport = self.capture(now=clock)
        self.assertLess(len(transport.calls), 5)

    def test_valid_response_finishing_after_target_is_retained_but_cannot_vote(self):
        clock = [NOW]
        late = datetime(2026, 10, 13, 20, 0, 0, tzinfo=timezone.utc)
        def finish_late(_envelope): clock[0] = late
        transport = CaptureHTTP(self.out, modifier=finish_late)
        self.capture(transport=transport, now=lambda: clock[0])
        _, bundle, analysis = self.retained()
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(bundle["transport_records"][0]["status"], "VALIDATED_EXPIRED")
        self.assertIn("brigade_text", bundle["transport_records"][0]["safe_response"]["content"])
        self.assertEqual(bundle["transcripts"][0]["error_code"], "RESPONSE_EXPIRED_AFTER_GENERATION")
        self.assertIsNone(bundle["transcripts"][0]["response_text"])
        self.assertTrue(all(item["recommendation"] is None for item in analysis["symbols"][0]["opinions"]))

    def test_valid_response_finishing_after_feature_age_limit_cannot_vote(self):
        clock = [NOW]
        late = datetime(2026, 10, 13, 19, 59, 1, tzinfo=timezone.utc)
        def finish_late(_envelope): clock[0] = late
        transport = CaptureHTTP(self.out, modifier=finish_late)
        self.capture(transport=transport, now=lambda: clock[0])
        _, bundle, analysis = self.retained()
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(bundle["transport_records"][0]["status"], "VALIDATED_EXPIRED")
        self.assertEqual(bundle["transcripts"][0]["error_code"], "RESPONSE_EXPIRED_AFTER_GENERATION")
        self.assertIsNone(analysis["symbols"][0]["opinions"][0]["recommendation"])

    def test_rehashed_accepted_provider_response_cannot_change_native_transcript(self):
        self.capture()
        request, bundle, _ = self.retained()
        bundle["transport_records"][0]["safe_response"]["content"] = json.dumps({"brigade_text": VALID_RESPONSE.replace("BUY", "EXIT")})
        with self.assertRaisesRegex(ValueError, "native response transcript"):
            validate_transcript_bundle(bundle, request)

    def test_corrupt_or_missing_completed_analysis_cannot_be_reused(self):
        self.capture()
        path = self.out / "analysis.json"
        path.chmod(0o600)
        path.write_bytes(b"{}\n")
        with self.assertRaises(ValueError): self.capture()

    def test_missing_completed_replay_file_requires_receipt_recovery(self):
        self.capture()
        (self.out / "request.replay.json").unlink()
        with self.assertRaisesRegex(ValueError, "consumed or interrupted"):
            self.capture()

    def test_unknown_receipts_are_not_silently_ignored_during_recovery(self):
        transport = CaptureHTTP(self.out, interrupt_after=0)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        (self.out / "receipt-9999.json").write_bytes(b"{}\n")
        with self.assertRaises(ValueError): self.capture(recover=True)

    def test_missing_receipt_gap_is_not_treated_as_unattempted(self):
        transport = CaptureHTTP(self.out, interrupt_after=2)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        (self.out / "receipt-0001.json").unlink()
        with self.assertRaises(ValueError): self.capture(recover=True)

    def test_corrupt_receipt_binding_prevents_recovery(self):
        transport = CaptureHTTP(self.out, interrupt_after=2)
        with self.assertRaises(KeyboardInterrupt): self.capture(transport=transport)
        path = self.out / "receipt-0001.json"
        saved = json.loads(path.read_bytes())
        saved["transcript"]["request"]["prompt"] = "altered prompt"
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(saved))
        with self.assertRaises(ValueError): self.capture(recover=True)

    def test_each_final_publication_boundary_recovers_without_repeating_posts(self):
        from blackpod_build_week.brigade_shadow_transport import _write as original_write
        for filename in ("transcript-bundle.json", "request.replay.json", "analysis.json"):
            with self.subTest(filename=filename):
                directory = self.base / ("interrupted-" + filename.replace(".", "-"))
                transport = CaptureHTTP(directory)
                def interrupt(target, raw, sources):
                    if Path(target).name == filename: raise RuntimeError("injected publication interruption")
                    return original_write(target, raw, sources)
                with patch("blackpod_build_week.brigade_shadow_transport._write", side_effect=interrupt):
                    with self.assertRaises(RuntimeError): self.capture(transport=transport, directory=directory)
                self.assertEqual(len(transport.calls), 5)
                with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("recovery provider forbidden")):
                    recovered, provider = self.capture(directory=directory, recover=True, now=lambda: NOW + timedelta(minutes=10))
                self.assertEqual(provider.calls, [])
                self.assertTrue((directory / "analysis.json").is_file())
                replay = BrigadeShadowRequest.from_bytes((directory / "request.replay.json").read_bytes())
                self.assertEqual(replay.recorded_at, NOW.isoformat().replace("+00:00", "Z"))

    def test_uncertain_post_before_receipt_publication_recovers_as_missing_without_retry(self):
        from blackpod_build_week.desk_candidate_review_cli import _write as original_write
        transport = CaptureHTTP(self.out)
        def interrupt(target, raw, sources):
            if Path(target).name == "receipt-0001.json": raise RuntimeError("injected receipt interruption")
            return original_write(target, raw, sources)
        with patch("blackpod_build_week.desk_candidate_review_cli._write", side_effect=interrupt):
            with self.assertRaises(RuntimeError): self.capture(transport=transport)
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue((self.out / "call-intent-0001.json").is_file())
        self.assertFalse((self.out / "receipt-0001.json").exists())
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("uncertain call retry forbidden")):
            result, _ = self.capture(recover=True)
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(result["durable_call_intent_count"], 1)
        self.assertEqual(result["retained_receipt_count"], 0)
        self.assertEqual(result["unconfirmed_call_count"], 1)
        _, bundle, analysis = self.retained()
        self.assertEqual(bundle["transport_records"], [])
        self.assertTrue(all(opinion["recommendation"] is None for opinion in analysis["symbols"][0]["opinions"]))

    def test_more_than_forty_planned_member_requests_is_rejected_before_client(self):
        dry = assess_brigade_shadow(self.fx.request, (self.fx.forecast_event,), self.fx.blobs)
        dry["response_transcripts"] = (dry["response_transcripts"] * 9)[:41]
        with patch("blackpod_build_week.brigade_shadow_transport.assess_brigade_shadow", return_value=dry):
            with self.assertRaisesRegex(ValueError, "forty"):
                self.capture()
        self.assertFalse((self.out / "generation-intent.json").exists())

    def test_source_runtime_and_symlink_output_guards_run_before_provider(self):
        source = self.base / "source"
        source.mkdir(); (source / ".git").mkdir()
        runtime = self.base / "runtime"
        runtime.mkdir(); (runtime / "ledger.lock").write_bytes(b"")
        link = self.base / "capture-link"
        link.symlink_to(self.base / "elsewhere", target_is_directory=True)
        for directory in (source / "capture", runtime / "capture", link / "capture"):
            with self.subTest(directory=directory):
                with self.assertRaises((ValueError, JournalUnsafePathError)): self.capture(directory=directory)
                self.assertFalse((directory / "generation-intent.json").exists())

    def test_provider_free_bundle_validation_rejects_hostile_model_and_trace_tokens(self):
        self.capture()
        request, original, _ = self.retained()
        for field in ("model", "trace_id"):
            for hostile in ({"unexpected": "object"}, "sk-proj-abcdefghijklmnop", "bad\ncontrol"):
                with self.subTest(field=field, hostile=hostile):
                    bundle = copy.deepcopy(original)
                    bundle["transport_records"][0][field] = hostile
                    bundle["transport_records"][0]["safe_response"][field] = hostile
                    with self.assertRaisesRegex(ValueError, "unsafe model or trace"):
                        validate_transcript_bundle(bundle, request)

    def test_provider_free_bundle_validation_rejects_hostile_revision_tokens(self):
        self.capture()
        request, original, _ = self.retained()
        for hostile in ({"revision": "object"}, "sk-proj-abcdefghijklmnop", "bad\ncontrol"):
            with self.subTest(hostile=hostile):
                bundle = copy.deepcopy(original)
                bundle["transport_records"][0]["model_revision"] = hostile
                bundle["transport_records"][0]["safe_response"]["data"]["model_revision"] = hostile
                with self.assertRaisesRegex(ValueError, "unsafe model or trace"):
                    validate_transcript_bundle(bundle, request)

    def test_provider_free_bundle_validation_rejects_nontext_content(self):
        self.capture()
        request, bundle, _ = self.retained()
        bundle["transport_records"][0]["safe_response"]["content"] = {"brigade_text": VALID_RESPONSE}
        with self.assertRaisesRegex(ValueError, "bounded JSON text"):
            validate_transcript_bundle(bundle, request)

    def test_failed_capture_diagnostics_reject_unknown_keys_and_untyped_flags(self):
        def bad(_envelope): return HttpResponse(500, {}, b"synthetic HTTP failure")
        self.capture(transport=CaptureHTTP(self.out, modifier=bad))
        request, original, _ = self.retained()
        for mutation in (lambda failure: failure.update(unknown="unexpected"), lambda failure: failure.update(resumable=0)):
            bundle = copy.deepcopy(original)
            mutation(bundle["transport_records"][0]["failure"])
            with self.assertRaisesRegex(ValueError, "unsupported diagnostics"):
                validate_transcript_bundle(bundle, request)


if __name__ == "__main__": unittest.main()
