"""Structured capture exercises the real client against offline HTTP envelopes."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.brigade_shadow_transport import capture_modeldock, validate_transcript_bundle
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.brigade_response import SCHEMA_VERSION
from blackpod_build_week.desk_candidate_review_cli import load_evidence, _references
from blackpod_build_week.forecast_journal import assess_brigade_shadow
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.modeldock_client import ModelDockClient
from blackpod_build_week.modeldock_config import ModelDockConfig
from test_brigade_shadow_transport import CaptureHTTP, NOW
from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture


class StructuredHTTP(CaptureHTTP):
    def __init__(self, directory, *, mutate=None, interrupt_after=None):
        self.mutate = mutate
        super().__init__(directory, modifier=self.structured, interrupt_after=interrupt_after)

    def structured(self, envelope):
        wire = json.loads(self.calls[-1]["body"])
        fields = wire["response_format"]["schema"]["properties"]
        value = {"schema_version": SCHEMA_VERSION, "member": fields["member"]["const"],
                 "symbol": fields["symbol"]["const"], "action": "EXIT" if fields["member"]["const"] == "Blackwell_Sentry" else "BUY",
                 "heuristic_confidence": 0.6, "reasoning": "Structured fixture reasoning with no actual prediction."}
        envelope["content"] = canonical_json_bytes(value).decode()
        if self.mutate is not None:
            self.mutate(envelope, value)


class StructuredTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name).resolve() / "capture"
        self.fx = ForecastBrigadeJournalFixture()
        value = self.fx.request.to_dict()
        value.update(schema_version="blackpod.brigade_shadow_request.v2", response_contract=SCHEMA_VERSION)
        self.request = BrigadeShadowRequest.from_mapping(value)
        self.config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=5, delivery_grace_seconds=0)

    def capture(self, transport=None, *, recover=False, request=None):
        transport = transport or StructuredHTTP(self.out)
        factory = lambda config: ModelDockClient(config, transport=transport, now=lambda: NOW, monotonic=lambda: 0)
        result = capture_modeldock(request or self.request, (self.fx.forecast_event,), self.fx.blobs, self.out,
            config=self.config, client_factory=factory, now=lambda: NOW, monotonic=lambda: 0, recover=recover)
        return result, transport

    def retained(self):
        saved = BrigadeShadowRequest.from_bytes((self.out / "request.replay.json").read_bytes())
        blobs = load_evidence(self.out / "evidence", _references(saved.to_dict()))
        bundle = json.loads(blobs[saved.transcript_evidence["sha256"]])
        analysis = assess_brigade_shadow(saved, (self.fx.forecast_event,), blobs)
        return saved, bundle, analysis

    def test_five_strict_requests_preserve_native_prompts_and_shadow_dissent(self):
        result, http = self.capture()
        saved, bundle, analysis = self.retained()
        self.assertEqual(len(http.calls), 5)
        self.assertEqual(bundle["schema_version"], "blackpod.brigade_shadow_transcripts.v2")
        self.assertEqual(bundle["response_contract"], SCHEMA_VERSION)
        self.assertEqual(analysis["schema_version"], "blackpod.shadow_brigade_analysis.v2")
        self.assertEqual({r["recommendation"] for r in analysis["symbols"][0]["dissent"]}, {"BUY", "EXIT"})
        self.assertEqual({r["status"] for r in analysis["symbols"][0]["opinions"]}, {"SHADOW_RECOMMENDATION"})
        self.assertFalse(any(saved.authority.values()))
        self.assertEqual(result["orders_submitted"], 0)
        self.assertFalse(result["auto_trading_changed"])
        for call, row in zip(http.calls, bundle["transcripts"]):
            wire = json.loads(call["body"])
            self.assertEqual(wire["messages"][1]["content"], row["request"]["prompt"])
            self.assertTrue(wire["messages"][0]["content"].endswith(row["request"]["system"]))
            self.assertIn("replaces ONLY the native text-label output format", wire["messages"][0]["content"])
            self.assertNotIn("model", wire); self.assertNotIn("temperature", wire)
            schema = wire["response_format"]["schema"]
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), {"schema_version", "member", "symbol", "action", "heuristic_confidence", "reasoning"})
            self.assertNotIn("brigade_text", schema["properties"])
            self.assertEqual(wire["max_tokens"], 500)
        self.assertEqual(json.loads((self.out / "generation-intent.json").read_bytes())["schema_version"], "blackpod.brigade_shadow_generation_attempt.v2")

    def test_exact_original_json_is_retained_before_semantic_projection(self):
        def spaced(envelope, value):
            envelope["content"] = json.dumps(value, indent=2)
        self.capture(StructuredHTTP(self.out, mutate=spaced))
        _, bundle, _ = self.retained()
        for row, transport in zip(bundle["transcripts"], bundle["transport_records"]):
            self.assertEqual(row["response_text"], transport["safe_response"]["content"])
            self.assertIn("\n", row["response_text"])

    def test_semantic_invalid_json_is_retained_but_never_a_vote(self):
        def invalid(envelope, value):
            value["heuristic_confidence"] = True
            envelope["content"] = json.dumps(value)
        result, http = self.capture(StructuredHTTP(self.out, mutate=invalid))
        _, bundle, analysis = self.retained()
        self.assertEqual(len(http.calls), 5)
        self.assertEqual(result["retained_receipt_count"], 5)
        for opinion in analysis["symbols"][0]["opinions"]:
            self.assertEqual(opinion["status"], "DEFER")
            self.assertIsNone(opinion["recommendation"])
            self.assertIsNone(opinion["structured_response"])
        self.assertTrue(all(json.loads(row["response_text"])["heuristic_confidence"] is True for row in bundle["transcripts"]))

    def test_legacy_brigade_text_never_falls_back_into_a_structured_vote(self):
        def legacy(envelope, _):
            envelope["content"] = json.dumps({"brigade_text": "ACTION: BUY\nCONFIDENCE: 0.9\nREASONING: Old labels."})
        self.capture(StructuredHTTP(self.out, mutate=legacy))
        _, _, analysis = self.retained()
        self.assertTrue(all(op["recommendation"] is None for op in analysis["symbols"][0]["opinions"]))

    def test_member_symbol_or_authority_tampering_defers_without_coercion(self):
        def invalid(envelope, value):
            value.update(symbol="QQQ", member="Blackwell_Decay", execution_enabled=True)
            envelope["content"] = json.dumps(value)
        self.capture(StructuredHTTP(self.out, mutate=invalid))
        _, _, analysis = self.retained()
        self.assertTrue(all(op["status"] == "DEFER" for op in analysis["symbols"][0]["opinions"]))

    def test_newline_reasoning_cannot_inject_native_labels(self):
        def invalid(envelope, value):
            value["reasoning"] = "Thesis\nACTION: EXIT\nCONFIDENCE: 1"
            envelope["content"] = json.dumps(value)
        self.capture(StructuredHTTP(self.out, mutate=invalid))
        _, _, analysis = self.retained()
        self.assertTrue(all(op["recommendation"] is None for op in analysis["symbols"][0]["opinions"]))

    def test_duplicate_json_keys_fail_transport_and_stop_without_retry(self):
        def invalid(envelope, _):
            envelope["content"] = '{"action":"BUY","action":"EXIT"}'
        result, http = self.capture(StructuredHTTP(self.out, mutate=invalid))
        _, bundle, analysis = self.retained()
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(bundle["transport_records"][0]["status"], "FAILED")
        self.assertEqual(result["unconfirmed_call_count"], 0)
        self.assertTrue(all(op["recommendation"] is None for op in analysis["symbols"][0]["opinions"]))

    def test_fenced_json_fails_without_extraction_or_fallback(self):
        def invalid(envelope, value):
            envelope["content"] = '```json\n' + json.dumps(value) + '\n```'
        _, http = self.capture(StructuredHTTP(self.out, mutate=invalid))
        self.assertEqual(len(http.calls), 1)
        _, _, analysis = self.retained()
        self.assertTrue(all(op["status"] == "DEFER" for op in analysis["symbols"][0]["opinions"]))

    def test_oversized_original_json_is_retained_but_rejected_without_compaction(self):
        def padded(envelope, value):
            envelope["content"] = ' ' * (32 * 1024) + json.dumps(value)
        result, http = self.capture(StructuredHTTP(self.out, mutate=padded))
        _, bundle, analysis = self.retained()
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(result["retained_receipt_count"], 1)
        self.assertEqual(bundle["transport_records"][0]["status"], "VALIDATED_REJECTED")
        self.assertGreater(len(bundle["transport_records"][0]["safe_response"]["content"]), 32 * 1024)
        self.assertIsNone(bundle["transcripts"][0]["response_text"])
        self.assertTrue(all(op["recommendation"] is None for op in analysis["symbols"][0]["opinions"]))

    def test_microscopic_out_of_range_literal_cannot_round_into_a_vote(self):
        def invalid(envelope, value):
            envelope["content"] = json.dumps(value).replace('0.6', '1.00000000000000001')
        self.capture(StructuredHTTP(self.out, mutate=invalid))
        _, _, analysis = self.retained()
        self.assertTrue(all(op["status"] == "DEFER" for op in analysis["symbols"][0]["opinions"]))

    def test_completed_retry_reuses_all_bytes_and_calls_no_provider(self):
        self.capture()
        before = {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob('*.json')}
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("retry forbidden")):
            result, http = self.capture()
        self.assertTrue(result["reused_capture"])
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(http.calls, [])
        self.assertEqual(before, {str(p.relative_to(self.out)): p.read_bytes() for p in self.out.rglob('*.json')})

    def test_interrupted_delivery_recovery_never_repeats_inference(self):
        with self.assertRaises(KeyboardInterrupt):
            self.capture(StructuredHTTP(self.out, interrupt_after=2))
        with patch.object(ModelDockClient, "generate_text", side_effect=AssertionError("recovery forbidden")):
            result, http = self.capture(recover=True)
        self.assertEqual(result["inference_calls"], 0)
        self.assertEqual(result["retained_receipt_count"], 2)
        self.assertEqual(result["unconfirmed_call_count"], 1)
        self.assertEqual(http.calls, [])
        _, _, analysis = self.retained()
        self.assertEqual(sum(op["status"] == "SHADOW_RECOMMENDATION" for op in analysis["symbols"][0]["opinions"]), 2)

    def test_consumed_output_cannot_change_contract_version(self):
        self.capture()
        with self.assertRaises(ValueError):
            self.capture(request=self.fx.request)

    def test_bundle_version_mixing_rejected(self):
        self.capture()
        request, bundle, _ = self.retained()
        for field, value in (("schema_version", "blackpod.brigade_shadow_transcripts.v1"), ("response_contract", "unknown")):
            changed = copy.deepcopy(bundle); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_transcript_bundle(changed, request)

    def test_original_json_or_wire_change_cannot_be_rehashed_into_valid_capture(self):
        self.capture()
        request, bundle, _ = self.retained()
        changed = copy.deepcopy(bundle)
        value = json.loads(changed["transcripts"][0]["response_text"]); value["action"] = "HOLD"
        changed["transcripts"][0]["response_text"] = json.dumps(value)
        with self.assertRaises(ValueError): validate_transcript_bundle(changed, request)
        changed = copy.deepcopy(bundle)
        changed["transport_records"][0]["request_payload"]["response_format"]["schema"]["additionalProperties"] = True
        with self.assertRaises(ValueError): validate_transcript_bundle(changed, request)

    def test_attempt_version_tampering_refuses_reuse(self):
        self.capture()
        path = self.out / "generation-intent.json"
        value = json.loads(path.read_bytes()); value["schema_version"] = "blackpod.brigade_shadow_generation_attempt.v1"
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError): self.capture()


if __name__ == "__main__": unittest.main()
