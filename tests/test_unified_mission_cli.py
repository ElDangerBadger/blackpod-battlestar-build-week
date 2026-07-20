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
    ModelDockCallStatus,
    OperatorResult,
    RunMode,
    StageStatus,
)
from blackpod_build_week.harbormaster import (
    EXIT_INVALID_REQUEST,
    EXIT_SUCCESS,
    EXIT_UNIFIED_MISSION_FAILURE,
    build_mission_run_parser,
    main,
)
from blackpod_build_week.mission_presentation import MissionPresentationResult
from blackpod_build_week.unified_mission_workflow import (
    MissionThrough,
    UnifiedMissionAction,
    UnifiedMissionInvocationError,
)


MISSION_ID = "mission-buildweek-replay-001"


def _stage(
    status: StageStatus,
    native_state: str | None = None,
    *,
    modeldock_calls: tuple[object, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        native_state=native_state,
        modeldock_calls=modeldock_calls,
    )


class UnifiedMissionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.mission_root = self.base / "missions" / MISSION_ID
        self.presentation_root = self.mission_root / "presentation"
        self.current_snapshot = self.mission_root / "mission_snapshot.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def presentation(self) -> MissionPresentationResult:
        return MissionPresentationResult(
            captain_log=object(),  # type: ignore[arg-type]
            mission_summary=object(),  # type: ignore[arg-type]
            captains_log_json_path=self.presentation_root / "captains_log.json",
            captains_log_markdown_path=self.presentation_root / "captains_log.md",
            mission_summary_path=self.presentation_root / "mission_summary.json",
            mission_brief_path=self.presentation_root / "mission_brief.html",
            captains_log_json_written=False,
            captains_log_markdown_written=False,
            mission_summary_written=False,
            mission_brief_written=False,
        )

    def result(
        self,
        *,
        outcome: MissionOutcome = MissionOutcome.APPROVED,
        phase: CurrentPhase = CurrentPhase.COMPLETE,
        revision: int = 13,
        action: UnifiedMissionAction = UnifiedMissionAction.EXECUTED,
        technical_success: bool = True,
        executed_stages: tuple[str, ...] = (
            "oracle",
            "modeldock",
            "council",
            "governor",
            "operator",
            "navigator",
        ),
        modeldock: bool = True,
        governor_status: StageStatus = StageStatus.SUCCEEDED,
        governor_state: str | None = "PROCEED",
        operator_result: OperatorResult | None = OperatorResult.APPROVED_FOR_HANDOFF,
        operator_route: str | None = "PENDING_APPROVAL",
        navigator_status: StageStatus = StageStatus.SUCCEEDED,
        navigator_created: bool = True,
        stopped: bool = False,
        no_op: bool = False,
        through: MissionThrough = MissionThrough.NAVIGATOR,
    ) -> SimpleNamespace:
        calls: tuple[object, ...] = ()
        if modeldock:
            calls = (
                SimpleNamespace(status=ModelDockCallStatus.SUCCEEDED),
            )
        snapshot = SimpleNamespace(
            mission_id=MISSION_ID,
            run_mode=RunMode.REPLAY,
            current_phase=phase,
            mission_outcome=outcome,
            revision=revision,
            stages={
                "harbormaster": _stage(StageStatus.SUCCEEDED, "INITIALIZED"),
                "oracle": _stage(
                    StageStatus.SUCCEEDED,
                    "READY",
                    modeldock_calls=calls,
                ),
                "council": _stage(StageStatus.SUCCEEDED, "ALIGNED"),
                "governor": _stage(governor_status, governor_state),
                "navigator": _stage(
                    navigator_status,
                    "CREATED" if navigator_created else None,
                ),
            },
            operator=SimpleNamespace(
                result=operator_result,
                route=operator_route,
            ),
            navigator=SimpleNamespace(
                mode=SimpleNamespace(value="SHADOW"),
                plan_status=(
                    SimpleNamespace(value="CREATED") if navigator_created else None
                ),
            ),
        )
        return SimpleNamespace(
            request=SimpleNamespace(symbol="AAPL"),
            snapshot=snapshot,
            paths=SimpleNamespace(current_snapshot=self.current_snapshot),
            action=action,
            technical_success=technical_success,
            no_op=no_op,
            stopped=stopped,
            through=through,
            executed_stages=executed_stages,
            initialization_action=None,
            presentation=self.presentation(),
        )

    def invoke(
        self,
        arguments: list[str],
        *,
        result: object | None = None,
        error: Exception | None = None,
    ) -> tuple[int, str, str, mock.MagicMock]:
        target = (
            "blackpod_build_week.harbormaster.resume_unified_mission"
            if arguments[0] == "mission-resume"
            else "blackpod_build_week.harbormaster.run_unified_mission"
        )
        patch_options = (
            {"side_effect": error} if error is not None else {"return_value": result}
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch(target, **patch_options) as runner, contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            exit_code = main(arguments)
        return exit_code, stdout.getvalue(), stderr.getvalue(), runner

    def test_mission_run_maps_replay_settings_and_with_modeldock(self) -> None:
        arguments = [
            "mission-run",
            "--request",
            "examples/mission_request.replay.json",
            "--artifacts-root",
            str(self.base),
            "--with-modeldock",
            "--through",
            "OPERATOR",
            "--operator-action",
            "REJECT",
            "--operator-id",
            "demo-operator",
            "--operator-reason",
            "Rejected at the deterministic operator gate.",
            "--oracle-replay-fixture",
            "fixtures/oracle_replay_quotes.v1.json",
            "--modeldock-replay-fixture",
            "fixtures/modeldock_oracle_narrative.replay.v1.json",
            "--council-replay-fixture",
            "fixtures/council_replay_policy.v1.json",
            "--governor-replay-fixture",
            "fixtures/governor_replay_context.proceed.v1.json",
            "--operator-replay-fixture",
            "fixtures/operator_replay_action.reject.v1.json",
            "--navigator-replay-fixture",
            "fixtures/navigator_replay.shadow.v1.json",
            "--deadline-seconds",
            "12.5",
            "--strict-battlestar-clean",
        ]
        exit_code, _, stderr, runner = self.invoke(
            arguments,
            result=self.result(
                outcome=MissionOutcome.VETOED,
                action=UnifiedMissionAction.EXECUTED,
                executed_stages=("oracle", "modeldock", "council", "governor", "operator"),
                operator_result=OperatorResult.REJECTED,
                navigator_status=StageStatus.NOT_STARTED,
                navigator_created=False,
                through=MissionThrough.OPERATOR,
            ),
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        settings = runner.call_args.args[0]
        self.assertEqual(settings.request_path, Path("examples/mission_request.replay.json"))
        self.assertIsNone(settings.mission_id)
        self.assertEqual(settings.artifacts_root, self.base)
        self.assertIs(settings.with_modeldock, True)
        self.assertEqual(settings.through, "OPERATOR")
        self.assertEqual(settings.operator_action, "REJECT")
        self.assertEqual(settings.operator_id, "demo-operator")
        self.assertEqual(
            settings.operator_reason,
            "Rejected at the deterministic operator gate.",
        )
        self.assertEqual(
            settings.oracle_replay_fixture,
            Path("fixtures/oracle_replay_quotes.v1.json"),
        )
        self.assertEqual(
            settings.modeldock_replay_fixture,
            Path("fixtures/modeldock_oracle_narrative.replay.v1.json"),
        )
        self.assertEqual(
            settings.council_replay_fixture,
            Path("fixtures/council_replay_policy.v1.json"),
        )
        self.assertEqual(
            settings.governor_replay_fixture,
            Path("fixtures/governor_replay_context.proceed.v1.json"),
        )
        self.assertEqual(
            settings.operator_replay_fixture,
            Path("fixtures/operator_replay_action.reject.v1.json"),
        )
        self.assertEqual(
            settings.navigator_replay_fixture,
            Path("fixtures/navigator_replay.shadow.v1.json"),
        )
        self.assertEqual(settings.deadline_seconds, 12.5)
        self.assertIs(settings.strict_battlestar_clean, True)

    def test_mission_resume_maps_live_inputs_and_without_modeldock(self) -> None:
        arguments = [
            "mission-resume",
            "--mission-id",
            MISSION_ID,
            "--artifacts-root",
            str(self.base),
            "--without-modeldock",
            "--through",
            "NAVIGATOR",
            "--operator-action",
            "APPROVE_HANDOFF",
            "--operator-id",
            "live-operator",
            "--operator-reason",
            "Approved for local SHADOW planning.",
            "--expires-in-minutes",
            "30",
            "--council-policy-input",
            "inputs/live-council-policy.json",
            "--governor-context-input",
            "inputs/live-governor-context.json",
            "--deadline-seconds",
            "27",
        ]
        exit_code, _, stderr, runner = self.invoke(
            arguments,
            result=self.result(modeldock=False),
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        settings = runner.call_args.args[0]
        self.assertIsNone(settings.request_path)
        self.assertEqual(settings.mission_id, MISSION_ID)
        self.assertIs(settings.with_modeldock, False)
        self.assertEqual(settings.through, "NAVIGATOR")
        self.assertEqual(settings.operator_action, "APPROVE_HANDOFF")
        self.assertEqual(settings.operator_id, "live-operator")
        self.assertEqual(settings.expires_in_minutes, 30)
        self.assertEqual(
            settings.council_policy_input,
            Path("inputs/live-council-policy.json"),
        )
        self.assertEqual(
            settings.governor_context_input,
            Path("inputs/live-governor-context.json"),
        )
        self.assertIsNone(settings.council_replay_fixture)
        self.assertIsNone(settings.governor_replay_fixture)
        self.assertEqual(settings.deadline_seconds, 27.0)

    def test_modeldock_mode_is_required_and_mutually_exclusive(self) -> None:
        parser = build_mission_run_parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as missing:
            parser.parse_args(["--request", "request.json"])
        self.assertEqual(missing.exception.code, 2)
        self.assertIn("one of the arguments --with-modeldock --without-modeldock is required", stderr.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as conflict:
            parser.parse_args(
                [
                    "--request",
                    "request.json",
                    "--with-modeldock",
                    "--without-modeldock",
                ]
            )
        self.assertEqual(conflict.exception.code, 2)
        self.assertIn("not allowed with argument", stderr.getvalue())

    def test_approved_summary_and_exact_presentation_paths(self) -> None:
        result = self.result()
        exit_code, stdout, stderr, _ = self.invoke(
            [
                "mission-run",
                "--request",
                "request.json",
                "--artifacts-root",
                str(self.base),
                "--with-modeldock",
            ],
            result=result,
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn(f"Mission: {MISSION_ID}\n", stdout)
        self.assertIn("Symbol: AAPL\n", stdout)
        self.assertIn("Mode: REPLAY\n", stdout)
        self.assertIn("Harbormaster   SUCCEEDED\n", stdout)
        self.assertIn("Oracle         SUCCEEDED\n", stdout)
        self.assertIn("ModelDock      SUCCEEDED\n", stdout)
        self.assertIn("Council        SUCCEEDED\n", stdout)
        self.assertIn("Governor       PROCEED\n", stdout)
        self.assertIn("Operator       APPROVED_FOR_HANDOFF\n", stdout)
        self.assertIn("Navigator      SHADOW PLAN CREATED\n", stdout)
        self.assertIn("Outcome: APPROVED\n", stdout)
        self.assertIn("Current phase: COMPLETE\n", stdout)
        self.assertIn("Snapshots: 13\n", stdout)
        self.assertIn("Unified action: EXECUTED\n", stdout)
        self.assertIn(
            f"Current snapshot: {self.current_snapshot.resolve()}\n",
            stdout,
        )
        self.assertIn(
            "Captain's log: "
            f"{(self.presentation_root / 'captains_log.md').resolve()}\n",
            stdout,
        )
        self.assertIn(
            "Mission summary: "
            f"{(self.presentation_root / 'mission_summary.json').resolve()}\n",
            stdout,
        )

    def test_deliberately_stopped_held_summary_exits_zero(self) -> None:
        result = self.result(
            outcome=MissionOutcome.HELD,
            phase=CurrentPhase.OPERATOR,
            revision=9,
            action=UnifiedMissionAction.STOPPED,
            executed_stages=("oracle", "modeldock", "council", "governor"),
            operator_result=None,
            operator_route="PENDING_APPROVAL",
            navigator_status=StageStatus.NOT_STARTED,
            navigator_created=False,
            stopped=True,
            through=MissionThrough.GOVERNOR,
        )
        exit_code, stdout, stderr, _ = self.invoke(
            [
                "mission-run",
                "--request",
                "request.json",
                "--artifacts-root",
                str(self.base),
                "--with-modeldock",
                "--through",
                "GOVERNOR",
            ],
            result=result,
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("Governor       PROCEED\n", stdout)
        self.assertIn("Operator       PENDING_APPROVAL\n", stdout)
        self.assertIn("Navigator      NOT_STARTED\n", stdout)
        self.assertIn("Outcome: HELD\n", stdout)
        self.assertIn("Current phase: OPERATOR\n", stdout)
        self.assertIn("Snapshots: 9\n", stdout)
        self.assertIn("Unified action: STOPPED\n", stdout)

    def test_technical_failure_result_prints_summary_and_exits_nonzero(self) -> None:
        result = self.result(
            outcome=MissionOutcome.FAILED,
            phase=CurrentPhase.NAVIGATOR,
            action=UnifiedMissionAction.FAILED,
            technical_success=False,
            navigator_status=StageStatus.FAILED,
            navigator_created=False,
        )
        exit_code, stdout, stderr, _ = self.invoke(
            [
                "mission-resume",
                "--mission-id",
                MISSION_ID,
                "--artifacts-root",
                str(self.base),
                "--with-modeldock",
            ],
            result=result,
        )

        self.assertEqual(exit_code, EXIT_UNIFIED_MISSION_FAILURE)
        self.assertIn("Navigator      FAILED\n", stdout)
        self.assertIn("Outcome: FAILED\n", stdout)
        self.assertIn("Unified action: FAILED\n", stdout)
        self.assertIn("ended in a technical failure", stderr)

    def test_operator_control_invocation_errors_are_invalid_requests(self) -> None:
        cases = (
            (
                [
                    "mission-run",
                    "--request",
                    "request.json",
                    "--with-modeldock",
                ],
                "operator action, identity, and reason are required",
            ),
            (
                [
                    "mission-resume",
                    "--mission-id",
                    MISSION_ID,
                    "--without-modeldock",
                    "--operator-action",
                    "REJECT",
                    "--operator-id",
                    "second-operator",
                    "--operator-reason",
                    "Conflicting second action.",
                ],
                "operator action conflicts with the completed approval",
            ),
        )
        for arguments, message in cases:
            with self.subTest(command=arguments[0], message=message):
                exit_code, stdout, stderr, runner = self.invoke(
                    arguments,
                    error=UnifiedMissionInvocationError(message),
                )
                self.assertEqual(exit_code, EXIT_INVALID_REQUEST)
                self.assertEqual(stdout, "")
                self.assertIn("invalid unified mission invocation", stderr)
                self.assertIn(message, stderr)
                runner.assert_called_once()

    def test_repeated_completed_mission_reports_explicit_no_op(self) -> None:
        result = self.result(
            action=UnifiedMissionAction.NO_OP_ALREADY_SATISFIED,
            executed_stages=(),
            no_op=True,
        )
        exit_code, stdout, stderr, _ = self.invoke(
            [
                "mission-resume",
                "--mission-id",
                MISSION_ID,
                "--artifacts-root",
                str(self.base),
                "--with-modeldock",
            ],
            result=result,
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("Outcome: APPROVED\n", stdout)
        self.assertIn("Unified action: NO_OP_ALREADY_SATISFIED\n", stdout)
        self.assertIn("Executed stages: none\n", stdout)


if __name__ == "__main__":
    unittest.main()
