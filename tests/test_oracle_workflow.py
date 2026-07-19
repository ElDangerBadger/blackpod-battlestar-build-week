from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.battlestar_config import (
    BattlestarConfig,
    BattlestarConfigurationError,
)
from blackpod_build_week.contracts import (
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    OracleTransportKind,
    StageStatus,
)
from blackpod_build_week.hashing import sha256_bytes, sha256_file
from blackpod_build_week.mission_store import ImmutableArtifactError, MissionStore
from blackpod_build_week.oracle_adapter import (
    EXPECTED_ORACLE_OUTPUT_FILENAMES,
    OracleExecutionResult,
    OracleFailure,
)
from blackpod_build_week.oracle_workflow import (
    ORACLE_ATTEMPT_DIRECTORY,
    ORACLE_FLEET_INPUT_PATH,
    OracleAction,
    OracleInvocationError,
    OracleRunSettings,
    OracleStateConflictError,
    run_oracle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_FIXTURE = PROJECT_ROOT / "fixtures/oracle_replay_quotes.v1.json"
OBSERVED_AT = "2026-07-18T18:05:00Z"


def replay_request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-workflow-001",
            "mission_id": "mission-workflow-001",
            "run_mode": "REPLAY",
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-workflow",
            "metadata": {},
        }
    )


class SuccessfulAdapter:
    def __init__(self, *, native_state: str = "READY") -> None:
        self.calls = 0
        self.native_state = native_state
        self.received_replay = False

    def execute(self, request, context, *, replay_input=None):
        self.calls += 1
        self.received_replay = replay_input is not None
        for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES:
            payload = json.dumps(
                {"artifact": filename, "diagnostics_state": self.native_state},
                sort_keys=True,
            ).encode("utf-8") + b"\n"
            (context.output_absolute / filename).write_bytes(payload)
        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=OracleTransportKind.REPLAY_FIXTURE,
            status=StageStatus.SUCCEEDED,
            native_state=self.native_state,
            produced_paths=tuple(
                f"{context.output_dir}/{name}"
                for name in EXPECTED_ORACLE_OUTPUT_FILENAMES
            ),
            failure=None,
            run_id="oracle-run-test",
            fleet_id="fleet-oracles-vapors-example",
            readiness_state="READY",
            downstream_ready=True,
            headline="fixture",
            blocker_count=0,
            warning_count=2,
        )


class FailedAdapter:
    def __init__(self, *, resumable: bool = True) -> None:
        self.calls = 0
        self.resumable = resumable

    def execute(self, request, context, *, replay_input=None):
        self.calls += 1
        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=OracleTransportKind.REPLAY_FIXTURE,
            status=StageStatus.FAILED,
            native_state=None,
            produced_paths=(),
            failure=OracleFailure(
                code="ORACLE_EXECUTION_FAILED",
                error_type="FixtureFailure",
                message="deterministic technical failure",
                resumable=self.resumable,
            ),
        )


class InterruptedAdapter:
    def execute(self, request, context, *, replay_input=None):
        raise KeyboardInterrupt("simulated process interruption")


class OracleWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.artifacts_root = self.base / "artifacts"
        self.store = MissionStore(self.artifacts_root)
        request = replay_request()
        self.initialized = self.store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        battlestar_root = self.base / "battlestar"
        module_path = battlestar_root / "blackpod/runtime/oracle_pipeline.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("# fake read-only Oracle module\n", encoding="utf-8")
        fleet_path = battlestar_root / "configs/universes/oracles_vapors.example.yaml"
        fleet_path.parent.mkdir(parents=True)
        fleet_path.write_bytes(b"fleet_id: fleet-oracles-vapors-example\n")
        self.config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=module_path.resolve(),
            fleet_path=fleet_path.resolve(),
            git_revision="a" * 40,
            git_branch="fixture-branch",
            dirty_worktree=True,
        )
        self.settings = OracleRunSettings(
            mission_id="mission-workflow-001",
            artifacts_root=self.artifacts_root,
            replay_fixture=REPLAY_FIXTURE,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def config_loader(self, **kwargs):
        return self.config

    def execute_workflow(self, adapter):
        return run_oracle(
            self.settings,
            adapter=adapter,
            config_loader=self.config_loader,
        )

    def test_success_writes_running_and_success_revisions(self) -> None:
        adapter = SuccessfulAdapter(native_state="DEGRADED")
        result = self.execute_workflow(adapter)
        oracle = result.snapshot.stages["oracle"]

        self.assertEqual(result.action, OracleAction.EXECUTED)
        self.assertEqual(adapter.calls, 1)
        self.assertTrue(adapter.received_replay)
        self.assertEqual(result.snapshot.revision, 3)
        self.assertEqual(oracle.status, StageStatus.SUCCEEDED)
        self.assertEqual(oracle.native_state, "DEGRADED")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(result.snapshot.terminal)
        for name in ("council", "governor", "navigator"):
            self.assertEqual(result.snapshot.stages[name].status, StageStatus.NOT_STARTED)

        revisions = result.paths.snapshots_dir
        running = json.loads((revisions / "mission_snapshot-r0002.json").read_text())
        success = json.loads((revisions / "mission_snapshot-r0003.json").read_text())
        self.assertEqual(running["stages"]["oracle"]["status"], "RUNNING")
        self.assertEqual(success["stages"]["oracle"]["status"], "SUCCEEDED")
        self.assertEqual(
            running["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0001.json"),
        )
        self.assertEqual(
            success["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0002.json"),
        )

    def test_artifact_hashes_sizes_containment_and_no_absolute_source_leak(self) -> None:
        result = self.execute_workflow(SuccessfulAdapter())
        root = result.paths.mission_root
        for artifact in result.snapshot.artifacts:
            target = root / artifact.path
            self.assertTrue(target.resolve().is_relative_to(root))
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        snapshots = "".join(
            path.read_text(encoding="utf-8")
            for path in sorted(result.paths.snapshots_dir.glob("*.json"))
        )
        self.assertNotIn(str(self.config.root), snapshots)
        self.assertNotIn(str(REPLAY_FIXTURE.resolve()), snapshots)

    def test_repeated_identical_success_is_a_validated_no_op(self) -> None:
        adapter = SuccessfulAdapter()
        first = self.execute_workflow(adapter)
        original_revision = (
            first.paths.snapshots_dir / "mission_snapshot-r0003.json"
        ).read_bytes()
        second = self.execute_workflow(adapter)

        self.assertEqual(second.action, OracleAction.NO_OP_ALREADY_SUCCEEDED)
        self.assertEqual(second.snapshot.revision, 3)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            first.paths.snapshots_dir.joinpath("mission_snapshot-r0003.json").read_bytes(),
            original_revision,
        )
        self.assertFalse(
            first.paths.snapshots_dir.joinpath("mission_snapshot-r0004.json").exists()
        )

    def test_technical_failure_commits_failed_revision_and_repeat_conflicts(self) -> None:
        result = self.execute_workflow(FailedAdapter(resumable=True))
        oracle = result.snapshot.stages["oracle"]

        self.assertEqual(oracle.status, StageStatus.FAILED)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.ORACLE)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(result.snapshot.terminal)
        self.assertIsNotNone(oracle.error)
        with self.assertRaisesRegex(OracleStateConflictError, "previously FAILED"):
            self.execute_workflow(FailedAdapter())

    def test_nonresumable_failure_is_terminal(self) -> None:
        result = self.execute_workflow(FailedAdapter(resumable=False))
        self.assertTrue(result.snapshot.terminal)

    def test_interrupted_running_attempt_conflicts_on_restart(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            self.execute_workflow(InterruptedAdapter())
        loaded = self.store.load_mission("mission-workflow-001")
        self.assertEqual(loaded.snapshot.stages["oracle"].status, StageStatus.RUNNING)

        with self.assertRaisesRegex(OracleStateConflictError, "already RUNNING"):
            self.execute_workflow(SuccessfulAdapter())

    def test_existing_immutable_input_is_not_overwritten(self) -> None:
        original = b"do-not-overwrite\n"
        target = self.initialized.paths.mission_root / ORACLE_FLEET_INPUT_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(original)

        with self.assertRaises(ImmutableArtifactError):
            self.execute_workflow(SuccessfulAdapter())
        self.assertEqual(target.read_bytes(), original)

    def test_live_and_replay_arguments_are_never_substituted(self) -> None:
        live = MissionRequest.from_mapping(
            {
                "schema_version": "blackpod.mission_request.v1",
                "request_id": "request-live-workflow",
                "mission_id": "mission-live-workflow",
                "run_mode": "LIVE",
                "symbol": "AAPL",
                "requested_at": OBSERVED_AT,
                "operator_id": "operator-workflow",
                "metadata": {},
            }
        )
        live_store = MissionStore(self.base / "live-artifacts")
        live_store.initialize(
            live,
            mission_id=live.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        with self.assertRaisesRegex(OracleInvocationError, "LIVE missions"):
            run_oracle(
                OracleRunSettings(
                    mission_id=live.mission_id or "",
                    artifacts_root=self.base / "live-artifacts",
                    replay_fixture=REPLAY_FIXTURE,
                ),
                adapter=SuccessfulAdapter(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(OracleInvocationError, "require --replay-fixture"):
            run_oracle(
                OracleRunSettings(
                    mission_id="mission-workflow-001",
                    artifacts_root=self.artifacts_root,
                ),
                adapter=SuccessfulAdapter(),
                config_loader=self.config_loader,
            )

    def test_preflight_failure_occurs_before_artifact_root_is_touched(self) -> None:
        untouched_root = self.base / "must-remain-absent"

        def rejected_config(**kwargs):
            raise BattlestarConfigurationError("unsafe Battlestar path")

        with self.assertRaises(BattlestarConfigurationError):
            run_oracle(
                OracleRunSettings(
                    mission_id="mission-not-inspected",
                    artifacts_root=untouched_root,
                    replay_fixture=REPLAY_FIXTURE,
                ),
                adapter=SuccessfulAdapter(),
                config_loader=rejected_config,
            )
        self.assertFalse(untouched_root.exists())

    def test_changed_fixture_is_not_identical_completed_invocation(self) -> None:
        self.execute_workflow(SuccessfulAdapter())
        changed_fixture = self.base / "changed-fixture.json"
        changed_fixture.write_bytes(REPLAY_FIXTURE.read_bytes().replace(b"1000000", b"999999", 1))
        changed_settings = OracleRunSettings(
            mission_id=self.settings.mission_id,
            artifacts_root=self.artifacts_root,
            replay_fixture=changed_fixture,
        )
        with self.assertRaisesRegex(OracleStateConflictError, "does not match"):
            run_oracle(
                changed_settings,
                adapter=SuccessfulAdapter(),
                config_loader=self.config_loader,
            )

    def test_output_hash_is_sha256_of_exact_native_bytes(self) -> None:
        result = self.execute_workflow(SuccessfulAdapter())
        report = next(
            item for item in result.snapshot.artifacts if item.name == "oracle_report"
        )
        self.assertEqual(
            report.sha256,
            sha256_bytes((result.paths.mission_root / report.path).read_bytes()),
        )


if __name__ == "__main__":
    unittest.main()
