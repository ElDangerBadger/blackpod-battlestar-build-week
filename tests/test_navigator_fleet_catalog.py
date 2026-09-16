"""Offline fleet-reference capture tests; no provider, service, or Git calls."""
from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from blackpod_build_week import cabin_reader, navigator_catalog, navigator_fleet_catalog as fleet
from blackpod_build_week.cabin_context import CabinContextError, capture_cabin_context
from blackpod_build_week.contracts import ContractValidationError, MissionSnapshot
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore, UnsafePathError
from test_cabin_context import CAPTURED_AT, REVISION, market_bytes, market_value, request

SOURCE = {"git_revision": REVISION, "backend_sha256": "b" * 64, "worktree_dirty": True}


class NavigatorFleetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.store = MissionStore(self.base / "artifacts")
        self.request = request()
        self.mission_id = self.request.mission_id
        initialized = self.store.initialize(self.request, mission_id=self.mission_id,
            started_at=CAPTURED_AT, observed_at=CAPTURED_AT)
        self.root = initialized.paths.mission_root
        self.fleet_bytes = canonical_json_bytes({"symbol_count": 2, "symbols": [{"symbol": "SPY"}, {"symbol": "QQQ"}]})
        self.fleet_ref = self.store.write_immutable_artifact(self.mission_id,
            relative_path="oracle/normalized.json", payload=self.fleet_bytes,
            name="oracle_normalized_snapshot", producer="oracle", schema_version=None, observed_at=CAPTURED_AT)
        loaded = self.store.load_mission(self.mission_id)
        snapshot = loaded.snapshot.to_dict()
        snapshot.update(revision=2, snapshot_id=f"{self.mission_id}-r0002",
            previous_snapshot_sha256=loaded.current_snapshot_sha256,
            artifacts=[*snapshot["artifacts"], self.fleet_ref.to_dict()])
        self.store.commit_snapshot(loaded.paths, MissionSnapshot.from_mapping(snapshot))
        capture_cabin_context(self.store, mission_id=self.mission_id, captured_at=CAPTURED_AT,
            market_bytes=market_bytes(), market_transport="LOCAL_JSON",
            market_source_identity="offline-original", navigator_git_revision=REVISION)
        self.originals = self.state()

    def state(self):
        return {path.relative_to(self.root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob("*") if path.is_file()}

    def variant(self, symbol="SPY", timeframe="1d", period=250):
        value = market_value()
        value.update(symbol=symbol, timeframe=timeframe, ma_period=period)
        value["summary"]["ma_period"] = period
        value["data"] = {"provider": "yfinance", "source": "provider", "stale": False, "age_seconds": 0}
        payload = (json.dumps(value, indent=1) + " \n").encode()
        return fleet.NavigatorFleetCapture(symbol, timeframe, period, CAPTURED_AT,
            "LOCAL_JSON", "offline-fleet", payload)

    def capture(self, *captures, **kwargs):
        return fleet.capture_navigator_fleet(self.store, mission_id=self.mission_id,
            captured_at=CAPTURED_AT, navigator_source=kwargs.get("source", SOURCE),
            captures=captures or [self.variant()])

    def assert_no_capture(self):
        self.assertFalse((self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH).exists())
        self.assertFalse((self.root / "presentation/navigator_fleet").exists())
        self.assertFalse(list((self.root / "presentation").glob(".navigator-catalog-*")))
        self.assertEqual(self.state(), self.originals)

    def reader(self):
        return cabin_reader.CabinReader(self.store.artifacts_root, self.mission_id)

    def rewrite_catalog(self, update):
        target = self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH
        value = json.loads(target.read_bytes())
        update(value)
        target.write_bytes(canonical_json_bytes(value))

    def test_exact_capture_publication_hashes_idempotency_and_no_reader_writes(self):
        first = self.capture(self.variant(), self.variant("QQQ"))
        self.assertTrue(first.written)
        self.assertEqual(first.catalog.fleet_snapshot, self.fleet_ref)
        self.assertEqual(dict(first.catalog.navigator_source), SOURCE)
        before = self.state()
        self.assertFalse(self.capture(self.variant(), self.variant("QQQ")).written)
        reader = self.reader()
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("reader write")):
            feed = reader.current()
        self.assertEqual(feed["status"], "READY")
        manifest_bytes = reader.artifact(feed["publication_id"], cabin_reader.MANIFEST_PATH)
        self.assertEqual(feed["publication_id"], sha256_bytes(manifest_bytes))
        reference = json.loads(manifest_bytes)["navigator_fleet_catalog"]
        catalog_bytes = reader.artifact(feed["publication_id"], reference["path"])
        self.assertEqual(reference["sha256"], sha256_bytes(catalog_bytes))
        self.assertEqual(reference["byte_size"], len(catalog_bytes))
        self.assertEqual(reference["producer"], "harbormaster")
        self.assertEqual(reference["observed_at"], CAPTURED_AT)
        for entry in first.catalog.entries:
            payload = reader.artifact(feed["publication_id"], entry.artifact.path)
            self.assertEqual(payload, self.variant(entry.symbol).payload)
            self.assertEqual(sha256_bytes(payload), entry.artifact.sha256)
        self.assertEqual(before, self.state())
        for path, original in self.originals.items():
            self.assertEqual(self.state()[path], original)

    def test_atomic_validation_rejects_wrong_symbol_pair_synthetic_duplicate_and_source(self):
        good = self.variant()
        synthetic = json.loads(good.payload)
        synthetic["data"]["provider"] = "synthetic"
        cases = [
            [good, replace(self.variant("QQQ"), payload=b"{}")], [good, good],
            [self.variant("MSFT")], [self.variant("AAPL")], [replace(good, symbol="../SPY")],
            [replace(good, timeframe="1h")], [replace(good, ma_period=20)],
            [replace(good, payload=canonical_json_bytes(synthetic))],
            [replace(good, source_identity="/tmp/provider")], [replace(good, transport="REPLAY")],
        ]
        for captures in cases:
            with self.subTest(captures=captures), self.assertRaises(ContractValidationError):
                self.capture(*captures)
            self.assert_no_capture()
        for field, value in (("git_revision", "a"), ("backend_sha256", "z" * 64), ("worktree_dirty", "true")):
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                self.capture(source={**SOURCE, field: value})
            self.assert_no_capture()

    def test_size_budgets_reject_before_publish_including_new_manifest(self):
        for name in ("MAX_VARIANT_BYTES", "MAX_CATALOG_CAPTURE_BYTES"):
            with mock.patch.object(fleet, name, len(self.variant().payload) - 1), self.assertRaises(ContractValidationError):
                self.capture()
            self.assert_no_capture()
        publication = cabin_reader.capture_publication(cabin_reader.ReadOnlyMissionStore(self.store.artifacts_root), self.mission_id)
        with mock.patch.object(fleet, "_publish_catalog_files", return_value=False):
            result = self.capture()
        budget = sum(map(len, publication.files.values())) + len(self.variant().payload) + len(canonical_json_bytes(result.catalog.to_dict()))
        with mock.patch.object(cabin_reader, "MAX_PUBLICATION_BYTES", budget), mock.patch.object(fleet, "_publish_catalog_files") as publish:
            with self.assertRaisesRegex(CabinContextError, "publication byte limit"):
                self.capture()
            publish.assert_not_called()
        self.assert_no_capture()

    def test_publish_failure_cleans_only_new_fleet_files(self):
        real_link = navigator_catalog.os.link
        calls = 0
        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("offline injected failure")
            return real_link(*args, **kwargs)
        with mock.patch.object(navigator_catalog.os, "link", side_effect=fail), self.assertRaises(OSError):
            self.capture(self.variant(), self.variant("QQQ"))
        self.assert_no_capture()

    def test_existing_conflict_or_symlink_is_never_overwritten(self):
        directory = self.root / "presentation/navigator_fleet"
        directory.mkdir()
        target = self.root / fleet.fleet_market_path("SPY", "1d", 250)
        target.write_bytes(b"original conflicting bytes")
        with self.assertRaises(CabinContextError):
            self.capture()
        self.assertEqual(target.read_bytes(), b"original conflicting bytes")
        target.unlink()
        outside = self.base / "outside.json"
        outside.write_bytes(self.variant().payload)
        target.symlink_to(outside)
        with self.assertRaises(UnsafePathError):
            self.capture()
        self.assertTrue(target.is_symlink())
        self.assertFalse((self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH).exists())

    def test_old_catalog_bytes_remain_unchanged(self):
        value = market_value()
        value.update(timeframe="1h", ma_period=20)
        value["summary"]["ma_period"] = 20
        navigator_catalog.capture_navigator_catalog(self.store, mission_id=self.mission_id, captured_at=CAPTURED_AT,
            captures=[navigator_catalog.NavigatorVariantCapture("1h", 20, CAPTURED_AT, "LOCAL_JSON", "offline-original-variant", REVISION, canonical_json_bytes(value))])
        before = self.state()
        self.capture()
        after = self.state()
        for path, original in before.items():
            self.assertEqual(after[path], original)

    def test_catalog_commit_is_last_and_partial_files_are_not_visible(self):
        real_link = navigator_catalog.os.link
        observations = []
        def observe(*args, **kwargs):
            result = real_link(*args, **kwargs)
            reader = self.reader()
            feed = reader.current()
            self.assertEqual(feed["status"], "READY")
            manifest = json.loads(reader.artifact(feed["publication_id"], cabin_reader.MANIFEST_PATH))
            observations.append((args[1], "navigator_fleet_catalog" in manifest))
            return result
        with mock.patch.object(navigator_catalog.os, "link", side_effect=observe):
            self.capture(self.variant(), self.variant("QQQ"))
        self.assertEqual(observations, [("SPY-1d-ma250.json", False), ("QQQ-1d-ma250.json", False),
                                        ("navigator_fleet_catalog.json", True)])

    def test_reader_accepts_fleet_catalog_without_default_context(self):
        (self.root / "presentation/cabin_context.json").unlink()
        (self.root / "presentation/navigator_market.json").unlink()
        self.capture()
        self.assertEqual(self.reader().current()["status"], "READY")

    def test_reader_rejects_fleet_catalog_that_appears_during_capture(self):
        self.capture()
        target = self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH
        saved = target.read_bytes()
        target.unlink()
        original_projection = cabin_reader.project_mission_presentation
        def appear(*args, **kwargs):
            target.write_bytes(saved)
            return original_projection(*args, **kwargs)
        with mock.patch.object(cabin_reader, "project_mission_presentation", side_effect=appear):
            self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")

    def test_reader_rejects_catalog_symlink_and_mid_capture_variant_changes(self):
        self.capture()
        catalog_path = self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH
        saved = catalog_path.read_bytes()
        outside = self.base / "catalog-outside.json"
        outside.write_bytes(saved)
        catalog_path.unlink()
        catalog_path.symlink_to(outside)
        self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")
        catalog_path.unlink()
        catalog_path.write_bytes(saved)
        path = fleet.fleet_market_path("SPY", "1d", 250)
        real_read = cabin_reader._read_file
        count = 0
        def changed(root, relative, **kwargs):
            nonlocal count
            payload = real_read(root, relative, **kwargs)
            if relative == path:
                count += 1
                if count > 1:
                    return b" " + payload[1:]
            return payload
        with mock.patch.object(cabin_reader, "_read_file", side_effect=changed):
            self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")

    def test_reader_rejects_correlation_membership_path_and_reference_tampering(self):
        self.capture()
        path = self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH
        original = path.read_bytes()
        updates = [
            lambda value: value.update(mission_id="mission-other"),
            lambda value: value.update(request_id="request-other"),
            lambda value: value.update(mission_symbol="QQQ"),
            lambda value: value.update(run_mode="REPLAY"),
            lambda value: value["fleet_snapshot"].update(sha256="0" * 64),
            lambda value: value["entries"][0].update(symbol="../SPY"),
            lambda value: value["entries"][0]["artifact"].update(path="../private.json"),
            lambda value: value["entries"].append(value["entries"][0]),
        ]
        for update in updates:
            path.write_bytes(original)
            self.rewrite_catalog(update)
            self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")

    def test_reader_rejects_rehashed_payload_symbol_pair_and_synthetic_and_missing_bytes(self):
        self.capture()
        original = json.loads(self.variant().payload)
        path = self.root / fleet.fleet_market_path("SPY", "1d", 250)
        for field, value in (("symbol", "QQQ"), ("timeframe", "1h"), ("ma_period", 20), ("provider", "synthetic")):
            changed = json.loads(json.dumps(original))
            if field == "provider":
                changed["data"]["provider"] = value
            else:
                changed[field] = value
                if field == "ma_period":
                    changed["summary"]["ma_period"] = value
            payload = canonical_json_bytes(changed)
            path.write_bytes(payload)
            self.rewrite_catalog(lambda catalog: catalog["entries"][0]["artifact"].update(sha256=sha256_bytes(payload), byte_size=len(payload)))
            self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")
        path.unlink()
        self.assertEqual(self.reader().current()["status"], "UNAVAILABLE")

    def test_reader_bounds_every_fleet_read_and_does_not_publish_orphans(self):
        orphan = self.root / fleet.fleet_market_path("QQQ", "1d", 250)
        orphan.parent.mkdir()
        orphan.write_bytes(self.variant("QQQ").payload)
        reader = self.reader()
        feed = reader.current()
        self.assertIsNone(reader.artifact(feed["publication_id"], orphan.relative_to(self.root).as_posix()))
        self.capture()
        with mock.patch.object(cabin_reader, "_read_file", wraps=cabin_reader._read_file) as read:
            self.assertEqual(self.reader().current()["status"], "READY")
        calls = [call for call in read.call_args_list if call.args[1] == fleet.fleet_market_path("SPY", "1d", 250)]
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(call.kwargs["max_bytes"] <= len(self.variant().payload) for call in calls))

    def http_capture(self, fetcher, **kwargs):
        options = dict(artifacts_root=self.store.artifacts_root, mission_id=self.mission_id,
            navigator_base_url="http://127.0.0.1:8001", navigator_repository=self.base,
            fetcher=fetcher, sleeper=mock.Mock(), clock=lambda: CAPTURED_AT)
        options.update(kwargs)
        return fleet.capture_navigator_fleet_from_http(**options)

    def test_http_defaults_all_observed_daily250_paces_and_reports_without_retries(self):
        calls = []
        def fetcher(url, **kwargs):
            query = parse_qs(urlsplit(url).query)
            symbol = query["symbol"][0]
            self.assertEqual(kwargs["expected_symbol"], symbol)
            self.assertEqual(query["timeframe"], ["1d"])
            self.assertEqual(query["ma"], ["250"])
            calls.append(symbol)
            return self.variant(symbol).payload
        sleeper, progress = mock.Mock(), mock.Mock()
        with mock.patch.object(fleet, "inspect_navigator_source", return_value=SOURCE) as inspect:
            result = self.http_capture(fetcher, sleeper=sleeper, progress=progress)
        self.assertEqual(calls, ["SPY", "QQQ"])
        self.assertEqual(len(result.catalog.entries), 2)
        sleeper.assert_called_once_with(1.1)
        self.assertEqual(progress.call_count, 2)
        self.assertEqual(inspect.call_count, 2)

    def test_http_failure_changed_source_or_nonloopback_publishes_nothing(self):
        with mock.patch.object(fleet, "inspect_navigator_source", return_value=SOURCE):
            with self.assertRaisesRegex(CabinContextError, "offline failure"):
                self.http_capture(mock.Mock(side_effect=[self.variant().payload, CabinContextError("offline failure")]))
        self.assert_no_capture()
        with mock.patch.object(fleet, "inspect_navigator_source", side_effect=[SOURCE, {**SOURCE, "backend_sha256": "c" * 64}]):
            with self.assertRaisesRegex(CabinContextError, "source changed"):
                self.http_capture(mock.Mock(side_effect=[self.variant().payload, self.variant("QQQ").payload]))
        self.assert_no_capture()
        for url in ("https://example.com", "http://user:pass@127.0.0.1", "http://127.0.0.1/other", "http://127.0.0.1?secret=x"):
            fetcher = mock.Mock()
            with self.assertRaises(CabinContextError):
                self.http_capture(fetcher, navigator_base_url=url)
            fetcher.assert_not_called()
        self.assert_no_capture()

    def test_http_final_clock_mission_update_cannot_reanchor_publication(self):
        calls = 0
        after_update = None

        def clock():
            nonlocal calls, after_update
            calls += 1
            # Two per-entry timestamps precede the final catalog timestamp.
            # The last call runs after HTTP acquisition's original-byte checks.
            if calls == 3:
                loaded = self.store.load_mission(self.mission_id)
                snapshot = loaded.snapshot.to_dict()
                revision = loaded.snapshot.revision + 1
                snapshot.update(revision=revision, snapshot_id=f"{self.mission_id}-r{revision:04d}",
                    previous_snapshot_sha256=loaded.current_snapshot_sha256,
                    observed_at="2026-07-19T18:31:00Z")
                self.store.commit_snapshot(loaded.paths, MissionSnapshot.from_mapping(snapshot))
                after_update = self.state()
            return "2026-07-19T18:31:00Z"

        fetcher = mock.Mock(side_effect=[self.variant().payload, self.variant("QQQ").payload])
        with mock.patch.object(fleet, "inspect_navigator_source", return_value=SOURCE), \
                mock.patch.object(fleet, "_baseline", wraps=fleet._baseline) as baseline:
            with self.assertRaisesRegex(CabinContextError, "original mission.*changed"):
                self.http_capture(fetcher, clock=clock)
        self.assertEqual(calls, 3)
        self.assertEqual(fetcher.call_count, 2)
        baseline.assert_called_once()
        self.assertIsNotNone(after_update)
        self.assertEqual(self.store.load_mission(self.mission_id).snapshot.revision, 3)
        self.assertEqual(self.reader().current()["status"], "READY")
        self.assertFalse((self.root / fleet.NAVIGATOR_FLEET_CATALOG_PATH).exists())
        self.assertFalse((self.root / "presentation/navigator_fleet").exists())
        self.assertFalse(list((self.root / "presentation").glob(".navigator-catalog-*")))
        self.assertEqual(self.state(), after_update)

    def test_http_existing_catalog_and_invalid_pacing_reject_before_fetch(self):
        for pace in (0, 1, float("nan"), True):
            fetcher = mock.Mock()
            with self.assertRaises(CabinContextError):
                self.http_capture(fetcher, pace_seconds=pace)
            fetcher.assert_not_called()
        self.capture()
        fetcher = mock.Mock()
        with self.assertRaises(CabinContextError):
            self.http_capture(fetcher)
        fetcher.assert_not_called()


class NavigatorFleetSourceTests(unittest.TestCase):
    def test_normalized_membership_is_strict_but_does_not_reinterpret_fields(self):
        valid = {"symbol_count": 2, "other": "retained", "symbols": [{"symbol": "BRK.B", "price": 123}, {"symbol": "SPY"}]}
        self.assertEqual(fleet.fleet_symbols(canonical_json_bytes(valid)), ("BRK.B", "SPY"))
        for value in ({"symbols": []}, {"symbols": [{"symbol": "SPY"}, {"symbol": "SPY"}]},
                      {"symbols": [{"symbol": "../SPY"}]}, {"symbol_count": True, "symbols": [{"symbol": "SPY"}]},
                      {"symbol_count": 2, "symbols": [{"symbol": "SPY"}]}, {"symbols": ["SPY"]}):
            with self.assertRaises(ContractValidationError):
                fleet.fleet_symbols(canonical_json_bytes(value))

    def test_backend_fingerprint_sorted_runtime_only_preserves_dirty_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "backend/src"
            source.mkdir(parents=True)
            (source / "z.py").write_bytes(b"z = 1\n")
            (source / "a.py").write_bytes(b"a = 1\n")
            (source / "test_ignored.py").write_bytes(b"test\n")
            (source / "tests").mkdir()
            (source / "tests/example.py").write_bytes(b"test\n")
            records = [{"path": "backend/src/a.py", "sha256": sha256_bytes(b"a = 1\n")},
                       {"path": "backend/src/z.py", "sha256": sha256_bytes(b"z = 1\n")}]
            with mock.patch.object(fleet, "inspect_git_revision", return_value=REVISION), mock.patch.object(fleet.subprocess, "run", return_value=SimpleNamespace(stdout=" M backend/src/a.py\n")):
                result = fleet.inspect_navigator_source(root)
                self.assertEqual(result, {"git_revision": REVISION, "backend_sha256": sha256_bytes(canonical_json_bytes(records)), "worktree_dirty": True})
                (source / "a.py").write_bytes(b"a = 2\n")
                self.assertNotEqual(result["backend_sha256"], fleet.inspect_navigator_source(root)["backend_sha256"])
                (source / "link.py").symlink_to(source / "a.py")
                with self.assertRaises(CabinContextError):
                    fleet.inspect_navigator_source(root)


if __name__ == "__main__":
    unittest.main()
