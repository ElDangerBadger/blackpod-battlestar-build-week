from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

from blackpod_build_week.harbormaster import (
    EXIT_INVALID_REQUEST,
    EXIT_MODELDOCK_FAILURE,
    EXIT_SUCCESS,
    main,
)
from blackpod_build_week.modeldock_preflight import ModelDockPreflightReport
from blackpod_build_week.oracle_enrichment_workflow import run_oracle_enrichment
from tests import test_oracle_enrichment_workflow as workflow_tests


class ModelDockCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = workflow_tests.OracleEnrichmentWorkflowTests(
            methodName="runTest"
        )
        self.harness.setUp()
        self.environment = {
            "MODELDOCK_BASE_URL": "http://127.0.0.1:8000",
            "MODELDOCK_TIMEOUT_SECONDS": "10",
        }

    def tearDown(self) -> None:
        self.harness.tearDown()

    def invoke(self) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        arguments = [
            "enrich-oracle",
            "--mission-id",
            self.harness.request.mission_id or "",
            "--artifacts-root",
            str(self.harness.artifacts_root),
            "--replay-fixture",
            str(self.harness.replay_pack_path),
        ]
        with (
            patch.dict("os.environ", self.environment, clear=True),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_deterministic_replay_exits_zero_and_prints_provenance(self) -> None:
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertIn("oracle_status=SUCCEEDED", stdout)
        self.assertIn("modeldock_call_status=SUCCEEDED", stdout)
        self.assertIn("provider=mlx", stdout)
        self.assertIn("model=mlx-community/test-narrative-model", stdout)
        self.assertIn("trace_id=trace-modeldock-workflow-test", stdout)
        self.assertIn("narrative_artifact_path=oracle/modeldock/oracle_narrative.json", stdout)
        self.assertIn("current_phase=COUNCIL", stdout)
        self.assertIn("mission_outcome=INCOMPLETE", stdout)

    def test_repeated_completed_invocation_is_explicit_no_op(self) -> None:
        self.assertEqual(self.invoke()[0], EXIT_SUCCESS)
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, EXIT_SUCCESS, stderr)
        self.assertIn("modeldock_action=NO_OP_ALREADY_SUCCEEDED", stdout)
        self.assertEqual(
            self.harness.store.load_mission(
                self.harness.request.mission_id or ""
            ).snapshot.revision,
            5,
        )

    def test_valid_live_fake_result_exits_zero(self) -> None:
        result, transport = self.harness.execute_live()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "blackpod_build_week.harbormaster.run_oracle_enrichment",
                return_value=result,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "enrich-oracle",
                    "--mission-id",
                    "mission-modeldock-live-001",
                    "--artifacts-root",
                    str(self.harness.base / "live-artifacts"),
                ]
            )
        self.assertEqual(code, EXIT_SUCCESS, stderr.getvalue())
        self.assertEqual(transport.calls, 2)
        self.assertIn("provider=mlx", stdout.getvalue())
        self.assertIn("trace_id=trace-modeldock-live-test", stdout.getvalue())

    def test_mocked_live_response_exits_nonzero_under_strict_policy(self) -> None:
        result, transport = self.harness.execute_live(mocked=True)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "blackpod_build_week.harbormaster.run_oracle_enrichment",
                return_value=result,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "enrich-oracle",
                    "--mission-id",
                    "mission-modeldock-live-001",
                    "--artifacts-root",
                    str(self.harness.base / "live-artifacts"),
                ]
            )

        self.assertEqual(transport.calls, 2)
        self.assertEqual(code, EXIT_MODELDOCK_FAILURE)
        self.assertIn("modeldock_call_status=FAILED", stdout.getvalue())
        self.assertIn("MODELDOCK_MOCKED_LIVE_RESPONSE", stderr.getvalue())
        self.assertIsNone(result.narrative_artifact_path)

    def test_strict_timeout_snapshot_exits_nonzero(self) -> None:
        def timeout_run(settings):
            return run_oracle_enrichment(
                settings,
                client=workflow_tests.TimeoutClient(),
                config_loader=self.harness.config_loader,
            )

        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "blackpod_build_week.harbormaster.run_oracle_enrichment",
                side_effect=timeout_run,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "enrich-oracle",
                    "--mission-id",
                    self.harness.request.mission_id or "",
                    "--artifacts-root",
                    str(self.harness.artifacts_root),
                    "--replay-fixture",
                    str(self.harness.replay_pack_path),
                ]
            )
        self.assertEqual(code, EXIT_MODELDOCK_FAILURE)
        self.assertIn("modeldock_call_status=FAILED", stdout.getvalue())
        self.assertIn("MODELDOCK_TIMEOUT", stderr.getvalue())

    def test_invalid_oracle_state_exits_nonzero_without_network(self) -> None:
        other_root = self.harness.base / "phase1-only"
        store = self.harness.store.__class__(other_root)
        store.initialize(
            self.harness.request,
            mission_id=self.harness.request.mission_id or "",
            started_at=self.harness.request.requested_at,
            observed_at=self.harness.request.requested_at,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.dict("os.environ", self.environment, clear=True),
            patch(
                "blackpod_build_week.modeldock_client.UrlLibTransport.request",
                side_effect=AssertionError("network called"),
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(
                [
                    "enrich-oracle",
                    "--mission-id",
                    self.harness.request.mission_id or "",
                    "--artifacts-root",
                    str(other_root),
                    "--replay-fixture",
                    str(self.harness.replay_pack_path),
                ]
            )
        self.assertNotEqual(code, EXIT_SUCCESS)
        self.assertIn("ModelDock", stderr.getvalue())

    def test_preflight_cli_reports_deep_readiness_fields(self) -> None:
        report = ModelDockPreflightReport(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
            service_reachable=True,
            health_ready=True,
            health_response={"status": "ok", "service": "modeldock", "version": "0.1.0"},
            models_endpoint_ready=True,
            selected_model_available=True,
            text_generate_endpoint_available=True,
            inference_ready=True,
            provider="mlx",
            model="gemma-4-e4b-it-4bit",
            model_revision="revision-test",
            trace_id="trace-preflight-cli",
            mocked=False,
            latency_ms=12.5,
            observed_at="2026-07-19T12:00:00Z",
            issues=(),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "blackpod_build_week.harbormaster.load_modeldock_config",
                return_value=object(),
            ),
            patch(
                "blackpod_build_week.harbormaster.run_modeldock_preflight",
                return_value=report,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["modeldock-preflight"])

        self.assertEqual(code, EXIT_SUCCESS, stderr.getvalue())
        self.assertIn(
            'health_response={"service":"modeldock","status":"ok","version":"0.1.0"}',
            stdout.getvalue(),
        )
        self.assertIn("models_endpoint_ready=true", stdout.getvalue())
        self.assertIn("selected_model_available=true", stdout.getvalue())
        self.assertIn("provider=mlx", stdout.getvalue())

    def test_preflight_cli_mocked_or_shallow_result_exits_nonzero(self) -> None:
        report = ModelDockPreflightReport(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
            service_reachable=True,
            health_ready=True,
            health_response={"status": "ok", "service": "modeldock", "version": "0.1.0"},
            models_endpoint_ready=True,
            selected_model_available=True,
            text_generate_endpoint_available=True,
            inference_ready=False,
            provider="mlx",
            model="gemma-4-e4b-it-4bit",
            model_revision=None,
            trace_id="trace-preflight-mocked",
            mocked=True,
            latency_ms=5.0,
            observed_at="2026-07-19T12:00:00Z",
            issues=(
                {
                    "code": "mocked_live_response",
                    "message": "LIVE ModelDock narrative rejected a mocked response",
                    "resumable": False,
                },
            ),
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "blackpod_build_week.harbormaster.load_modeldock_config",
                return_value=object(),
            ),
            patch(
                "blackpod_build_week.harbormaster.run_modeldock_preflight",
                return_value=report,
            ),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["modeldock-preflight"])

        self.assertEqual(code, EXIT_MODELDOCK_FAILURE)
        self.assertIn("mocked=true", stdout.getvalue())
        self.assertIn("mocked_live_response", stderr.getvalue())

    def test_preflight_cli_missing_configuration_exits_invalid(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.dict("os.environ", {}, clear=True),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            code = main(["modeldock-preflight"])

        self.assertEqual(code, EXIT_INVALID_REQUEST)
        self.assertIn("MODELDOCK_BASE_URL", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
