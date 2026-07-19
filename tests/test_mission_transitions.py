from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import (
    ArtifactReference,
    ComponentProvenance,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    OracleTransportKind,
    RunMode,
    StageError,
    StageStatus,
)
from blackpod_build_week.mission_store import ImmutableArtifactError, MissionStore
from blackpod_build_week.mission_transitions import (
    MissionTransitionError,
    begin_oracle,
    complete_oracle,
    fail_oracle,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"


def request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-transition-001",
            "mission_id": "mission-transition-001",
            "run_mode": "REPLAY",
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-transition",
            "metadata": {},
        }
    )


def provenance() -> ComponentProvenance:
    return ComponentProvenance.from_mapping(
        {
            "git_revision": "a" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "oracle_entry_point": (
                "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
            ),
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "fixture-transition-v1",
            "replay_fixture_sha256": "b" * 64,
        }
    )


def artifact(name: str, path: str, payload: bytes) -> ArtifactReference:
    from blackpod_build_week.hashing import sha256_bytes

    return ArtifactReference.from_mapping(
        {
            "name": name,
            "path": path,
            "sha256": sha256_bytes(payload),
            "producer": "oracle" if path.startswith("oracle/attempt") else "harbormaster",
            "byte_size": len(payload),
            "schema_version": None,
            "observed_at": OBSERVED_AT,
        }
    )


class OracleTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        mission_request = request()
        self.initialized = self.store.initialize(
            mission_request,
            mission_id=mission_request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        self.fleet_payload = b"fleet: deterministic\n"
        self.fixture_payload = b'{"fixture":"deterministic"}\n'
        self.fleet = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracles_vapors.example.yaml",
            payload=self.fleet_payload,
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=OBSERVED_AT,
        )
        self.fixture = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracle_replay_input.json",
            payload=self.fixture_payload,
            name="oracle_replay_input",
            producer="harbormaster",
            schema_version="blackpod.oracle_replay_input.v1",
            observed_at=OBSERVED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def running_snapshot(self):
        return begin_oracle(
            self.initialized.snapshot,
            previous_snapshot_sha256=self.initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=provenance(),
            input_artifacts=(self.fleet, self.fixture),
        )

    def test_begin_writes_running_revision_and_preserves_all_stages(self) -> None:
        running = self.running_snapshot()
        digest = self.store.commit_snapshot(self.initialized.paths, running)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(running.revision, 2)
        self.assertEqual(running.previous_snapshot_sha256, self.initialized.snapshot_sha256)
        self.assertEqual(loaded.current_snapshot_sha256, digest)
        self.assertEqual(loaded.snapshot.stages["oracle"].status, StageStatus.RUNNING)
        self.assertEqual(set(loaded.snapshot.stages), {
            "harbormaster", "oracle", "council", "governor", "navigator"
        })
        for name in ("council", "governor", "navigator"):
            self.assertEqual(loaded.snapshot.stages[name].status, StageStatus.NOT_STARTED)

    def test_success_chains_hash_and_advances_only_to_council(self) -> None:
        running = self.running_snapshot()
        running_digest = self.store.commit_snapshot(self.initialized.paths, running)
        payload = b'{"diagnostics_state":"DEGRADED"}\n'
        path = "oracle/attempt-0001/oracle_report_live.json"
        target = self.initialized.paths.mission_root / path
        target.parent.mkdir(parents=True)
        target.write_bytes(payload)
        output = artifact("oracle_report", path, payload)

        complete = complete_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            native_state="DEGRADED",
            output_artifacts=(output,),
        )
        self.store.commit_snapshot(self.initialized.paths, complete)

        self.assertEqual(complete.stages["oracle"].status, StageStatus.SUCCEEDED)
        self.assertEqual(complete.stages["oracle"].native_state, "DEGRADED")
        self.assertEqual(complete.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(complete.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(complete.terminal)
        for name in ("council", "governor", "navigator"):
            self.assertEqual(complete.stages[name].status, StageStatus.NOT_STARTED)

    def test_technical_failure_is_distinct_from_native_state(self) -> None:
        running = self.running_snapshot()
        running_digest = self.store.commit_snapshot(self.initialized.paths, running)
        error = StageError.from_mapping(
            {
                "code": "ORACLE_TIMEOUT",
                "error_type": "DeadlineExceeded",
                "message": "Oracle deadline exceeded",
                "resumable": True,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=error,
        )

        self.assertEqual(failed.stages["oracle"].status, StageStatus.FAILED)
        self.assertIsNone(failed.stages["oracle"].native_state)
        self.assertEqual(failed.current_phase, CurrentPhase.ORACLE)
        self.assertEqual(failed.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(failed.terminal)

    def test_non_resumable_failure_is_terminal(self) -> None:
        running = self.running_snapshot()
        error = StageError.from_mapping(
            {
                "code": "ORACLE_MALFORMED_RESULT",
                "error_type": "ContractValidationError",
                "message": "Oracle returned malformed output",
                "resumable": False,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_oracle(
            running,
            previous_snapshot_sha256="c" * 64,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=error,
        )
        self.assertTrue(failed.terminal)

    def test_duplicate_oracle_start_and_revision_overwrite_are_rejected(self) -> None:
        running = self.running_snapshot()
        self.store.commit_snapshot(self.initialized.paths, running)

        with self.assertRaises(MissionTransitionError):
            begin_oracle(
                running,
                previous_snapshot_sha256="d" * 64,
                observed_at=OBSERVED_AT,
                provenance=provenance(),
                input_artifacts=(self.fleet,),
            )
        with self.assertRaises(ImmutableArtifactError):
            self.store.commit_snapshot(self.initialized.paths, running)


if __name__ == "__main__":
    unittest.main()
