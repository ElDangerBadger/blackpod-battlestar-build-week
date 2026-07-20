from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.preflight import (
    CheckStatus,
    PreflightCheck,
    PreflightReport,
    RunMode,
)


def _report(*, ready: bool) -> PreflightReport:
    return PreflightReport(
        schema_version="blackpod.demo_preflight.v1",
        mode=RunMode.REPLAY,
        observed_at="2026-07-19T12:00:00Z",
        checks=(
            PreflightCheck(
                component="build_week",
                name="python",
                status=CheckStatus.PASS if ready else CheckStatus.FAIL,
                required=True,
                message=(
                    "Python runtime satisfies the Build Week requirement"
                    if ready
                    else "Python runtime is unsupported"
                ),
                details={"version": "3.11.9", "minimum": "3.11"},
            ),
        ),
    )


class PreflightCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.temporary.name) / "artifacts"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, report: PreflightReport, *extra: str):
        # Imported here so this test remains isolated from command startup while
        # the preflight module itself is tested independently.
        from blackpod_build_week.harbormaster import main

        stdout = io.StringIO()
        stderr = io.StringIO()
        captured = []

        def fake_run(settings):
            captured.append(settings)
            return report

        with (
            patch(
                "blackpod_build_week.harbormaster.run_preflight",
                side_effect=fake_run,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "preflight",
                    "--mode",
                    "replay",
                    "--artifacts-root",
                    str(self.artifacts),
                    *extra,
                ]
            )
        return code, stdout.getvalue(), stderr.getvalue(), captured

    def test_ready_preflight_exits_zero_and_prints_checks(self) -> None:
        code, stdout, stderr, captured = self.invoke(_report(ready=True))
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].mode, RunMode.REPLAY)
        self.assertEqual(captured[0].artifacts_root, self.artifacts)
        self.assertFalse(captured[0].strict_clean)
        self.assertIn("REPLAY", stdout)
        self.assertIn("build_week", stdout)
        self.assertIn("python", stdout)
        self.assertIn("PASS", stdout)
        self.assertIn("true", stdout.lower())

    def test_mandatory_failure_exits_nonzero_and_reports_not_ready(self) -> None:
        code, stdout, _, captured = self.invoke(_report(ready=False))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(captured), 1)
        self.assertIn("FAIL", stdout)
        self.assertIn("false", stdout.lower())

    def test_strict_clean_option_is_forwarded(self) -> None:
        code, _, stderr, captured = self.invoke(
            _report(ready=True), "--strict-clean"
        )
        self.assertEqual(code, 0, stderr)
        self.assertTrue(captured[0].strict_clean)


if __name__ == "__main__":
    unittest.main()
