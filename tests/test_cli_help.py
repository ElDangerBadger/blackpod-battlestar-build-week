from __future__ import annotations

import contextlib
import io
import unittest

from blackpod_build_week.harbormaster import main


class RootCliHelpTests(unittest.TestCase):
    def test_root_help_lists_every_existing_command_and_direct_initialization(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as stopped,
        ):
            main(["--help"])

        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(stderr.getvalue(), "")
        output = stdout.getvalue()
        self.assertIn("--request", output)
        for command in (
            "preflight",
            "demo",
            "validate-demo-packs",
            "mission-run",
            "mission-resume",
            "run-oracle",
            "enrich-oracle",
            "modeldock-preflight",
            "run-council",
            "run-governor",
            "operator-action",
            "run-navigator",
        ):
            with self.subTest(command=command):
                self.assertIn(command, output)

    def test_command_specific_help_still_uses_the_existing_parser(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as stopped,
        ):
            main(["demo", "--help"])

        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("{approved,held,vetoed,failed,incomplete}", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
