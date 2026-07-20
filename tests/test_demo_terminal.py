from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from blackpod_build_week.contracts import (
    ApprovalScope,
    DemoModelDockMode,
    MissionOutcome,
    OperatorActionStatus,
    RunMode,
    StageError,
    StageStatus,
)
from blackpod_build_week.demo_terminal import render_demo_terminal
from blackpod_build_week.mission_presentation import MissionPresentationResult
from blackpod_build_week.unified_mission_workflow import UnifiedMissionAction


class DemoTerminalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "missions/mission-demo"
        self.presentation_root = self.root / "presentation"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def result(self, *, failed: bool = False):
        navigator_error = (
            StageError.from_mapping(
                {
                    "code": "NAVIGATOR_INTAKE_REJECTED",
                    "error_type": "NavigatorIntakeError",
                    "message": "controlled intake rejection",
                    "resumable": False,
                    "observed_at": "2026-07-18T18:07:00Z",
                }
            )
            if failed
            else None
        )
        stage_values = {
            "HARBORMASTER": "SUCCEEDED",
            "ORACLE": "READY",
            "MODELDOCK": "SUCCEEDED",
            "COUNCIL": "MIXED",
            "GOVERNOR": "PROCEED",
            "OPERATOR": "APPROVED_FOR_HANDOFF",
            "NAVIGATOR": "FAILED" if failed else "SHADOW PLAN CREATED",
        }
        ordered = tuple(
            SimpleNamespace(stage=name, display_state=value)
            for name, value in stage_values.items()
        )
        presentation = MissionPresentationResult(
            captain_log=object(),  # type: ignore[arg-type]
            mission_summary=SimpleNamespace(ordered_stages=ordered),
            captains_log_json_path=self.presentation_root / "captains_log.json",
            captains_log_markdown_path=self.presentation_root / "captains_log.md",
            mission_summary_path=self.presentation_root / "mission_summary.json",
            captains_log_json_written=True,
            captains_log_markdown_written=True,
            mission_summary_written=True,
        )
        navigator_status = StageStatus.FAILED if failed else StageStatus.SUCCEEDED
        snapshot = SimpleNamespace(
            mission_id="mission-demo",
            run_mode=RunMode.REPLAY,
            mission_outcome=(
                MissionOutcome.FAILED if failed else MissionOutcome.APPROVED
            ),
            approval_scope=(
                None if failed else ApprovalScope.NAVIGATOR_SHADOW_HANDOFF
            ),
            revision=13,
            terminal=True,
            stages={
                "harbormaster": SimpleNamespace(
                    status=StageStatus.SUCCEEDED, native_state="INITIALIZED", error=None
                ),
                "oracle": SimpleNamespace(
                    status=StageStatus.SUCCEEDED, native_state="READY", error=None
                ),
                "council": SimpleNamespace(
                    status=StageStatus.SUCCEEDED, native_state="MIXED", error=None
                ),
                "governor": SimpleNamespace(
                    status=StageStatus.SUCCEEDED, native_state="PROCEED", error=None
                ),
                "navigator": SimpleNamespace(
                    status=navigator_status,
                    native_state=None if failed else "CREATED",
                    error=navigator_error,
                ),
            },
            operator=SimpleNamespace(
                action_status=OperatorActionStatus.SUCCEEDED,
                error=None,
            ),
        )
        unified = SimpleNamespace(
            request=SimpleNamespace(symbol="AAPL"),
            snapshot=snapshot,
            presentation=presentation,
            action=(
                UnifiedMissionAction.FAILED
                if failed
                else UnifiedMissionAction.EXECUTED
            ),
            technical_success=not failed,
            paths=SimpleNamespace(
                current_snapshot=self.root / "mission_snapshot.json",
                mission_root=self.root,
            ),
        )
        return SimpleNamespace(
            unified=unified,
            modeldock_mode=DemoModelDockMode.REPLAYED,
            manifest_path=self.presentation_root / "demo_manifest.json",
            rehearsal=None,
        )

    def test_approved_output_is_plain_deterministic_and_presentation_friendly(self) -> None:
        result = self.result()
        first = render_demo_terminal(result, no_color=True)
        second = render_demo_terminal(result, no_color=False)
        self.assertEqual(first, second)
        self.assertNotIn("\x1b[", first)
        self.assertIn("BLACKPOD BATTLESTAR\n", first)
        self.assertIn("Mission: mission-demo\n", first)
        self.assertIn("[✓] Oracle          READY\n", first)
        self.assertIn("[✓] Governor        PROCEED\n", first)
        self.assertIn("[✓] Navigator       SHADOW PLAN CREATED\n", first)
        self.assertIn("Outcome: APPROVED\n", first)
        self.assertIn("Approval scope: NAVIGATOR_SHADOW_HANDOFF\n", first)
        self.assertIn("ModelDock mode: REPLAYED\n", first)

    def test_failed_output_is_sanitized_and_actionable(self) -> None:
        output = render_demo_terminal(self.result(failed=True))
        self.assertIn("Outcome: FAILED\n", output)
        self.assertIn("Failed stage: NAVIGATOR\n", output)
        self.assertIn(
            "Reason: NAVIGATOR_INTAKE_REJECTED: controlled intake rejection\n",
            output,
        )
        self.assertIn("Resumable: false\n", output)
        self.assertIn("Last valid snapshot:", output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
