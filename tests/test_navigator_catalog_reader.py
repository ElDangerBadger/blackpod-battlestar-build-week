"""Offline acceptance checks for catalog-bound read-only publications.

Variants below are contract fixtures, not claimed market acquisitions. The
captured fixture is adapted only inside disposable test directories.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackpod_build_week import cabin_reader
from blackpod_build_week.cabin_context import CABIN_CONTEXT_PATH, capture_cabin_context
from blackpod_build_week.cabin_reader import CabinReader, MANIFEST_PATH
from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.navigator_catalog import (
    NAVIGATOR_CATALOG_PATH,
    NavigatorVariantCapture,
    capture_navigator_catalog,
    variant_path,
)


MISSION_ID = "mission-catalog-reader-001"
OBSERVED_AT = "2026-07-18T20:00:00Z"
CAPTURED_AT = "2026-07-19T20:00:00Z"
DEFAULT_PATH = "presentation/navigator_market.json"
VARIANT_PATH = variant_path("1h", 20)


class NavigatorCatalogReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.artifacts = self.base / "artifacts"
        self.store = MissionStore(self.artifacts)
        request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-catalog-reader-001",
            "mission_id": MISSION_ID,
            "run_mode": "LIVE", "symbol": "AAPL", "requested_at": OBSERVED_AT,
            "operator_id": "catalog-reader-test", "metadata": {},
        })
        initialized = self.store.initialize(
            request, mission_id=MISSION_ID, started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        self.root = initialized.paths.mission_root
        fixture = Path(__file__).resolve().parents[1] / "fixtures/cabin/aapl_navigator_market.live_capture.json"
        self.default_bytes = fixture.read_bytes()
        capture_cabin_context(
            self.store, mission_id=MISSION_ID, captured_at=OBSERVED_AT,
            market_bytes=self.default_bytes, market_transport="LOCAL_JSON",
            market_source_identity="offline-reader-default", navigator_git_revision="a" * 40,
        )
        variant = json.loads(self.default_bytes)
        variant.update(timeframe="1h", ma_period=20)
        variant["summary"]["ma_period"] = 20
        self.variant_bytes = canonical_json_bytes(variant)
        self.reader = CabinReader(self.artifacts, MISSION_ID)

    def publish_catalog(self):
        return capture_navigator_catalog(
            self.store, mission_id=MISSION_ID, captured_at=CAPTURED_AT,
            captures=[NavigatorVariantCapture(
                "1h", 20, CAPTURED_AT, "LOCAL_JSON", "offline-reader-variant",
                "b" * 40, self.variant_bytes,
            )],
        )

    def file_state(self):
        return {
            path.relative_to(self.artifacts).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.artifacts.rglob("*") if path.is_file()
        }

    def manifest(self):
        feed = self.reader.current()
        self.assertEqual(feed["status"], "READY")
        payload = self.reader.artifact(feed["publication_id"], MANIFEST_PATH)
        self.assertIsNotNone(payload)
        self.assertEqual(feed["publication_id"], sha256_bytes(payload))
        return feed, json.loads(payload)

    def rewrite_catalog(self, update):
        path = self.root / NAVIGATOR_CATALOG_PATH
        catalog = json.loads(path.read_bytes())
        update(catalog)
        path.write_bytes(canonical_json_bytes(catalog))

    def replace_variant_and_rehash(self, value):
        payload = canonical_json_bytes(value)
        (self.root / VARIANT_PATH).write_bytes(payload)
        self.rewrite_catalog(lambda catalog: catalog["entries"][0]["artifact"].update(
            byte_size=len(payload), sha256=sha256_bytes(payload),
        ))

    def test_optional_catalog_changes_hash_without_changing_original_evidence(self):
        original_paths = ("mission_snapshot.json", "request/mission_request.json", CABIN_CONTEXT_PATH, DEFAULT_PATH)
        originals = {path: (self.root / path).read_bytes() for path in original_paths}
        initial, old_manifest = self.manifest()
        self.assertNotIn("navigator_catalog", old_manifest)
        self.publish_catalog()
        before = self.file_state()
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("reader wrote files")):
            latest, manifest = self.manifest()
        self.assertEqual(before, self.file_state())
        self.assertNotEqual(initial["publication_id"], latest["publication_id"])
        self.assertEqual(latest["observed_at"], OBSERVED_AT)
        self.assertEqual(manifest["generated_at"], OBSERVED_AT)
        for path, payload in originals.items():
            self.assertEqual((self.root / path).read_bytes(), payload)
            self.assertEqual(self.reader.artifact(latest["publication_id"], path), payload)
        reference = manifest["navigator_catalog"]
        catalog_bytes = self.reader.artifact(latest["publication_id"], reference["path"])
        self.assertEqual(reference["name"], "navigator_catalog")
        self.assertEqual(reference["observed_at"], CAPTURED_AT)
        self.assertEqual(reference["byte_size"], len(catalog_bytes))
        self.assertEqual(reference["sha256"], sha256_bytes(catalog_bytes))
        entry_reference = json.loads(catalog_bytes)["entries"][0]["artifact"]
        self.assertEqual(entry_reference["sha256"], sha256_bytes(self.variant_bytes))
        self.assertEqual(self.reader.artifact(latest["publication_id"], VARIANT_PATH), self.variant_bytes)
        self.assertIsNone(self.reader.artifact(initial["publication_id"], VARIANT_PATH))

    def test_unreferenced_variant_files_are_not_published(self):
        path = self.root / VARIANT_PATH
        path.parent.mkdir()
        path.write_bytes(self.variant_bytes)
        feed, manifest = self.manifest()
        self.assertNotIn("navigator_catalog", manifest)
        self.assertIsNone(self.reader.artifact(feed["publication_id"], VARIANT_PATH))
        self.assertEqual(self.reader.artifact(feed["publication_id"], DEFAULT_PATH), self.default_bytes)

    def test_tampered_or_missing_variant_never_returns_ready(self):
        self.publish_catalog()
        prior, _ = self.manifest()
        path = self.root / VARIANT_PATH
        for bad_bytes in (b"{}\n", self.variant_bytes + b" ", self.variant_bytes[:-1]):
            with self.subTest(length=len(bad_bytes)):
                path.write_bytes(bad_bytes)
                feed = self.reader.current()
                self.assertEqual(feed["status"], "UNAVAILABLE")
                self.assertNotIn("publication_id", feed)
        path.unlink()
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
        # Existing publications stay immutable; they are never silently used as
        # today's current feed when its source is broken.
        self.assertEqual(self.reader.artifact(prior["publication_id"], VARIANT_PATH), self.variant_bytes)

    def test_rehashing_does_not_authorize_wrong_pair_symbol_or_synthetic_data(self):
        self.publish_catalog()
        for field, value in (("timeframe", "1wk"), ("ma_period", 50), ("symbol", "MSFT")):
            with self.subTest(field=field):
                changed = json.loads(self.variant_bytes)
                changed[field] = value
                if field == "ma_period":
                    changed["summary"]["ma_period"] = value
                self.replace_variant_and_rehash(changed)
                self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
        changed = json.loads(self.variant_bytes)
        changed["data"] = {"stale": False, "age_seconds": 0, "source": "provider", "provider": "synthetic"}
        self.replace_variant_and_rehash(changed)
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_catalog_correlation_and_duplicate_pairs_are_rejected(self):
        self.publish_catalog()
        original = (self.root / NAVIGATOR_CATALOG_PATH).read_bytes()
        for field, value in (
            ("mission_id", "mission-other-001"), ("request_id", "request-other-001"),
            ("symbol", "MSFT"), ("run_mode", "REPLAY"),
        ):
            with self.subTest(field=field):
                (self.root / NAVIGATOR_CATALOG_PATH).write_bytes(original)
                self.rewrite_catalog(lambda catalog: catalog.update({field: value}))
                self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
        (self.root / NAVIGATOR_CATALOG_PATH).write_bytes(original)
        self.rewrite_catalog(lambda catalog: catalog["entries"].append(catalog["entries"][0]))
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_catalog_cannot_replace_the_original_default_pair(self):
        self.publish_catalog()
        default = json.loads(self.default_bytes)
        default_pair_path = variant_path(default["timeframe"], default["ma_period"])
        (self.root / default_pair_path).write_bytes(self.default_bytes)
        def replace_entry(catalog):
            entry = catalog["entries"][0]
            entry.update(timeframe=default["timeframe"], ma_period=default["ma_period"])
            entry["artifact"].update(path=default_pair_path, byte_size=len(self.default_bytes), sha256=sha256_bytes(self.default_bytes))
        self.rewrite_catalog(replace_entry)
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_unsafe_catalog_paths_are_rejected_before_any_variant_read(self):
        self.publish_catalog()
        original = (self.root / NAVIGATOR_CATALOG_PATH).read_bytes()
        for path in ("../secret", "/absolute", "presentation/../secret", "presentation\\secret", "presentation/navigator_variants/unknown.json"):
            with self.subTest(path=path):
                (self.root / NAVIGATOR_CATALOG_PATH).write_bytes(original)
                self.rewrite_catalog(lambda catalog: catalog["entries"][0]["artifact"].update(path=path))
                with mock.patch.object(cabin_reader, "_read_file", wraps=cabin_reader._read_file) as reader:
                    self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
                self.assertFalse(any(call.args[1] == path for call in reader.call_args_list))

    def test_catalog_and_variant_symlinks_are_not_followed(self):
        self.publish_catalog()
        for relative in (NAVIGATOR_CATALOG_PATH, VARIANT_PATH):
            with self.subTest(relative=relative):
                target = self.root / relative
                payload = target.read_bytes()
                outside = self.base / "outside.json"
                outside.write_bytes(payload)
                target.unlink()
                target.symlink_to(outside)
                self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
                target.unlink()
                target.write_bytes(payload)

    def test_each_variant_read_is_bounded_by_its_declared_size(self):
        self.publish_catalog()
        with mock.patch.object(cabin_reader, "_read_file", wraps=cabin_reader._read_file) as reader:
            self.manifest()
        variant_calls = [call for call in reader.call_args_list if call.args[1] == VARIANT_PATH]
        self.assertGreaterEqual(len(variant_calls), 2)
        for call in variant_calls:
            self.assertLessEqual(call.kwargs["max_bytes"], len(self.variant_bytes))

    def test_publication_total_byte_limit_is_enforced(self):
        self.publish_catalog()
        with mock.patch.object(cabin_reader, "MAX_PUBLICATION_BYTES", 1):
            feed = self.reader.current()
        self.assertEqual(feed["status"], "UNAVAILABLE")
        self.assertNotIn(str(self.artifacts), json.dumps(feed))

    def test_catalog_requires_both_original_context_and_original_market(self):
        self.publish_catalog()
        for relative in (CABIN_CONTEXT_PATH, DEFAULT_PATH):
            with self.subTest(relative=relative):
                target = self.root / relative
                payload = target.read_bytes()
                target.unlink()
                self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
                target.write_bytes(payload)

    def test_variant_changed_during_capture_cannot_publish_a_mixed_revision(self):
        self.publish_catalog()
        read_file = cabin_reader._read_file
        changed = False
        def racing_read(root, relative, **kwargs):
            nonlocal changed
            payload = read_file(root, relative, **kwargs)
            if relative == VARIANT_PATH and not changed:
                changed = True
                (root / relative).write_bytes(payload + b" ")
            return payload
        with mock.patch.object(cabin_reader, "_read_file", side_effect=racing_read):
            feed = self.reader.current()
        self.assertTrue(changed)
        self.assertEqual(feed["status"], "UNAVAILABLE")
        self.assertNotIn("publication_id", feed)


if __name__ == "__main__":
    unittest.main()
