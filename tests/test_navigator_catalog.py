"""Offline capture/atomicity checks; test variants are not market acquisitions."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from blackpod_build_week import cabin_reader, navigator_catalog as catalog_module
from blackpod_build_week.cabin_context import (
    CABIN_CONTEXT_PATH, CabinContextConflictError, CabinContextError,
    capture_cabin_context,
)
from blackpod_build_week.cabin_reader import CabinReader
from blackpod_build_week.contracts import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.navigator_catalog import (
    NAVIGATOR_CATALOG_PATH, NavigatorVariantCapture,
    capture_navigator_catalog, capture_navigator_catalog_from_http, variant_path,
)
from test_cabin_context import CAPTURED_AT, REVISION, market_bytes, market_value, request


class NavigatorCatalogCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.store = MissionStore(self.base / "artifacts")
        self.request = request()
        self.mission_id = self.request.mission_id
        initialized = self.store.initialize(
            self.request, mission_id=self.mission_id,
            started_at=CAPTURED_AT, observed_at=CAPTURED_AT,
        )
        self.root = initialized.paths.mission_root
        capture_cabin_context(
            self.store, mission_id=self.mission_id, captured_at=CAPTURED_AT,
            market_bytes=market_bytes(), market_transport="LOCAL_JSON",
            market_source_identity="offline-catalog-default", navigator_git_revision=REVISION,
        )
        self.originals = {path: (self.root / path).read_bytes() for path in (
            "request/mission_request.json", "mission_snapshot.json", CABIN_CONTEXT_PATH,
            "presentation/navigator_market.json",
        )}

    def variant(self, timeframe="1h", ma_period=20):
        value = market_value()
        value.update(timeframe=timeframe, ma_period=ma_period)
        value["summary"]["ma_period"] = ma_period
        # Preserve deliberately noncanonical formatting, including trailing space.
        payload = (json.dumps(value, indent=1) + " \n").encode()
        return NavigatorVariantCapture(
            timeframe, ma_period, CAPTURED_AT, "LOCAL_JSON",
            "offline-catalog-variant", REVISION, payload,
        )

    def capture(self, *variants):
        return capture_navigator_catalog(
            self.store, mission_id=self.mission_id, captured_at=CAPTURED_AT,
            captures=variants or [self.variant()],
        )

    def assert_no_capture(self):
        self.assertFalse((self.root / NAVIGATOR_CATALOG_PATH).exists())
        self.assertFalse((self.root / "presentation/navigator_variants").exists())
        self.assertFalse(list((self.root / "presentation").glob(".navigator-catalog-*")))
        for path, payload in self.originals.items():
            self.assertEqual((self.root / path).read_bytes(), payload)

    def http_capture(self, fetcher, **kwargs):
        with mock.patch.object(catalog_module, "inspect_git_revision", return_value=REVISION):
            return capture_navigator_catalog_from_http(
                artifacts_root=self.store.artifacts_root, mission_id=self.mission_id,
                navigator_base_url="http://127.0.0.1:8001", navigator_repository=self.base,
                fetcher=fetcher, clock=lambda: CAPTURED_AT, **kwargs,
            )

    def test_preserves_exact_bytes_and_original_evidence_and_is_idempotent(self):
        variant = self.variant()
        first = self.capture(variant)
        self.assertTrue(first.written)
        self.assertEqual((self.root / variant_path("1h", 20)).read_bytes(), variant.payload)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertFalse(self.capture(variant).written)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()})
        for path, payload in self.originals.items():
            self.assertEqual((self.root / path).read_bytes(), payload)
        self.assertEqual(CabinReader(self.store.artifacts_root, self.mission_id).current()["status"], "READY")

    def test_validates_every_variant_before_writing_any(self):
        good = self.variant()
        invalid = replace(self.variant("1wk", 50), payload=b"{}")
        with self.assertRaises(ContractValidationError):
            self.capture(good, invalid)
        self.assert_no_capture()

    def test_rejects_default_duplicate_wrong_pair_and_invalid_provenance(self):
        good = self.variant()
        cases = [
            (self.variant("1d", 250),), (good, good),
            (replace(good, timeframe="1wk"),),
            (replace(good, ma_period=50),),
            (replace(good, navigator_git_revision="abc"),),
            (replace(good, source_identity="/private/path"),),
            (replace(good, transport="REPLAY"),),
        ]
        for variants in cases:
            with self.subTest(variants=variants), self.assertRaises(ContractValidationError):
                self.capture(*variants)
            self.assert_no_capture()

    def test_size_limits_reject_before_staging(self):
        good = self.variant()
        for limit in ("MAX_VARIANT_BYTES", "MAX_CATALOG_CAPTURE_BYTES"):
            with self.subTest(limit=limit), mock.patch.object(catalog_module, limit, len(good.payload) - 1):
                with self.assertRaises(ContractValidationError):
                    self.capture(good)
            self.assert_no_capture()

    def test_publish_failure_rolls_back_only_new_links(self):
        first, second = self.variant(), self.variant("1wk", 50)
        real_link = catalog_module.os.link
        count = 0
        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("injected publication failure")
            return real_link(*args, **kwargs)
        with mock.patch.object(catalog_module.os, "link", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "injected"):
                self.capture(first, second)
        self.assert_no_capture()

    def test_partial_capture_is_not_visible_until_catalog_commit(self):
        real_link = catalog_module.os.link
        statuses = []
        def inspect_after_link(*args, **kwargs):
            result = real_link(*args, **kwargs)
            feed = CabinReader(self.store.artifacts_root, self.mission_id).current()
            statuses.append((args[1], feed["status"]))
            return result
        with mock.patch.object(catalog_module.os, "link", side_effect=inspect_after_link):
            self.capture(self.variant(), self.variant("1wk", 50))
        self.assertEqual([name for name, _ in statuses], ["1h-ma20.json", "1wk-ma50.json", "navigator_catalog.json"])
        self.assertTrue(all(status == "READY" for _, status in statuses))

    def test_existing_conflict_is_never_overwritten(self):
        variant = self.variant()
        target = self.root / variant_path("1h", 20)
        target.parent.mkdir()
        target.write_bytes(b"existing evidence")
        with self.assertRaises(CabinContextConflictError):
            self.capture(variant)
        self.assertEqual(target.read_bytes(), b"existing evidence")
        self.assertFalse((self.root / NAVIGATOR_CATALOG_PATH).exists())

    def test_baseline_change_prevents_publication(self):
        real_publish = catalog_module._publish_catalog_files
        def mutate_snapshot(root, payloads, baseline):
            self.assertIn("mission_snapshot.json", baseline)
            snapshot = root / "mission_snapshot.json"
            snapshot.write_bytes(b" " + snapshot.read_bytes()[1:])
            return real_publish(root, payloads, baseline)
        with mock.patch.object(catalog_module, "_publish_catalog_files", side_effect=mutate_snapshot):
            with self.assertRaises(CabinContextError):
                self.capture()
        self.assertFalse((self.root / NAVIGATOR_CATALOG_PATH).exists())
        self.assertFalse((self.root / "presentation/navigator_variants").exists())

    def test_preflight_accounts_for_the_larger_catalog_bound_manifest(self):
        variant = self.variant()
        publication = cabin_reader.capture_publication(
            cabin_reader.ReadOnlyMissionStore(self.store.artifacts_root), self.mission_id,
        )
        with mock.patch.object(catalog_module, "_publish_catalog_files", return_value=False):
            dry_run = self.capture(variant)
        # This budget fits all new files with the OLD manifest, but not the
        # expanded manifest that must bind the catalog. Reject before writing.
        too_small = (sum(map(len, publication.files.values())) + len(variant.payload)
                     + len(canonical_json_bytes(dry_run.catalog.to_dict())))
        with mock.patch.object(cabin_reader, "MAX_PUBLICATION_BYTES", too_small):
            with mock.patch.object(catalog_module, "_publish_catalog_files") as publish:
                with self.assertRaisesRegex(CabinContextError, "publication byte limit"):
                    self.capture(variant)
                publish.assert_not_called()
        self.assert_no_capture()

    def test_http_requests_only_nondefault_pairs_and_preserves_responses(self):
        calls = []
        def fetcher(url, **kwargs):
            query = parse_qs(urlsplit(url).query)
            pair = (query["timeframe"][0], int(query["ma"][0]))
            self.assertEqual(query["symbol"], ["AAPL"])
            self.assertEqual(kwargs["expected_symbol"], "AAPL")
            self.assertGreater(kwargs["max_response_bytes"], 0)
            calls.append(pair)
            return self.variant(*pair).payload
        result = self.http_capture(fetcher)
        self.assertEqual(len(calls), 14)
        self.assertEqual(len(set(calls)), 14)
        self.assertNotIn(("1d", 250), calls)
        self.assertEqual(len(result.catalog.entries), 14)
        for pair in calls:
            self.assertEqual((self.root / variant_path(*pair)).read_bytes(), self.variant(*pair).payload)

    def test_http_failure_writes_no_partial_catalog_or_variants(self):
        fetcher = mock.Mock(side_effect=[self.variant().payload, CabinContextError("unavailable")])
        with self.assertRaisesRegex(CabinContextError, "unavailable"):
            self.http_capture(fetcher)
        self.assert_no_capture()

    def test_http_existing_catalog_rejected_before_fetch(self):
        self.capture()
        fetcher = mock.Mock(side_effect=AssertionError("unexpected provider request"))
        with self.assertRaises(CabinContextConflictError):
            self.http_capture(fetcher)
        fetcher.assert_not_called()


if __name__ == "__main__":
    unittest.main()
