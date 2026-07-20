from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import (
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    ModelDockCallStatus,
    OracleTransportKind,
    StageStatus,
)
from blackpod_build_week.contracts.oracle_narrative import (
    ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
    ModelDockReplayPack,
    OracleFactCatalog,
    OracleNarrativeSelection,
)
from blackpod_build_week.council_workflow import _validate_council_preconditions
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_store import (
    ImmutableArtifactError,
    MissionStore,
    PersistenceError,
)
from blackpod_build_week.modeldock_client import (
    HttpResponse,
    ModelDockClient,
    ModelDockClientError,
    ModelDockFailure,
)
from blackpod_build_week.modeldock_config import ModelDockConfig
from blackpod_build_week.oracle_adapter import (
    EXPECTED_ORACLE_OUTPUT_FILENAMES,
    OracleExecutionResult,
)
from blackpod_build_week.oracle_enrichment_workflow import (
    MODELDOCK_NARRATIVE_ARTIFACT,
    MODELDOCK_NARRATIVE_PATH,
    MODELDOCK_PROVENANCE_ARTIFACT,
    MODELDOCK_REQUEST_ARTIFACT,
    MODELDOCK_REQUEST_PATH,
    MODELDOCK_RESPONSE_ARTIFACT,
    ORACLE_EVIDENCE_ARTIFACTS,
    OracleEnrichmentAction,
    OracleEnrichmentSettings,
    OracleEnrichmentStateConflictError,
    _build_narrative_request,
    _build_wire_request,
    _load_oracle_evidence,
    run_oracle_enrichment,
)
from blackpod_build_week.oracle_workflow import OracleRunSettings, run_oracle


OBSERVED_AT = "2026-07-18T18:05:00Z"


def replay_request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-modeldock-workflow-001",
            "mission_id": "mission-modeldock-workflow-001",
            "run_mode": "REPLAY",
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-modeldock-workflow",
            "metadata": {},
        }
    )


def oracle_documents() -> dict[str, dict[str, object]]:
    measurement_id = "oracle-measurements-test"
    diagnostics_id = "oracle-diagnostics-test"
    readiness_id = "oracle-readiness-test"
    normalized_id = "oracle-normalized-test"
    assessment_id = "oracle-assessment-test"
    measurements = {
        "measurement_id": measurement_id,
        "generated_at": OBSERVED_AT,
        "as_of": OBSERVED_AT,
        "dashboard_ready": True,
        "breadth_score": 1.0,
        "cyclical_strength": 0.25,
        "defensive_strength": 0.5,
        "leadership_concentration": 0.15,
        "risk_off_score": 0.5,
        "risk_on_score": 0.5,
        "rotation_velocity": 0.0,
        "sector_dispersion": 0.06,
        "symbols": ["XLK", "XLF", "SPY"],
        "warnings": ["MISSING_PRIOR_ORACLE_MEASUREMENTS"],
        "blockers": [],
    }
    diagnostics = {
        "diagnostics_id": diagnostics_id,
        "measurement_id": measurement_id,
        "readiness_id": readiness_id,
        "normalized_snapshot_id": normalized_id,
        "generated_at": OBSERVED_AT,
        "diagnostics_state": "READY",
        "dashboard_ready": True,
        "provenance_complete": True,
        "symbols_used_count": 3,
        "symbols_missing_count": 0,
        "symbols_excluded_count": 0,
        "fallback_count": 0,
        "summary": "Oracle measurement diagnostics are READY.",
        "warnings": [],
        "blockers": [],
    }
    readiness = {
        "readiness_id": readiness_id,
        "normalized_snapshot_id": normalized_id,
        "fleet_id": "fleet-test",
        "source_snapshot_id": "source-snapshot-test",
        "quality_report_id": "quality-test",
        "generated_at": OBSERVED_AT,
        "readiness_state": "READY",
        "downstream_ready": True,
        "dashboard_ready": True,
        "coverage_ok": True,
        "completeness_ok": True,
        "freshness_ok": True,
        "warnings": [],
        "blockers": [],
    }
    assessment = {
        "assessment_id": assessment_id,
        "measurement_id": measurement_id,
        "generated_at": OBSERVED_AT,
        "as_of": OBSERVED_AT,
        "breadth_posture": "EXPANDING_BREADTH",
        "leadership_posture": "BROAD_LEADERSHIP",
        "rotation_posture": "DEFENSIVE_ROTATION",
        "risk_regime_posture": "NEUTRAL",
        "confidence": 1.0,
        "dashboard_ready": True,
        "warnings": [],
        "blockers": [],
    }
    report = {
        "report_id": "oracle-report-test",
        "measurement_id": measurement_id,
        "measurements_id": measurement_id,
        "diagnostics_id": diagnostics_id,
        "assessment_id": assessment_id,
        "generated_at": OBSERVED_AT,
        "as_of": OBSERVED_AT,
        "headline": "Expanding breadth with neutral structure.",
        "summary": "Validated fixed-fleet Oracle summary.",
        "breadth_posture": "EXPANDING_BREADTH",
        "leadership_posture": "BROAD_LEADERSHIP",
        "rotation_posture": "DEFENSIVE_ROTATION",
        "risk_regime_posture": "NEUTRAL",
        "diagnostics_state": "READY",
        "dashboard_ready": True,
        "assessment_summary": {
            "breadth_posture": "EXPANDING_BREADTH",
            "leadership_posture": "BROAD_LEADERSHIP",
            "rotation_posture": "DEFENSIVE_ROTATION",
            "risk_regime_posture": "NEUTRAL",
            "confidence": 1.0,
        },
        "key_measurements": {
            "breadth_score": 1.0,
            "defensive_strength": 0.5,
            "cyclical_strength": 0.25,
        },
        "warnings": ["MISSING_PRIOR_ORACLE_MEASUREMENTS"],
        "blockers": [],
    }
    return {
        "oracle_measurements_live.json": measurements,
        "oracle_measurement_diagnostics_live.json": diagnostics,
        "fleet-oracles-vapors-example_readiness.json": readiness,
        "oracle_assessment_live.json": assessment,
        "oracle_report_live.json": report,
    }


class EvidenceOracleAdapter:
    def execute(self, request, context, *, replay_input=None):
        documents = oracle_documents()
        for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES:
            payload = documents.get(filename, {"artifact": filename})
            (context.output_absolute / filename).write_bytes(
                canonical_json_bytes(payload)
            )
        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=(
                OracleTransportKind.REPLAY_FIXTURE
                if request.run_mode.value == "REPLAY"
                else OracleTransportKind.LIVE_YFINANCE
            ),
            status=StageStatus.SUCCEEDED,
            native_state="READY",
            produced_paths=tuple(
                f"{context.output_dir}/{filename}"
                for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES
            ),
            failure=None,
        )


class TimeoutClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, *args, **kwargs):
        self.calls += 1
        raise ModelDockClientError(
            ModelDockFailure(
                code="timeout",
                error_type="TimeoutError",
                message="ModelDock request exceeded its client-side deadline",
                resumable=True,
                latency_ms=10_000.0,
                started_at=OBSERVED_AT,
                observed_at=OBSERVED_AT,
            )
        )


class InterruptedClient:
    def generate_text(self, *args, **kwargs):
        raise KeyboardInterrupt("interrupted")


class BombClient:
    def generate_text(self, *args, **kwargs):
        raise AssertionError("idempotent repeat called ModelDock")


class StaticTransport:
    def __init__(self, response: dict[str, object]) -> None:
        body = canonical_json_bytes(response)
        self.response = HttpResponse(
            200,
            {"Content-Length": str(len(body))},
            body,
        )
        self.model = response["model"]
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def request(self, **kwargs):
        self.calls += 1
        self.requests.append(dict(kwargs))
        if kwargs.get("url", "").endswith("/models"):
            payload = canonical_json_bytes(
                {
                    "models": [
                        {
                            "name": self.model,
                            "provider": "mlx",
                            "capabilities": ["text"],
                        }
                    ]
                }
            )
            return HttpResponse(
                200,
                {"Content-Length": str(len(payload))},
                payload,
            )
        return self.response


class OracleEnrichmentWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.artifacts_root = self.base / "artifacts"
        self.store = MissionStore(self.artifacts_root)
        self.request = replay_request()
        self.store.initialize(
            self.request,
            mission_id=self.request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        battlestar_root = self.base / "battlestar"
        module_path = battlestar_root / "blackpod/runtime/oracle_pipeline.py"
        module_path.parent.mkdir(parents=True)
        module_path.write_text("# test module\n", encoding="utf-8")
        fleet_path = battlestar_root / "configs/universes/oracles_vapors.example.yaml"
        fleet_path.parent.mkdir(parents=True)
        fleet_path.write_text("fleet_id: fleet-test\n", encoding="utf-8")
        config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=module_path.resolve(),
            fleet_path=fleet_path.resolve(),
            git_revision="a" * 40,
            git_branch="test",
            dirty_worktree=False,
        )
        run_oracle(
            OracleRunSettings(
                mission_id=self.request.mission_id or "",
                artifacts_root=self.artifacts_root,
                replay_fixture=(
                    Path(__file__).resolve().parents[1]
                    / "fixtures/oracle_replay_quotes.v1.json"
                ),
            ),
            adapter=EvidenceOracleAdapter(),
            config_loader=lambda **_: config,
        )
        self.config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
        )
        self.replay_pack_path = self.base / "modeldock-replay.json"
        self._write_replay_pack()
        self.settings = OracleEnrichmentSettings(
            mission_id=self.request.mission_id or "",
            artifacts_root=self.artifacts_root,
            replay_fixture=self.replay_pack_path,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def config_loader(self, **kwargs):
        return self.config

    def _write_replay_pack(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        refs, evidence = _load_oracle_evidence(
            loaded.request, loaded.snapshot, loaded.paths.mission_root
        )
        narrative_request = _build_narrative_request(
            loaded.request,
            loaded.snapshot,
            source_artifacts=refs,
            evidence=evidence,
        )
        wire = _build_wire_request(self.config, narrative_request)
        selection = OracleNarrativeSelection.from_mapping(
            {
                "schema_version": ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
                "selected_fact_ids": [
                    "oracle.measurements.breadth_score",
                    "oracle.diagnostics.diagnostics_state",
                ],
                "summary": "Validated fleet evidence reflects broad participation.",
                "interpretation": "Defensive strength exceeds cyclical strength within the validated fleet measurements.",
                "uncertainties": [
                    "The evidence covers a fixed validation fleet and is not security-specific."
                ],
                "confidence_explanation": "Confidence is bounded by current-source completeness and absent prior-period comparison.",
                "prohibited_actions_acknowledged": True,
            }
        )
        narrative = selection.expand(
            OracleFactCatalog.from_request(narrative_request),
            narrative_request,
        )
        model = "mlx-community/test-narrative-model"
        response = {
            "status": "ok",
            "request_type": "text.generate",
            "profile": "default",
            "provider": "mlx",
            "model": model,
            "content": selection.canonical_json_bytes().decode("utf-8"),
            "data": {
                "engine": "mlx-lm",
                "model_path": "models/mlx-community/test-narrative-model",
                "profile": "default",
            },
            "metadata": {
                "blackpod_correlation": wire["metadata"]["blackpod_correlation"],
                "requested_max_tokens": 2048,
                "effective_max_tokens": 2048,
                "generated_token_count": 64,
                "stop_reason": "completed_or_eos",
                "generation_options": {"temperature": 0.0},
            },
            "trace_id": "trace-modeldock-workflow-test",
            "mocked": False,
        }
        pack = ModelDockReplayPack.from_mapping(
            {
                "schema_version": "blackpod.modeldock_replay_pack.v1",
                "fixture_id": "modeldock-workflow-replay-001",
                "created_at": OBSERVED_AT,
                "observed_at": OBSERVED_AT,
                "oracle_input": narrative_request.to_dict(),
                "request": wire,
                "response": response,
                "expected_narrative": narrative.to_dict(),
                "expected_provenance": {
                    "schema_version": "blackpod.modeldock_replay_expected_provenance.v1",
                    "provider": "mlx",
                    "model": model,
                    "model_revision": None,
                    "trace_id": "trace-modeldock-workflow-test",
                    "mocked": False,
                },
                "expected_snapshot_changes": {
                    "schema_version": "blackpod.modeldock_replay_expected_snapshot_changes.v1",
                    "oracle_status": "SUCCEEDED",
                    "modeldock_call_status": "SUCCEEDED",
                    "current_phase": "COUNCIL",
                    "mission_outcome": "INCOMPLETE",
                    "terminal": False,
                    "narrative_output": MODELDOCK_NARRATIVE_ARTIFACT,
                },
            }
        )
        self.replay_pack_path.write_bytes(pack.canonical_json_bytes())

    def execute(self, *, client=None):
        return run_oracle_enrichment(
            self.settings,
            client=client,
            config_loader=self.config_loader,
        )

    def execute_live(self, *, mocked: bool = False):
        live_root = self.base / "live-artifacts"
        live_store = MissionStore(live_root)
        live_request = MissionRequest.from_mapping(
            {
                "schema_version": "blackpod.mission_request.v1",
                "request_id": "request-modeldock-live-001",
                "mission_id": "mission-modeldock-live-001",
                "run_mode": "LIVE",
                "symbol": "MSFT",
                "requested_at": OBSERVED_AT,
                "operator_id": "operator-modeldock-live",
                "metadata": {},
            }
        )
        live_store.initialize(
            live_request,
            mission_id=live_request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        battlestar = BattlestarConfig(
            root=(self.base / "battlestar").resolve(),
            oracle_module_path=(
                self.base / "battlestar/blackpod/runtime/oracle_pipeline.py"
            ).resolve(),
            fleet_path=(
                self.base
                / "battlestar/configs/universes/oracles_vapors.example.yaml"
            ).resolve(),
            git_revision="a" * 40,
            git_branch="test",
            dirty_worktree=False,
        )
        fixed_clock = lambda: datetime(2026, 7, 18, 18, 5, tzinfo=UTC)
        run_oracle(
            OracleRunSettings(
                mission_id=live_request.mission_id or "",
                artifacts_root=live_root,
            ),
            adapter=EvidenceOracleAdapter(),
            config_loader=lambda **_: battlestar,
            clock=fixed_clock,
        )
        loaded = live_store.load_mission(live_request.mission_id or "")
        refs, evidence = _load_oracle_evidence(
            loaded.request,
            loaded.snapshot,
            loaded.paths.mission_root,
        )
        narrative_request = _build_narrative_request(
            loaded.request,
            loaded.snapshot,
            source_artifacts=refs,
            evidence=evidence,
        )
        live_config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
            model="mlx-community/test-live-model",
        )
        wire = _build_wire_request(live_config, narrative_request)
        selection = OracleNarrativeSelection.from_mapping(
            {
                "schema_version": ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
                "selected_fact_ids": ["oracle.measurements.breadth_score"],
                "summary": "Validated fleet evidence reflects broad participation.",
                "interpretation": "Defensive strength exceeds cyclical strength within the validated fleet measurements.",
                "uncertainties": [
                    "The evidence covers a fixed validation fleet and is not security-specific."
                ],
                "confidence_explanation": "Confidence is bounded by current-source completeness and absent prior-period comparison.",
                "prohibited_actions_acknowledged": True,
            }
        )
        response = {
            "status": "ok",
            "request_type": "text.generate",
            "profile": "default",
            "provider": "mlx",
            "model": "mlx-community/test-live-model",
            "content": selection.canonical_json_bytes().decode("utf-8"),
            "data": {
                "engine": "mlx-lm",
                "model_path": "models/mlx-community/test-live-model",
                "profile": "default",
            },
            "metadata": {
                "blackpod_correlation": wire["metadata"]["blackpod_correlation"],
                "requested_max_tokens": 2048,
                "effective_max_tokens": 2048,
                "generated_token_count": 64,
                "stop_reason": "completed_or_eos",
                "generation_options": {"temperature": 0.0},
            },
            "trace_id": "trace-modeldock-live-test",
            "mocked": mocked,
        }
        transport = StaticTransport(response)
        client = ModelDockClient(
            live_config,
            transport=transport,
            monotonic=lambda: 0.0,
            now=fixed_clock,
        )
        result = run_oracle_enrichment(
            OracleEnrichmentSettings(
                mission_id=live_request.mission_id or "",
                artifacts_root=live_root,
            ),
            client=client,
            config_loader=lambda **_: live_config,
            clock=fixed_clock,
        )
        return result, transport

    def test_success_preserves_oracle_facts_and_writes_canonical_artifacts(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        oracle_report = loaded.paths.mission_root / ORACLE_EVIDENCE_ARTIFACTS["report"][1]
        report_before = oracle_report.read_bytes()

        result = self.execute()
        oracle = result.snapshot.stages["oracle"]
        self.assertEqual(result.action, OracleEnrichmentAction.EXECUTED)
        self.assertEqual(result.snapshot.revision, 5)
        self.assertEqual(oracle.status, StageStatus.SUCCEEDED)
        self.assertEqual(oracle.native_state, "READY")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(result.snapshot.terminal)
        self.assertEqual(oracle.modeldock_calls[0].status, ModelDockCallStatus.SUCCEEDED)
        self.assertIn(MODELDOCK_NARRATIVE_ARTIFACT, oracle.outputs)
        self.assertEqual(oracle_report.read_bytes(), report_before)
        for stage in ("council", "governor", "navigator"):
            self.assertEqual(result.snapshot.stages[stage].status, StageStatus.NOT_STARTED)

        artifacts = {item.name: item for item in result.snapshot.artifacts}
        self.assertEqual(
            set(oracle.modeldock_calls[0].artifacts),
            {
                MODELDOCK_REQUEST_ARTIFACT,
                MODELDOCK_RESPONSE_ARTIFACT,
                MODELDOCK_NARRATIVE_ARTIFACT,
                MODELDOCK_PROVENANCE_ARTIFACT,
            },
        )
        for name in oracle.modeldock_calls[0].artifacts:
            artifact = artifacts[name]
            target = result.paths.mission_root / artifact.path
            self.assertTrue(target.resolve().is_relative_to(result.paths.mission_root))
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        response_text = (result.paths.mission_root / artifacts[MODELDOCK_RESPONSE_ARTIFACT].path).read_text()
        self.assertNotIn("model_path", response_text)
        self.assertNotIn(str(self.base), response_text)
        response_payload = json.loads(response_text)
        model_selection = json.loads(response_payload["content"])
        self.assertEqual(
            model_selection["schema_version"],
            ORACLE_NARRATIVE_SELECTION_SCHEMA_VERSION,
        )
        self.assertEqual(
            model_selection["selected_fact_ids"],
            [
                "oracle.measurements.breadth_score",
                "oracle.diagnostics.diagnostics_state",
            ],
        )
        self.assertNotIn("observed_facts", model_selection)
        self.assertNotIn("warnings", model_selection)
        self.assertNotIn("mission_id", model_selection)
        self.assertNotIn("request_id", model_selection)
        self.assertNotIn("symbol", model_selection)

        narrative_payload = json.loads(
            (
                result.paths.mission_root
                / artifacts[MODELDOCK_NARRATIVE_ARTIFACT].path
            ).read_text()
        )
        self.assertEqual(narrative_payload["schema_version"], "blackpod.oracle_narrative.v1")
        self.assertEqual(
            [fact["value"] for fact in narrative_payload["observed_facts"]],
            [1.0, "READY"],
        )
        self.assertEqual(
            narrative_payload["warnings"],
            ["MISSING_PRIOR_ORACLE_MEASUREMENTS"],
        )

        revisions = result.paths.snapshots_dir
        running = json.loads((revisions / "mission_snapshot-r0004.json").read_text())
        success = json.loads((revisions / "mission_snapshot-r0005.json").read_text())
        self.assertEqual(running["stages"]["oracle"]["status"], "RUNNING")
        self.assertEqual(
            running["stages"]["oracle"]["modeldock_calls"][0]["status"],
            "RUNNING",
        )
        self.assertEqual(success["stages"]["oracle"]["status"], "SUCCEEDED")
        self.assertEqual(
            running["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0003.json"),
        )
        self.assertEqual(
            success["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0004.json"),
        )

    def test_replay_never_constructs_or_calls_live_transport(self) -> None:
        with patch(
            "blackpod_build_week.modeldock_client.UrlLibTransport.request",
            side_effect=AssertionError("network called"),
        ):
            result = self.execute()
        self.assertEqual(result.call.status, ModelDockCallStatus.SUCCEEDED)

    def test_live_verifies_route_then_uses_one_generation_call_and_never_replay(self) -> None:
        result, transport = self.execute_live()
        self.assertEqual(transport.calls, 2)
        self.assertEqual(
            [item["method"] for item in transport.requests],
            ["GET", "POST"],
        )
        self.assertEqual(result.snapshot.run_mode.value, "LIVE")
        self.assertEqual(result.call.status, ModelDockCallStatus.SUCCEEDED)
        self.assertFalse(result.call.mocked)
        self.assertEqual(result.call.provider, "mlx")
        self.assertEqual(
            result.snapshot.components["modeldock"].transport.value,
            "LIVE_HTTP",
        )
        self.assertFalse(
            (result.paths.mission_root / "oracle/inputs/modeldock_replay.json").exists()
        )

    def test_timeout_follows_strict_failure_policy_without_corrupting_facts(self) -> None:
        client = TimeoutClient()
        result = self.execute(client=client)
        oracle = result.snapshot.stages["oracle"]
        self.assertEqual(client.calls, 1)
        self.assertEqual(oracle.status, StageStatus.FAILED)
        self.assertEqual(oracle.native_state, "READY")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.ORACLE)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(result.snapshot.terminal)
        self.assertEqual(oracle.modeldock_calls[0].status, ModelDockCallStatus.FAILED)
        self.assertEqual(
            oracle.modeldock_calls[0].artifacts,
            (MODELDOCK_REQUEST_ARTIFACT, MODELDOCK_PROVENANCE_ARTIFACT),
        )
        self.assertIn("oracle_report", oracle.outputs)
        self.assertNotIn(MODELDOCK_NARRATIVE_ARTIFACT, oracle.outputs)

    def test_malformed_response_identity_commits_sanitized_failed_snapshot(self) -> None:
        pack = ModelDockReplayPack.from_file(self.replay_pack_path)
        malformed = copy.deepcopy(pack.response)
        malformed["provider"] = "bad provider"
        client = ModelDockClient(
            self.config,
            transport=StaticTransport(malformed),
            monotonic=lambda: 0.0,
            now=lambda: datetime(2026, 7, 18, 18, 5, tzinfo=UTC),
        )

        result = self.execute(client=client)

        self.assertEqual(result.snapshot.revision, 5)
        self.assertEqual(result.snapshot.stages["oracle"].status, StageStatus.FAILED)
        self.assertEqual(result.call.status, ModelDockCallStatus.FAILED)
        self.assertIsNone(result.call.provider)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        provenance = json.loads(
            (
                result.paths.mission_root
                / "oracle/modeldock/provenance.json"
            ).read_text()
        )
        self.assertIsNone(provenance["provider"])
        self.assertEqual(
            result.snapshot.previous_snapshot_sha256,
            sha256_file(result.paths.snapshots_dir / "mission_snapshot-r0004.json"),
        )

    def test_unknown_model_selected_fact_id_is_a_sanitized_technical_failure(self) -> None:
        pack = ModelDockReplayPack.from_file(self.replay_pack_path)
        malformed = copy.deepcopy(pack.response)
        selection = json.loads(malformed["content"])
        selection["selected_fact_ids"] = ["oracle.measurements.unknown_fact"]
        malformed["content"] = json.dumps(
            selection,
            sort_keys=True,
            separators=(",", ":"),
        )
        client = ModelDockClient(
            self.config,
            transport=StaticTransport(malformed),
            monotonic=lambda: 0.0,
            now=lambda: datetime(2026, 7, 18, 18, 5, tzinfo=UTC),
        )

        result = self.execute(client=client)

        self.assertEqual(result.snapshot.stages["oracle"].status, StageStatus.FAILED)
        self.assertEqual(result.call.status, ModelDockCallStatus.FAILED)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertNotIn(
            MODELDOCK_NARRATIVE_ARTIFACT,
            result.snapshot.stages["oracle"].outputs,
        )
        self.assertEqual(
            result.snapshot.stages["oracle"].error.message,
            "ModelDock narrative failed its versioned contract validation",
        )

    def test_identical_repeat_is_no_op_without_rewriting(self) -> None:
        first = self.execute()
        revision = first.paths.current_snapshot.read_bytes()
        second = self.execute(client=BombClient())
        self.assertEqual(second.action, OracleEnrichmentAction.NO_OP_ALREADY_SUCCEEDED)
        self.assertEqual(second.snapshot.revision, 5)
        self.assertEqual(second.paths.current_snapshot.read_bytes(), revision)
        self.assertFalse(
            (second.paths.snapshots_dir / "mission_snapshot-r0006.json").exists()
        )

    def test_interrupted_running_attempt_is_not_resumed(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            self.execute(client=InterruptedClient())
        loaded = self.store.load_mission(self.request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 4)
        self.assertEqual(loaded.snapshot.stages["oracle"].status, StageStatus.RUNNING)
        with self.assertRaisesRegex(OracleEnrichmentStateConflictError, "RUNNING"):
            self.execute(client=BombClient())

    def test_existing_immutable_request_is_not_overwritten(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        target = loaded.paths.mission_root / MODELDOCK_REQUEST_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(b"immutable sentinel\n")
        with self.assertRaises(ImmutableArtifactError):
            self.execute()
        self.assertEqual(target.read_bytes(), b"immutable sentinel\n")
        self.assertEqual(
            self.store.load_mission(self.request.mission_id or "").snapshot.revision,
            3,
        )

    def test_tampered_oracle_evidence_is_rejected_before_modeldock_write(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        artifact = next(
            item
            for item in loaded.snapshot.artifacts
            if item.name == "oracle_measurements"
        )
        target = loaded.paths.mission_root / artifact.path
        original = target.read_bytes()
        target.write_bytes(original + b"\n")

        with self.assertRaisesRegex(
            PersistenceError,
            "artifact hash mismatch",
        ):
            self.execute()

        self.assertFalse(
            (loaded.paths.mission_root / MODELDOCK_REQUEST_PATH).exists()
        )
        target.write_bytes(original)
        self.assertEqual(
            self.store.load_mission(self.request.mission_id or "").snapshot.revision,
            3,
        )

    def test_council_receives_validated_narrative_as_carry_forward_context(self) -> None:
        result = self.execute()
        selected = _validate_council_preconditions(
            result.request,
            result.snapshot,
            mission_root=result.paths.mission_root,
        )
        self.assertIn(MODELDOCK_NARRATIVE_ARTIFACT, selected)
        self.assertEqual(
            selected[MODELDOCK_NARRATIVE_ARTIFACT].path,
            MODELDOCK_NARRATIVE_PATH,
        )


if __name__ == "__main__":
    unittest.main()
