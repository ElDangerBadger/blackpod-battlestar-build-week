"""Five pinned native Brigade members and separate Decay, entirely offline."""
from __future__ import annotations

import copy
import math
import socket
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.forecast_intake import assess_forecast_intake
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_brigade_analysis import (
    BRIGADE_SOURCE_SHA256, DECAY_SOURCE_SHA256, MEMBERS, ShadowBrigadeAnalysisError,
    build_shadow_brigade_analysis, evidence_for_shadow_brigade_analysis, validate_shadow_brigade_analysis,
)

ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-10-12T20:00:00Z"
GENERATED_AT = "2026-10-12T20:01:00Z"
FEATURE_CUTOFF = "2026-10-12T19:59:00Z"
TRAINING_CUTOFF = "2026-10-12T19:58:00Z"
ISSUED_AT = "2026-10-12T19:59:30Z"
VALID_RESPONSE = "ACTION: BUY\nCONFIDENCE: 0.70\nREASONING: Synthetic governed fixture opinion; not live trading advice."
AUTHORITY = {"authorization_enabled": False, "capital_activation_enabled": False,
             "execution_enabled": False, "policy_changes_enabled": False}


class BrigadeFixture:
    """Self-contained synthetic evidence; no sibling applications are needed."""
    def __init__(self, *, horizons=5, provenance=True, history=90, close_fn=None):
        self.brigade = (ROOT / "fixtures/shadow_galactica_analysis/blackwell_brigade.py").read_bytes()
        self.decay = (ROOT / "fixtures/shadow_brigade_analysis/decay.py").read_bytes()
        self.blobs = {}
        def keep(path, value):
            raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
            digest = sha256_bytes(raw)
            self.blobs[digest] = raw
            return {"path": path, "sha256": digest, "size_bytes": len(raw)}
        self.keep = keep
        source = ("Date,Symbol,Q10,Q50,Q90,Pattern,Timeframe,Horizon\n" + "".join(
            f"2026-10-12,AAA,{100+i},{102+i},{107+i},LIVE,1D,{i+1}D\n" for i in range(horizons))).encode()
        raw_ref = keep("forecast/AAA.csv", source)
        future_session_days = (13, 14, 15, 16, 19)
        calendar = {"schema_version": "blackpod.forecast_session_calendar.v1", "symbol": "AAA",
                    "anchor_at": FEATURE_CUTOFF, "captured_at": FEATURE_CUTOFF,
                    "sessions": [{"opens_at": f"2026-10-{future_session_days[i]:02d}T13:30:00Z", "closes_at": f"2026-10-{future_session_days[i]:02d}T20:00:00Z"} for i in range(horizons)]}
        calendar_ref = keep("forecast/calendar.json", calendar)
        feature_ref = keep("forecast/features.json", {"schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "FEATURES", "symbol": "AAA",
                          "observations": [{"observed_at": FEATURE_CUTOFF, "values": {"close": "100"}}]})
        training_ref = keep("forecast/training.json", {"schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "TRAINING", "symbol": "AAA",
                           "observations": [{"observed_at": "2026-10-09T20:00:00Z", "target_observed_at": TRAINING_CUTOFF,
                                             "values": {"close": "100", "future_close": "102"}}]})
        config_ref = keep("forecast/config.json", {"schema_version": "blackpod.forecast_model_config.v1", "model_kind": "EXTERNAL_QUANTILE",
                          "quantile_levels": ["0.10", "0.50", "0.90"], "target": "FUTURE_CLOSE", "currency": "USD", "feature_names": ["close"]})
        model_ref = keep("forecast/model.json", {"fixture": "retained synthetic model artifact, never loaded"})
        producer_ref = keep("forecast/producer.txt", b"SYNTHETIC FIXTURE: source identity is a retained declaration, not attestation.\n")
        manifest = {"schema_version": "blackpod.forecast_provenance.v1", "source_sha256": raw_ref["sha256"],
                    "status": "REVIEWED_SOURCE_BOUND", "reviewed_by": "fixture-reviewer", "reviewed_at": AS_OF,
                    "model": {"model_id": "fixture-quantile", "model_version": "fixture-v1", "model_kind": "EXTERNAL_QUANTILE",
                              "producer_evidence": producer_ref, "model_artifact_evidence": model_ref, "config_evidence": config_ref,
                              "feature_evidence": feature_ref, "training_evidence": training_ref, "calibration_evidence": None},
                    "rows": [{"source_row_number": i + 1, "symbol": "AAA", "issued_at": ISSUED_AT,
                              "feature_cutoff": FEATURE_CUTOFF, "training_cutoff": TRAINING_CUTOFF,
                              "horizon_count": i + 1, "horizon_unit": "TRADING_SESSION", "target_at": f"2026-10-{future_session_days[i]:02d}T20:00:00Z",
                              "target_session_evidence": calendar_ref, "units": "PRICE_USD", "value_semantics": "PREDICTED_CLOSE_LEVEL",
                              "reference_price": "100", "reference_at": FEATURE_CUTOFF} for i in range(horizons)]}
        manifest_ref = keep("forecast/provenance.json", manifest) if provenance else None
        self.intake_mapping = {"schema_version": "blackpod.forecast_intake.v1", "intake_id": "synthetic-brigade-intake",
                               "recorded_at": AS_OF, "shadow_as_of": AS_OF, "domain": "TRADING", "mode": "SHADOW",
                               "scope": "SHADOW_FORECAST_INTAKE_ONLY", "policy": {"interface_version": "DAILY_USD_PRICE_V1",
                               "max_forecast_age_seconds": 86400, "max_feature_age_seconds": 86400, "max_training_age_seconds": 86400,
                               "allowed_horizon_sessions": [1, 2, 3, 4, 5]},
                               "sources": [{"source_id": "fixture-AAA", "evidence": raw_ref, "format": "GALACTICA_PHASE2_CSV", "provenance_evidence": manifest_ref}],
                               "authority": dict(AUTHORITY)}
        self.intake = ForecastIntake.from_mapping(self.intake_mapping)
        start = datetime(2026, 10, 12, tzinfo=timezone.utc) - timedelta(days=history)
        bars = []
        for i in range(history):
            price = close_fn(i) if close_fn is not None else 100 + i * 0.03 + math.sin(i / 3)
            bars.append({"t": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"),
                         "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 10000 + i * 10})
        snapshots = {symbol: {"latestQuote": {"bp": 100, "ap": 100.05, "t": AS_OF}} for symbol in ("AAA", "SPY")}
        bar_map = {"AAA": bars, "SPY": copy.deepcopy(bars)}
        snapshot_ref = keep("market/snapshots.json", snapshots)
        bars_ref = keep("market/bars.json", {"bars": bar_map, "next_page_token": None})
        self.market = {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": AS_OF, "feed": "IEX", "adjustment": "RAW",
                       "snapshots": snapshots, "bars": bar_map, "source_evidence": [snapshot_ref, bars_ref]}
        self.raw = canonical_json_bytes(self.market)

    def build(self, **kwargs):
        return build_shadow_brigade_analysis(self.intake, self.raw, self.brigade, self.decay, generated_at=kwargs.pop("generated_at", GENERATED_AT),
                                             blobs=self.blobs, **kwargs)

    def evidence(self):
        retained = evidence_for_shadow_brigade_analysis(self.intake, self.raw, self.brigade, self.decay, self.blobs)
        return {sha256_bytes(raw): raw for raw in retained.values()}


class ShadowBrigadeAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.fixture = BrigadeFixture()

    def generated(self, response=VALID_RESPONSE, **kwargs):
        return self.fixture.build(text_generator=lambda _request: response, allow_generation=True, **kwargs)

    def test_fixtures_are_exact_reviewed_native_source_snapshots(self):
        self.assertEqual(sha256_bytes(self.fixture.brigade), BRIGADE_SOURCE_SHA256)
        self.assertEqual(sha256_bytes(self.fixture.decay), DECAY_SOURCE_SHA256)

    def test_fixture_is_admitted_but_not_an_authorization(self):
        result = assess_forecast_intake(self.fixture.intake, self.fixture.blobs)
        self.assertEqual(result["admitted_count"], 5)
        self.assertFalse(any(result["authority"].values()))

    def test_default_does_not_generate_or_invent_a_member_vote(self):
        packet = self.fixture.build()
        self.assertEqual(packet["response_capture_status"], "INFERENCE_DISABLED")
        self.assertEqual(len(packet["response_transcripts"]), 5)
        for coverage, opinion in zip(packet["symbols"][0]["member_coverage"], packet["symbols"][0]["opinions"]):
            self.assertEqual(coverage["reason_codes"], ["INFERENCE_DISABLED"])
            self.assertEqual(opinion["status"], "DEFER")
            self.assertIsNone(opinion["recommendation"])
            self.assertEqual(opinion["native_parser_output"]["action"], "HOLD")
            self.assertEqual(opinion["native_parser_output"]["confidence_label"], "0.55")

    def test_missing_governed_forecasts_prevents_generator_invocation(self):
        fixture = BrigadeFixture(provenance=False)
        def forbidden(_request):
            raise AssertionError("generator must not be reached")
        packet = fixture.build(text_generator=forbidden, allow_generation=True)
        self.assertEqual(packet["response_transcripts"], [])
        self.assertEqual(packet["symbols"][0]["opinions"], [])
        self.assertTrue(all("NO_CURRENT_GOVERNED_FORECAST" in row["reason_codes"] for row in packet["symbols"][0]["member_coverage"]))

    def test_generator_is_explicit_opt_in(self):
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.fixture.build(text_generator=lambda _request: VALID_RESPONSE)
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.fixture.build(allow_generation=True)

    def test_actual_five_native_member_calls_and_plan_suppression(self):
        requests = []
        def generate(request):
            requests.append(request)
            return VALID_RESPONSE
        packet = self.fixture.build(text_generator=generate, allow_generation=True)
        self.assertEqual([request["member"] for request in requests], list(MEMBERS))
        for request, opinion in zip(requests, packet["symbols"][0]["opinions"]):
            self.assertEqual(request["temperature"], "0.7")
            self.assertEqual(request["max_tokens"], 500)
            self.assertEqual(opinion["recommendation"], "BUY")
            self.assertFalse(opinion["confidence_is_probability"])
            self.assertTrue(opinion["trade_plan_suppressed"])
            self.assertNotIn("qty", opinion)
            self.assertNotIn("order_type", opinion)
        self.assertFalse(packet["auto_trading_enabled"])
        self.assertFalse(any(packet["authority"].values()))

    def test_original_agent_prompts_are_retained_exactly(self):
        packet = self.generated()
        prompts = [record["request"]["prompt"] for record in packet["response_transcripts"]]
        self.assertIn("Analyze AAA for asymmetric opportunity.", prompts[0])
        self.assertIn("Assess risk profile for AAA.", prompts[1])
        self.assertIn("Analyze AAA in regime context.", prompts[2])
        self.assertIn("Analyze AAA volume and liquidity.", prompts[3])
        self.assertIn("Analyze AAA for chart patterns.", prompts[4])
        self.assertIn("10-period range:", prompts[4])
        self.assertEqual(packet["symbols"][0]["forecast_path_semantics"], "FUTURE_PREDICTED_CLOSE_LEVELS")

    def test_forecast_target_path_is_not_observed_trend(self):
        fixture = BrigadeFixture(close_fn=lambda i: 130 - i * 0.3)
        packet = fixture.build(text_generator=lambda _request: VALID_RESPONSE, allow_generation=True)
        context = packet["symbols"][0]["context"]
        self.assertTrue(context["downtrend"])
        self.assertFalse(context["uptrend"])
        self.assertLess(float(context["sma3"]), float(context["sma10"]))
        self.assertEqual(context["q50"], "106.0")
        self.assertIn("Recent direction: RISING", packet["response_transcripts"][-1]["request"]["prompt"])
        self.assertIn("Trend: DOWNTREND", packet["response_transcripts"][-1]["request"]["prompt"])

    def test_canary_volume_uses_prior_twenty_observed_bars(self):
        context = self.generated()["symbols"][0]["context"]
        volumes = [row["v"] for row in self.fixture.market["bars"]["AAA"]]
        expected = volumes[-1] / (sum(volumes[-21:-1]) / 20)
        self.assertEqual(float(context["volume_ratio"]), expected)
        self.assertTrue(context["volume_available"])

    def test_pathfinder_requires_three_distinct_future_targets(self):
        fixture = BrigadeFixture(horizons=1)
        packet = fixture.build(text_generator=lambda _request: VALID_RESPONSE, allow_generation=True)
        self.assertEqual(len(packet["response_transcripts"]), 4)
        self.assertIn("INSUFFICIENT_FORECAST_PATH_TARGETS", packet["symbols"][0]["member_coverage"][-1]["reason_codes"])

    def test_freshness_is_rechecked_at_generation_not_only_intake(self):
        packet = self.fixture.build(generated_at="2026-10-13T20:00:00Z", text_generator=lambda _request: VALID_RESPONSE, allow_generation=True)
        self.assertEqual(packet["response_transcripts"], [])
        for row in packet["symbols"][0]["member_coverage"]:
            self.assertIn("ISSUED_AT_STALE_AT_GENERATION", row["reason_codes"])
            self.assertIn("FORECAST_TARGET_NO_LONGER_FUTURE", row["reason_codes"])

    def test_generation_before_frozen_assessment_is_rejected(self):
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.fixture.build(generated_at="2026-10-12T19:59:00Z")

    def test_retained_response_replays_byte_identically_without_generation(self):
        packet = self.generated()
        replayed = self.fixture.build(transcripts=packet["response_transcripts"])
        self.assertEqual(canonical_json_bytes(packet), canonical_json_bytes(replayed))
        validate_shadow_brigade_analysis(packet, self.fixture.evidence())

    def test_interrupted_partial_capture_defers_missing_responses_without_retry(self):
        captured = self.generated()["response_transcripts"][:2]
        partial = self.fixture.build(transcripts=captured)
        self.assertEqual(len(partial["response_transcripts"]), 5)
        self.assertEqual([record["error_code"] for record in partial["response_transcripts"]],
                         [None, None, "RETAINED_RESPONSE_MISSING", "RETAINED_RESPONSE_MISSING", "RETAINED_RESPONSE_MISSING"])
        self.assertEqual([opinion["recommendation"] for opinion in partial["symbols"][0]["opinions"]], ["BUY", "BUY", None, None, None])
        validate_shadow_brigade_analysis(partial, self.fixture.evidence())

    def test_expired_captured_response_is_a_null_recommendation_not_a_parser_vote(self):
        records = self.generated()["response_transcripts"]
        records[0].update(response_text=None, error_code="RESPONSE_EXPIRED_AFTER_GENERATION")
        packet = self.fixture.build(transcripts=records)
        opinion = packet["symbols"][0]["opinions"][0]
        self.assertEqual(opinion["status"], "DEFER")
        self.assertIsNone(opinion["recommendation"])
        self.assertIsNone(opinion["confidence_label"])
        self.assertEqual(opinion["native_parser_output"]["action"], "HOLD")
        self.assertEqual(packet["symbols"][0]["member_coverage"][0]["reason_codes"], ["RESPONSE_EXPIRED_AFTER_GENERATION"])
        validate_shadow_brigade_analysis(packet, self.fixture.evidence())

    def test_evidence_closure_excludes_unreferenced_blobs_and_preserves_sources(self):
        unrelated = b"unrelated bytes must not enter this review evidence closure"
        self.fixture.blobs[sha256_bytes(unrelated)] = unrelated
        retained = evidence_for_shadow_brigade_analysis(self.fixture.intake, self.fixture.raw, self.fixture.brigade, self.fixture.decay, self.fixture.blobs)
        self.assertNotIn(unrelated, retained.values())
        for path in ("brigade/forecast-intake.json", "brigade/market-packet.json", "brigade/blackwell_brigade.py", "brigade/decay.py"):
            self.assertIn(path, retained)

    def test_disabled_packet_replays_without_network_subprocess_or_original_import(self):
        packet = self.fixture.build()
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess forbidden")):
            validate_shadow_brigade_analysis(packet, self.fixture.evidence())
        self.assertNotIn("agents.blackwell_brigade", sys.modules)
        self.assertNotIn("agents.decay", sys.modules)

    def test_raw_dissent_is_preserved_without_a_consensus_authorization(self):
        def generate(request):
            action = "EXIT" if request["member"] == "Blackwell_Sentry" else "BUY"
            return VALID_RESPONSE.replace("ACTION: BUY", "ACTION: " + action)
        packet = self.fixture.build(text_generator=generate, allow_generation=True)
        self.assertEqual({item["recommendation"] for item in packet["symbols"][0]["dissent"]}, {"BUY", "EXIT"})
        self.assertFalse(any(packet["authority"].values()))

    def test_unanimous_opinions_have_no_fabricated_dissent(self):
        self.assertEqual(self.generated()["symbols"][0]["dissent"], [])

    def test_missing_labels_native_fallback_is_not_promoted_to_vote(self):
        packet = self.generated("An unstructured synthetic statement.")
        for opinion in packet["symbols"][0]["opinions"]:
            self.assertEqual(opinion["status"], "DEFER")
            self.assertIsNone(opinion["recommendation"])
            self.assertEqual(opinion["native_parser_output"]["action"], "HOLD")

    def test_label_spacing_incompatible_with_native_parser_is_deferred(self):
        for label in ("ACTION", "CONFIDENCE", "REASONING"):
            with self.subTest(label=label):
                packet = self.generated(VALID_RESPONSE.replace(label + ":", label + " :"))
                self.assertTrue(all(item["status"] == "DEFER" for item in packet["symbols"][0]["opinions"]))

    def test_bad_or_duplicated_action_labels_are_deferred(self):
        for response in (VALID_RESPONSE.replace("ACTION: BUY", "ACTION: ENTER_LONG"), VALID_RESPONSE + "\nACTION: EXIT"):
            with self.subTest(response=response):
                packet = self.generated(response)
                self.assertTrue(all(item["recommendation"] is None for item in packet["symbols"][0]["opinions"]))

    def test_nonfinite_out_of_range_and_missing_confidence_are_deferred(self):
        for value in ("NaN", "Infinity", "1.1", "-0.1", "garbage"):
            with self.subTest(value=value):
                packet = self.generated(VALID_RESPONSE.replace("0.70", value))
                self.assertTrue(all(item["confidence_label"] is None for item in packet["symbols"][0]["opinions"]))

    def test_generator_failure_is_retained_with_sanitized_error_and_replay(self):
        def broken(_request):
            raise RuntimeError("fixture-secret-must-never-appear")
        packet = self.fixture.build(text_generator=broken, allow_generation=True)
        self.assertNotIn("fixture-secret", canonical_json_bytes(packet).decode())
        self.assertTrue(all(record["error_code"] == "SHADOW_GENERATION_FAILED" for record in packet["response_transcripts"]))
        validate_shadow_brigade_analysis(packet, self.fixture.evidence())

    def test_oversized_and_nontext_provider_returns_are_deferred(self):
        for response in ("x" * 32769, {"action": "BUY"}):
            with self.subTest(response_type=type(response)):
                packet = self.generated(response)
                self.assertTrue(all(record["error_code"] == "UNSUPPORTED_OR_OVERSIZED_RESPONSE" for record in packet["response_transcripts"]))

    def test_source_pin_changes_are_rejected_before_generator(self):
        for brigade, decay in ((self.fixture.brigade + b"\n# changed", self.fixture.decay), (self.fixture.brigade, self.fixture.decay + b"\n# changed")):
            with self.assertRaises(ShadowBrigadeAnalysisError):
                build_shadow_brigade_analysis(self.fixture.intake, self.fixture.raw, brigade, decay, generated_at=GENERATED_AT, blobs=self.fixture.blobs)

    def test_replay_rejects_changed_prompt_response_opinion_authority_or_context(self):
        original = self.generated()
        mutations = (
            lambda packet: packet["response_transcripts"][0]["request"].update(prompt="changed"),
            lambda packet: packet["response_transcripts"][0].update(response_text=VALID_RESPONSE.replace("BUY", "EXIT")),
            lambda packet: packet["symbols"][0]["opinions"][0].update(recommendation="EXIT"),
            lambda packet: packet["authority"].update(execution_enabled=True),
            lambda packet: packet["symbols"][0]["context"].update(q50="999.0"),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                packet = copy.deepcopy(original)
                mutation(packet)
                with self.assertRaises(ShadowBrigadeAnalysisError):
                    validate_shadow_brigade_analysis(packet, self.fixture.evidence())

    def test_replay_rejects_duplicate_or_unknown_member_transcripts(self):
        packet = self.generated()
        records = copy.deepcopy(packet["response_transcripts"])
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.fixture.build(transcripts=records + [records[0]])
        records[0]["request"]["member"] = "NewAgent"
        with self.assertRaises(ShadowBrigadeAnalysisError):
            self.fixture.build(transcripts=records)

    def test_symbols_are_bounded_unique_and_requests_cannot_escape_subset(self):
        for symbols in ([], ["AAA", "AAA"], ["S" + str(i) for i in range(9)]):
            with self.assertRaises(ShadowBrigadeAnalysisError):
                self.fixture.build(symbols=symbols)
        packet = self.generated(symbols=["SPY"])
        self.assertEqual(packet["requested_symbols"], ["SPY"])
        self.assertEqual(packet["response_transcripts"], [])
        self.assertEqual(packet["symbols"][0]["forecast_gate"], "DEFER")

    def test_decay_is_native_observed_calculation_and_separate_from_five_members(self):
        packet = self.fixture.build()
        decay = packet["symbols"][0]["decay"]
        self.assertEqual(decay["status"], "CONNECTED_SHADOW_ONLY")
        self.assertEqual(decay["observed_calculation"]["agent"], "Blackwell_Decay")
        self.assertTrue(decay["benchmark_timestamp_alignment_verified"])
        self.assertEqual([row["member"] for row in packet["symbols"][0]["member_coverage"]], list(MEMBERS))

    def test_decay_detects_observed_slow_bleed_without_forecasts_or_inference(self):
        fixture = BrigadeFixture(provenance=False, close_fn=lambda i: 150 * 0.99 ** i)
        fixture.market["bars"]["SPY"] = [{**row, "o": 100, "h": 101, "l": 99, "c": 100} for row in fixture.market["bars"]["SPY"]]
        bars_ref = fixture.keep("market/bars.json", {"bars": fixture.market["bars"], "next_page_token": None})
        fixture.market["source_evidence"][1] = bars_ref
        fixture.raw = canonical_json_bytes(fixture.market)
        packet = fixture.build()
        self.assertEqual(packet["symbols"][0]["decay"]["recommendation"], "EXIT")
        self.assertEqual(packet["symbols"][0]["opinions"], [])
        self.assertFalse(any(packet["authority"].values()))

    def test_insufficient_observed_history_defers_members_and_decay(self):
        fixture = BrigadeFixture(history=1)
        packet = fixture.build()
        self.assertEqual(packet["symbols"][0]["decay"]["status"], "DEFER")
        self.assertTrue(all(row["status"] == "DEFER" for row in packet["symbols"][0]["member_coverage"]))

    def test_retained_market_tampering_is_rejected(self):
        changed = copy.deepcopy(self.fixture.market)
        changed["bars"]["AAA"][0]["c"] += 0.1
        with self.assertRaises(ValueError):
            build_shadow_brigade_analysis(self.fixture.intake, canonical_json_bytes(changed), self.fixture.brigade, self.fixture.decay,
                                           generated_at=GENERATED_AT, blobs=self.fixture.blobs)

    def test_model_artifacts_are_retained_data_never_deserialized_or_executed(self):
        self.assertIn(b"never loaded", self.fixture.blobs[next(ref["sha256"] for ref in
            [__import__("json").loads(self.fixture.blobs[self.fixture.intake.sources[0]["provenance_evidence"]["sha256"]])["model"]["model_artifact_evidence"]])])
        packet = self.generated()
        self.assertEqual(packet["forecast_result"]["admitted_count"], 5)


if __name__ == "__main__":
    unittest.main()
