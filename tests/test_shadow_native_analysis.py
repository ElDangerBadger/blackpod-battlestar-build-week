"""Offline native replay: frozen real source code over synthetic market inputs."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_native_analysis import (
    AUTHORITY, FLEET_SYMBOLS, NativeAnalysisError, NativeAnalysisPacket,
    SOURCE_PINS, capture_native_sources, derive_native_analysis,
    native_symbol_states, validate_native_analysis,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/shadow_native_analysis/source_bundle.v1.json"


def test_fixture_sources() -> dict[str, bytes]:
    """Frozen reviewed sources; deterministic CI requires no sibling checkout."""
    value = json.loads(FIXTURE.read_bytes())
    return {key: zlib.decompress(base64.b64decode(encoded, validate=True)) for key, encoded in value["sources"].items()}


def test_fixture_market() -> dict:
    """Synthetic geometry; neither live prices nor a historical return claim."""
    snapshots = {}
    bars = {}
    for index, symbol in enumerate(FLEET_SYMBOLS):
        price = 102.0 if symbol == "XLK" else 100.0
        snapshots[symbol] = {
            "latestTrade": {"p": price, "t": "2026-10-12T19:00:00Z"},
            "latestQuote": {"bp": price - 0.01, "ap": price + 0.01, "t": "2026-10-12T19:00:00Z"},
            "dailyBar": {"o": 100.0, "h": 103.0, "l": 99.0, "c": price, "v": 100000, "t": "2026-10-12T04:00:00Z"},
            "prevDailyBar": {"o": 99.0, "h": 101.0, "l": 98.0, "c": 100.0, "v": 100000, "t": "2026-10-09T04:00:00Z"},
        }
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        bars[symbol] = [{"t": (start + timedelta(days=offset)).isoformat().replace("+00:00", "Z"),
                         "o": 90.0 + offset * 0.05, "h": 91.0 + offset * 0.05,
                         "l": 89.0 + offset * 0.05, "c": 90.0 + offset * 0.05, "v": 100000}
                        for offset in range(93)]
    return {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": "2026-10-12T19:00:01Z",
            "feed": "IEX", "adjustment": "RAW", "snapshots": snapshots, "bars": bars,
            "source_evidence": []}


def _reidentify(value: dict) -> dict:
    value["analysis_id"] = "shadow-native-analysis-" + sha256_bytes(canonical_json_bytes({k: v for k, v in value.items() if k != "analysis_id"}))
    return value


class NativeAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = test_fixture_sources()
        cls.market = test_fixture_market()
        cls.packet = derive_native_analysis(cls.market, cls.sources)

    def test_frozen_source_closure_matches_whole_file_pins(self):
        self.assertEqual(set(self.sources), set(SOURCE_PINS))
        self.assertEqual({key: sha256_bytes(raw) for key, raw in self.sources.items()}, dict(SOURCE_PINS))
        self.assertEqual(len(SOURCE_PINS), 24)

    def test_replay_is_exact_and_deterministic(self):
        self.assertEqual(canonical_json_bytes(derive_native_analysis(deepcopy(self.market), dict(self.sources))), canonical_json_bytes(self.packet))
        validate_native_analysis(self.packet, self.market, self.sources)

    def test_content_addressed_journal_blobs_replay(self):
        blobs = {sha256_bytes(raw): raw for raw in self.sources.values()}
        blobs[sha256_bytes(b"unrelated evidence")] = b"unrelated evidence"
        validate_native_analysis(self.packet, self.market, blobs)

    def test_exact_native_candidate_attention_without_order_authority(self):
        states = native_symbol_states(self.packet)
        self.assertEqual(states["XLK"]["candidate_state"], "REVIEW")
        self.assertEqual(states["XLK"]["candidate_confidence_label"], 0.9)
        self.assertEqual(states["XLK"]["senate_disposition"], "MONITOR")
        self.assertEqual(states["SPY"]["candidate_state"], "OBSERVE")
        self.assertEqual(self.packet["authority"], AUTHORITY)
        self.assertFalse(self.packet["canonical_mission_run"])
        self.assertIn("NOT_FORECAST_PROBABILITY", self.packet["confidence_semantics"])

    def test_native_measurement_semantics_are_preserved(self):
        measurements = self.packet["outputs"]["oracle_measurements"]
        self.assertEqual(len(measurements["symbols"]), 14)
        self.assertAlmostEqual(measurements["breadth_score"], 1 / 14, places=6)
        self.assertEqual(measurements["leadership_concentration"], 1)
        self.assertEqual(measurements["rotation_velocity"], 0)
        self.assertIn("MISSING_PRIOR_ORACLE_MEASUREMENTS", measurements["warnings"])
        self.assertIn("VXZ", measurements["provenance"]["symbols_excluded"])

    def test_shared_evidence_is_not_independent_consensus(self):
        self.assertEqual(self.packet["evidence_ancestry"], "SAME_FROZEN_MARKET_PACKET")
        self.assertIn("ORACLE_CANDIDATE_AND_SENATE_SHARE_MARKET_EVIDENCE", self.packet["limitations"])
        self.assertIn("NO_CONNECTED_BRIGADE_SPYGLASS_OR_PREDICTIVE_FORECASTS", self.packet["limitations"])

    def test_shadow_readiness_does_not_claim_market_freshness(self):
        readiness = self.packet["outputs"]["shadow_input_readiness"]
        self.assertTrue(readiness["coverage_ok"])
        self.assertFalse(readiness["freshness_ok"])
        self.assertFalse(self.packet["provider_identity_attested"])

    def test_nanosecond_original_timestamps_retained(self):
        market = deepcopy(self.market)
        market["snapshots"]["XLK"]["latestTrade"]["t"] = "2026-10-12T19:00:00.123456789Z"
        packet = derive_native_analysis(market, self.sources)
        first = packet["outputs"]["normalized_snapshot"]["symbols"][0]
        self.assertEqual(first["timestamp"], "2026-10-12T19:00:00.123456789Z")

    def test_fixed_code_change_fails_before_compilation(self):
        changed = dict(self.sources)
        path = next(iter(changed))
        changed[path] += b"\nraise RuntimeError('should never execute')\n"
        with patch("blackpod_build_week.shadow_native_analysis.ast.parse", side_effect=AssertionError("compiled untrusted code")):
            with self.assertRaisesRegex(NativeAnalysisError, "pin mismatch"):
                derive_native_analysis(self.market, changed)

    def test_unknown_file_is_rejected(self):
        changed = dict(self.sources)
        changed["blackpod/__init__.py"] = b"raise RuntimeError('initializer')"
        with self.assertRaisesRegex(NativeAnalysisError, "exact reviewed closure"):
            derive_native_analysis(self.market, changed)

    def test_missing_dependency_is_rejected(self):
        changed = dict(self.sources)
        changed.pop(next(iter(changed)))
        with self.assertRaises(NativeAnalysisError):
            derive_native_analysis(self.market, changed)

    def test_no_native_package_provider_or_filesystem_imports(self):
        import builtins
        imported = []
        original = builtins.__import__
        def tracked(name, *args, **kwargs):
            imported.append(name)
            if name.startswith(("blackpod", "alpaca", "yfinance", "requests", "subprocess")):
                raise AssertionError("native or provider imported")
            return original(name, *args, **kwargs)
        with patch.object(builtins, "__import__", tracked), patch.object(builtins, "open", side_effect=AssertionError("opened source during replay")):
            self.assertEqual(derive_native_analysis(self.market, self.sources), self.packet)
        self.assertFalse(any(name.startswith("blackpod") for name in imported))

    def test_capture_reads_safe_exact_source_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for path, raw in self.sources.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            self.assertEqual(capture_native_sources(root), self.sources)

    def test_capture_rejects_linked_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for path, raw in self.sources.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            path = next(iter(self.sources))
            target = root / "linked.py"
            target.write_bytes(self.sources[path])
            (root / path).unlink()
            (root / path).symlink_to(target)
            with self.assertRaises(Exception):
                capture_native_sources(root)

    def test_capture_detects_native_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            for path, raw in self.sources.items():
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
            path = next(iter(self.sources))
            (root / path).write_bytes(self.sources[path] + b"\n")
            with self.assertRaisesRegex(NativeAnalysisError, "pin mismatch"):
                capture_native_sources(root)

    def test_invalid_market_geometry_rejects_before_native_loading(self):
        market = deepcopy(self.market)
        market["snapshots"]["XLK"]["dailyBar"]["h"] = 98
        with patch("blackpod_build_week.shadow_native_analysis._load_native", side_effect=AssertionError("loaded invalid inputs")):
            with self.assertRaisesRegex(NativeAnalysisError, "OHLC geometry"):
                derive_native_analysis(market, self.sources)

    def test_missing_fleet_symbol_is_not_invented(self):
        market = deepcopy(self.market)
        del market["snapshots"]["VXZ"]
        with self.assertRaisesRegex(NativeAnalysisError, "all 21"):
            derive_native_analysis(market, self.sources)

    def test_numeric_unsupported_inputs_fail(self):
        for value in (True, "NaN", "Infinity", -1, 0, None, "1000000000001"):
            with self.subTest(value=value):
                market = deepcopy(self.market)
                market["snapshots"]["XLK"]["latestTrade"]["p"] = value
                with self.assertRaises(NativeAnalysisError):
                    derive_native_analysis(market, self.sources)

    def test_zero_volume_allowed_without_inventing_liquidity(self):
        market = deepcopy(self.market)
        market["snapshots"]["VXZ"]["dailyBar"]["v"] = 0
        packet = derive_native_analysis(market, self.sources)
        symbol = next(row for row in packet["outputs"]["normalized_snapshot"]["symbols"] if row["symbol"] == "VXZ")
        self.assertEqual(symbol["volume"], 0)

    def test_future_source_timestamp_is_rejected(self):
        market = deepcopy(self.market)
        market["snapshots"]["XLK"]["latestTrade"]["t"] = "2026-10-13T19:00:00Z"
        with self.assertRaisesRegex(NativeAnalysisError, "timestamps are inconsistent"):
            derive_native_analysis(market, self.sources)

    def test_previous_session_cannot_equal_current_session(self):
        market = deepcopy(self.market)
        market["snapshots"]["XLK"]["prevDailyBar"]["t"] = market["snapshots"]["XLK"]["dailyBar"]["t"]
        with self.assertRaisesRegex(NativeAnalysisError, "timestamps are inconsistent"):
            derive_native_analysis(market, self.sources)

    def test_raw_feed_boundary_is_fixed(self):
        for field, value in (("feed", "SIP"), ("adjustment", "ALL"), ("schema_version", "future.v2")):
            with self.subTest(field=field):
                market = deepcopy(self.market)
                market[field] = value
                with self.assertRaises(NativeAnalysisError):
                    derive_native_analysis(market, self.sources)

    def test_modified_output_fails_even_when_rehashed(self):
        packet = deepcopy(self.packet)
        packet["outputs"]["trading_candidate_report"]["candidates"][0]["candidate_state"] = "OBSERVE"
        _reidentify(packet)
        with self.assertRaisesRegex(NativeAnalysisError, "does not replay"):
            validate_native_analysis(packet, self.market, self.sources)

    def test_changed_source_input_fails_replay(self):
        market = deepcopy(self.market)
        market["snapshots"]["XLK"]["latestTrade"]["p"] = 101
        with self.assertRaisesRegex(NativeAnalysisError, "does not replay"):
            validate_native_analysis(self.packet, market, self.sources)

    def test_unknown_packet_field_fails(self):
        packet = deepcopy(self.packet)
        packet["execute"] = True
        with self.assertRaises(NativeAnalysisError):
            NativeAnalysisPacket.from_mapping(packet)

    def test_authority_cannot_be_activated(self):
        for field in AUTHORITY:
            with self.subTest(field=field):
                packet = deepcopy(self.packet)
                packet["authority"][field] = True
                _reidentify(packet)
                with self.assertRaises(NativeAnalysisError):
                    NativeAnalysisPacket.from_mapping(packet)

    def test_false_authority_requires_boolean(self):
        packet = deepcopy(self.packet)
        packet["authority"]["auto_trading_enabled"] = 0
        _reidentify(packet)
        with self.assertRaises(NativeAnalysisError):
            NativeAnalysisPacket.from_mapping(packet)

    def test_provider_attestation_cannot_be_claimed(self):
        packet = deepcopy(self.packet)
        packet["provider_identity_attested"] = True
        _reidentify(packet)
        with self.assertRaises(NativeAnalysisError):
            NativeAnalysisPacket.from_mapping(packet)

    def test_code_descriptor_size_fails_replay_when_rehashed(self):
        packet = deepcopy(self.packet)
        packet["source_evidence"][0]["size_bytes"] += 1
        _reidentify(packet)
        with self.assertRaisesRegex(NativeAnalysisError, "does not replay"):
            validate_native_analysis(packet, self.market, self.sources)

    def test_packet_defensive_copy_and_strict_json(self):
        contract = NativeAnalysisPacket.from_mapping(deepcopy(self.packet))
        altered = contract.to_dict()
        altered["authority"]["auto_trading_enabled"] = True
        self.assertEqual(contract.to_dict(), self.packet)
        self.assertEqual(NativeAnalysisPacket.from_bytes(contract.to_bytes()).to_dict(), self.packet)
        with self.assertRaises(ValueError):
            NativeAnalysisPacket.from_bytes(b'{"schema_version":"a","schema_version":"b"}')


if __name__ == "__main__":
    unittest.main()
