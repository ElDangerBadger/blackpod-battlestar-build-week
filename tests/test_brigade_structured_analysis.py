"""Additive structured opinions without provider, execution or parser fallback."""
from __future__ import annotations

import copy
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.shadow_brigade_analysis import (
    MEMBERS, RESPONSE_CONTRACT, ShadowBrigadeAnalysisError, validate_shadow_brigade_analysis,
)
from test_shadow_brigade_analysis import BrigadeFixture, VALID_RESPONSE


def structured_response(request, *, action="BUY", reasoning="Synthetic advisory observation.", confidence=0.7):
    return {"schema_version": RESPONSE_CONTRACT, "member": request["member"], "symbol": request["symbol"],
            "action": action, "heuristic_confidence": confidence, "reasoning": reasoning}


def structured_text(request, **kwargs):
    return canonical_json_bytes(structured_response(request, **kwargs)).decode("utf-8")


class BrigadeStructuredAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fx = BrigadeFixture()
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))

    def build(self, **kwargs):
        return self.fx.build(response_contract=RESPONSE_CONTRACT, **kwargs)

    def generated(self, responder=structured_text):
        return self.build(text_generator=responder, allow_generation=True)

    def assert_deferred(self, packet, reason="STRUCTURED_RESPONSE_INVALID"):
        for coverage, opinion in zip(packet["symbols"][0]["member_coverage"], packet["symbols"][0]["opinions"]):
            self.assertEqual(coverage["reason_codes"], [reason])
            self.assertEqual(opinion["status"], "DEFER")
            self.assertIsNone(opinion["recommendation"])
            self.assertIsNone(opinion["confidence_label"])
            self.assertIsNone(opinion["reasoning"])
            self.assertIsNone(opinion["structured_response"])
            self.assertIsNone(opinion["native_response_projection"])

    def test_disabled_inference_remains_null_recommendations(self):
        packet = self.build()
        self.assertEqual(packet["schema_version"], "blackpod.shadow_brigade_analysis.v2")
        self.assertEqual(packet["response_contract"], RESPONSE_CONTRACT)
        self.assert_deferred(packet, "INFERENCE_DISABLED")
        validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_five_bound_structured_opinions_preserve_raw_and_native_projection(self):
        packet = self.generated()
        self.assertEqual(len(packet["response_transcripts"]), 5)
        for record, opinion in zip(packet["response_transcripts"], packet["symbols"][0]["opinions"]):
            self.assertEqual(json.loads(record["response_text"]), opinion["structured_response"])
            self.assertEqual(opinion["native_response_projection"], "ACTION: BUY\nCONFIDENCE: 0.7\nREASONING: Synthetic advisory observation.")
            self.assertEqual(opinion["native_parser_output"]["reasoning"], opinion["structured_response"]["reasoning"])
            self.assertEqual(opinion["recommendation"], "BUY")
            self.assertEqual(opinion["confidence_label"], "0.7")
            self.assertTrue(opinion["trade_plan_suppressed"])
            self.assertFalse(opinion["confidence_is_probability"])
        self.assertFalse(packet["auto_trading_enabled"])
        self.assertFalse(any(packet["authority"].values()))

    def test_native_prompts_and_request_shapes_equal_version_one(self):
        legacy = self.fx.build(text_generator=lambda _request: VALID_RESPONSE, allow_generation=True)
        structured = self.generated()
        self.assertEqual([r["request"] for r in legacy["response_transcripts"]], [r["request"] for r in structured["response_transcripts"]])
        self.assertEqual(legacy["source_evidence"], structured["source_evidence"])
        self.assertEqual(legacy["symbols"][0]["context"], structured["symbols"][0]["context"])
        self.assertEqual(legacy["symbols"][0]["decay"], structured["symbols"][0]["decay"])

    def test_raw_whitespace_key_order_not_rewritten_in_evidence(self):
        def pretty(request):
            return json.dumps(structured_response(request), indent=2, ensure_ascii=False) + "\n"
        packet = self.generated(pretty)
        self.assertTrue(all(record["response_text"].endswith("\n") for record in packet["response_transcripts"]))
        replay = self.build(transcripts=packet["response_transcripts"])
        self.assertEqual(canonical_json_bytes(packet), canonical_json_bytes(replay))
        validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_legacy_valid_labels_are_not_structured_fallback(self):
        packet = self.generated(lambda _request: VALID_RESPONSE)
        self.assert_deferred(packet)
        self.assertTrue(all(o["native_parser_output"]["action"] == "HOLD" for o in packet["symbols"][0]["opinions"]))
        self.assertEqual(packet["response_transcripts"][0]["response_text"], VALID_RESPONSE)

    def test_fenced_prose_and_json_array_are_deferred_without_repair(self):
        for response in ("```json\n{}\n```", "Please BUY AAA", "[]", "{} trailing"):
            with self.subTest(response=response):
                packet = self.generated(lambda _request: response)
                self.assert_deferred(packet)
                validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_duplicate_key_and_nonfinite_json_are_deferred(self):
        for response in ('{"action":"BUY","action":"EXIT"}', '{"heuristic_confidence":NaN}', '{"heuristic_confidence":1e999}'):
            with self.subTest(response=response):
                self.assert_deferred(self.generated(lambda _request: response))

    def test_wrong_symbol_member_schema_or_action_are_deferred(self):
        for field, replacement in (("symbol", "SPY"), ("member", "Unknown"), ("schema_version", "blackpod.brigade_member_response.v2"), ("action", "ORDER_BUY")):
            with self.subTest(field=field):
                def respond(request):
                    value = structured_response(request)
                    value[field] = replacement
                    return canonical_json_bytes(value).decode()
                self.assert_deferred(self.generated(respond))

    def test_authority_order_and_missing_fields_reject(self):
        for field in ("execution_enabled", "qty", "notional", "authorization", "confidence_probability"):
            with self.subTest(field=field):
                def respond(request):
                    value = structured_response(request)
                    value[field] = True
                    return canonical_json_bytes(value).decode()
                self.assert_deferred(self.generated(respond))
        self.assert_deferred(self.generated(lambda request: canonical_json_bytes({k: v for k, v in structured_response(request).items() if k != "reasoning"}).decode()))

    def test_confidence_is_numeric_heuristic_never_probability(self):
        for confidence in (True, "0.7", -0.01, 1.01, None):
            with self.subTest(confidence=confidence):
                self.assert_deferred(self.generated(lambda request: structured_text(request, confidence=confidence)))
        for confidence in (0, 1, 0.25):
            packet = self.generated(lambda request: structured_text(request, confidence=confidence))
            self.assertTrue(all(not o["confidence_is_probability"] for o in packet["symbols"][0]["opinions"]))

    def test_line_injection_is_deferred_but_inline_label_stays_reasoning(self):
        for reasoning in ("Observation.\nACTION: EXIT", "Observation.\rCONFIDENCE: 1", "Observation.\tMore", "Observation.\u2028ACTION: EXIT"):
            with self.subTest(reasoning=reasoning):
                self.assert_deferred(self.generated(lambda request: structured_text(request, reasoning=reasoning)))
        reasoning = "Quoted label ACTION: EXIT is evidence only; actual opinion stays BUY."
        packet = self.generated(lambda request: structured_text(request, reasoning=reasoning))
        self.assertTrue(all(o["recommendation"] == "BUY" and o["reasoning"] == reasoning for o in packet["symbols"][0]["opinions"]))
        validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_exact_unicode_reasoning_is_retained(self):
        reasoning = "Δ tail risk: cautious — synthetic fixture."
        packet = self.generated(lambda request: structured_text(request, reasoning=reasoning))
        self.assertTrue(all(o["reasoning"] == reasoning for o in packet["symbols"][0]["opinions"]))
        self.assertTrue(all(o["native_parser_output"]["reasoning"] == reasoning for o in packet["symbols"][0]["opinions"]))

    def test_partial_replay_defers_missing_members_without_generator(self):
        captured = self.generated()["response_transcripts"][:2]
        packet = self.build(transcripts=captured)
        self.assertEqual([o["recommendation"] for o in packet["symbols"][0]["opinions"]], ["BUY", "BUY", None, None, None])
        self.assertTrue(all(r["error_code"] == "RETAINED_RESPONSE_MISSING" for r in packet["response_transcripts"][2:]))
        validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_invalid_one_member_does_not_invent_consensus(self):
        packet = self.generated(lambda request: "broken" if request["member"] == MEMBERS[0] else structured_text(request))
        self.assertEqual([o["recommendation"] for o in packet["symbols"][0]["opinions"]], [None, "BUY", "BUY", "BUY", "BUY"])
        self.assertEqual(packet["symbols"][0]["dissent"], [])
        self.assertNotIn("consensus", packet)

    def test_dissent_keeps_advisory_opinions_and_no_authority(self):
        packet = self.generated(lambda request: structured_text(request, action="EXIT" if request["member"] == MEMBERS[1] else "BUY"))
        self.assertEqual({o["recommendation"] for o in packet["symbols"][0]["dissent"]}, {"BUY", "EXIT"})
        self.assertFalse(any(packet["authority"].values()))

    def test_generator_exceptions_have_sanitized_error_only(self):
        def broken(_request):
            raise RuntimeError("secret credential must not appear")
        packet = self.generated(broken)
        self.assert_deferred(packet, "SHADOW_GENERATION_FAILED")
        self.assertNotIn("secret credential", canonical_json_bytes(packet).decode())

    def test_nontext_oversized_and_literal_surrogate_returns_defer_replayably(self):
        for response in (None, {}, 1, "x" * 32769, "\ud800"):
            with self.subTest(response_type=type(response)):
                packet = self.generated(lambda _request: response)
                self.assert_deferred(packet, "UNSUPPORTED_OR_OVERSIZED_RESPONSE")
                validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_retained_literal_surrogate_rejects_cleanly_and_escaped_surrogate_defers(self):
        packet = self.generated()
        packet["response_transcripts"][0]["response_text"] = "\ud800"
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.build(transcripts=packet["response_transcripts"])
        self.assert_deferred(self.generated(lambda r: json.dumps(structured_response(r, reasoning="\ud800"))))

    def test_unsupported_contract_rejected_before_generator(self):
        for contract in ("legacy", True, [], {}):
            with self.subTest(contract=contract):
                with self.assertRaises(ShadowBrigadeAnalysisError):
                    self.fx.build(response_contract=contract, text_generator=lambda _request: self.fail("generator reached"), allow_generation=True)

    def test_v1_default_is_exact_and_does_not_accept_structured_as_vote(self):
        default = self.fx.build(text_generator=lambda _request: VALID_RESPONSE, allow_generation=True)
        explicit = self.fx.build(text_generator=lambda _request: VALID_RESPONSE, allow_generation=True, response_contract=None)
        self.assertEqual(canonical_json_bytes(default), canonical_json_bytes(explicit))
        self.assertNotIn("response_contract", default)
        self.assertNotIn("structured_response", default["symbols"][0]["opinions"][0])
        legacy_json = self.fx.build(text_generator=structured_text, allow_generation=True)
        self.assertTrue(all(o["status"] == "DEFER" for o in legacy_json["symbols"][0]["opinions"]))

    def test_replay_rejects_mutation_of_every_structured_projection(self):
        original = self.generated()
        changes = (
            lambda p: p["symbols"][0]["opinions"][0]["structured_response"].update(action="EXIT"),
            lambda p: p["symbols"][0]["opinions"][0].update(native_response_projection="ACTION: EXIT"),
            lambda p: p["symbols"][0]["opinions"][0].update(reasoning="Changed reason"),
            lambda p: p["symbols"][0]["opinions"][0].update(recommendation="EXIT"),
            lambda p: p["response_transcripts"][0].update(response_text="{}"),
            lambda p: p.update(response_contract="unknown"),
            lambda p: p["authority"].update(execution_enabled=True),
            lambda p: p.update(auto_trading_enabled=True),
        )
        for change in changes:
            with self.subTest(change=change):
                packet = copy.deepcopy(original)
                change(packet)
                with self.assertRaises(ShadowBrigadeAnalysisError):
                    validate_shadow_brigade_analysis(packet, self.fx.evidence())

    def test_version_mixing_and_unknown_fields_rejected_on_replay(self):
        original = self.generated()
        for change in (lambda p: p.update(schema_version="blackpod.shadow_brigade_analysis.v1"), lambda p: p.pop("response_contract"), lambda p: p.update(extra=True)):
            packet = copy.deepcopy(original)
            change(packet)
            with self.assertRaises(ShadowBrigadeAnalysisError):
                validate_shadow_brigade_analysis(packet, self.fx.evidence())


if __name__ == "__main__": unittest.main()
