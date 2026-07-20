from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from blackpod_build_week.contracts import (
    CAPTAINS_LOG_SCHEMA_VERSION,
    MISSION_SUMMARY_ARTIFACT_LINKS,
    MISSION_SUMMARY_SCHEMA_VERSION,
    PRESENTATION_COMPONENT_STAGES,
    CaptainsLog,
    ComponentProvenance,
    ContractValidationError,
    MissionRequest,
    MissionSummary,
    StageError,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_presentation import (
    MissionPresentationError,
    render_mission_presentation,
)
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.mission_transitions import begin_oracle, fail_oracle


OBSERVED_AT = "2026-07-18T20:00:00Z"


def mission_request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-presentation-001",
            "mission_id": "mission-presentation-001",
            "run_mode": "REPLAY",
            "symbol": "NVDA",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-presentation",
            "metadata": {},
        }
    )


class MissionPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        request = mission_request()
        self.initialized = self.store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_phase1_projection_is_strict_deterministic_and_mission_relative(self) -> None:
        loaded = self.store.load_mission(self.initialized.snapshot.mission_id)
        original_snapshots = tuple(loaded.paths.snapshots_dir.iterdir())

        result = render_mission_presentation(self.store, loaded)

        self.assertEqual(result.captain_log.schema_version, CAPTAINS_LOG_SCHEMA_VERSION)
        self.assertEqual(
            result.mission_summary.schema_version, MISSION_SUMMARY_SCHEMA_VERSION
        )
        self.assertEqual(result.mission_summary.final_outcome.value, "INCOMPLETE")
        self.assertEqual(result.mission_summary.snapshot_count, 1)
        self.assertEqual(
            result.mission_summary.canonical_snapshot_path,
            "mission_snapshot.json",
        )
        self.assertEqual(result.mission_summary.modeldock.status, "NOT_RECORDED")
        self.assertEqual(
            result.mission_summary.display_title, "BlackPod Mission: NVDA"
        )
        self.assertEqual(
            result.mission_summary.subtitle, "REPLAY | INCOMPLETE | ORACLE"
        )
        self.assertEqual(
            tuple(stage.stage for stage in result.mission_summary.ordered_stages),
            PRESENTATION_COMPONENT_STAGES,
        )
        self.assertEqual(
            tuple(
                stage.display_state
                for stage in result.mission_summary.ordered_stages
            ),
            (
                "SUCCEEDED",
                "NOT_STARTED",
                "NOT_RECORDED",
                "NOT_STARTED",
                "NOT_STARTED",
                "NOT_STARTED",
                "NOT_STARTED",
            ),
        )
        self.assertTrue(result.mission_summary.resumable)
        self.assertEqual(result.mission_summary.event_count, 8)
        self.assertEqual(
            result.mission_summary.artifact_links,
            MISSION_SUMMARY_ARTIFACT_LINKS,
        )
        self.assertEqual(
            tuple(entry.stage for entry in result.captain_log.entries),
            (
                "HARBORMASTER",
                "ORACLE",
                "MODELDOCK",
                "COUNCIL",
                "GOVERNOR",
                "OPERATOR",
                "NAVIGATOR",
                "MISSION",
            ),
        )
        self.assertEqual(
            [entry.status for entry in result.captain_log.entries],
            [
                "SUCCEEDED",
                "NOT_STARTED",
                "NOT_RECORDED",
                "NOT_STARTED",
                "NOT_STARTED",
                "NOT_STARTED",
                "NOT_STARTED",
                "INCOMPLETE",
            ],
        )
        for path in (
            result.captains_log_json_path,
            result.captains_log_markdown_path,
            result.mission_summary_path,
        ):
            self.assertTrue(path.resolve().is_relative_to(loaded.paths.mission_root))
        self.assertEqual(
            result.captains_log_json_path.read_bytes(),
            canonical_json_bytes(result.captain_log.to_dict()),
        )
        self.assertEqual(
            result.mission_summary_path.read_bytes(),
            canonical_json_bytes(result.mission_summary.to_dict()),
        )
        self.assertEqual(
            CaptainsLog.from_mapping(
                json.loads(result.captains_log_json_path.read_text(encoding="utf-8"))
            ),
            result.captain_log,
        )
        self.assertEqual(
            MissionSummary.from_mapping(
                json.loads(result.mission_summary_path.read_text(encoding="utf-8"))
            ),
            result.mission_summary,
        )
        markdown = result.captains_log_markdown_path.read_text(encoding="utf-8")
        self.assertIn("# Captain's Log: mission-presentation-001", markdown)
        self.assertNotIn(str(self.base), markdown)
        self.assertEqual(tuple(loaded.paths.snapshots_dir.iterdir()), original_snapshots)

        for entry in result.captain_log.entries:
            self.assertTrue(entry.source_artifacts)
            for source in entry.source_artifacts:
                self.assertFalse(Path(source.path).is_absolute())
                source_path = loaded.paths.mission_root.joinpath(
                    *source.path.split("/")
                )
                self.assertEqual(sha256_file(source_path), source.sha256)
                self.assertEqual(source_path.stat().st_size, source.byte_size)
        for stage in result.mission_summary.ordered_stages:
            self.assertTrue(stage.artifact_paths)
            for artifact_path in stage.artifact_paths:
                self.assertFalse(Path(artifact_path).is_absolute())

    def test_identical_render_is_an_explicit_three_file_no_op(self) -> None:
        first = render_mission_presentation(
            self.store, self.store.load_mission(self.initialized.snapshot.mission_id)
        )
        paths = (
            first.captains_log_json_path,
            first.captains_log_markdown_path,
            first.mission_summary_path,
        )
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

        second = render_mission_presentation(
            self.store, self.store.load_mission(self.initialized.snapshot.mission_id)
        )

        self.assertFalse(second.captains_log_json_written)
        self.assertFalse(second.captains_log_markdown_written)
        self.assertFalse(second.mission_summary_written)
        self.assertEqual(
            {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths},
            before,
        )

    def test_failed_stage_uses_only_structured_canonical_failure(self) -> None:
        mission_id = self.initialized.snapshot.mission_id
        oracle_input = self.store.write_immutable_artifact(
            mission_id,
            relative_path="oracle/inputs/replay.json",
            payload=b"{}\n",
            name="oracle_replay_input",
            producer="harbormaster",
            schema_version="blackpod.oracle_replay_input.v1",
            observed_at=OBSERVED_AT,
        )
        provenance = ComponentProvenance.from_mapping(
            {
                "git_revision": "a" * 40,
                "git_branch": "fixture",
                "dirty_worktree": False,
                "oracle_entry_point": "blackpod.oracle.fixture",
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": "fixture-oracle-presentation",
                "replay_fixture_sha256": "b" * 64,
            }
        )
        running = begin_oracle(
            self.initialized.snapshot,
            previous_snapshot_sha256=self.initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=provenance,
            input_artifacts=(oracle_input,),
        )
        running_sha = self.store.commit_snapshot(self.initialized.paths, running)
        failed = fail_oracle(
            running,
            previous_snapshot_sha256=running_sha,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=StageError.from_mapping(
                {
                    "code": "ORACLE_CONTROLLED_FAILURE",
                    "error_type": "FixtureFailure",
                    "message": "sanitized fixture failure",
                    "resumable": False,
                    "observed_at": OBSERVED_AT,
                }
            ),
        )
        self.store.commit_snapshot(self.initialized.paths, failed)

        result = render_mission_presentation(
            self.store, self.store.load_mission(mission_id)
        )

        self.assertEqual(result.mission_summary.final_outcome.value, "FAILED")
        self.assertEqual(result.mission_summary.snapshot_count, 3)
        self.assertEqual(
            result.mission_summary.important_warnings,
            ("ORACLE: ORACLE_CONTROLLED_FAILURE",),
        )
        oracle_entry = result.captain_log.entries[1]
        self.assertEqual(oracle_entry.status, "FAILED")
        self.assertIn("ORACLE_CONTROLLED_FAILURE", oracle_entry.summary)
        self.assertNotIn("sanitized fixture failure", oracle_entry.summary)

    def test_contracts_reject_unknown_fields_and_incomplete_loaded_history(self) -> None:
        result = render_mission_presentation(
            self.store, self.store.load_mission(self.initialized.snapshot.mission_id)
        )
        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["invented"] = True
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["schema_version"] = "blackpod.mission_summary.v1"
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["ordered_stages"][0]["artifact_paths"] = [
            "/tmp/local-artifact.json"
        ]
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["ordered_stages"] = list(
            reversed(malformed_summary["ordered_stages"])
        )
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["resumable"] = False
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_summary = result.mission_summary.to_dict()
        malformed_summary["artifact_links"]["mission_summary"] = (
            "presentation/other.json"
        )
        with self.assertRaises(ContractValidationError):
            MissionSummary.from_mapping(malformed_summary)

        malformed_log = result.captain_log.to_dict()
        malformed_log["entries"][0]["status"] = "free form"
        with self.assertRaises(ContractValidationError):
            CaptainsLog.from_mapping(malformed_log)

        incomplete = replace(
            self.store.load_mission(self.initialized.snapshot.mission_id),
            snapshot_history=(),
        )
        with self.assertRaises(MissionPresentationError):
            render_mission_presentation(self.store, incomplete)


if __name__ == "__main__":
    unittest.main()
