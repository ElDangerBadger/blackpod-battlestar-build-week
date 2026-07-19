from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.harbormaster import (
    EXIT_DUPLICATE_MISSION,
    EXIT_INVALID_REQUEST,
    EXIT_PERSISTENCE_FAILURE,
    EXIT_SUCCESS,
    HarbormasterSettings,
    initialize_mission,
    main,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "blackpod.mission_request.v1",
        "request_id": "request-cli-001",
        "run_mode": "LIVE",
        "symbol": "NVDA",
        "requested_at": "2026-07-18T20:00:00Z",
        "operator_id": "operator-cli",
        "metadata": {},
    }
    payload.update(overrides)
    return payload


class HarbormasterCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_request(self, payload: object, name: str = "request.json") -> Path:
        path = self.base / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def call_main(self, *arguments: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(list(arguments))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_valid_live_request_cli_summary_and_exit_code(self) -> None:
        request_path = self.write_request(
            request_payload(mission_id="mission-live-cli-001")
        )
        artifacts_root = self.base / "live-artifacts"

        exit_code, stdout, stderr = self.call_main(
            "--request",
            str(request_path),
            "--artifacts-root",
            str(artifacts_root),
        )

        self.assertEqual(exit_code, EXIT_SUCCESS)
        self.assertEqual(stderr, "")
        self.assertIn("mission_id=mission-live-cli-001\n", stdout)
        self.assertIn("run_mode=LIVE\n", stdout)
        self.assertIn("current_phase=ORACLE\n", stdout)
        self.assertIn("mission_outcome=INCOMPLETE\n", stdout)
        self.assertIn("snapshot_path=", stdout)

    def test_replay_request_has_identical_id_and_snapshot_in_separate_roots(self) -> None:
        request_path = self.write_request(request_payload(run_mode="REPLAY"))
        first = initialize_mission(
            HarbormasterSettings(request_path, self.base / "first-artifacts")
        )
        second = initialize_mission(
            HarbormasterSettings(request_path, self.base / "second-artifacts")
        )

        self.assertEqual(first.snapshot.mission_id, second.snapshot.mission_id)
        self.assertEqual(
            first.paths.current_snapshot.read_bytes(),
            second.paths.current_snapshot.read_bytes(),
        )
        self.assertEqual(first.snapshot.run_mode.value, "REPLAY")
        self.assertEqual(first.snapshot.started_at, "2026-07-18T20:00:00Z")

    def test_invalid_requests_return_schema_exit_code(self) -> None:
        cases = {
            "unsupported-version.json": request_payload(schema_version="future.v2"),
            "invalid-mode.json": request_payload(run_mode="DRY_RUN"),
            "unsafe-id.json": request_payload(mission_id="../outside"),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                request_path = self.write_request(payload, name)
                exit_code, stdout, stderr = self.call_main(
                    "--request",
                    str(request_path),
                    "--artifacts-root",
                    str(self.base / f"artifacts-{name}"),
                )
                self.assertEqual(exit_code, EXIT_INVALID_REQUEST)
                self.assertEqual(stdout, "")
                self.assertIn("harbormaster: invalid request:", stderr)

    def test_malformed_json_returns_schema_exit_code(self) -> None:
        request_path = self.base / "malformed.json"
        request_path.write_text("{malformed", encoding="utf-8")

        exit_code, stdout, stderr = self.call_main(
            "--request",
            str(request_path),
            "--artifacts-root",
            str(self.base / "malformed-artifacts"),
        )

        self.assertEqual(exit_code, EXIT_INVALID_REQUEST)
        self.assertEqual(stdout, "")
        self.assertIn("not valid JSON", stderr)

    def test_duplicate_initialization_returns_duplicate_exit_code(self) -> None:
        request_path = self.write_request(
            request_payload(mission_id="mission-duplicate-cli")
        )
        artifacts_root = self.base / "duplicate-artifacts"
        arguments = (
            "--request",
            str(request_path),
            "--artifacts-root",
            str(artifacts_root),
        )

        first_code, _, _ = self.call_main(*arguments)
        second_code, stdout, stderr = self.call_main(*arguments)

        self.assertEqual(first_code, EXIT_SUCCESS)
        self.assertEqual(second_code, EXIT_DUPLICATE_MISSION)
        self.assertEqual(stdout, "")
        self.assertIn("duplicate mission", stderr)

    def test_write_failure_returns_persistence_exit_code(self) -> None:
        request_path = self.write_request(
            request_payload(mission_id="mission-write-failure")
        )
        artifacts_root = self.base / "not-a-directory"
        artifacts_root.write_text("occupied", encoding="utf-8")

        exit_code, stdout, stderr = self.call_main(
            "--request",
            str(request_path),
            "--artifacts-root",
            str(artifacts_root),
        )

        self.assertEqual(exit_code, EXIT_PERSISTENCE_FAILURE)
        self.assertEqual(stdout, "")
        self.assertIn("persistence failure", stderr)

    def test_python_module_entry_point_returns_real_process_exit_codes(self) -> None:
        valid_path = self.write_request(
            request_payload(mission_id="mission-process-cli"),
            "process-valid.json",
        )
        invalid_path = self.base / "process-invalid.json"
        invalid_path.write_text("[]", encoding="utf-8")
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src") + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )

        valid = subprocess.run(
            [
                sys.executable,
                "-m",
                "blackpod_build_week.harbormaster",
                "--request",
                str(valid_path),
                "--artifacts-root",
                str(self.base / "process-artifacts"),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        invalid = subprocess.run(
            [
                sys.executable,
                "-m",
                "blackpod_build_week.harbormaster",
                "--request",
                str(invalid_path),
                "--artifacts-root",
                str(self.base / "invalid-process-artifacts"),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(valid.returncode, EXIT_SUCCESS, valid.stderr)
        self.assertEqual(invalid.returncode, EXIT_INVALID_REQUEST, invalid.stderr)


if __name__ == "__main__":
    unittest.main()

