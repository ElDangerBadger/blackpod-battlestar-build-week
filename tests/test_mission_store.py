from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.hashing import sha256_file
from blackpod_build_week.mission_store import (
    DuplicateMissionError,
    ImmutableArtifactError,
    MissionStore,
    PersistenceError,
    UnsafePathError,
    _atomic_write_bytes,
)


def stored_request(mission_id: str = "mission-store-001") -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-store-001",
            "mission_id": mission_id,
            "run_mode": "REPLAY",
            "symbol": "MSFT",
            "requested_at": "2026-07-18T19:00:00Z",
            "operator_id": "operator-store",
            "metadata": {},
        }
    )


class MissionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def initialize(self):
        request = stored_request()
        return self.store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=request.requested_at,
            observed_at=request.requested_at,
        )

    def test_expected_layout_hashes_and_identical_snapshot_bytes(self) -> None:
        result = self.initialize()

        self.assertEqual(
            result.paths.mission_root,
            (self.base / "artifacts/missions/mission-store-001").resolve(),
        )
        self.assertTrue(result.paths.request_path.is_file())
        self.assertTrue(result.paths.revision_snapshot.is_file())
        self.assertTrue(result.paths.current_snapshot.is_file())
        self.assertEqual(
            result.paths.revision_snapshot.read_bytes(),
            result.paths.current_snapshot.read_bytes(),
        )
        self.assertEqual(
            result.snapshot.artifacts[0].sha256,
            sha256_file(result.paths.request_path),
        )
        self.assertEqual(result.snapshot_sha256, sha256_file(result.paths.revision_snapshot))
        for path in (
            result.paths.request_path,
            result.paths.revision_snapshot,
            result.paths.current_snapshot,
        ):
            self.assertTrue(path.resolve().is_relative_to(result.paths.mission_root))

    def test_duplicate_mission_initialization_preserves_original_bytes(self) -> None:
        first = self.initialize()
        original_request = first.paths.request_path.read_bytes()
        original_revision = first.paths.revision_snapshot.read_bytes()
        original_current = first.paths.current_snapshot.read_bytes()

        with self.assertRaises(DuplicateMissionError):
            self.initialize()

        self.assertEqual(first.paths.request_path.read_bytes(), original_request)
        self.assertEqual(first.paths.revision_snapshot.read_bytes(), original_revision)
        self.assertEqual(first.paths.current_snapshot.read_bytes(), original_current)

    def test_immutable_revision_is_never_overwritten(self) -> None:
        result = self.initialize()
        original_digest = sha256_file(result.paths.revision_snapshot)

        with self.assertRaises(ImmutableArtifactError):
            self.store.commit_snapshot(result.paths, result.snapshot)

        self.assertEqual(sha256_file(result.paths.revision_snapshot), original_digest)

    def test_path_containment_rejects_traversal(self) -> None:
        for unsafe_id in ("../outside", "/absolute", "nested/mission", "nested\\mission"):
            with self.subTest(mission_id=unsafe_id):
                with self.assertRaises(UnsafePathError):
                    self.store.mission_root_for(unsafe_id)

    def test_path_containment_rejects_symlinked_missions_root(self) -> None:
        artifacts_root = self.base / "linked-artifacts"
        outside = self.base / "outside"
        artifacts_root.mkdir()
        outside.mkdir()
        (artifacts_root / "missions").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(UnsafePathError, "escapes artifacts root"):
            MissionStore(artifacts_root).mission_root_for("mission-safe")

    def test_commit_rejects_forged_current_snapshot_path(self) -> None:
        result = self.initialize()
        outside = self.base / "outside.json"
        outside.write_bytes(b"outside-must-not-change\n")
        forged_paths = replace(result.paths, current_snapshot=outside)

        with self.assertRaisesRegex(UnsafePathError, "current_snapshot"):
            self.store.commit_snapshot(forged_paths, result.snapshot)

        self.assertEqual(outside.read_bytes(), b"outside-must-not-change\n")

    def test_commit_rejects_artifact_symlink_escape(self) -> None:
        result = self.initialize()
        outside = self.base / "outside-request.json"
        outside.write_bytes(result.paths.request_path.read_bytes())
        result.paths.request_path.unlink()
        result.paths.request_path.symlink_to(outside)

        with self.assertRaisesRegex(UnsafePathError, "escapes mission root"):
            self.store.commit_snapshot(result.paths, result.snapshot)

    def test_atomic_write_preserves_current_snapshot_if_replace_fails(self) -> None:
        destination = self.base / "mission_snapshot.json"
        destination.write_bytes(b"previous-complete-snapshot\n")

        with mock.patch(
            "blackpod_build_week.mission_store.os.replace",
            side_effect=OSError("simulated replace failure"),
        ):
            with self.assertRaises(PersistenceError):
                _atomic_write_bytes(destination, b"next-complete-snapshot\n")

        self.assertEqual(destination.read_bytes(), b"previous-complete-snapshot\n")
        self.assertEqual(list(self.base.glob(".mission_snapshot.json.*.tmp")), [])

    def test_successful_atomic_write_leaves_no_temporary_file(self) -> None:
        destination = self.base / "mission_snapshot.json"
        _atomic_write_bytes(destination, b"complete-snapshot\n")

        self.assertEqual(destination.read_bytes(), b"complete-snapshot\n")
        self.assertEqual(list(self.base.glob(".mission_snapshot.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
