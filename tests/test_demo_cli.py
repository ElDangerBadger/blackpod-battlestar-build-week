from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from blackpod_build_week.demo_workflow import DemoWorkflowError
from blackpod_build_week.harbormaster import (
    EXIT_DEMO_VALIDATION_FAILURE,
    EXIT_INVALID_REQUEST,
    EXIT_SUCCESS,
    EXIT_UNIFIED_MISSION_FAILURE,
    main,
)


class DemoCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, arguments: list[str], result: object):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch(
                "blackpod_build_week.harbormaster.run_demo",
                return_value=result,
            ) as runner,
            mock.patch(
                "blackpod_build_week.harbormaster.render_demo_terminal",
                return_value="DETERMINISTIC DEMO\n",
            ) as renderer,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue(), runner, renderer

    def test_all_five_scenarios_have_canonical_exit_codes(self) -> None:
        for scenario in ("approved", "held", "vetoed", "failed", "incomplete"):
            with self.subTest(scenario=scenario):
                successful = scenario != "failed"
                result = SimpleNamespace(
                    unified=SimpleNamespace(technical_success=successful)
                )
                code, stdout, stderr, runner, _ = self.invoke(
                    ["demo", scenario, "--artifacts-root", str(self.base / scenario)],
                    result,
                )
                self.assertEqual(
                    code,
                    EXIT_SUCCESS if successful else EXIT_UNIFIED_MISSION_FAILURE,
                )
                self.assertEqual(stdout, "DETERMINISTIC DEMO\n")
                self.assertEqual(stderr, "")
                self.assertEqual(runner.call_args.args[0].scenario, scenario)

    def test_flags_are_explicitly_forwarded_and_no_color_is_deterministic(self) -> None:
        result = SimpleNamespace(unified=SimpleNamespace(technical_success=True))
        code, _, stderr, runner, renderer = self.invoke(
            [
                "demo",
                "approved",
                "--without-modeldock",
                "--rehearse",
                "--strict-battlestar-clean",
                "--no-color",
            ],
            result,
        )
        self.assertEqual(code, EXIT_SUCCESS, stderr)
        settings = runner.call_args.args[0]
        self.assertIsNone(settings.artifacts_root)
        self.assertTrue(settings.without_modeldock)
        self.assertTrue(settings.rehearse)
        self.assertTrue(settings.strict_battlestar_clean)
        renderer.assert_called_once_with(result, no_color=True)

    def test_normal_failure_is_sanitized_and_debug_re_raises(self) -> None:
        error = DemoWorkflowError("controlled failure\nwithout a stack")
        stderr = io.StringIO()
        with mock.patch(
            "blackpod_build_week.harbormaster.run_demo", side_effect=error
        ), contextlib.redirect_stderr(stderr):
            code = main(["demo", "approved"])
        self.assertEqual(code, EXIT_INVALID_REQUEST)
        self.assertNotIn("Traceback", stderr.getvalue())
        self.assertIn("controlled failure without a stack", stderr.getvalue())

        with mock.patch(
            "blackpod_build_week.harbormaster.run_demo", side_effect=error
        ), self.assertRaises(DemoWorkflowError):
            main(["demo", "approved", "--debug"])


class ValidateDemoPacksCliTests(unittest.TestCase):
    def test_ready_and_failed_reports_map_to_stable_output_and_exit(self) -> None:
        cases = (
            (
                SimpleNamespace(
                    ready=True,
                    results=(
                        SimpleNamespace(
                            scenario="approved",
                            outcome=SimpleNamespace(value="APPROVED"),
                            snapshot_count=13,
                        ),
                    ),
                    failures=(),
                ),
                EXIT_SUCCESS,
                "demo_packs_ready=true",
            ),
            (
                SimpleNamespace(
                    ready=False,
                    results=(),
                    failures=(
                        SimpleNamespace(scenario="held", reason="outcome mismatch"),
                    ),
                ),
                EXIT_DEMO_VALIDATION_FAILURE,
                "demo_packs_ready=false",
            ),
        )
        for report, expected_code, expected_line in cases:
            with self.subTest(ready=report.ready):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    mock.patch(
                        "blackpod_build_week.harbormaster.load_demo_catalog",
                        return_value=object(),
                    ),
                    mock.patch(
                        "blackpod_build_week.harbormaster.validate_demo_packs",
                        return_value=report,
                    ),
                    contextlib.redirect_stdout(stdout),
                    contextlib.redirect_stderr(stderr),
                ):
                    code = main(["validate-demo-packs"])
                self.assertEqual(code, expected_code)
                self.assertIn(expected_line, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
