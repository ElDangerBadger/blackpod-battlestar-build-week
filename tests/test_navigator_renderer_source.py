from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_navigator_renderer import RendererSourceError, check_renderer


class NavigatorRendererSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.local = self.root / "build-week"
        self.upstream = self.root / "battlestar"
        self.destination = self.local / "ui/renderer/Ocean.tsx"
        self.source = self.upstream / "navigator/src/scene/Ocean2.tsx"
        self.destination.parent.mkdir(parents=True)
        self.source.parent.mkdir(parents=True)
        self.destination.write_bytes(b"export const ocean = 'adapted';\n")
        self.source.write_bytes(b"export const ocean = 'canonical';\n")
        (self.destination.parent / "Adapter.tsx").write_text("adapter", encoding="utf-8")
        self.pinned = self.source.read_bytes()
        self.manifest = {
            "schema_version": 1,
            "canonical_revision": "a" * 40,
            "source_root": "navigator/src",
            "renderer_root": "ui/renderer",
            "consumer_files": ["Adapter.tsx"],
            "files": [{
                "source": "scene/Ocean2.tsx",
                "destination": "Ocean.tsx",
                "source_sha256": hashlib.sha256(self.pinned).hexdigest(),
                "destination_sha256": hashlib.sha256(self.destination.read_bytes()).hexdigest(),
                "adaptation": "Read-only props replace the standalone store",
            }],
        }
        self.manifest_path = self.local / "manifest.json"
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def check(self, *, upstream: bool = False) -> list[str]:
        return check_renderer(self.local, self.manifest_path, self.upstream if upstream else None)

    def test_local_snapshot_needs_no_canonical_checkout_or_git(self) -> None:
        with patch("scripts.check_navigator_renderer.subprocess.run") as git:
            self.assertEqual(self.check(), [])
        git.assert_not_called()

    def test_local_drift_is_reported_without_changing_files_or_manifest(self) -> None:
        self.destination.write_bytes(b"changed")
        original_manifest = self.manifest_path.read_bytes()
        self.assertEqual(self.check(), ["local renderer drift: Ocean.tsx"])
        self.assertEqual(self.destination.read_bytes(), b"changed")
        self.assertEqual(self.manifest_path.read_bytes(), original_manifest)

    def test_missing_renderer_and_consumer_files_are_reported(self) -> None:
        self.destination.unlink()
        (self.destination.parent / "Adapter.tsx").unlink()
        findings = self.check()
        self.assertEqual(len(findings), 2)
        self.assertTrue(all("missing regular file" in finding for finding in findings))

    def test_new_runtime_files_cannot_bypass_the_mapping(self) -> None:
        extra = self.destination.parent / "effects/new.frag"
        extra.parent.mkdir()
        extra.write_text("new shader", encoding="utf-8")
        (self.destination.parent / "Ocean.test.tsx").write_text("test", encoding="utf-8")
        self.assertEqual(self.check(), ["unclassified renderer file: effects/new.frag"])

    def test_consumer_adapters_may_change_without_repinning_canonical_renderer(self) -> None:
        (self.destination.parent / "Adapter.tsx").write_text("new host contract adapter", encoding="utf-8")
        self.assertEqual(self.check(), [])

    def test_rejects_path_traversal_and_absolute_paths(self) -> None:
        original = copy.deepcopy(self.manifest)
        for field in ("source_root", "renderer_root", "source", "destination"):
            for invalid in ("../outside", "/outside", "nested/../../outside", "nested\\outside", "nested//file"):
                with self.subTest(field=field, path=invalid):
                    self.manifest = copy.deepcopy(original)
                    container = self.manifest if field.endswith("root") else self.manifest["files"][0]
                    container[field] = invalid
                    self.write_manifest()
                    with self.assertRaisesRegex(RendererSourceError, "normalized relative path"):
                        self.check()

    def test_symbolic_link_cannot_stand_in_for_a_mapped_file(self) -> None:
        outside = self.root / "outside.tsx"
        outside.write_bytes(self.destination.read_bytes())
        self.destination.unlink()
        self.destination.symlink_to(outside)
        self.assertTrue(any("symbolic link" in finding for finding in self.check()))

    def test_duplicate_mapping_and_consumer_overlap_are_rejected(self) -> None:
        self.manifest["files"].append(copy.deepcopy(self.manifest["files"][0]))
        self.write_manifest()
        with self.assertRaisesRegex(RendererSourceError, "duplicate source"):
            self.check()
        self.manifest["files"].pop()
        self.manifest["consumer_files"].append("Ocean.tsx")
        self.write_manifest()
        with self.assertRaisesRegex(RendererSourceError, "duplicate destination or consumer"):
            self.check()

    def test_unpinned_or_empty_manifests_are_rejected(self) -> None:
        for field, invalid in (("canonical_revision", "HEAD"), ("files", []), ("schema_version", 2)):
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = invalid
                self.write_manifest()
                with self.assertRaises(RendererSourceError):
                    self.check()
                self.manifest[field] = original

    def test_upstream_compares_pinned_and_current_files_without_requiring_head_match(self) -> None:
        with patch("scripts.check_navigator_renderer._pinned_source", return_value=self.pinned) as pinned:
            self.assertEqual(self.check(upstream=True), [])
        pinned.assert_called_once_with(self.upstream.resolve(), "a" * 40, "navigator/src/scene/Ocean2.tsx")

    def test_current_upstream_drift_requires_review_even_when_pinned_source_matches(self) -> None:
        self.source.write_bytes(b"upstream changed")
        with patch("scripts.check_navigator_renderer._pinned_source", return_value=self.pinned):
            self.assertEqual(self.check(upstream=True), ["upstream source drift: scene/Ocean2.tsx"])

    def test_pinned_source_hash_mismatch_is_reported(self) -> None:
        with patch("scripts.check_navigator_renderer._pinned_source", return_value=b"different pinned source"):
            self.assertEqual(self.check(upstream=True), ["manifest disagrees with pinned canonical source: scene/Ocean2.tsx"])

    def test_missing_current_upstream_source_is_reported(self) -> None:
        self.source.unlink()
        with patch("scripts.check_navigator_renderer._pinned_source", return_value=self.pinned):
            self.assertIn("missing regular file", self.check(upstream=True)[0])

    def test_unavailable_pinned_commit_is_reported(self) -> None:
        with patch("scripts.check_navigator_renderer._pinned_source", side_effect=RendererSourceError("cannot read pinned canonical source")):
            self.assertEqual(self.check(upstream=True), ["cannot read pinned canonical source"])


if __name__ == "__main__":
    unittest.main()
