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
from blackpod_build_week.council_workflow import CouncilAction
from blackpod_build_week.harbormaster import (
    EXIT_COUNCIL_FAILURE,
    EXIT_SUCCESS,
    main,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"


class CouncilCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.current_snapshot = self.base / "mission_snapshot.json"
        self.current_snapshot.write_text("{}\n", encoding="utf-8")
        self.council_directory = self.base / "council/attempt-0001"
        self.council_directory.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def result(
        self,
        *,
        status: StageStatus,
        action: CouncilAction = CouncilAction.EXECUTED,
        resumable: bool = True,
    ):
        error = None
        native_state = "CONFLICTED"
        phase = CurrentPhase.GOVERNOR
        outcome = MissionOutcome.INCOMPLETE
        terminal = False
        if status is StageStatus.FAILED:
            native_state = None
            phase = CurrentPhase.COUNCIL
            outcome = MissionOutcome.FAILED
            terminal = not resumable
            error = StageError.from_mapping(
                {
                    "code": "COUNCIL_EXECUTION_FAILED",
                    "error_type": "FixtureFailure",
                    "message": "deterministic technical failure",
                    "resumable": resumable,
                    "observed_at": OBSERVED_AT,
                }
            )
        snapshot = SimpleNamespace(
            mission_id="mission-cli-council-001",
            run_mode=RunMode.REPLAY,
            current_phase=phase,
            mission_outcome=outcome,
            terminal=terminal,
            stages={
                "council": StageSnapshot(
                    status=status,
                    native_state=native_state,
                    error=error,
                )
            },
            components={
                "battlestar_council": SimpleNamespace(
                    git_revision="b" * 40,
                    git_branch="main",
                    dirty_worktree=True,
                )
            },
        )
        return SimpleNamespace(
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            council_artifact_directory=self.council_directory,
            action=action,
        )

    def invoke(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "run-council",
                    "--mission-id",
                    "mission-cli-council-001",
                    "--artifacts-root",
                    str(self.base),
                    "--replay-fixture",
                    "fixtures/council_replay_policy.v1.json",
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_successful_replay_council_exits_zero_and_prints_contract(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_council",
            return_value=self.result(status=StageStatus.SUCCEEDED),
        ) as runner:
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("mission_id=mission-cli-council-001\n", stdout)
        self.assertIn("run_mode=REPLAY\n", stdout)
        self.assertIn("council_status=SUCCEEDED\n", stdout)
        self.assertIn("council_native_state=CONFLICTED\n", stdout)
        self.assertIn("current_phase=GOVERNOR\n", stdout)
        self.assertIn("mission_outcome=INCOMPLETE\n", stdout)
        self.assertIn("council_artifact_directory=", stdout)
        self.assertIn("battlestar_dirty=true\n", stdout)
        settings = runner.call_args.args[0]
        self.assertEqual(settings.mission_id, "mission-cli-council-001")
        self.assertEqual(
            settings.replay_fixture,
            Path("fixtures/council_replay_policy.v1.json"),
        )
        self.assertIsNone(settings.policy_input)

    def test_failed_council_exits_nonzero_and_prints_failed_snapshot(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_council",
            return_value=self.result(status=StageStatus.FAILED),
        ):
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_COUNCIL_FAILURE)
        self.assertIn("council_status=FAILED\n", stdout)
        self.assertIn("current_phase=COUNCIL\n", stdout)
        self.assertIn("mission_outcome=FAILED\n", stdout)
        self.assertIn("COUNCIL_EXECUTION_FAILED", stderr)

    def test_repeated_completed_invocation_reports_no_op_and_exits_zero(self) -> None:
        no_op = self.result(
            status=StageStatus.SUCCEEDED,
            action=CouncilAction.NO_OP_ALREADY_SUCCEEDED,
        )
        with mock.patch(
            "blackpod_build_week.harbormaster.run_council",
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
        self.assertIn("council_action=NO_OP_ALREADY_SUCCEEDED\n", stdout)


if __name__ == "__main__":
    unittest.main()
