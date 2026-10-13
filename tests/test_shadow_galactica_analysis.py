"""Native Spyglass facts and original Brigade opinions, entirely offline."""
from __future__ import annotations

import copy
import math
import socket
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Inexact, Rounded, localcontext
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_galactica_analysis import (
    BAR_LIMIT, LIMITATIONS, SOURCE_PINS, ShadowGalacticaAnalysisError,
    build_shadow_galactica_analysis, evidence_for_shadow_galactica_analysis,
    symbol_challenges, symbol_gate, validate_shadow_galactica_analysis,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "shadow_galactica_analysis"
CAPTURED_AT = "2026-10-12T20:00:00Z"
GENERATED_AT = "2026-10-12T20:01:00Z"
TRANSCRIPT = """SYNTHETIC FIXTURE: not historical trading performance.
Model: fixture-legacy
🔬 Analyzing AAA
📋 Blackwell Brigade Analysis:
 Blackwell_Scout: BUY (confidence=0.70)
 → Synthetic momentum opinion.
 Blackwell_Sentry: EXIT (confidence=0.80)
 → Synthetic tail-risk dissent.
 Blackwell_Advisor: HOLD (confidence=0.60)
 → Synthetic regime uncertainty.
 Blackwell_Canary: WATCH (confidence=0.65)
 → Synthetic volume uncertainty.
 Blackwell_Pathfinder: HOLD (confidence=0.55)
 → Synthetic pattern uncertainty.
🏛️ Senate Vote:
 ✓ Sen. Momentum: LONG @ 0.60
 → Synthetic long reasoning.
 ✗ Sen. Risk: HOLD @ 0.70
 → Synthetic dissent reasoning.
📊 DECISION: LONG @ 0.60
 Cohesion: 50% (1/2 agree)
 Dissent: Sen. Risk
============================================================
🔬 Analyzing BBB
📋 Blackwell Brigade Analysis:
 Blackwell_Scout: WATCH (confidence=0.60)
 → Synthetic interrupted opinion.
KeyboardInterrupt
""".encode("utf-8")


def market_mapping(count=90):
    start = datetime(2026, 10, 12, tzinfo=timezone.utc) - timedelta(days=count + 1)
    rows = []
    for i in range(count):
        close = round(100 + 4 * math.sin(i * math.pi / 10), 6)
        rows.append({"t": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"),
                     "o": close, "h": close + 1, "l": close - 1, "c": close, "v": 10000 + i * 10})
    return {"schema_version": "blackpod.shadow_market_capture.v1", "captured_at": CAPTURED_AT,
            "source_kind": "SYNTHETIC_FIXTURE", "bars": {"AAA": rows, "BBB": copy.deepcopy(rows)}}


class ShadowGalacticaAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spyglass = (ROOT / "spyglass.py").read_bytes()
        cls.parser = (ROOT / "brigade_debrief.py").read_bytes()
        cls.producer = (ROOT / "blackwell_brigade.py").read_bytes()

    def setUp(self):
        self.market = market_mapping()
        self.raw = canonical_json_bytes(self.market)

    def build(self, raw=None, **kwargs):
        return build_shadow_galactica_analysis(raw or self.raw, self.spyglass, generated_at=GENERATED_AT, **kwargs)

    def historical(self, **kwargs):
        return self.build(brigade_transcript=kwargs.pop("brigade_transcript", TRANSCRIPT), brigade_parser_source=self.parser,
                          brigade_producer_source=self.producer, brigade_as_of=kwargs.pop("brigade_as_of", "2026-04-24T20:00:00Z"), **kwargs)

    def blobs(self, raw=None, transcript=TRANSCRIPT):
        values = [raw or self.raw, self.spyglass, self.parser, self.producer, transcript]
        return {sha256_bytes(value): value for value in values}

    def test_fixture_sources_are_byte_exact_approved_native_snapshots(self):
        for name, source in (("spyglass.py", self.spyglass), ("scripts/brigade_debrief.py", self.parser), ("agents/blackwell_brigade.py", self.producer)):
            self.assertEqual(SOURCE_PINS[name], sha256_bytes(source))

    def test_actual_spyglass_runs_support_resistance_events_and_patterns(self):
        packet = self.build()
        self.assertEqual(packet["spyglass"]["status"], "CONNECTED_SHADOW_ONLY")
        row = packet["spyglass"]["observations"][0]
        self.assertTrue(row["structure"]["levels"])
        self.assertEqual(set(row["structure"]["patterns"]), {"double_top", "double_bottom", "head_shoulders", "inverse_hs", "triangle", "flag_pennant", "rsi_divergence"})
        self.assertTrue(row["structure"]["patterns"]["double_top"])
        self.assertFalse(row["confidence_is_probability"])
        for level in row["structure"]["levels"]:
            self.assertIsInstance(level["price"], str)
            self.assertIn(level["kind"], {"support", "resistance"})

    def test_repeat_is_byte_deterministic_without_clock_rewrites(self):
        self.assertEqual(canonical_json_bytes(self.build()), canonical_json_bytes(self.build()))
        self.assertEqual(canonical_json_bytes(self.historical()), canonical_json_bytes(self.historical()))
        self.assertEqual(self.historical()["brigade"]["parsed_report"]["generated_at"], GENERATED_AT)

    def test_missing_brigade_is_explicit_with_no_fabricated_opinions(self):
        packet = self.build()
        self.assertEqual(packet["brigade"]["status"], "MISSING_CURRENT_FORECASTS_AND_INFERENCE")
        self.assertIsNone(packet["brigade"]["parsed_report"])
        self.assertFalse(packet["brigade"]["current_generation_enabled"])
        self.assertFalse(packet["brigade"]["current_opinions_available"])

    def test_original_brigade_opinions_senate_dissent_and_incomplete_rows_are_preserved(self):
        brigade = self.historical()["brigade"]
        self.assertEqual(brigade["status"], "HISTORICAL_INPUT_ONLY")
        self.assertTrue(brigade["stale"])
        self.assertFalse(brigade["current_opinions_available"])
        first, incomplete = brigade["parsed_report"]["symbols"]
        self.assertEqual([opinion["action"] for opinion in first["brigade"]], ["BUY", "EXIT", "HOLD", "WATCH", "HOLD"])
        self.assertEqual(first["decision"]["dissent"], ["Risk"])
        self.assertEqual(first["brigade"][1]["reasoning"], "Synthetic tail-risk dissent.")
        self.assertEqual(first["brigade"][1]["confidence"], "0.8")
        self.assertTrue(incomplete["incomplete"])
        self.assertIsNone(incomplete["decision"])
        self.assertEqual(brigade["source_model_declared"], "fixture-legacy")
        self.assertEqual(brigade["member_coverage"][0]["missing_members"], ["Blackwell_Decay"])
        self.assertEqual(brigade["member_coverage"][0]["current_generation_status"], "DEFER")

    def test_import_never_authenticates_original_model_or_source_relationship(self):
        packet = self.historical()
        self.assertFalse(packet["brigade"]["provider_provenance_verified"])
        self.assertFalse(any(packet["authority"].values()))
        self.assertEqual(packet["limitations"], list(LIMITATIONS))

    def test_offline_runtime_never_opens_socket_subprocess_broker_or_ai(self):
        with patch.object(socket, "socket", side_effect=AssertionError("socket prohibited")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess prohibited")):
            packet = self.historical()
        self.assertEqual(packet["spyglass"]["status"], "CONNECTED_SHADOW_ONLY")
        self.assertNotIn("agents.blackwell_brigade", __import__("sys").modules)

    def test_changed_source_cannot_execute_even_when_rehashed_in_packet(self):
        with self.assertRaises(ShadowGalacticaAnalysisError):
            build_shadow_galactica_analysis(self.raw, self.spyglass + b"\nraise RuntimeError('untrusted')", generated_at=GENERATED_AT)
        packet = self.build(); source = self.spyglass + b"\n# tampered"
        packet["source_evidence"]["spyglass"].update(sha256=sha256_bytes(source), size_bytes=len(source))
        blobs = self.blobs(); blobs[sha256_bytes(source)] = source
        with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, self.market, blobs)

    def test_native_facts_replay_exactly_and_semantic_tampering_fails(self):
        packet = self.historical()
        self.assertEqual(packet, validate_shadow_galactica_analysis(packet, self.market, self.blobs()))
        changed = copy.deepcopy(packet); changed["spyglass"]["observations"][0]["structure"]["levels"][0]["price"] = "1"
        with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(changed, self.market, self.blobs())

    def test_changed_raw_market_even_with_new_hash_cannot_preserve_old_facts(self):
        packet = self.build(); changed = copy.deepcopy(self.market)
        changed["bars"]["AAA"][-1].update(o=120, h=122, l=119, c=121)
        raw = canonical_json_bytes(changed)
        packet["market_source"] = {"sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, changed, self.blobs(raw))

    def test_truncated_missing_or_hash_corrupt_evidence_fails(self):
        packet = self.historical()
        for corruption in ("missing", "wrong-size", "wrong-bytes"):
            changed = copy.deepcopy(packet); blobs = self.blobs()
            ref = changed["source_evidence"]["brigade_transcript"]
            if corruption == "missing": blobs.pop(ref["sha256"])
            elif corruption == "wrong-size": ref["size_bytes"] += 1
            else: blobs[ref["sha256"]] += b"changed"
            with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(changed, self.market, blobs)

    def test_source_rehash_cannot_remove_original_dissent_or_fabricate_current_votes(self):
        for field in ("current_opinions_available", "current_generation_enabled", "provider_provenance_verified"):
            packet = self.historical(); packet["brigade"][field] = True
            with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, self.market, self.blobs())
        packet = self.historical(); packet["brigade"]["parsed_report"]["symbols"][0]["decision"]["dissent"] = []
        with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, self.market, self.blobs())

    def test_source_and_generation_times_cannot_be_future_or_made_fresh(self):
        with self.assertRaises(ShadowGalacticaAnalysisError): self.historical(brigade_as_of="2026-10-13T20:00:00Z")
        with self.assertRaises(ShadowGalacticaAnalysisError): build_shadow_galactica_analysis(self.raw, self.spyglass, generated_at="2026-10-11T20:00:00Z")
        packet = self.historical(); packet["brigade"]["stale"] = False
        with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, self.market, self.blobs())

    def test_date_only_legacy_source_preserves_unknown_time_and_timezone(self):
        packet = self.historical(brigade_as_of="2026-04-24")
        self.assertEqual(packet["brigade"]["source_as_of"], "2026-04-24")
        self.assertEqual(packet["brigade"]["source_time_precision"], "DATE_ONLY_TIMEZONE_UNSPECIFIED")
        self.assertTrue(packet["brigade"]["stale"])
        self.assertEqual(packet, validate_shadow_galactica_analysis(packet, self.market, self.blobs()))
        self.assertIsNone(self.historical(brigade_as_of="2026-10-11")["brigade"]["stale"])
        for invalid in ("2026-02-30", "2026-10-13"):
            with self.assertRaises(ShadowGalacticaAnalysisError): self.historical(brigade_as_of=invalid)

    def test_date_only_source_cannot_disagree_with_original_transcript_header(self):
        source = b"Date: 2026-04-24\n" + TRANSCRIPT
        packet = self.historical(brigade_as_of="2026-04-24", brigade_transcript=source)
        self.assertEqual(packet["brigade"]["source_as_of"], "2026-04-24")
        with self.assertRaises(ShadowGalacticaAnalysisError): self.historical(brigade_as_of="2026-04-23", brigade_transcript=source)

    def test_daily_window_and_unproven_capture_date_bars_explicit(self):
        market = market_mapping(130); market["bars"]["AAA"].append({"t": "2026-10-12T00:00:00Z", "o": 100, "h": 101, "l": 99, "c": 100, "v": 10})
        packet = self.build(canonical_json_bytes(market))
        row = packet["spyglass"]["observations"][0]
        self.assertEqual(row["excluded_unproven_daily_bars"], 1)
        self.assertLessEqual(row["bar_count"], BAR_LIMIT)

    def test_insufficient_history_explicit_without_false_confirmation(self):
        row = self.build(canonical_json_bytes(market_mapping(10)))["spyglass"]["observations"][0]
        self.assertEqual(row["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(row["structure"]["patterns"], {})

    def test_invalid_bars_reject_before_native_calls(self):
        for changed in ("crossed", "NaN", "duplicate", "negative-volume", "future", "extra", "boolean"):
            market = copy.deepcopy(self.market); rows = market["bars"]["AAA"]
            if changed == "crossed": rows[-1]["h"] = 1
            elif changed == "NaN": rows[-1]["c"] = "NaN"
            elif changed == "duplicate": rows[-1]["t"] = rows[-2]["t"]
            elif changed == "negative-volume": rows[-1]["v"] = -1
            elif changed == "future": rows[-1]["t"] = "2026-10-13T00:00:00Z"
            elif changed == "extra": rows[-1]["policy"] = "BUY"
            else: rows[-1]["c"] = True
            with self.subTest(changed=changed), self.assertRaises((ShadowGalacticaAnalysisError, ContractValidationError)):
                self.build(canonical_json_bytes(market))

    def test_historical_inputs_are_all_or_none_with_explicit_as_of(self):
        for kwargs in ({"brigade_transcript": TRANSCRIPT}, {"brigade_parser_source": self.parser}, {"brigade_producer_source": self.producer}, {"brigade_as_of": "2026-04-24T20:00:00Z"}):
            with self.assertRaises(ShadowGalacticaAnalysisError): self.build(**kwargs)

    def test_malformed_packet_shape_and_hash_types_reject_cleanly(self):
        for changed in ("extra", "hash", "size", "authority"):
            packet = self.build()
            if changed == "extra": packet["orders"] = []
            elif changed == "hash": packet["market_source"]["sha256"] = []
            elif changed == "size": packet["market_source"]["size_bytes"] = True
            else: packet["authority"]["execution_enabled"] = True
            with self.assertRaises((ShadowGalacticaAnalysisError, ContractValidationError)):
                validate_shadow_galactica_analysis(packet, self.market, self.blobs())

    def test_versions_and_limitations_are_immutable_replay_inputs(self):
        for changed in ("version", "limitations"):
            packet = self.build()
            if changed == "version": packet["runtime_fingerprint"]["pandas"] = "other"
            else: packet["limitations"] = []
            with self.assertRaises(ShadowGalacticaAnalysisError): validate_shadow_galactica_analysis(packet, self.market, self.blobs())

    def test_native_structure_challenge_and_resistance_headroom_are_passive(self):
        packet = self.build()
        self.assertIn("BEARISH_PATTERN", symbol_challenges(packet)["AAA"])
        row = packet["spyglass"]["observations"][0]
        resistance = next(level for level in row["structure"]["levels"] if level["kind"] == "resistance")
        price = format(__import__("decimal").Decimal(resistance["price"]) - 1, "f")
        challenge = symbol_gate(packet, "AAA", price, "2")
        self.assertIn("RESISTANCE_HEADROOM_LT_STOP_SCENARIO", challenge["blocking_reason_codes"])
        self.assertFalse(challenge["execution_authority_granted"])
        self.assertIn("SPYGLASS_SYMBOL_NOT_REVIEWED", symbol_gate(packet, "ZZZ", "100", "2")["blocking_reason_codes"])

    def test_old_patterns_remain_original_facts_but_cannot_block_current_research(self):
        market = market_mapping()
        for rows in market["bars"].values():
            for row in rows:
                when = datetime.fromisoformat(row["t"].replace("Z", "+00:00")) - timedelta(days=60)
                row["t"] = when.isoformat().replace("+00:00", "Z")
        packet = self.build(canonical_json_bytes(market))
        row = packet["spyglass"]["observations"][0]
        self.assertTrue(row["structure"]["patterns"]["double_top"])
        self.assertTrue(row["challenge_assessment"]["excluded_historical_refs"])
        self.assertEqual(row["challenge_assessment"]["comparison_at"], CAPTURED_AT)
        self.assertEqual(row["challenge_assessment"]["window_calendar_days"], 30)
        self.assertNotIn("BEARISH_PATTERN", symbol_challenges(packet)["AAA"])
        self.assertIsNone(symbol_gate(packet, "AAA", "100", "2")["nearest_resistance_headroom_usd"])

    def test_derived_stop_distance_precision_and_hostile_decimal_context_are_supported(self):
        packet = self.build()
        distance = "8.857142857142857142857142857142857142857142857142857142857142857"
        expected = symbol_gate(packet, "AAA", "100", distance)
        with localcontext() as context:
            context.prec = 1; context.traps[Inexact] = True; context.traps[Rounded] = True
            self.assertEqual(expected, symbol_gate(packet, "AAA", "100", distance))

    def test_retained_evidence_helper_has_no_writes_and_exact_source_bytes(self):
        evidence = evidence_for_shadow_galactica_analysis(self.raw, self.spyglass, brigade_transcript=TRANSCRIPT,
            brigade_parser_source=self.parser, brigade_producer_source=self.producer)
        self.assertEqual(evidence["galactica/spyglass.py"], self.spyglass)
        self.assertEqual(evidence["galactica/brigade-transcript.txt"], TRANSCRIPT)
        self.assertEqual(len(evidence), 4)


if __name__ == "__main__": unittest.main()
