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
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    RunMode,
    StageError,
    StageSnapshot,
    StageStatus,
)
from blackpod_build_week.harbormaster import (
    EXIT_NAVIGATOR_FAILURE,
    EXIT_OPERATOR_FAILURE,
    EXIT_SUCCESS,
    main,
)
from blackpod_build_week.navigator_workflow import NavigatorPreconditionError
from blackpod_build_week.operator_workflow import OperatorPreconditionError


OBSERVED_AT = "2026-07-18T18:07:00Z"


class Phase5CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.current_snapshot = self.base / "mission_snapshot.json"
        self.current_snapshot.write_text("{}\n", encoding="utf-8")
        self.operator_directory = self.base / "operator/attempt-0001"
        self.navigator_directory = self.base / "navigator/attempt-0001"
        self.operator_directory.mkdir(parents=True)
        self.navigator_directory.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def operator_result(self, action: OperatorAction = OperatorAction.APPROVE_HANDOFF):
        approved = action is OperatorAction.APPROVE_HANDOFF
        result = (
            OperatorResult.APPROVED_FOR_HANDOFF
            if approved
            else OperatorResult.REJECTED
        )
        snapshot = SimpleNamespace(
            mission_id="mission-buildweek-replay-001",
            current_phase=(CurrentPhase.NAVIGATOR if approved else CurrentPhase.COMPLETE),
            mission_outcome=(MissionOutcome.HELD if approved else MissionOutcome.VETOED),
        )
        return SimpleNamespace(
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            disposition=SimpleNamespace(value="EXECUTED"),
            operator_artifact_directory=self.operator_directory,
            technical_status=OperatorActionStatus.SUCCEEDED,
            action=action,
            result=result,
            action_id="operator-action-1234567890abcdef",
            operator_id="demo-operator",
            acted_at=OBSERVED_AT,
        )

    def navigator_result(self, *, failed: bool = False):
        error = None
        status = StageStatus.SUCCEEDED
        phase = CurrentPhase.COMPLETE
        outcome = MissionOutcome.APPROVED
        if failed:
            status = StageStatus.FAILED
            phase = CurrentPhase.NAVIGATOR
            outcome = MissionOutcome.FAILED
            error = StageError.from_mapping(
                {
                    "code": "NAVIGATOR_INTAKE_REJECTED",
                    "error_type": "NavigatorIntakeError",
                    "message": "controlled intake rejection",
                    "resumable": False,
                    "observed_at": OBSERVED_AT,
                }
            )
        snapshot = SimpleNamespace(
            mission_id="mission-buildweek-replay-001",
            current_phase=phase,
            mission_outcome=outcome,
            stages={
                "navigator": StageSnapshot(
                    status=status,
                    native_state="REJECTED" if failed else "CREATED",
                    error=error,
                )
            },
        )
        return SimpleNamespace(
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            action=SimpleNamespace(value="EXECUTED"),
            navigator_artifact_directory=self.navigator_directory,
            handoff_status=SimpleNamespace(value="STAGED"),
            intake_status=SimpleNamespace(value="REJECTED" if failed else "ACCEPTED"),
            plan_status=None if failed else SimpleNamespace(value="CREATED"),
            mode=SimpleNamespace(value="SHADOW"),
        )

    def invoke_operator(self, action: str, fixture: str, reason: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "operator-action",
                    "--mission-id",
                    "mission-buildweek-replay-001",
                    "--action",
                    action,
                    "--operator-id",
                    "demo-operator",
                    "--reason",
                    reason,
                    "--artifacts-root",
                    str(self.base),
                    "--replay-fixture",
                    fixture,
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def invoke_navigator(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(
                [
                    "run-navigator",
                    "--mission-id",
                    "mission-buildweek-replay-001",
                    "--artifacts-root",
                    str(self.base),
                    "--replay-fixture",
                    "fixtures/navigator_replay.shadow.v1.json",
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def test_approve_and_reject_are_explicit_successful_actions(self) -> None:
        cases = (
            (
                OperatorAction.APPROVE_HANDOFF,
                "fixtures/operator_replay_action.approve.v1.json",
                "Approved for deterministic Navigator SHADOW planning.",
            ),
            (
                OperatorAction.REJECT,
                "fixtures/operator_replay_action.reject.v1.json",
                "Rejected at the deterministic operator gate.",
            ),
        )
        for action, fixture, reason in cases:
            with self.subTest(action=action.value), mock.patch(
                "blackpod_build_week.harbormaster.run_operator_action",
                return_value=self.operator_result(action),
            ) as runner:
                code, stdout, stderr = self.invoke_operator(action.value, fixture, reason)
            self.assertEqual(code, EXIT_SUCCESS)
            self.assertEqual(stderr, "")
            self.assertIn(f"action={action.value}\n", stdout)
            self.assertIn("operator_action_status=SUCCEEDED\n", stdout)
            settings = runner.call_args.args[0]
            self.assertEqual(settings.action, action.value)
            self.assertEqual(settings.replay_fixture, Path(fixture))

    def test_navigator_success_and_controlled_failure_exit_codes(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_navigator",
            return_value=self.navigator_result(),
        ):
            code, stdout, stderr = self.invoke_navigator()
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("navigator_status=SUCCEEDED\n", stdout)
        self.assertIn("handoff_status=STAGED\n", stdout)
        self.assertIn("intake_status=ACCEPTED\n", stdout)
        self.assertIn("plan_status=CREATED\n", stdout)
        self.assertIn("mode=SHADOW\n", stdout)
        self.assertIn("mission_outcome=APPROVED\n", stdout)

        with mock.patch(
            "blackpod_build_week.harbormaster.run_navigator",
            return_value=self.navigator_result(failed=True),
        ):
            code, stdout, stderr = self.invoke_navigator()
        self.assertEqual(code, EXIT_NAVIGATOR_FAILURE)
        self.assertIn("navigator_status=FAILED\n", stdout)
        self.assertIn("NAVIGATOR_INTAKE_REJECTED", stderr)

    def test_operator_technical_failure_exits_nonzero(self) -> None:
        failed = self.operator_result()
        failed.technical_status = OperatorActionStatus.FAILED
        failed.result = None
        failed.action_id = None
        with mock.patch(
            "blackpod_build_week.harbormaster.run_operator_action",
            return_value=failed,
        ):
            code, stdout, _ = self.invoke_operator(
                "APPROVE_HANDOFF",
                "fixtures/operator_replay_action.approve.v1.json",
                "Approved for deterministic Navigator SHADOW planning.",
            )
        self.assertEqual(code, EXIT_OPERATOR_FAILURE)
        self.assertIn("operator_action_status=FAILED\n", stdout)

    def test_invalid_operator_and_navigator_states_exit_nonzero(self) -> None:
        with mock.patch(
            "blackpod_build_week.harbormaster.run_operator_action",
            side_effect=OperatorPreconditionError("Governor PROCEED is required"),
        ):
            code, _, stderr = self.invoke_operator(
                "APPROVE_HANDOFF",
                "fixtures/operator_replay_action.approve.v1.json",
                "Approved for deterministic Navigator SHADOW planning.",
            )
        self.assertEqual(code, EXIT_OPERATOR_FAILURE)
        self.assertIn("operator state conflict", stderr)

        with mock.patch(
            "blackpod_build_week.harbormaster.run_navigator",
            side_effect=NavigatorPreconditionError(
                "APPROVED_FOR_HANDOFF is required"
            ),
        ):
            code, _, stderr = self.invoke_navigator()
        self.assertEqual(code, EXIT_NAVIGATOR_FAILURE)
        self.assertIn("Navigator state conflict", stderr)

    def test_repeated_completed_actions_report_explicit_no_op_and_exit_zero(self) -> None:
        operator = self.operator_result()
        operator.disposition = SimpleNamespace(value="NO_OP_ALREADY_SUCCEEDED")
        with mock.patch(
            "blackpod_build_week.harbormaster.run_operator_action",
            return_value=operator,
        ):
            code, stdout, stderr = self.invoke_operator(
                "APPROVE_HANDOFF",
                "fixtures/operator_replay_action.approve.v1.json",
                "Approved for deterministic Navigator SHADOW planning.",
            )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn(
            "operator_action_disposition=NO_OP_ALREADY_SUCCEEDED\n", stdout
        )

        navigator = self.navigator_result()
        navigator.action = SimpleNamespace(value="NO_OP_ALREADY_SUCCEEDED")
        with mock.patch(
            "blackpod_build_week.harbormaster.run_navigator",
            return_value=navigator,
        ):
            code, stdout, stderr = self.invoke_navigator()
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("navigator_action=NO_OP_ALREADY_SUCCEEDED\n", stdout)


if __name__ == "__main__":
    unittest.main()
