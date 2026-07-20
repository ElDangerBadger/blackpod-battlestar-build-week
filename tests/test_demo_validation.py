from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import (
    CAPTAINS_LOG_PATH,
    CAPTAINS_LOG_SCHEMA_VERSION,
    DEMO_MANIFEST_PATH,
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    MISSION_SUMMARY_PATH,
    MISSION_SUMMARY_SCHEMA_VERSION,
    DemoManifest,
    MissionOutcome,
    MissionRequest,
    OracleTransportKind,
    StageStatus,
)
from blackpod_build_week.demo_validation import (
    DemoMissionTarget,
    DemoValidationError,
    DemoValidationResult,
    validate_demo_catalog,
    validate_demo_mission,
    validate_demo_packs,
)
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.mission_presentation import render_mission_presentation
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.oracle_adapter import (
    EXPECTED_ORACLE_OUTPUT_FILENAMES,
    OracleExecutionResult,
)
from blackpod_build_week.oracle_workflow import OracleRunSettings, run_oracle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = PROJECT_ROOT / "examples/mission_request.replay.json"
ORACLE_FIXTURE = PROJECT_ROOT / "fixtures/oracle_replay_quotes.v1.json"


class SuccessfulOracle:
    def execute(self, request, context, *, replay_input=None):
        for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES:
            payload = {"artifact": filename, "warnings": []}
            encoded = (
                (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
                if filename.endswith(".jsonl")
                else canonical_json_bytes(payload)
            )
            (context.output_absolute / filename).write_bytes(encoded)
        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=OracleTransportKind.REPLAY_FIXTURE,
            status=StageStatus.SUCCEEDED,
            native_state="READY",
            produced_paths=tuple(
                f"{context.output_dir}/{filename}"
                for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES
            ),
            failure=None,
            run_id="oracle-demo-validation",
            fleet_id="fleet-oracles-vapors-example",
            readiness_state="READY",
            downstream_ready=True,
            headline="Deterministic Oracle validation fixture.",
            blocker_count=0,
            warning_count=0,
        )


class GeneratedDemo:
    def __init__(self, base: Path) -> None:
        self.artifacts_root = base / "artifacts"
        self.store = MissionStore(self.artifacts_root)
        request = MissionRequest.from_file(REQUEST_PATH)
        self.mission_id = request.mission_id or ""
        self.store.initialize(
            request,
            mission_id=self.mission_id,
            started_at=request.requested_at,
            observed_at=request.requested_at,
        )
        battlestar_root = base / "battlestar"
        oracle_module = battlestar_root / "blackpod/runtime/oracle_pipeline.py"
        oracle_module.parent.mkdir(parents=True)
        oracle_module.write_text("# test-only Oracle seam\n", encoding="utf-8")
        fleet = battlestar_root / "configs/universes/oracles_vapors.example.yaml"
        fleet.parent.mkdir(parents=True)
        fleet.write_text("fleet_id: fleet-oracles-vapors-example\n", encoding="utf-8")
        config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=oracle_module.resolve(),
            fleet_path=fleet.resolve(),
            git_revision="a" * 40,
            git_branch="demo-validation",
            dirty_worktree=False,
        )
        run_oracle(
            OracleRunSettings(
                mission_id=self.mission_id,
                artifacts_root=self.artifacts_root,
                replay_fixture=ORACLE_FIXTURE,
            ),
            adapter=SuccessfulOracle(),
            config_loader=lambda **_kwargs: config,
        )
        loaded = self.store.load_mission(self.mission_id)
        render_mission_presentation(self.store, loaded)
        catalog_spec = validate_demo_catalog().scenario("incomplete")
        self.spec = replace(
            catalog_spec,
            with_modeldock=False,
            modeldock_fixture=None,
            expected_snapshot_count=3,
        )
        self._write_manifest()

    @property
    def mission_root(self) -> Path:
        return self.store.paths_for(self.mission_id).mission_root

    def _write_manifest(self) -> None:
        loaded = self.store.load_mission(self.mission_id)
        snapshot = loaded.snapshot
        log = self.store.reference_existing_artifact(
            self.mission_id,
            relative_path=CAPTAINS_LOG_PATH,
            name="captains_log",
            producer="harbormaster",
            schema_version=CAPTAINS_LOG_SCHEMA_VERSION,
            observed_at=snapshot.observed_at,
        )
        summary = self.store.reference_existing_artifact(
            self.mission_id,
            relative_path=MISSION_SUMMARY_PATH,
            name="mission_summary",
            producer="harbormaster",
            schema_version=MISSION_SUMMARY_SCHEMA_VERSION,
            observed_at=snapshot.observed_at,
        )
        final_snapshot = self.store.reference_existing_artifact(
            self.mission_id,
            relative_path="mission_snapshot.json",
            name="mission_snapshot",
            producer="harbormaster",
            schema_version=MISSION_SNAPSHOT_SCHEMA_VERSION,
            observed_at=snapshot.observed_at,
        )
        manifest = DemoManifest.from_mapping(
            {
                "schema_version": "blackpod.demo_manifest.v1",
                "demo_scenario": "incomplete",
                "mission_id": self.mission_id,
                "symbol": loaded.request.symbol,
                "run_mode": "REPLAY",
                "build_week_revision": "b" * 40,
                "battlestar_revision": "a" * 40,
                "modeldock_mode": "DISABLED",
                "modeldock_revision_or_service_identity": None,
                "modeldock_provider": None,
                "modeldock_model": None,
                "modeldock_trace_id": None,
                "final_outcome": "INCOMPLETE",
                "snapshot_count": 3,
                "captains_log": log.to_dict(),
                "mission_summary": summary.to_dict(),
                "final_snapshot": final_snapshot.to_dict(),
                "generated_at": snapshot.observed_at,
                "shadow_only_declaration": "NAVIGATOR_SHADOW_ONLY_NO_EXECUTION",
                "allowed_operations": ["VALIDATE", "PLAN_ONLY"],
                "prohibited_operations": [
                    "SUBMIT_ORDER",
                    "CANCEL_ORDER",
                    "MODIFY_PORTFOLIO",
                    "BROKER_CALL",
                ],
            }
        )
        self.store.write_presentation_artifact(
            self.mission_id,
            relative_path=DEMO_MANIFEST_PATH,
            payload=canonical_json_bytes(manifest.to_dict()),
        )


class GeneratedDemoValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.generated = GeneratedDemo(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def validate(self):
        return validate_demo_mission(
            self.generated.store,
            self.generated.spec,
            self.generated.mission_id,
            exit_code=0,
        )

    def test_validates_snapshot_chain_presentation_hashes_and_expected_state(self) -> None:
        result = self.validate()

        self.assertEqual(result.scenario, "incomplete")
        self.assertEqual(result.snapshot_count, 3)
        self.assertEqual(result.outcome.value, "INCOMPLETE")
        self.assertTrue(result.captains_log_path.is_file())
        self.assertTrue(result.mission_summary_path.is_file())
        self.assertTrue(result.manifest_path.is_file())

    def test_changed_expected_outcome_and_exit_code_are_rejected(self) -> None:
        changed = replace(
            self.generated.spec, expected_outcome=MissionOutcome.VETOED
        )
        with self.assertRaises(DemoValidationError):
            validate_demo_mission(
                self.generated.store,
                changed,
                self.generated.mission_id,
                exit_code=0,
            )
        with self.assertRaisesRegex(DemoValidationError, "exit code"):
            validate_demo_mission(
                self.generated.store,
                self.generated.spec,
                self.generated.mission_id,
                exit_code=11,
            )

    def test_broken_snapshot_hash_chain_is_rejected(self) -> None:
        revision_two = self.generated.mission_root / "snapshots/mission_snapshot-r0002.json"
        revision_two.write_bytes(revision_two.read_bytes() + b" ")

        with self.assertRaisesRegex(DemoValidationError, "snapshot revision hash chain"):
            self.validate()

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        path = self.generated.mission_root / DEMO_MANIFEST_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        value["captains_log"]["sha256"] = "f" * 64
        path.write_bytes(canonical_json_bytes(value))

        with self.assertRaisesRegex(DemoValidationError, "artifact hashes"):
            self.validate()

    def test_absolute_path_secret_and_execution_operation_are_rejected(self) -> None:
        cases = (
            ({"path": "/tmp/private.json"}, "absolute path"),
            ({"note": "Bearer abcdefghijklmnop"}, "secret-like"),
            ({"operation": "SUBMIT_ORDER"}, "prohibited execution"),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload):
                path = self.generated.mission_root / "presentation/unsafe.json"
                path.write_bytes(canonical_json_bytes(payload))
                with self.assertRaisesRegex(DemoValidationError, expected):
                    self.validate()
                path.unlink()


class DemoPackRunnerTests(unittest.TestCase):
    def test_injected_runner_checks_every_pack_and_collects_failures(self) -> None:
        catalog = validate_demo_catalog()
        calls: list[str] = []

        def runner(resolved):
            calls.append(resolved.spec.name)
            if resolved.spec.name == "held":
                raise RuntimeError("controlled pack failure")
            return DemoMissionTarget(Path("artifacts"), "mission-demo", 0)

        def validated(_store, spec, mission_id, *, exit_code=None):
            return DemoValidationResult(
                scenario=spec.name,
                mission_id=mission_id,
                outcome=spec.expected_outcome,
                snapshot_count=spec.expected_snapshot_count,
                captains_log_path=Path("captains_log.json"),
                mission_summary_path=Path("mission_summary.json"),
                manifest_path=Path("demo_manifest.json"),
            )

        with mock.patch(
            "blackpod_build_week.demo_validation.validate_demo_mission",
            side_effect=validated,
        ):
            report = validate_demo_packs(catalog, runner)

        self.assertEqual(tuple(calls), tuple(item.name for item in catalog.scenarios))
        self.assertFalse(report.ready)
        self.assertEqual(tuple(item.scenario for item in report.failures), ("held",))
        self.assertEqual(len(report.results), len(catalog.scenarios) - 1)
        with self.assertRaises(DemoValidationError):
            report.require_ready()


if __name__ == "__main__":
    unittest.main()
