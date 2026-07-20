from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.prepare_cabin_demo import PreparationError, _synchronize_destination


class CabinDemoDestinationTests(unittest.TestCase):
    def test_sync_removes_only_files_absent_from_selected_mission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "approved"
            (destination / "presentation" / "old").mkdir(parents=True)
            kept = destination / "presentation" / "mission_summary.json"
            kept.write_text("canonical", encoding="utf-8")
            (destination / "presentation" / "portfolio_snapshot.json").write_text(
                "stale", encoding="utf-8"
            )
            (destination / "presentation" / "old" / "evidence.json").write_text(
                "stale", encoding="utf-8"
            )

            removed = _synchronize_destination(
                destination,
                {Path("presentation/mission_summary.json")},
            )

            self.assertEqual(removed, 2)
            self.assertEqual(kept.read_text(encoding="utf-8"), "canonical")
            self.assertFalse((destination / "presentation" / "portfolio_snapshot.json").exists())
            self.assertFalse((destination / "presentation" / "old").exists())

    def test_sync_rejects_symbolic_links_in_public_demo_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "live"
            destination.mkdir()
            target = base / "outside.json"
            target.write_text("outside", encoding="utf-8")
            (destination / "evidence.json").symlink_to(target)

            with self.assertRaisesRegex(PreparationError, "symbolic link"):
                _synchronize_destination(destination, set())

            self.assertEqual(target.read_text(encoding="utf-8"), "outside")


if __name__ == "__main__":
    unittest.main()
