from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from blackpod_build_week.battlestar_config import (
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    BattlestarConfig,
    BattlestarConfigurationError,
    CANDIDATE_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    MANDATE_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
)
from blackpod_build_week.contracts import (
    ComponentProvenance,
    CouncilTransportKind,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    OracleTransportKind,
    StageStatus,
)
from blackpod_build_week.council_adapter import (
    COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
    EXPECTED_COUNCIL_OUTPUT_FILENAMES,
    CouncilAdapter,
    CouncilExecutionResult,
    CouncilFailure,
    CouncilMissionContext,
    CouncilSupportingInput,
    CouncilTransportTimeout,
)
from blackpod_build_week.council_workflow import (
    COUNCIL_ATTEMPT_DIRECTORY,
    COUNCIL_LINEAGE_PATH,
    COUNCIL_NATIVE_OUTPUT_ARTIFACTS,
    COUNCIL_PROVENANCE_PATH,
    COUNCIL_SUPPORTING_INPUT_PATH,
    REQUIRED_ORACLE_INPUTS,
    CouncilAction,
    CouncilInvocationError,
    CouncilPreconditionError,
    CouncilRunSettings,
    CouncilStateConflictError,
    run_council,
)
from blackpod_build_week.hashing import sha256_bytes, sha256_file
from blackpod_build_week.mission_store import (
    ImmutableArtifactError,
    MissionNotFoundError,
    MissionStore,
    PersistenceError,
)
from blackpod_build_week.mission_transitions import begin_oracle, complete_oracle


OBSERVED_AT = "2026-07-18T18:05:00Z"
ORACLE_REVISION = "a" * 40
COUNCIL_REVISION = "b" * 40


def replay_request(
    *,
    mission_id: str = "mission-council-workflow-001",
    run_mode: str = "REPLAY",
) -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": f"request-{mission_id.removeprefix('mission-')}",
            "mission_id": mission_id,
            "run_mode": run_mode,
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-council-workflow",
            "metadata": {},
        }
    )


def supporting_payload(*, run_mode: str = "REPLAY", input_id: str = "council-input-001") -> bytes:
    value = {
        "schema_version": COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
        "input_id": input_id,
        "run_mode": run_mode,
        "generated_at": OBSERVED_AT,
        "mandate": {
            "as_of": OBSERVED_AT,
            "ok": True,
            "reason": "BUILD_WEEK_POLICY_OK",
            "allowed_sides": ["BUY", "SELL"],
            "max_trades": 2,
            "risk_posture": "NORMAL",
            "source": "build-week-test-fixture",
        },
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


class SuccessfulCouncilAdapter:
    def __init__(self, *, native_state: str = "ALIGNED") -> None:
        self.calls = 0
        self.native_state = native_state
        self.received_mode = None
        self.received_modeldock_narrative_path = None

    def execute(self, request, context, *, supporting_input):
        self.calls += 1
        self.received_mode = supporting_input.run_mode
        self.received_modeldock_narrative_path = (
            context.oracle_modeldock_narrative_path
        )
        for filename in COUNCIL_NATIVE_OUTPUT_ARTIFACTS:
            payload = {
                "artifact": filename,
                "native_state": self.native_state,
                "key_conflicts": ["Senate and Oracle remain divided."],
            }
            (context.output_absolute / filename).write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return CouncilExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=(
                CouncilTransportKind.REPLAY_FIXTURE
                if request.run_mode.value == "REPLAY"
                else CouncilTransportKind.LIVE_MISSION_INPUTS
            ),
            status=StageStatus.SUCCEEDED,
            native_state=self.native_state,
            produced_paths=tuple(
                f"{context.output_dir}/{filename}"
                for filename in COUNCIL_NATIVE_OUTPUT_ARTIFACTS
            ),
            failure=None,
            input_id=supporting_input.input_id,
            candidate_report_id="candidate-report-001",
            senate_review_packet_id="senate-review-001",
            senate_deliberation_id="senate-deliberation-001",
            input_packet_id="council-input-packet-001",
            synthesis_id="council-synthesis-001",
            summary_id="council-summary-001",
            warnings=("retain caution",),
            blockers=(),
            alignments=(),
            conflicts=("Senate and Oracle remain divided.",),
            source_lineage=(
                *(REQUIRED_ORACLE_INPUTS[name] for name in REQUIRED_ORACLE_INPUTS),
                *(
                    (context.oracle_modeldock_narrative_path,)
                    if context.oracle_modeldock_narrative_path is not None
                    else ()
                ),
                COUNCIL_SUPPORTING_INPUT_PATH,
            ),
        )


class FailedCouncilAdapter:
    def __init__(self, *, resumable: bool = True) -> None:
        self.calls = 0
        self.resumable = resumable

    def execute(self, request, context, *, supporting_input):
        self.calls += 1
        return CouncilExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=CouncilTransportKind.REPLAY_FIXTURE,
            status=StageStatus.FAILED,
            native_state=None,
            produced_paths=(),
            failure=CouncilFailure(
                code="COUNCIL_EXECUTION_FAILED",
                error_type="FixtureFailure",
                message="deterministic Council technical failure",
                resumable=self.resumable,
            ),
            input_id=supporting_input.input_id,
        )


class InterruptedCouncilAdapter:
    def execute(self, request, context, *, supporting_input):
        raise KeyboardInterrupt("simulated Council interruption")


class MalformedCouncilAdapter:
    def execute(self, request, context, *, supporting_input):
        return {"status": "SUCCEEDED", "native_state": "ALIGNED"}


class MismatchedCouncilAdapter(SuccessfulCouncilAdapter):
    def execute(self, request, context, *, supporting_input):
        result = super().execute(request, context, supporting_input=supporting_input)
        values = dict(result.__dict__) if hasattr(result, "__dict__") else {
            field: getattr(result, field) for field in result.__dataclass_fields__
        }
        values["request_id"] = "request-wrong-correlation"
        return CouncilExecutionResult(**values)


class RecordingCouncilTransport:
    def __init__(self, *, native_state: str = "CONFLICTED") -> None:
        self.calls = 0
        self.deadline_seconds = None
        self.request = None
        self.native_state = native_state

    def run(self, request, *, deadline_seconds):
        self.calls += 1
        self.deadline_seconds = deadline_seconds
        self.request = request
        output = request.mission_root / request.output_dir
        values = {
            "mandate_policy.json": {"ok": True},
            "trading_candidate_report.json": {"report_id": "candidate-report-001"},
            "senate_review_packet.json": {"packet_id": "senate-review-001"},
            "senate_deliberation.json": {
                "deliberation_id": "senate-deliberation-001"
            },
            "council_input_packet.json": {"packet_id": "council-input-packet-001"},
            "council_advisor_runtime_config.json": {
                "as_of": OBSERVED_AT,
                "advisor_manifest": [
                    {"advisor_name": name}
                    for name in (
                        "oracle_report",
                        "mandate",
                        "trading_candidate_report",
                        "senate_review_packet",
                        "senate_deliberation",
                    )
                ],
            },
            "council_advisor_runtime_validation.json": {
                "readiness_status": "READY"
            },
            "advisor_health_summary.json": {
                "advisor_count": 5,
                "overall_status": "READY",
                "advisors": [
                    {
                        "advisor_name": name,
                        "enabled": True,
                        "loaded": True,
                        "healthy": True,
                        "required": True,
                        "severity": "OK",
                        "freshness": "fresh",
                        "source_path": f"council/attempt-0001/{name}.json",
                        "source_sha256": "a" * 64,
                    }
                    for name in (
                        "oracle_report",
                        "mandate",
                        "trading_candidate_report",
                        "senate_review_packet",
                        "senate_deliberation",
                    )
                ],
            },
            "council_synthesis.json": {
                "synthesis_state": self.native_state,
                "synthesis_id": "council-synthesis-001",
                "input_packet_id": "council-input-packet-001",
                "key_conflicts": ["Senate dissent remains material."],
            },
            "council_executive_summary.json": {
                "summary_id": "council-summary-001",
                "synthesis_id": "council-synthesis-001",
            },
        }
        for filename, value in values.items():
            (output / filename).write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return {
            "native_state": self.native_state,
            "produced_paths": [
                f"{request.output_dir}/{filename}"
                for filename in EXPECTED_COUNCIL_OUTPUT_FILENAMES
            ],
            "input_id": request.supporting_input["input_id"],
            "candidate_report_id": "candidate-report-001",
            "senate_review_packet_id": "senate-review-001",
            "senate_deliberation_id": "senate-deliberation-001",
            "input_packet_id": "council-input-packet-001",
            "synthesis_id": "council-synthesis-001",
            "summary_id": "council-summary-001",
            "warnings": ["retain caution"],
            "blockers": [],
            "alignments": ["Oracle evidence is internally consistent."],
            "conflicts": ["Senate dissent remains material."],
            "dissent": [
                {
                    "candidate_id": "candidate-001",
                    "deliberation_state": "UNFAVORABLE",
                }
            ],
        }


class RaisingCouncilTransport:
    def __init__(self, exception) -> None:
        self.exception = exception
        self.calls = 0

    def run(self, request, *, deadline_seconds):
        self.calls += 1
        raise self.exception


class MalformedCouncilTransport:
    def run(self, request, *, deadline_seconds):
        return {"native_state": "ALIGNED"}


class CouncilAdapterContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.battlestar_root = (self.base / "battlestar").resolve()
        for relative_path in (
            CANDIDATE_MODULE_RELATIVE_PATH,
            SENATE_REVIEW_MODULE_RELATIVE_PATH,
            SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
            MANDATE_MODULE_RELATIVE_PATH,
            COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
            COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
            ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
            RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
        ):
            module = self.battlestar_root / relative_path
            module.parent.mkdir(parents=True, exist_ok=True)
            module.write_text("# fake Battlestar module\n", encoding="utf-8")

        self.request = replay_request(mission_id="mission-council-adapter-001")
        self.mission_root = (
            self.base / "artifacts/missions" / (self.request.mission_id or "")
        ).resolve()
        self.mission_root.mkdir(parents=True)
        for relative_path in REQUIRED_ORACLE_INPUTS.values():
            artifact = self.mission_root / relative_path
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
        (self.mission_root / COUNCIL_ATTEMPT_DIRECTORY).mkdir(parents=True)
        self.context = CouncilMissionContext(
            mission_id=self.request.mission_id or "",
            mission_root=self.mission_root,
            output_dir=COUNCIL_ATTEMPT_DIRECTORY,
        )
        self.supporting_input = CouncilSupportingInput.from_bytes(
            supporting_payload()
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def execute(self, transport, *, request=None, supporting_input=None):
        adapter = CouncilAdapter(
            self.battlestar_root,
            transport=transport,
            deadline_seconds=7.5,
        )
        return adapter.execute(
            self.request if request is None else request,
            self.context,
            supporting_input=(
                self.supporting_input
                if supporting_input is None
                else supporting_input
            ),
        )

    def test_success_preserves_correlation_dissent_and_native_conflict(self) -> None:
        transport = RecordingCouncilTransport(native_state="CONFLICTED")
        result = self.execute(transport)

        self.assertEqual(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.native_state, "CONFLICTED")
        self.assertEqual(result.mission_id, self.request.mission_id)
        self.assertEqual(result.request_id, self.request.request_id)
        self.assertEqual(result.symbol, self.request.symbol)
        self.assertEqual(result.run_mode.value, "REPLAY")
        self.assertEqual(result.transport, CouncilTransportKind.REPLAY_FIXTURE)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(transport.deadline_seconds, 7.5)
        self.assertEqual(
            transport.request.supporting_input["run_mode"],
            "REPLAY",
        )
        self.assertEqual(result.warnings, ("retain caution",))
        self.assertEqual(result.conflicts, ("Senate dissent remains material.",))
        self.assertEqual(result.dissent[0]["deliberation_state"], "UNFAVORABLE")
        self.assertEqual(
            result.source_lineage,
            (
                *(REQUIRED_ORACLE_INPUTS[name] for name in REQUIRED_ORACLE_INPUTS),
                COUNCIL_SUPPORTING_INPUT_PATH,
            ),
        )

    def test_native_blocked_is_technically_successful(self) -> None:
        result = self.execute(RecordingCouncilTransport(native_state="BLOCKED"))
        self.assertEqual(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.native_state, "BLOCKED")
        self.assertIsNone(result.failure)

    def test_malformed_return_is_a_structured_nonresumable_failure(self) -> None:
        result = self.execute(MalformedCouncilTransport())
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_MALFORMED_RESULT")
        self.assertFalse(result.failure.resumable)

    def test_technical_exception_is_sanitized(self) -> None:
        transport = RaisingCouncilTransport(
            RuntimeError(
                f"failed under {self.battlestar_root} and {self.mission_root}"
            )
        )
        result = self.execute(transport)

        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_EXECUTION_FAILED")
        self.assertNotIn(str(self.battlestar_root), result.failure.message)
        self.assertNotIn(str(self.mission_root), result.failure.message)
        self.assertFalse(result.failure.resumable)

    def test_timeout_is_explicit_and_replay_is_not_resumable(self) -> None:
        result = self.execute(
            RaisingCouncilTransport(CouncilTransportTimeout("deadline exceeded"))
        )
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_TIMEOUT")
        self.assertFalse(result.failure.resumable)

    def test_correlation_and_mode_mismatch_do_not_call_transport(self) -> None:
        transport = RecordingCouncilTransport()
        mismatched_request = replay_request(mission_id="mission-correlation-wrong")
        correlation = self.execute(transport, request=mismatched_request)
        self.assertEqual(correlation.failure.code, "COUNCIL_CORRELATION_MISMATCH")
        self.assertEqual(transport.calls, 0)

        live_supporting = CouncilSupportingInput.from_bytes(
            supporting_payload(run_mode="LIVE", input_id="council-live-input-001")
        )
        mode = self.execute(transport, supporting_input=live_supporting)
        self.assertEqual(mode.failure.code, "COUNCIL_MODE_MISMATCH")
        self.assertEqual(transport.calls, 0)

    def test_live_transport_never_substitutes_replay_mode(self) -> None:
        live_request = replay_request(
            mission_id=self.request.mission_id or "",
            run_mode="LIVE",
        )
        live_supporting = CouncilSupportingInput.from_bytes(
            supporting_payload(run_mode="LIVE", input_id="council-live-input-001")
        )
        transport = RecordingCouncilTransport(native_state="MIXED")
        result = self.execute(
            transport,
            request=live_request,
            supporting_input=live_supporting,
        )

        self.assertEqual(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.transport, CouncilTransportKind.LIVE_MISSION_INPUTS)
        self.assertEqual(transport.request.supporting_input["run_mode"], "LIVE")

    def test_existing_native_output_is_never_overwritten(self) -> None:
        protected = self.context.output_absolute / "council_synthesis.json"
        protected.write_bytes(b"do-not-overwrite\n")
        transport = RecordingCouncilTransport()
        result = self.execute(transport)

        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_IMMUTABLE_COLLISION")
        self.assertEqual(transport.calls, 0)
        self.assertEqual(protected.read_bytes(), b"do-not-overwrite\n")


class CouncilWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.artifacts_root = self.base / "artifacts"
        self.store = MissionStore(self.artifacts_root)
        self.request = replay_request()
        self._initialize_completed_oracle(self.request)

        battlestar_root = self.base / "battlestar"
        oracle_module = battlestar_root / "blackpod/runtime/oracle_pipeline.py"
        oracle_module.parent.mkdir(parents=True)
        oracle_module.write_text("# fake module\n", encoding="utf-8")
        fleet_path = battlestar_root / "configs/universes/oracles_vapors.example.yaml"
        fleet_path.parent.mkdir(parents=True)
        fleet_path.write_text("fleet_id: test\n", encoding="utf-8")
        self.config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=oracle_module.resolve(),
            fleet_path=fleet_path.resolve(),
            git_revision=COUNCIL_REVISION,
            git_branch="fixture-council",
            dirty_worktree=True,
        )
        self.replay_fixture = self.base / "council-replay.json"
        self.replay_fixture.write_bytes(supporting_payload())
        self.settings = CouncilRunSettings(
            mission_id=self.request.mission_id or "",
            artifacts_root=self.artifacts_root,
            replay_fixture=self.replay_fixture,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def config_loader(self, **kwargs):
        return self.config

    def execute_workflow(self, adapter):
        return run_council(
            self.settings,
            adapter=adapter,
            config_loader=self.config_loader,
        )

    def _initialize_completed_oracle(
        self, request: MissionRequest, *, store: MissionStore | None = None
    ) -> None:
        target_store = self.store if store is None else store
        initialized = target_store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        fleet = target_store.write_immutable_artifact(
            request.mission_id or "",
            relative_path="oracle/inputs/oracles_vapors.example.yaml",
            payload=b"fleet_id: fixture\n",
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=OBSERVED_AT,
        )
        oracle_provenance = ComponentProvenance.from_mapping(
            {
                "git_revision": ORACLE_REVISION,
                "git_branch": "fixture-oracle",
                "dirty_worktree": False,
                "oracle_entry_point": (
                    "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
                ),
                "run_mode": request.run_mode.value,
                "transport": (
                    OracleTransportKind.REPLAY_FIXTURE.value
                    if request.run_mode.value == "REPLAY"
                    else OracleTransportKind.LIVE_YFINANCE.value
                ),
                "replay_fixture_id": (
                    "oracle-input-001" if request.run_mode.value == "REPLAY" else None
                ),
                "replay_fixture_sha256": (
                    "c" * 64 if request.run_mode.value == "REPLAY" else None
                ),
            }
        )
        running = begin_oracle(
            initialized.snapshot,
            previous_snapshot_sha256=initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=oracle_provenance,
            input_artifacts=(fleet,),
        )
        running_digest = target_store.commit_snapshot(initialized.paths, running)
        outputs = []
        for name, path in REQUIRED_ORACLE_INPUTS.items():
            outputs.append(
                target_store.write_immutable_artifact(
                    request.mission_id or "",
                    relative_path=path,
                    payload=(json.dumps({"artifact": name}) + "\n").encode(),
                    name=name,
                    producer="oracle",
                    schema_version=None,
                    observed_at=OBSERVED_AT,
                )
            )
        succeeded = complete_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            native_state="READY",
            output_artifacts=outputs,
        )
        target_store.commit_snapshot(initialized.paths, succeeded)

    def test_success_writes_running_and_success_revisions(self) -> None:
        adapter = SuccessfulCouncilAdapter(native_state="CONFLICTED")
        result = self.execute_workflow(adapter)
        council = result.snapshot.stages["council"]

        self.assertEqual(result.action, CouncilAction.EXECUTED)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(result.snapshot.revision, 5)
        self.assertEqual(council.status, StageStatus.SUCCEEDED)
        self.assertEqual(council.native_state, "CONFLICTED")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.GOVERNOR)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(result.snapshot.terminal)
        self.assertEqual(result.snapshot.stages["governor"].status, StageStatus.NOT_STARTED)
        self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED)
        self.assertEqual(set(result.snapshot.stages), {
            "harbormaster", "oracle", "council", "governor", "navigator"
        })

        revisions = result.paths.snapshots_dir
        running = json.loads((revisions / "mission_snapshot-r0004.json").read_text())
        success = json.loads((revisions / "mission_snapshot-r0005.json").read_text())
        self.assertEqual(running["stages"]["council"]["status"], "RUNNING")
        self.assertEqual(success["stages"]["council"]["status"], "SUCCEEDED")
        self.assertEqual(
            running["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0003.json"),
        )
        self.assertEqual(
            success["previous_snapshot_sha256"],
            sha256_file(revisions / "mission_snapshot-r0004.json"),
        )

    def test_modeldock_narrative_is_validated_carry_forward_not_native_policy(self) -> None:
        from tests.test_oracle_enrichment_workflow import (
            OracleEnrichmentWorkflowTests,
        )

        harness = OracleEnrichmentWorkflowTests(methodName="runTest")
        harness.setUp()
        try:
            enriched = harness.execute()
            replay_fixture = harness.base / "council-after-modeldock-replay.json"
            replay_fixture.write_bytes(supporting_payload())
            adapter = SuccessfulCouncilAdapter(native_state="ALIGNED")

            result = run_council(
                CouncilRunSettings(
                    mission_id=enriched.request.mission_id or "",
                    artifacts_root=harness.artifacts_root,
                    replay_fixture=replay_fixture,
                ),
                adapter=adapter,
                config_loader=self.config_loader,
            )

            self.assertEqual(result.snapshot.revision, 7)
            self.assertEqual(
                adapter.received_modeldock_narrative_path,
                "oracle/modeldock/oracle_narrative.json",
            )
            lineage = json.loads(
                (result.paths.mission_root / COUNCIL_LINEAGE_PATH).read_text()
            )
            inputs = {item["name"]: item for item in lineage["inputs"]}
            self.assertEqual(
                inputs["oracle_modeldock_narrative"]["usage"],
                "VALIDATED_CARRY_FORWARD_CONTEXT",
            )
            self.assertEqual(
                lineage["validated_carry_forward_context_names"],
                ["oracle_modeldock_narrative"],
            )
            outputs = {item["name"]: item for item in lineage["outputs"]}
            self.assertNotIn(
                "oracle_modeldock_narrative",
                outputs["council_synthesis"]["source_input_names"],
            )
            self.assertNotIn(
                "oracle_modeldock_narrative",
                outputs["council_executive_summary"]["source_input_names"],
            )
        finally:
            harness.tearDown()

    def test_lineage_hashes_correlation_and_dissent_are_preserved(self) -> None:
        result = self.execute_workflow(
            SuccessfulCouncilAdapter(native_state="CONFLICTED")
        )
        root = result.paths.mission_root
        for artifact in result.snapshot.artifacts:
            target = root / artifact.path
            self.assertTrue(target.resolve().is_relative_to(root))
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        artifacts = {item.name: item for item in result.snapshot.artifacts}
        for name, _producer, native_contract in (
            COUNCIL_NATIVE_OUTPUT_ARTIFACTS.values()
        ):
            self.assertEqual(artifacts[name].schema_version, native_contract)

        lineage = json.loads((root / COUNCIL_LINEAGE_PATH).read_text())
        self.assertEqual(lineage["mission_id"], self.request.mission_id)
        self.assertEqual(lineage["request_id"], self.request.request_id)
        self.assertEqual(
            {item["name"] for item in lineage["inputs"]},
            {*REQUIRED_ORACLE_INPUTS, "council_supporting_input"},
        )
        for entry in (*lineage["inputs"], *lineage["outputs"]):
            self.assertEqual(entry["mission_id"], self.request.mission_id)
            self.assertEqual(entry["request_id"], self.request.request_id)
            self.assertTrue(entry["originating_component_revision"])
            self.assertFalse(Path(entry["path"]).is_absolute())
        output_lineage = {item["name"]: item for item in lineage["outputs"]}
        supporting_lineage = next(
            item
            for item in lineage["inputs"]
            if item["name"] == "council_supporting_input"
        )
        self.assertEqual(
            supporting_lineage["originating_component_revision"],
            f"sha256:{artifacts['council_supporting_input'].sha256}",
        )
        self.assertEqual(
            set(output_lineage["council_advisor_health"]["source_input_names"]),
            {"council_advisor_runtime_validation", "council_input_packet"},
        )
        synthesis_sources = set(
            output_lineage["council_synthesis"]["source_input_names"]
        )
        self.assertTrue(
            {
                *REQUIRED_ORACLE_INPUTS,
                "council_supporting_input",
                "council_mandate_policy",
                "council_candidate_evidence",
                "council_senate_review_evidence",
                "council_senate_deliberation_evidence",
                "council_input_packet",
                "council_advisor_health",
            }.issubset(synthesis_sources)
        )
        self.assertIn(
            "council_synthesis",
            output_lineage["council_executive_summary"]["source_input_names"],
        )
        synthesis = (root / COUNCIL_ATTEMPT_DIRECTORY / "council_synthesis.json").read_text()
        self.assertIn("Senate and Oracle remain divided", synthesis)
        canonical = json.dumps(result.snapshot.to_dict())
        self.assertNotIn(str(self.config.root), canonical)
        self.assertNotIn(str(self.replay_fixture.resolve()), canonical)

    def test_repeated_identical_success_is_validated_no_op(self) -> None:
        adapter = SuccessfulCouncilAdapter()
        first = self.execute_workflow(adapter)
        r5 = (first.paths.snapshots_dir / "mission_snapshot-r0005.json").read_bytes()
        second = self.execute_workflow(adapter)

        self.assertEqual(second.action, CouncilAction.NO_OP_ALREADY_SUCCEEDED)
        self.assertEqual(second.snapshot.revision, 5)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            (first.paths.snapshots_dir / "mission_snapshot-r0005.json").read_bytes(),
            r5,
        )
        self.assertFalse((first.paths.snapshots_dir / "mission_snapshot-r0006.json").exists())

    def test_failure_commits_failed_revision_and_repeat_conflicts(self) -> None:
        result = self.execute_workflow(FailedCouncilAdapter(resumable=True))
        council = result.snapshot.stages["council"]
        self.assertEqual(council.status, StageStatus.FAILED)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(result.snapshot.terminal)
        self.assertIsNotNone(council.error)
        with self.assertRaisesRegex(CouncilStateConflictError, "previously FAILED"):
            self.execute_workflow(FailedCouncilAdapter())

    def test_nonresumable_failure_is_terminal(self) -> None:
        result = self.execute_workflow(FailedCouncilAdapter(resumable=False))
        self.assertTrue(result.snapshot.terminal)

    def test_interrupted_attempt_remains_running_and_restart_conflicts(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            self.execute_workflow(InterruptedCouncilAdapter())
        loaded = self.store.load_mission(self.request.mission_id or "")
        self.assertEqual(loaded.snapshot.stages["council"].status, StageStatus.RUNNING)
        with self.assertRaisesRegex(CouncilStateConflictError, "already RUNNING"):
            self.execute_workflow(SuccessfulCouncilAdapter())

    def test_adapter_correlation_mismatch_becomes_technical_failure(self) -> None:
        result = self.execute_workflow(MismatchedCouncilAdapter())
        self.assertEqual(result.snapshot.stages["council"].status, StageStatus.FAILED)
        self.assertEqual(
            result.snapshot.stages["council"].error.code,
            "COUNCIL_ADAPTER_FAILURE",
        )

    def test_malformed_adapter_return_becomes_technical_failure(self) -> None:
        result = self.execute_workflow(MalformedCouncilAdapter())
        self.assertEqual(result.snapshot.stages["council"].status, StageStatus.FAILED)
        self.assertEqual(
            result.snapshot.stages["council"].error.code,
            "COUNCIL_ADAPTER_FAILURE",
        )

    def test_missing_oracle_artifact_is_not_repaired(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        report = next(item for item in loaded.snapshot.artifacts if item.name == "oracle_report")
        target = loaded.paths.mission_root / report.path
        target.unlink()
        with self.assertRaises(PersistenceError):
            self.execute_workflow(SuccessfulCouncilAdapter())

    def test_oracle_artifact_hash_mismatch_is_rejected(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        report = next(
            item for item in loaded.snapshot.artifacts if item.name == "oracle_report"
        )
        target = loaded.paths.mission_root / report.path
        target.write_bytes(target.read_bytes() + b"tampered\n")
        with self.assertRaises(PersistenceError):
            self.execute_workflow(SuccessfulCouncilAdapter())

    def test_wrong_phase_is_rejected_before_writes(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        value = loaded.snapshot.to_dict()
        value.update(
            {
                "revision": 4,
                "snapshot_id": f"{self.request.mission_id}-r0004",
                "previous_snapshot_sha256": loaded.current_snapshot_sha256,
                "current_phase": "ORACLE",
            }
        )
        self.store.commit_snapshot(loaded.paths, MissionSnapshot.from_mapping(value))
        with self.assertRaisesRegex(CouncilPreconditionError, "COUNCIL phase"):
            self.execute_workflow(SuccessfulCouncilAdapter())
        self.assertFalse((loaded.paths.mission_root / COUNCIL_SUPPORTING_INPUT_PATH).exists())

    def test_oracle_not_completed_is_rejected(self) -> None:
        other_root = self.base / "phase1-only"
        store = MissionStore(other_root)
        request = replay_request(mission_id="mission-phase1-only")
        store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        with self.assertRaisesRegex(CouncilPreconditionError, "Oracle"):
            run_council(
                CouncilRunSettings(
                    mission_id=request.mission_id or "",
                    artifacts_root=other_root,
                    replay_fixture=self.replay_fixture,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )

    def test_missing_mission_is_reported(self) -> None:
        with self.assertRaises(MissionNotFoundError):
            run_council(
                CouncilRunSettings(
                    mission_id="mission-does-not-exist",
                    artifacts_root=self.artifacts_root,
                    replay_fixture=self.replay_fixture,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )

    def test_live_and_replay_never_fall_back(self) -> None:
        with self.assertRaisesRegex(CouncilInvocationError, "require --replay-fixture"):
            run_council(
                CouncilRunSettings(
                    mission_id=self.request.mission_id or "",
                    artifacts_root=self.artifacts_root,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(CouncilInvocationError, "may not receive --policy-input"):
            run_council(
                CouncilRunSettings(
                    mission_id=self.request.mission_id or "",
                    artifacts_root=self.artifacts_root,
                    replay_fixture=self.replay_fixture,
                    policy_input=self.replay_fixture,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )

    def test_live_uses_only_explicit_live_policy_input(self) -> None:
        live_root = self.base / "live-artifacts"
        live_store = MissionStore(live_root)
        request = replay_request(
            mission_id="mission-council-live-001",
            run_mode="LIVE",
        )
        self._initialize_completed_oracle(request, store=live_store)
        policy = self.base / "council-live-policy.json"
        policy.write_bytes(supporting_payload(run_mode="LIVE", input_id="live-policy-001"))
        adapter = SuccessfulCouncilAdapter(native_state="MIXED")

        result = run_council(
            CouncilRunSettings(
                mission_id=request.mission_id or "",
                artifacts_root=live_root,
                policy_input=policy,
            ),
            adapter=adapter,
            config_loader=self.config_loader,
            clock=lambda: datetime(2026, 7, 18, 18, 6, tzinfo=UTC),
        )

        self.assertEqual(result.snapshot.stages["council"].status, StageStatus.SUCCEEDED)
        self.assertEqual(adapter.received_mode.value, "LIVE")
        with self.assertRaisesRegex(CouncilInvocationError, "LIVE missions"):
            run_council(
                CouncilRunSettings(
                    mission_id=request.mission_id or "",
                    artifacts_root=live_root,
                    replay_fixture=self.replay_fixture,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )

    def test_malformed_supporting_input_is_rejected_before_council_write(self) -> None:
        self.replay_fixture.write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(CouncilInvocationError, "schema validation"):
            self.execute_workflow(SuccessfulCouncilAdapter())
        loaded = self.store.load_mission(self.request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 3)
        self.assertFalse(
            (loaded.paths.mission_root / COUNCIL_SUPPORTING_INPUT_PATH).exists()
        )

    def test_existing_attempt_artifact_is_not_overwritten(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        attempt = loaded.paths.mission_root / COUNCIL_ATTEMPT_DIRECTORY
        attempt.mkdir(parents=True)
        protected = attempt / "council_synthesis.json"
        protected.write_bytes(b"do-not-overwrite\n")
        result = self.execute_workflow(SuccessfulCouncilAdapter())

        self.assertEqual(result.snapshot.stages["council"].status, StageStatus.FAILED)
        self.assertEqual(protected.read_bytes(), b"do-not-overwrite\n")

    def test_existing_immutable_supporting_input_is_not_overwritten(self) -> None:
        loaded = self.store.load_mission(self.request.mission_id or "")
        target = loaded.paths.mission_root / COUNCIL_SUPPORTING_INPUT_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(b"do-not-overwrite\n")
        with self.assertRaises(ImmutableArtifactError):
            self.execute_workflow(SuccessfulCouncilAdapter())
        self.assertEqual(target.read_bytes(), b"do-not-overwrite\n")

    def test_changed_fixture_is_not_identical_completed_invocation(self) -> None:
        self.execute_workflow(SuccessfulCouncilAdapter())
        changed = self.base / "changed-council-replay.json"
        changed.write_bytes(supporting_payload(input_id="council-input-002"))
        with self.assertRaisesRegex(CouncilStateConflictError, "does not match"):
            run_council(
                CouncilRunSettings(
                    mission_id=self.request.mission_id or "",
                    artifacts_root=self.artifacts_root,
                    replay_fixture=changed,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=self.config_loader,
            )

    def test_preflight_failure_happens_before_artifact_root_is_touched(self) -> None:
        untouched = self.base / "must-remain-absent"

        def rejected_config(**kwargs):
            raise BattlestarConfigurationError("Council module missing")

        with self.assertRaises(BattlestarConfigurationError):
            run_council(
                CouncilRunSettings(
                    mission_id="mission-not-inspected",
                    artifacts_root=untouched,
                    replay_fixture=self.replay_fixture,
                ),
                adapter=SuccessfulCouncilAdapter(),
                config_loader=rejected_config,
            )
        self.assertFalse(untouched.exists())

    def test_provenance_and_lineage_hash_exact_committed_bytes(self) -> None:
        result = self.execute_workflow(SuccessfulCouncilAdapter())
        artifacts = {item.name: item for item in result.snapshot.artifacts}
        for name, path in (
            ("council_provenance", COUNCIL_PROVENANCE_PATH),
            ("council_lineage_manifest", COUNCIL_LINEAGE_PATH),
        ):
            self.assertEqual(
                artifacts[name].sha256,
                sha256_bytes((result.paths.mission_root / path).read_bytes()),
            )


if __name__ == "__main__":
    unittest.main()
