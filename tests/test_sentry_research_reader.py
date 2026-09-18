"""Synthetic bounded transport tests, not a calibration or market-data run."""
from __future__ import annotations

import copy
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from blackpod_build_week import sentry_research_reader as module
from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader, main


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture_documents():
    symbols = ["AAPL", "IWM", "JPM", "SPY"]
    declaration = {"schema_version": "sentry.calibration_v2_declaration.v1", "symbols": symbols,
        "reference_manifest_id": "frozen-reference", "primary_arm": module.ARMS[1],
        "arms": list(module.ARMS), "windows": [20, 60], "mean_new_names_limit": 2,
        "minimum_mean_jaccard": [2, 3], "capacity": 6, "per_profile_capacity": 4,
        "minimum_percentile": .95, "no_winner_selection": True,
        "order_submission_enabled": False, "current_attention_published": False, "oracle_council_integrated": False,
        "training_reference_start": "2019-01-01", "training_reference_end": "2022-12-31",
        "development_start": "2023-01-01", "development_end": "2024-12-31"}
    policies = [{"arm": arm, "role": role, "research_only": True, "order_submission_enabled": False,
        "capacity": 6, "minimum_percentile": .95, "per_profile_capacity": [["ETF", 4], ["GENERAL_EQUITY", 4]]}
        for arm, role in zip(module.ARMS, ("CONTROL", "PRIMARY", "EXPLORATORY"))]
    science = {"cohort": symbols, "reference_manifest_id": "frozen-reference", "primary_arm": module.ARMS[1],
        "windows": [20, 60], "mean_new_names_limit": 2, "minimum_mean_jaccard": [2, 3], "policies": policies,
        "required_sessions": 2, "bridge_sessions": [{"session_date": "2026-09-17"}],
        "evaluation_sessions": [{"session_date": "2026-09-18"}, {"session_date": "2026-11-27"}]}
    protocol = {"schema_version": "sentry.prospective_protocol.v2", "manifest_id": module.MANIFEST_ID,
        "scientific_spec": science, "status": "RESEARCH_ONLY", "production_ready": False,
        "observation_only": True, "order_submission_enabled": False, "current_attention_published": False}
    windows = {str(w): {arm: {"sessions": 502, "top_symbols": [["JPM", 75], ["SPY", 50]],
        "mean_new_names_per_day": {"value": 1.85 if arm == module.ARMS[2] else 3.32}, "new_names_total": 1000,
        "selected_mean": {"value": 4.5}, "coverage_of_natural_pool": {"value": .55},
        "unused_large_fraction": {"exact": [10**35, 10**39]}}
        for arm in module.ARMS} for w in (20, 60)}
    comparisons = {arm: {"sessions": 502, "mean_jaccard_ge_2_over_3": False,
        "workload_both_windows_mean_new_names_le_2": arm == module.ARMS[2],
        "admission_limit_workload_pass_by_construction": arm == module.ARMS[2],
        "all_session_mean_jaccard": {"value": .53}} for arm in module.ARMS}
    summary = {"development_id": "synthetic-development", "scope": "DEVELOPMENT_ONLY_2023_2024_NOT_INDEPENDENT_VALIDATION",
        "primary_arm": module.ARMS[1], "windows": windows, "cross_window_comparisons": comparisons,
        "cache_sha256": module.UPSTREAM_PINS["cache"], "results_sha256": module.UPSTREAM_PINS["results"]}
    closeout = {"schema_version": "sentry.v2_closeout_integrity.v1", "manifest_id": module.MANIFEST_ID,
        "verified_at": "2026-09-18T04:30:20.826014+00:00", "scheduler_loaded": True,
        "execution_authority_changed": False, "oracle_council_integrated": False, "new_calibration_experiments": False,
        "status": {"checked_at": "2026-09-18T04:30:20.826014Z", "manifest_id": module.MANIFEST_ID,
            "status": "RESEARCH_ONLY", "observation_only": True, "order_submission_enabled": False,
            "current_attention_published": False, "warmup_sealed": False,
            "prospective_status": "BLOCKED_MISSING_REQUIRED_EVIDENCE",
            "session_progress": {"required": 2, "verified_canonical": 0},
            "failures": [{"symbol": "IWM", "status": "CAPTURE_FAILED", "reason": "OHLCV_CONFLICT_RETAINED"}],
            "future_calendar_blockers": ["2026-11-27"]},
        "warmup": {"status": "FAILED_CLOSED_NOT_A_VALID_WARMUP", "symbol_outcomes": {
            "READY": 2, "CAPTURE_FAILED": 1, "BLOCKED_CAPTURE_FAILURE": 1},
            "complete_cohort_sealed": False, "failure_evidence_sealed": True, "prospective_sessions_scored": 0,
            "provider_requests": 3, "first_retrieved_at": "2026-09-18T04:15:00Z", "last_retrieved_at": "2026-09-18T04:26:00Z",
            "private_path": "/private/never-publish-me",
            "conflict": {"kind": "HISTORICAL_OVERLAP_CONFLICT", "session": "2026-09-16", "fields": ["adj_close", "volume"],
                "existing": {"date": "2026-09-16", "volume": "27522300"}, "incoming": {"date": "2026-09-16", "volume": "27599400"}}}}
    return {"development-declaration.json": declaration, "development-summary.json": summary,
            "prospective-protocol.json": protocol, "failed-warmup-integrity.json": closeout}


class SentryResearchReaderTests(unittest.TestCase):
    def setUp(self):
        clock_patch = patch.object(module, "datetime", wraps=datetime)
        self.clock = clock_patch.start(); self.addCleanup(clock_patch.stop)
        self.clock.now.return_value = datetime(2026, 9, 18, 5, tzinfo=timezone.utc)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.research, self.closeout = self.root / "research", self.root / "closeout"
        self.research.mkdir(); self.closeout.mkdir()
        self.documents = fixture_documents()
        self.pins = {}; self.publish_fixture()
        self.pin_patch = patch.dict(module.SOURCE_PINS, self.pins)
        self.pin_patch.start(); self.addCleanup(self.pin_patch.stop)

    def path(self, name):
        return (self.closeout if name == "failed-warmup-integrity.json" else self.research) / name

    def publish_fixture(self):
        # Synthetic reviewed pins are injected only in tests. No production
        # constructor accepts replacement pins or a caller-supplied validator.
        for name in ("development-declaration.json", "development-summary.json", "prospective-protocol.json"):
            raw = encoded(self.documents[name]); self.path(name).write_bytes(raw)
            self.pins[name] = hashlib.sha256(raw).hexdigest()
        self.documents["failed-warmup-integrity.json"]["unchanged_v2_artifact_hashes"] = {
            "development-declaration.json": self.pins["development-declaration.json"],
            "prospective-protocol.json": self.pins["prospective-protocol.json"],
            "development-cache-seed-1.json": module.UPSTREAM_PINS["cache"],
            "development-results-seed-1.json": module.UPSTREAM_PINS["results"]}
        name = "failed-warmup-integrity.json"
        raw = encoded(self.documents[name]); self.path(name).write_bytes(raw)
        self.pins[name] = hashlib.sha256(raw).hexdigest()

    def reader(self):
        return module.SentryResearchReader(self.research, self.closeout)

    def assertUnavailable(self, value):
        self.assertEqual(value["status"], "UNAVAILABLE")
        for field in ("source", "study", "prospective"): self.assertIsNone(value[field])
        self.assertNotIn(str(self.root), json.dumps(value))
        self.assertNotIn("never-publish-me", json.dumps(value))

    def test_default_has_no_discovery_reads_or_results(self):
        with patch.object(module, "_read_regular") as read:
            result = module.SentryResearchReader().current()
        read.assert_not_called()
        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertIsNone(result["source"])
        self.assertIsNone(result["study"])
        self.assertIsNone(result["prospective"])

    def test_explicit_all_or_none_normalized_configuration(self):
        for args in ((self.research, None), (None, self.closeout), (self.root / "../bad", self.closeout),
                     (self.root / "bad\nroot", self.closeout)):
            with self.subTest(args=args), self.assertRaises(ValueError): module.SentryResearchReader(*args)

    def test_projection_is_bounded_static_observation_and_source_time_is_distinct(self):
        before = {n: self.path(n).read_bytes() for n in self.pins}
        result = self.reader().current()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"]["archive_as_of"], "2026-09-18T04:30:20.826014Z")
        self.assertNotEqual(result["checked_at"], result["source"]["archive_as_of"])
        self.assertEqual(len(result["source"]["files"]), 4)
        self.assertEqual(result["study"]["cohort"], self.documents["development-declaration.json"]["symbols"])
        self.assertEqual([p["arm"] for p in result["study"]["policies"]], list(module.ARMS))
        self.assertEqual(result["study"]["criteria"]["minimum_mean_jaccard"], 2/3)
        self.assertTrue(result["study"]["all_policies_failed"])
        self.assertTrue(result["study"]["policies"][2]["capped_by_construction"])
        self.assertFalse(result["source"]["upstream_artifacts_reverified"])
        self.assertEqual(result["prospective"]["status"], "BLOCKED_MISSING_REQUIRED_EVIDENCE")
        self.assertEqual(result["prospective"]["completed_sessions"], 0)
        self.assertFalse(result["prospective"]["warmup"]["complete_cohort_sealed"])
        self.assertTrue(result["prospective"]["warmup"]["failure_evidence_sealed"])
        self.assertEqual(result["prospective"]["warmup"]["conflict"]["symbol"], "IWM")
        self.assertTrue(result["observation_only"])
        self.assertFalse(result["order_submission_enabled"])
        self.assertFalse(result["current_attention_published"])
        rendered = json.dumps(result)
        self.assertLess(len(rendered), module.MAX_FEED_BYTES)
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn("never-publish-me", rendered)
        self.assertNotIn(str(10**35), rendered)
        self.assertEqual(before, {n: self.path(n).read_bytes() for n in self.pins})

    def test_reads_exactly_four_small_files_never_large_panel_or_canonical_code(self):
        with patch.object(module, "_read_regular", wraps=module._read_regular) as read:
            self.assertEqual(self.reader().current()["status"], "READY")
        self.assertEqual([call.args[0].name for call in read.call_args_list], list(module.SOURCE_PINS))
        self.assertTrue(all(call.args[1] == 128 * 1024 for call in read.call_args_list))

    def test_future_archive_is_not_presented_as_available_evidence(self):
        self.clock.now.return_value = datetime(2026, 9, 17, 5, tzinfo=timezone.utc)
        self.assertUnavailable(self.reader().current())

    def test_missing_wrong_and_mutated_sources_fail_without_stale_fallback(self):
        reader = self.reader(); self.assertEqual(reader.current()["status"], "READY")
        source = self.path("development-summary.json"); original = source.read_bytes()
        for value in (b"{}", original + b"\n", original[:-1]):
            source.write_bytes(value); self.assertUnavailable(reader.current())
        source.unlink(); self.assertUnavailable(reader.current())
        self.assertUnavailable(module.SentryResearchReader(self.closeout, self.research).current())

    def test_symlink_file_parent_directory_and_nonregular_sources_are_refused(self):
        path = self.path("development-summary.json"); raw = path.read_bytes(); path.unlink()
        target = self.root / "external.json"; target.write_bytes(raw); path.symlink_to(target)
        self.assertUnavailable(self.reader().current()); path.unlink(); path.mkdir()
        self.assertUnavailable(self.reader().current()); path.rmdir(); os.mkfifo(path)
        self.assertUnavailable(self.reader().current()); path.unlink(); path.write_bytes(raw)
        link = self.root / "link"; link.symlink_to(self.research, target_is_directory=True)
        self.assertUnavailable(module.SentryResearchReader(link, self.closeout).current())

    def test_oversized_file_and_midread_mutation_fail_closed(self):
        source = self.path("development-summary.json"); original = source.read_bytes()
        source.write_bytes(b"x" * (module.MAX_SOURCE_BYTES + 1)); self.assertUnavailable(self.reader().current())
        source.write_bytes(original)
        real_read = os.read; changed = False
        def mutate(fd, amount):
            nonlocal changed
            value = real_read(fd, amount)
            if not changed:
                changed = True
                path = self.path("development-declaration.json")
                path.write_bytes(path.read_bytes() + b"\n")
            return value
        with patch("blackpod_build_week.sentry_reader.os.read", side_effect=mutate):
            self.assertUnavailable(self.reader().current())

    def test_strict_json_even_when_test_pin_matches_malformed_payload(self):
        source = self.path("development-summary.json")
        for raw in (b'{"same":1,"same":2}', b'{"number":NaN}', b'[]', b'{"number":Infinity}'):
            source.write_bytes(raw)
            with patch.dict(module.SOURCE_PINS, {source.name: hashlib.sha256(raw).hexdigest()}):
                self.assertUnavailable(self.reader().current())

    def test_crosslinks_criteria_counts_safety_and_profile_status_cannot_change(self):
        mutations = [
            lambda d: d["development-summary.json"].update(cache_sha256="0" * 64),
            lambda d: d["prospective-protocol.json"].update(status="PRODUCTION_CANDIDATE"),
            lambda d: d["prospective-protocol.json"].update(order_submission_enabled=True),
            lambda d: d["prospective-protocol.json"].update(manifest_id="different"),
            lambda d: d["development-declaration.json"].update(mean_new_names_limit=3),
            lambda d: d["development-declaration.json"].update(primary_arm=module.ARMS[2]),
            lambda d: d["failed-warmup-integrity.json"]["warmup"]["symbol_outcomes"].update(READY=3),
            lambda d: d["failed-warmup-integrity.json"]["warmup"].update(complete_cohort_sealed=True),
            lambda d: d["failed-warmup-integrity.json"]["status"].update(prospective_status="PENDING"),
            lambda d: d["failed-warmup-integrity.json"].update(oracle_council_integrated=True),
        ]
        original = fixture_documents()
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                self.documents = copy.deepcopy(original); mutate(self.documents); self.publish_fixture()
                with patch.dict(module.SOURCE_PINS, self.pins): self.assertUnavailable(self.reader().current())


class SentryResearchHTTPTests(unittest.TestCase):
    path = SentryResearchReaderTests.path
    publish_fixture = SentryResearchReaderTests.publish_fixture
    reader = SentryResearchReaderTests.reader

    def setUp(self):
        SentryResearchReaderTests.setUp(self)
        self.reader_instance = self.reader()
        self.server = CabinHTTPServer(CabinReader(), self.root, 0, sentry_research_reader=self.reader_instance)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self, path="/live/sentry/research.json", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse(); result = response.status, dict(response.getheaders()), response.read()
        connection.close(); return result

    def test_independent_get_no_store_and_legacy_unchanged(self):
        with patch.object(self.server.reader, "current") as mission, patch.object(self.server.sentry_reader, "current") as legacy:
            status, headers, raw = self.request()
        mission.assert_not_called(); legacy.assert_not_called()
        self.assertEqual(status, 200); self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(json.loads(raw)["status"], "READY")
        status, _, raw = self.request("/live/sentry/current.json")
        self.assertEqual(status, 200); self.assertEqual(json.loads(raw)["status"], "NOT_CONFIGURED")

    def test_host_origin_method_query_path_guards(self):
        with patch.object(self.reader_instance, "current") as read:
            for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
                self.assertEqual(self.request(headers=headers)[0], 403)
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                self.assertEqual(self.request(method=method)[0], 405)
            for path in ("/live/sentry/research.json?path=/private", "/live/sentry/../research.json",
                         "/live/sentry/%2e%2e/research.json", "/live/sentry/development-summary.json",
                         "/live/sentry/research.json/anything"):
                self.assertEqual(self.request(path)[0], 404)
        read.assert_not_called()

    def test_unconfigured_endpoint_and_head(self):
        self.server.sentry_research_reader = module.SentryResearchReader()
        status, _, raw = self.request(); self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["status"], "NOT_CONFIGURED")
        self.assertEqual(self.request(method="HEAD")[2], b"")


class SentryResearchCLITests(unittest.TestCase):
    def test_partial_research_configuration_rejected_before_server_start(self):
        with patch("blackpod_build_week.cabin_reader.CabinHTTPServer") as server, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): main(["--sentry-research-root", "/explicit/research"])
        server.assert_not_called()

    def test_optional_pair_is_independent_of_legacy_source_arguments(self):
        instance = Mock(); instance.server_port = 5174; instance.serve_forever.side_effect = KeyboardInterrupt
        with patch("blackpod_build_week.cabin_reader.CabinHTTPServer", return_value=instance) as server:
            self.assertEqual(main(["--sentry-research-root", "/explicit/research",
                                   "--sentry-research-closeout-root", "/explicit/closeout"]), 0)
        value = server.call_args.kwargs["sentry_research_reader"]
        self.assertEqual(value.research_root, Path("/explicit/research"))
        self.assertEqual(value.closeout_root, Path("/explicit/closeout"))
