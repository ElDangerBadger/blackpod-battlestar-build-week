from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from blackpod_build_week.contracts import (
    CurrentPhase,
    DemoModelDockMode,
    MissionOutcome,
)
from blackpod_build_week.demo_workflow import (
    DemoSettings,
    DemoWorkflowError,
    run_demo,
)
from blackpod_build_week.mission_presentation import MissionPresentationResult
from blackpod_build_week.unified_mission_workflow import UnifiedMissionAction


class DemoWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _result(
        self,
        settings,
        *,
        outcome: MissionOutcome = MissionOutcome.APPROVED,
        phase: CurrentPhase = CurrentPhase.COMPLETE,
        terminal: bool = True,
        revision: int = 13,
        success: bool = True,
        action: UnifiedMissionAction = UnifiedMissionAction.EXECUTED,
    ):
        mission_root = (
            Path(settings.artifacts_root)
            / "missions"
            / "mission-buildweek-replay-001"
        )
        presentation_root = mission_root / "presentation"
        mission_root.mkdir(parents=True, exist_ok=True)
        stable = mission_root / "stable.json"
        if not stable.exists():
            stable.write_text("{}\n", encoding="utf-8")
        presentation = MissionPresentationResult(
            captain_log=object(),  # type: ignore[arg-type]
            mission_summary=object(),  # type: ignore[arg-type]
            captains_log_json_path=presentation_root / "captains_log.json",
            captains_log_markdown_path=presentation_root / "captains_log.md",
            mission_summary_path=presentation_root / "mission_summary.json",
            captains_log_json_written=False,
            captains_log_markdown_written=False,
            mission_summary_written=False,
        )
        return SimpleNamespace(
            request=SimpleNamespace(symbol="AAPL"),
            snapshot=SimpleNamespace(
                mission_id="mission-buildweek-replay-001",
                mission_outcome=outcome,
                current_phase=phase,
                terminal=terminal,
                revision=revision,
            ),
            paths=SimpleNamespace(
                mission_root=mission_root,
                current_snapshot=mission_root / "mission_snapshot.json",
            ),
            action=action,
            technical_success=success,
            presentation=presentation,
        )

    @staticmethod
    def _manifest(mode: DemoModelDockMode = DemoModelDockMode.REPLAYED):
        return SimpleNamespace(modeldock_mode=mode)

    def test_approved_maps_committed_inputs_to_unified_workflow(self) -> None:
        captured: list[tuple[object, dict[str, str]]] = []

        def runner(settings, *, environ):
            captured.append((settings, environ))
            return self._result(settings)

        with mock.patch(
            "blackpod_build_week.demo_workflow._write_manifest",
            return_value=(self._manifest(), self.base / "demo_manifest.json"),
        ):
            result = run_demo(
                DemoSettings(scenario="approved", artifacts_root=self.base),
                environ={"BATTLESTAR_PATH": "/read-only/battlestar"},
                unified_runner=runner,
            )

        settings, environment = captured[0]
        self.assertEqual(result.scenario.name, "approved")
        self.assertTrue(settings.with_modeldock)
        self.assertEqual(settings.through.value, "NAVIGATOR")
        self.assertEqual(settings.operator_action.value, "APPROVE_HANDOFF")
        self.assertTrue(str(settings.oracle_replay_fixture).endswith("oracle_replay_quotes.v1.json"))
        self.assertEqual(environment["MODELDOCK_PROVIDER"], "mlx")
        self.assertNotIn("MODELDOCK_MODEL", environment)

    def test_without_modeldock_is_explicit_and_approved_only(self) -> None:
        def runner(settings, *, environ):
            del environ
            self.assertFalse(settings.with_modeldock)
            self.assertIsNone(settings.modeldock_replay_fixture)
            return self._result(settings, revision=11)

        with mock.patch(
            "blackpod_build_week.demo_workflow._write_manifest",
            return_value=(
                self._manifest(DemoModelDockMode.DISABLED),
                self.base / "demo_manifest.json",
            ),
        ):
            result = run_demo(
                DemoSettings(
                    scenario="approved",
                    artifacts_root=self.base,
                    without_modeldock=True,
                ),
                environ={},
                unified_runner=runner,
            )
        self.assertEqual(result.scenario.name, "without-modeldock")
        self.assertIs(result.modeldock_mode, DemoModelDockMode.DISABLED)

        with self.assertRaisesRegex(DemoWorkflowError, "approved demo"):
            run_demo(
                DemoSettings(
                    scenario="held",
                    artifacts_root=self.base / "held",
                    without_modeldock=True,
                ),
                environ={},
                unified_runner=runner,
            )

    def test_controlled_failed_scenario_is_expected_canonical_state(self) -> None:
        def runner(settings, *, environ):
            del environ
            return self._result(
                settings,
                outcome=MissionOutcome.FAILED,
                phase=CurrentPhase.NAVIGATOR,
                revision=13,
                success=False,
                action=UnifiedMissionAction.FAILED,
            )

        with mock.patch(
            "blackpod_build_week.demo_workflow._write_manifest",
            return_value=(self._manifest(), self.base / "demo_manifest.json"),
        ):
            result = run_demo(
                DemoSettings(scenario="failed", artifacts_root=self.base),
                environ={},
                unified_runner=runner,
            )
        self.assertFalse(result.unified.technical_success)

    def test_omitted_artifact_root_creates_one_fresh_isolated_root(self) -> None:
        isolated = self.base / "isolated-demo"

        def runner(settings, *, environ):
            del environ
            self.assertEqual(Path(settings.artifacts_root), isolated.resolve())
            return self._result(settings)

        with mock.patch(
            "blackpod_build_week.demo_workflow._write_manifest",
            return_value=(self._manifest(), isolated / "demo_manifest.json"),
        ):
            result = run_demo(
                DemoSettings(scenario="approved"),
                environ={},
                unified_runner=runner,
                temporary_root_factory=lambda: isolated,
            )
        self.assertTrue(result.created_isolated_root)
        self.assertEqual(result.artifacts_root, isolated.resolve())
        self.assertTrue(isolated.is_dir())

    def test_unexpected_outcome_is_rejected(self) -> None:
        def runner(settings, *, environ):
            del environ
            return self._result(
                settings,
                outcome=MissionOutcome.HELD,
                phase=CurrentPhase.OPERATOR,
                terminal=False,
                revision=9,
            )

        with self.assertRaisesRegex(DemoWorkflowError, "unexpected canonical state"):
            run_demo(
                DemoSettings(scenario="approved", artifacts_root=self.base),
                environ={},
                unified_runner=runner,
            )

    def test_cold_warm_rehearsal_is_an_explicit_unchanged_no_op(self) -> None:
        calls = 0

        def runner(settings, *, environ):
            nonlocal calls
            del environ
            calls += 1
            return self._result(
                settings,
                action=(
                    UnifiedMissionAction.EXECUTED
                    if calls == 1
                    else UnifiedMissionAction.NO_OP_ALREADY_SATISFIED
                ),
            )

        manifest = self._manifest()
        with mock.patch(
            "blackpod_build_week.demo_workflow._write_manifest",
            return_value=(manifest, self.base / "demo_manifest.json"),
        ):
            result = run_demo(
                DemoSettings(
                    scenario="approved",
                    artifacts_root=self.base,
                    rehearse=True,
                ),
                environ={},
                unified_runner=runner,
            )
        self.assertEqual(calls, 2)
        self.assertEqual(
            result.rehearsal.warm_action,
            UnifiedMissionAction.NO_OP_ALREADY_SATISFIED,
        )
        self.assertTrue(result.rehearsal.immutable_files_unchanged)

    def test_demo_readiness_source_has_no_broker_import_or_operation_call(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src/blackpod_build_week"
        prohibited_calls = {
            "submit_order",
            "cancel_order",
            "modify_portfolio",
            "broker_call",
        }
        for path in source_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = {alias.name.lower() for alias in node.names}
                    self.assertFalse(
                        any(
                            token in name
                            for name in imported
                            for token in ("alpaca", "robinhood", "broker")
                        ),
                        path,
                    )
                elif isinstance(node, ast.ImportFrom):
                    module = (node.module or "").lower()
                    self.assertFalse(
                        any(token in module for token in ("alpaca", "robinhood", "broker")),
                        path,
                    )
                elif isinstance(node, ast.Call):
                    function = node.func
                    name = (
                        function.id
                        if isinstance(function, ast.Name)
                        else function.attr
                        if isinstance(function, ast.Attribute)
                        else ""
                    )
                    self.assertNotIn(name.lower(), prohibited_calls, path)


if __name__ == "__main__":
    unittest.main()
