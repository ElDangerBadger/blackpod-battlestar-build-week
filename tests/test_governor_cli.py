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
from blackpod_build_week.governor_workflow import GovernorAction
from blackpod_build_week.harbormaster import (
    EXIT_GOVERNOR_FAILURE,
    EXIT_SUCCESS,
    main,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"


class GovernorCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.current_snapshot = self.base / "mission_snapshot.json"
        self.current_snapshot.write_text("{}\n", encoding="utf-8")
        self.governor_directory = self.base / "governor/attempt-0001"
        self.governor_directory.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def result(
        self,
        disposition: str = "PROCEED",
        *,
        failed: bool = False,
        action: GovernorAction = GovernorAction.EXECUTED,
    ):
        mappings = {
            "PROCEED": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                "READY",
                "OPERATOR_REVIEW",
            ),
            "HOLD": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                "READY",
                "OPERATOR_REVIEW",
            ),
            "REVIEW_REQUIRED": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                "REVIEW_REQUIRED",
                "OPERATOR_REVIEW",
            ),
            "BLOCKED": (
                CurrentPhase.GOVERNOR,
                MissionOutcome.HELD,
                "BLOCKED",
                "NONE",
            ),
            "STAND_DOWN": (
                CurrentPhase.COMPLETE,
                MissionOutcome.VETOED,
                "INVALID",
                "NONE",
            ),
        }
        phase, outcome, readiness, next_step = mappings[disposition]
        error = None
        status = StageStatus.SUCCEEDED
        native_state: str | None = disposition
        if failed:
            status = StageStatus.FAILED
            native_state = None
            phase = CurrentPhase.GOVERNOR
            outcome = MissionOutcome.FAILED
            readiness = None
            next_step = None
            error = StageError.from_mapping(
                {
                    "code": "GOVERNOR_EXECUTION_FAILED",
                    "error_type": "FixtureFailure",
                    "message": "deterministic technical failure",
                    "resumable": False,
                    "observed_at": OBSERVED_AT,
                }
            )
        snapshot = SimpleNamespace(
            mission_id="mission-cli-governor-001",
            run_mode=RunMode.REPLAY,
            current_phase=phase,
            mission_outcome=outcome,
            stages={
                "governor": StageSnapshot(
                    status=status,
                    native_state=native_state,
                    error=error,
                )
            },
            components={
                "battlestar_governor": SimpleNamespace(
                    git_revision="c" * 40,
                    git_branch="main",
                    dirty_worktree=True,
                )
            },
        )
        return SimpleNamespace(
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            governor_artifact_directory=self.governor_directory,
            action=action,
            readiness_state=readiness,
            allowed_next_step=next_step,
        )

    def invoke(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "run-governor",
                    "--mission-id",
                    "mission-cli-governor-001",
                    "--artifacts-root",
                    str(self.base),
                    "--replay-fixture",
                    "fixtures/governor_replay_context.proceed.v1.json",
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_all_rendered_dispositions_exit_zero(self) -> None:
        for disposition in (
            "PROCEED",
            "HOLD",
            "REVIEW_REQUIRED",
            "BLOCKED",
            "STAND_DOWN",
        ):
            with self.subTest(disposition=disposition), mock.patch(
                "blackpod_build_week.harbormaster.run_governor",
                return_value=self.result(disposition),
            ):
                code, stdout, stderr = self.invoke()
            self.assertEqual(code, EXIT_SUCCESS)
            self.assertEqual(stderr, "")
            self.assertIn("governor_status=SUCCEEDED\n", stdout)
            self.assertIn(f"governor_disposition={disposition}\n", stdout)

    def test_proceed_summary_is_held_and_records_required_fields(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_governor",
            return_value=self.result("PROCEED"),
        ) as runner:
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("mission_id=mission-cli-governor-001\n", stdout)
        self.assertIn("run_mode=REPLAY\n", stdout)
        self.assertIn("governor_readiness_state=READY\n", stdout)
        self.assertIn("allowed_next_step=OPERATOR_REVIEW\n", stdout)
        self.assertIn("current_phase=OPERATOR\n", stdout)
        self.assertIn("mission_outcome=HELD\n", stdout)
        self.assertIn("governor_artifact_directory=", stdout)
        self.assertIn("battlestar_dirty=true\n", stdout)
        settings = runner.call_args.args[0]
        self.assertEqual(settings.mission_id, "mission-cli-governor-001")
        self.assertEqual(
            settings.replay_fixture,
            Path("fixtures/governor_replay_context.proceed.v1.json"),
        )
        self.assertIsNone(settings.context_input)

    def test_technical_failure_exits_nonzero(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_governor",
            return_value=self.result(failed=True),
        ):
            code, stdout, stderr = self.invoke()

        self.assertEqual(code, EXIT_GOVERNOR_FAILURE)
        self.assertIn("governor_status=FAILED\n", stdout)
        self.assertIn("current_phase=GOVERNOR\n", stdout)
        self.assertIn("mission_outcome=FAILED\n", stdout)
        self.assertIn("GOVERNOR_EXECUTION_FAILED", stderr)

    def test_repeated_completed_invocation_reports_no_op(self) -> None:
        no_op = self.result(
            "PROCEED", action=GovernorAction.NO_OP_ALREADY_SUCCEEDED
        )
        with mock.patch(
            "blackpod_build_week.harbormaster.run_governor",
            side_effect=[self.result("PROCEED"), no_op],
        ):
            first_code, _, _ = self.invoke()
            second_code, stdout, stderr = self.invoke()

        self.assertEqual(first_code, EXIT_SUCCESS)
        self.assertEqual(second_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("governor_action=NO_OP_ALREADY_SUCCEEDED\n", stdout)


if __name__ == "__main__":
    unittest.main()
