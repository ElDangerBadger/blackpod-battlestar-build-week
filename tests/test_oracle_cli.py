from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from blackpod_build_week.contracts import (
    CurrentPhase,
    MissionOutcome,
    RunMode,
    StageError,
    StageSnapshot,
    StageStatus,
)
from blackpod_build_week.harbormaster import (
    EXIT_ORACLE_FAILURE,
    EXIT_SUCCESS,
    main,
)
from blackpod_build_week.oracle_workflow import OracleAction


OBSERVED_AT = "2026-07-18T18:05:00Z"


class OracleCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.current_snapshot = self.base / "mission_snapshot.json"
        self.current_snapshot.write_text("{}\n", encoding="utf-8")
        self.oracle_directory = self.base / "oracle/attempt-0001"
        self.oracle_directory.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def result(
        self,
        *,
        status: StageStatus,
        action: OracleAction = OracleAction.EXECUTED,
        resumable: bool = True,
    ):
        error = None
        native_state = "READY"
        phase = CurrentPhase.COUNCIL
        outcome = MissionOutcome.INCOMPLETE
        terminal = False
        if status is StageStatus.FAILED:
            native_state = None
            phase = CurrentPhase.ORACLE
            outcome = MissionOutcome.FAILED
            terminal = not resumable
            error = StageError.from_mapping(
                {
                    "code": "ORACLE_EXECUTION_FAILED",
                    "error_type": "FixtureFailure",
                    "message": "deterministic technical failure",
                    "resumable": resumable,
                    "observed_at": OBSERVED_AT,
                }
            )
        snapshot = SimpleNamespace(
            mission_id="mission-cli-oracle-001",
            run_mode=RunMode.REPLAY,
            current_phase=phase,
            mission_outcome=outcome,
            terminal=terminal,
            stages={
                "oracle": StageSnapshot(
                    status=status,
                    native_state=native_state,
                    error=error,
                )
            },
            components={
                "battlestar": SimpleNamespace(
                    git_revision="a" * 40,
                    git_branch="main",
                    dirty_worktree=True,
                )
            },
        )
        return SimpleNamespace(
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            oracle_artifact_directory=self.oracle_directory,
            action=action,
        )

    def invoke(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "run-oracle",
                    "--mission-id",
                    "mission-cli-oracle-001",
                    "--artifacts-root",
                    str(self.base),
                    "--replay-fixture",
                    "fixtures/oracle_replay_quotes.v1.json",
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_successful_replay_oracle_cli_exits_zero_and_prints_contract(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_oracle",
            return_value=self.result(status=StageStatus.SUCCEEDED),
        ) as runner:
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("mission_id=mission-cli-oracle-001\n", stdout)
        self.assertIn("run_mode=REPLAY\n", stdout)
        self.assertIn("oracle_status=SUCCEEDED\n", stdout)
        self.assertIn("oracle_native_state=READY\n", stdout)
        self.assertIn("current_phase=COUNCIL\n", stdout)
        self.assertIn("mission_outcome=INCOMPLETE\n", stdout)
        self.assertIn("oracle_artifact_directory=", stdout)
        self.assertIn("battlestar_dirty=true\n", stdout)
        settings = runner.call_args.args[0]
        self.assertEqual(settings.mission_id, "mission-cli-oracle-001")
        self.assertEqual(
            settings.replay_fixture,
            Path("fixtures/oracle_replay_quotes.v1.json"),
        )

    def test_failed_oracle_cli_exits_nonzero_and_prints_failed_snapshot(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_oracle",
            return_value=self.result(status=StageStatus.FAILED),
        ):
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_ORACLE_FAILURE)
        self.assertIn("oracle_status=FAILED\n", stdout)
        self.assertIn("current_phase=ORACLE\n", stdout)
        self.assertIn("mission_outcome=FAILED\n", stdout)
        self.assertIn("ORACLE_EXECUTION_FAILED", stderr)

    def test_repeated_completed_invocation_reports_no_op_and_exits_zero(self) -> None:
        no_op = self.result(
            status=StageStatus.SUCCEEDED,
            action=OracleAction.NO_OP_ALREADY_SUCCEEDED,
        )
        with mock.patch(
            "blackpod_build_week.harbormaster.run_oracle",
            side_effect=[
                self.result(status=StageStatus.SUCCEEDED),
                no_op,
            ],
        ):
            first_code, _, _ = self.invoke()
            second_code, stdout, stderr = self.invoke()

        self.assertEqual(first_code, EXIT_SUCCESS)
        self.assertEqual(second_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("oracle_action=NO_OP_ALREADY_SUCCEEDED\n", stdout)


if __name__ == "__main__":
    unittest.main()
