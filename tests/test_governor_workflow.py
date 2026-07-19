from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import (
    ComponentProvenance,
    CouncilComponentProvenance,
    CouncilTransportKind,
    CurrentPhase,
    GovernorTransportKind,
    MissionOutcome,
    MissionRequest,
    OperatorRoute,
    OracleTransportKind,
    RunMode,
    StageStatus,
)
from blackpod_build_week.governor_adapter import (
    GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
    GovernorExecutionResult,
    GovernorFailure,
)
from blackpod_build_week.governor_workflow import (
    GOVERNOR_ATTEMPT_DIRECTORY,
    GOVERNOR_LINEAGE_PATH,
    GOVERNOR_NATIVE_OUTPUT_ARTIFACTS,
    GOVERNOR_SUPPORTING_CONTEXT_PATH,
    REQUIRED_GOVERNOR_INPUTS,
    GovernorAction,
    GovernorInvocationError,
    GovernorPreconditionError,
    GovernorRunSettings,
    GovernorStateConflictError,
    run_governor,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_store import (
    ImmutableArtifactError,
    MissionNotFoundError,
    MissionStore,
    PersistenceError,
)
from blackpod_build_week.mission_transitions import (
    begin_council,
    begin_oracle,
    complete_council,
    complete_oracle,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"
ORACLE_REVISION = "a" * 40
COUNCIL_REVISION = "b" * 40
GOVERNOR_REVISION = "c" * 40
ROUTINE_WARNING = "MISSING_PRIOR_ORACLE_MEASUREMENTS"


def _request(
    mission_id: str = "mission-governor-workflow-001",
    *,
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
            "operator_id": "operator-governor-workflow",
            "metadata": {},
        }
    )


def _supporting_context_bytes(
    request: MissionRequest,
    *,
    context_id: str | None = None,
    replay_contract_case: str = "NORMAL",
    include_accountability: bool = True,
) -> bytes:
    payload: dict[str, object] = {
        "schema_version": GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
        "context_id": context_id or f"governor-context-{request.mission_id}",
        "mission_id": request.mission_id,
        "request_id": request.request_id,
        "run_mode": request.run_mode.value,
        "generated_at": OBSERVED_AT,
        "replay_contract_case": replay_contract_case,
    }
    if include_accountability:
        payload["accountability"] = {
            "outcomes": [],
            "notes": "No prior accountability observations are available.",
        }
    return canonical_json_bytes(payload)


def _oracle_provenance(run_mode: RunMode) -> ComponentProvenance:
    replay = run_mode is RunMode.REPLAY
    return ComponentProvenance.from_mapping(
        {
            "git_revision": ORACLE_REVISION,
            "git_branch": "fixture-oracle",
            "dirty_worktree": False,
            "oracle_entry_point": "blackpod.runtime.oracle_pipeline.run_oracle_pipeline",
            "run_mode": run_mode.value,
            "transport": (
                OracleTransportKind.REPLAY_FIXTURE.value
                if replay
                else OracleTransportKind.LIVE_YFINANCE.value
            ),
            "replay_fixture_id": "oracle-fixture-001" if replay else None,
            "replay_fixture_sha256": "d" * 64 if replay else None,
        }
    )


def _council_provenance(run_mode: RunMode) -> CouncilComponentProvenance:
    replay = run_mode is RunMode.REPLAY
    return CouncilComponentProvenance.from_mapping(
        {
            "git_revision": COUNCIL_REVISION,
            "git_branch": "fixture-council",
            "dirty_worktree": False,
            "candidate_entry_point": "blackpod.advisors.candidate.build",
            "senate_review_entry_point": "blackpod.advisors.senate_review.build",
            "senate_deliberation_entry_point": "blackpod.advisors.senate.build",
            "mandate_entry_point": "blackpod.advisors.mandate.MandateAdvisor.run",
            "runtime_validation_entry_point": "blackpod.runtime.validation.build",
            "advisor_health_entry_point": "blackpod.runtime.health.build",
            "council_synthesis_entry_point": "blackpod.governor.council.build",
            "council_executive_summary_entry_point": "blackpod.governor.summary.build",
            "run_mode": run_mode.value,
            "transport": (
                CouncilTransportKind.REPLAY_FIXTURE.value
                if replay
                else CouncilTransportKind.LIVE_MISSION_INPUTS.value
            ),
            "replay_fixture_id": "council-fixture-001" if replay else None,
            "replay_fixture_sha256": "e" * 64 if replay else None,
        }
    )


def _native_input_payload(
    name: str,
    *,
    summary_synthesis_id: str = "council-synthesis-001",
) -> dict[str, object]:
    if name == "oracle_report":
        return {
            "report_id": "oracle-report-001",
            "warnings": [ROUTINE_WARNING],
            "blockers": [],
        }
    if name == "oracle_measurement_diagnostics":
        return {"diagnostics_id": "oracle-diagnostics-001", "diagnostics_state": "READY"}
    if name == "oracle_readiness_report":
        return {"readiness_id": "oracle-readiness-001", "readiness_state": "READY"}
    if name == "council_synthesis":
        return {"synthesis_id": "council-synthesis-001", "synthesis_state": "MIXED"}
    if name == "council_executive_summary":
        return {
            "summary_id": "council-summary-001",
            "synthesis_id": summary_synthesis_id,
        }
    if name == "council_senate_deliberation_evidence":
        return {
            "deliberation_id": "senate-deliberation-001",
            "items": [
                {
                    "candidate_id": "candidate-001",
                    "market_context": {"oracle_report_id": "oracle-report-001"},
                }
            ],
        }
    if name == "council_mandate_policy":
        return {
            "as_of": OBSERVED_AT,
            "ok": True,
            "reason": "BUILD_WEEK_POLICY_OK",
            "allowed_sides": ["BUY", "SELL"],
            "max_trades": 2,
            "risk_posture": "NORMAL",
        }
    return {"artifact": name, "warnings": [], "blockers": []}


def _build_council_completed_mission(
    store: MissionStore,
    request: MissionRequest,
    *,
    lineage_request_id: str | None = None,
    summary_synthesis_id: str = "council-synthesis-001",
) -> None:
    mission_id = request.mission_id or ""
    initialized = store.initialize(
        request,
        mission_id=mission_id,
        started_at=OBSERVED_AT,
        observed_at=OBSERVED_AT,
    )
    oracle_input = store.write_immutable_artifact(
        mission_id,
        relative_path="oracle/inputs/oracles_vapors.example.yaml",
        payload=b"fleet_id: fixture\n",
        name="oracle_fleet_input",
        producer="battlestar",
        schema_version=None,
        observed_at=OBSERVED_AT,
    )
    oracle_running = begin_oracle(
        initialized.snapshot,
        previous_snapshot_sha256=initialized.snapshot_sha256,
        observed_at=OBSERVED_AT,
        provenance=_oracle_provenance(request.run_mode),
        input_artifacts=(oracle_input,),
    )
    oracle_running_digest = store.commit_snapshot(initialized.paths, oracle_running)
    oracle_outputs = []
    for name, (path, producer, contract) in REQUIRED_GOVERNOR_INPUTS.items():
        if not name.startswith("oracle_"):
            continue
        oracle_outputs.append(
            store.write_immutable_artifact(
                mission_id,
                relative_path=path,
                payload=canonical_json_bytes(_native_input_payload(name)),
                name=name,
                producer=producer,
                schema_version=contract,
                observed_at=OBSERVED_AT,
            )
        )
    oracle_complete = complete_oracle(
        oracle_running,
        previous_snapshot_sha256=oracle_running_digest,
        observed_at=OBSERVED_AT,
        native_state="READY",
        output_artifacts=oracle_outputs,
    )
    oracle_complete_digest = store.commit_snapshot(initialized.paths, oracle_complete)

    council_context = store.write_immutable_artifact(
        mission_id,
        relative_path="council/inputs/council_supporting_input.json",
        payload=canonical_json_bytes({"input_id": "council-fixture-001"}),
        name="council_supporting_input",
        producer="harbormaster" if request.run_mode is RunMode.REPLAY else "operator",
        schema_version="blackpod.council_supporting_input.v1",
        observed_at=OBSERVED_AT,
    )
    council_running = begin_council(
        oracle_complete,
        previous_snapshot_sha256=oracle_complete_digest,
        observed_at=OBSERVED_AT,
        provenance=_council_provenance(request.run_mode),
        existing_input_names=tuple(item.name for item in oracle_outputs),
        input_artifacts=(council_context,),
    )
    council_running_digest = store.commit_snapshot(initialized.paths, council_running)
    council_outputs = []
    for name, (path, producer, contract) in REQUIRED_GOVERNOR_INPUTS.items():
        if name.startswith("oracle_") or name == "council_lineage_manifest":
            continue
        council_outputs.append(
            store.write_immutable_artifact(
                mission_id,
                relative_path=path,
                payload=canonical_json_bytes(
                    _native_input_payload(
                        name,
                        summary_synthesis_id=summary_synthesis_id,
                    )
                ),
                name=name,
                producer=producer,
                schema_version=contract,
                observed_at=OBSERVED_AT,
            )
        )

    lineage_payload = {
        "schema_version": "blackpod.council_lineage.v1",
        "mission_id": mission_id,
        "request_id": lineage_request_id or request.request_id,
        "run_mode": request.run_mode.value,
        "observed_at": OBSERVED_AT,
        "inputs": [],
        "outputs": [
            {
                "name": artifact.name,
                "path": artifact.path,
                "producer": artifact.producer,
                "sha256": artifact.sha256,
                "byte_size": artifact.byte_size,
                "schema_version": artifact.schema_version,
                "observed_at": artifact.observed_at,
                "native_contract": artifact.schema_version,
                "originating_component_revision": COUNCIL_REVISION,
                "mission_id": mission_id,
                "request_id": request.request_id,
            }
            for artifact in council_outputs
        ],
    }
    lineage_spec = REQUIRED_GOVERNOR_INPUTS["council_lineage_manifest"]
    lineage = store.write_immutable_artifact(
        mission_id,
        relative_path=lineage_spec[0],
        payload=canonical_json_bytes(lineage_payload),
        name="council_lineage_manifest",
        producer=lineage_spec[1],
        schema_version=lineage_spec[2],
        observed_at=OBSERVED_AT,
    )
    council_complete = complete_council(
        council_running,
        previous_snapshot_sha256=council_running_digest,
        observed_at=OBSERVED_AT,
        native_state="MIXED",
        output_artifacts=(*council_outputs, lineage),
    )
    store.commit_snapshot(initialized.paths, council_complete)


@dataclass(frozen=True)
class PreparedMission:
    store: MissionStore
    request: MissionRequest
    artifacts_root: Path
    supporting_context: Path


class SuccessfulGovernorAdapter:
    def __init__(self, disposition: str = "PROCEED") -> None:
        self.disposition = disposition
        self.calls = 0
        self.received_mode: RunMode | None = None

    def execute(self, request, context, *, supporting_context):
        self.calls += 1
        self.received_mode = supporting_context.run_mode
        allowed_next_step = (
            "OPERATOR_REVIEW"
            if self.disposition in {"PROCEED", "HOLD", "REVIEW_REQUIRED"}
            else "NONE"
        )
        readiness_state = {
            "PROCEED": "READY",
            "HOLD": "READY",
            "REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "BLOCKED": "BLOCKED",
            "STAND_DOWN": "INVALID",
        }[self.disposition]
        output = context.mission_root / context.output_dir
        for filename, (_artifact_name, contract) in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS.items():
            payload: dict[str, object] = {
                "schema_version": contract,
                "artifact": filename,
                "mission_id": context.mission_id,
                "request_id": request.request_id,
            }
            if filename == "governor_decision.json":
                payload.update(
                    {
                        "decision_id": f"governor-decision-{self.disposition.lower()}",
                        "decision_state": self.disposition,
                        "allowed_next_step": allowed_next_step,
                        "warnings": [ROUTINE_WARNING],
                        "blockers": [],
                    }
                )
            elif filename == "governor_decision_readiness.json":
                payload.update({"readiness_state": readiness_state})
            elif filename == "warning_classification.json":
                payload.update(
                    {
                        "warnings": [ROUTINE_WARNING],
                        "classifications": [
                            {
                                "warning": ROUTINE_WARNING,
                                "classification": "NON_DEGRADING",
                            }
                        ],
                    }
                )
            elif filename == "governor_rendered_decision.json":
                payload.update(
                    {
                        "native_disposition": self.disposition,
                        "readiness_state": readiness_state,
                        "allowed_next_step": allowed_next_step,
                    }
                )
            (output / filename).write_bytes(canonical_json_bytes(payload))
        return GovernorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=(
                GovernorTransportKind.REPLAY_FIXTURE
                if request.run_mode is RunMode.REPLAY
                else GovernorTransportKind.LIVE_MISSION_INPUTS
            ),
            status=StageStatus.SUCCEEDED,
            native_disposition=self.disposition,
            readiness_state=readiness_state,
            decision_id=f"governor-decision-{self.disposition.lower()}",
            allowed_next_step=allowed_next_step,
            warnings=(ROUTINE_WARNING,),
            blocking_reasons=(
                ("MANDATE_REVIEW_REQUIRED",)
                if self.disposition == "BLOCKED"
                else ()
            ),
            review_requirements=(
                ("OPERATOR_REVIEW",)
                if self.disposition in {"HOLD", "REVIEW_REQUIRED"}
                else ()
            ),
            produced_paths=tuple(
                f"{context.output_dir}/{filename}"
                for filename in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS
            ),
            source_lineage=(
                *(REQUIRED_GOVERNOR_INPUTS[name][0] for name in REQUIRED_GOVERNOR_INPUTS),
                GOVERNOR_SUPPORTING_CONTEXT_PATH,
            ),
            failure=None,
            context_id=supporting_context.context_id,
            routine_warnings=(ROUTINE_WARNING,),
        )


class FailedGovernorAdapter:
    def __init__(self, *, resumable: bool = True) -> None:
        self.calls = 0
        self.resumable = resumable

    def execute(self, request, context, *, supporting_context):
        self.calls += 1
        return GovernorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=GovernorTransportKind.REPLAY_FIXTURE,
            status=StageStatus.FAILED,
            native_disposition=None,
            readiness_state=None,
            decision_id=None,
            allowed_next_step=None,
            warnings=(),
            blocking_reasons=(),
            review_requirements=(),
            produced_paths=(),
            source_lineage=(),
            failure=GovernorFailure(
                code="GOVERNOR_EXECUTION_FAILED",
                error_type="FixtureFailure",
                message="deterministic Governor technical failure",
                resumable=self.resumable,
            ),
            context_id=supporting_context.context_id,
        )


class InterruptedGovernorAdapter:
    def execute(self, request, context, *, supporting_context):
        raise KeyboardInterrupt("simulated Governor interruption")


class UnsafeGovernorAdapter(SuccessfulGovernorAdapter):
    def execute(self, request, context, *, supporting_context):
        result = super().execute(
            request,
            context,
            supporting_context=supporting_context,
        )
        values = {
            field_name: getattr(result, field_name)
            for field_name in result.__dataclass_fields__
        }
        values["produced_paths"] = (*result.produced_paths[:-1], "/tmp/escape.json")
        return GovernorExecutionResult(**values)


class GovernorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        battlestar_root = self.base / "battlestar"
        battlestar_root.mkdir()
        oracle_module = battlestar_root / "oracle.py"
        oracle_module.write_text("# fixture\n", encoding="utf-8")
        fleet = battlestar_root / "fleet.yaml"
        fleet.write_text("fleet_id: fixture\n", encoding="utf-8")
        self.config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=oracle_module.resolve(),
            fleet_path=fleet.resolve(),
            git_revision=GOVERNOR_REVISION,
            git_branch="fixture-governor",
            dirty_worktree=False,
        )
        self.default = self.prepare("default")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def config_loader(self, **_kwargs) -> BattlestarConfig:
        return self.config

    def prepare(
        self,
        suffix: str,
        *,
        run_mode: str = "REPLAY",
        lineage_request_id: str | None = None,
        summary_synthesis_id: str = "council-synthesis-001",
        replay_contract_case: str = "NORMAL",
    ) -> PreparedMission:
        request = _request(f"mission-governor-{suffix}", run_mode=run_mode)
        artifacts_root = self.base / f"artifacts-{suffix}"
        store = MissionStore(artifacts_root)
        _build_council_completed_mission(
            store,
            request,
            lineage_request_id=lineage_request_id,
            summary_synthesis_id=summary_synthesis_id,
        )
        context = self.base / f"governor-context-{suffix}.json"
        context.write_bytes(
            _supporting_context_bytes(
                request,
                replay_contract_case=replay_contract_case,
            )
        )
        return PreparedMission(store, request, artifacts_root, context)

    def execute(self, prepared: PreparedMission, adapter):
        settings = GovernorRunSettings(
            mission_id=prepared.request.mission_id or "",
            artifacts_root=prepared.artifacts_root,
            replay_fixture=(
                prepared.supporting_context
                if prepared.request.run_mode is RunMode.REPLAY
                else None
            ),
            context_input=(
                prepared.supporting_context
                if prepared.request.run_mode is RunMode.LIVE
                else None
            ),
        )
        return run_governor(
            settings,
            adapter=adapter,
            config_loader=self.config_loader,
        )

    def test_all_rendered_dispositions_are_technical_successes(self) -> None:
        expected = {
            "PROCEED": (CurrentPhase.OPERATOR, MissionOutcome.HELD, False, OperatorRoute.PENDING_APPROVAL),
            "HOLD": (CurrentPhase.OPERATOR, MissionOutcome.HELD, False, OperatorRoute.PENDING_REVIEW),
            "REVIEW_REQUIRED": (CurrentPhase.OPERATOR, MissionOutcome.HELD, False, OperatorRoute.PENDING_REVIEW),
            "BLOCKED": (CurrentPhase.GOVERNOR, MissionOutcome.HELD, True, OperatorRoute.CLOSED_BLOCKED),
            "STAND_DOWN": (CurrentPhase.COMPLETE, MissionOutcome.VETOED, True, OperatorRoute.CLOSED_NO_ACTION),
        }
        for disposition, (phase, outcome, terminal, route) in expected.items():
            with self.subTest(disposition=disposition):
                prepared = self.prepare(
                    disposition.lower().replace("_", "-"),
                    replay_contract_case=(
                        "INVALID_STAND_DOWN"
                        if disposition == "STAND_DOWN"
                        else "NORMAL"
                    ),
                )
                result = self.execute(prepared, SuccessfulGovernorAdapter(disposition))
                governor = result.snapshot.stages["governor"]
                self.assertEqual(governor.status, StageStatus.SUCCEEDED)
                self.assertEqual(governor.native_state, disposition)
                self.assertEqual(result.snapshot.current_phase, phase)
                self.assertEqual(result.snapshot.mission_outcome, outcome)
                self.assertEqual(result.snapshot.terminal, terminal)
                self.assertEqual(result.snapshot.operator.route, route)
                self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED)
                self.assertEqual(
                    set(result.snapshot.stages),
                    {"harbormaster", "oracle", "council", "governor", "navigator"},
                )
                self.assertTrue(
                    all(
                        value is None
                        for value in (
                            result.snapshot.operator.action,
                            result.snapshot.operator.result,
                            result.snapshot.operator.operator_id,
                            result.snapshot.operator.acted_at,
                        )
                    )
                )

    def test_success_writes_running_and_final_hash_chained_revisions(self) -> None:
        r5_path = self.default.store.paths_for(
            self.default.request.mission_id or ""
        ).snapshots_dir / "mission_snapshot-r0005.json"
        r5_before = r5_path.read_bytes()
        result = self.execute(self.default, SuccessfulGovernorAdapter("PROCEED"))
        r6 = result.paths.snapshots_dir / "mission_snapshot-r0006.json"
        r7 = result.paths.snapshots_dir / "mission_snapshot-r0007.json"
        running = json.loads(r6.read_text(encoding="utf-8"))
        final = json.loads(r7.read_text(encoding="utf-8"))
        self.assertEqual(result.snapshot.revision, 7)
        self.assertEqual(running["stages"]["governor"]["status"], "RUNNING")
        self.assertEqual(final["stages"]["governor"]["status"], "SUCCEEDED")
        self.assertEqual(running["previous_snapshot_sha256"], sha256_file(r5_path))
        self.assertEqual(final["previous_snapshot_sha256"], sha256_file(r6))
        self.assertEqual(r5_path.read_bytes(), r5_before)

    def test_warning_classification_is_preserved_without_failure(self) -> None:
        result = self.execute(self.default, SuccessfulGovernorAdapter("PROCEED"))
        warning_path = (
            result.paths.mission_root
            / GOVERNOR_ATTEMPT_DIRECTORY
            / "warning_classification.json"
        )
        payload = json.loads(warning_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["warnings"], [ROUTINE_WARNING])
        self.assertEqual(
            payload["classifications"][0]["classification"],
            "NON_DEGRADING",
        )
        self.assertEqual(result.snapshot.stages["governor"].status, StageStatus.SUCCEEDED)

    def test_lineage_artifacts_are_contained_hash_exact_and_relative(self) -> None:
        result = self.execute(self.default, SuccessfulGovernorAdapter("HOLD"))
        root = result.paths.mission_root
        for artifact in result.snapshot.artifacts:
            self.assertFalse(Path(artifact.path).is_absolute())
            target = root / artifact.path
            self.assertTrue(target.resolve().is_relative_to(root.resolve()))
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        lineage = json.loads((root / GOVERNOR_LINEAGE_PATH).read_text(encoding="utf-8"))
        self.assertEqual(lineage["mission_id"], self.default.request.mission_id)
        self.assertEqual(lineage["request_id"], self.default.request.request_id)
        self.assertEqual(
            {entry["name"] for entry in lineage["inputs"]},
            {*REQUIRED_GOVERNOR_INPUTS, "governor_supporting_context"},
        )
        for entry in (*lineage["inputs"], *lineage["outputs"]):
            self.assertFalse(Path(entry["path"]).is_absolute())
            self.assertTrue(entry["originating_component_revision"])
            self.assertEqual(entry["mission_id"], self.default.request.mission_id)
            self.assertEqual(entry["request_id"], self.default.request.request_id)
        serialized = json.dumps(result.snapshot.to_dict())
        self.assertNotIn(str(self.config.root), serialized)
        self.assertNotIn(str(self.default.supporting_context.resolve()), serialized)

    def test_technical_failure_commits_failed_revision_and_navigator_stays_idle(self) -> None:
        result = self.execute(self.default, FailedGovernorAdapter(resumable=True))
        governor = result.snapshot.stages["governor"]
        self.assertEqual(result.snapshot.revision, 7)
        self.assertEqual(governor.status, StageStatus.FAILED)
        self.assertEqual(governor.error.code, "GOVERNOR_EXECUTION_FAILED")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.GOVERNOR)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(result.snapshot.terminal)
        self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED)
        self.assertIsNone(result.snapshot.operator.route)

    def test_repeated_identical_success_is_an_explicit_no_op(self) -> None:
        adapter = SuccessfulGovernorAdapter("PROCEED")
        first = self.execute(self.default, adapter)
        r7 = (first.paths.snapshots_dir / "mission_snapshot-r0007.json").read_bytes()
        second = self.execute(self.default, adapter)
        self.assertEqual(second.action, GovernorAction.NO_OP_ALREADY_SUCCEEDED)
        self.assertEqual(second.snapshot.revision, 7)
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            (first.paths.snapshots_dir / "mission_snapshot-r0007.json").read_bytes(),
            r7,
        )
        self.assertFalse((first.paths.snapshots_dir / "mission_snapshot-r0008.json").exists())

    def test_interrupted_running_attempt_and_failed_attempt_conflict_on_restart(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            self.execute(self.default, InterruptedGovernorAdapter())
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 6)
        self.assertEqual(loaded.snapshot.stages["governor"].status, StageStatus.RUNNING)
        with self.assertRaisesRegex(GovernorStateConflictError, "already RUNNING"):
            self.execute(self.default, SuccessfulGovernorAdapter())

        failed = self.prepare("failed-conflict")
        self.execute(failed, FailedGovernorAdapter())
        with self.assertRaisesRegex(GovernorStateConflictError, "previously FAILED"):
            self.execute(failed, SuccessfulGovernorAdapter())

    def test_missing_mission_and_incomplete_prior_stages_are_rejected(self) -> None:
        with self.assertRaises(MissionNotFoundError):
            run_governor(
                GovernorRunSettings(
                    mission_id="mission-does-not-exist",
                    artifacts_root=self.base / "missing-artifacts",
                    replay_fixture=self.default.supporting_context,
                ),
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )

        request = _request("mission-governor-phase1-only")
        root = self.base / "phase1-only"
        store = MissionStore(root)
        store.initialize(
            request,
            mission_id=request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        fixture = self.base / "phase1-only-context.json"
        fixture.write_bytes(_supporting_context_bytes(request))
        with self.assertRaisesRegex(GovernorPreconditionError, "Oracle"):
            run_governor(
                GovernorRunSettings(
                    mission_id=request.mission_id or "",
                    artifacts_root=root,
                    replay_fixture=fixture,
                ),
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )

    def test_wrong_phase_and_snapshot_correlation_are_rejected(self) -> None:
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        object.__setattr__(loaded.snapshot, "current_phase", CurrentPhase.COUNCIL)
        with patch(
            "blackpod_build_week.governor_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            with self.assertRaisesRegex(GovernorPreconditionError, "GOVERNOR phase"):
                self.execute(self.default, SuccessfulGovernorAdapter())

        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        object.__setattr__(loaded.snapshot, "request_id", "request-wrong-correlation")
        with patch(
            "blackpod_build_week.governor_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            with self.assertRaisesRegex(GovernorPreconditionError, "correlation"):
                self.execute(self.default, SuccessfulGovernorAdapter())

    def test_missing_or_tampered_council_summary_and_mandate_are_rejected(self) -> None:
        for suffix, artifact_name, mutation in (
            ("missing-summary", "council_executive_summary", "missing"),
            ("tampered-summary", "council_executive_summary", "tamper"),
            ("missing-mandate", "council_mandate_policy", "missing"),
        ):
            with self.subTest(artifact=artifact_name, mutation=mutation):
                prepared = self.prepare(suffix)
                loaded = prepared.store.load_mission(prepared.request.mission_id or "")
                artifact = next(
                    item for item in loaded.snapshot.artifacts if item.name == artifact_name
                )
                target = loaded.paths.mission_root / artifact.path
                if mutation == "missing":
                    target.unlink()
                else:
                    target.write_bytes(target.read_bytes() + b"tampered\n")
                with self.assertRaises(PersistenceError):
                    self.execute(prepared, SuccessfulGovernorAdapter())

    def test_council_lineage_and_native_correlation_mismatches_are_rejected(self) -> None:
        bad_lineage = self.prepare(
            "bad-lineage",
            lineage_request_id="request-unrelated-lineage",
        )
        with self.assertRaisesRegex(GovernorPreconditionError, "lineage correlation"):
            self.execute(bad_lineage, SuccessfulGovernorAdapter())

        bad_summary = self.prepare(
            "bad-summary-correlation",
            summary_synthesis_id="council-synthesis-unrelated",
        )
        with self.assertRaisesRegex(GovernorPreconditionError, "does not correlate"):
            self.execute(bad_summary, SuccessfulGovernorAdapter())

    def test_missing_accountability_context_is_rejected_before_governor_write(self) -> None:
        self.default.supporting_context.write_bytes(
            _supporting_context_bytes(
                self.default.request,
                include_accountability=False,
            )
        )
        with self.assertRaisesRegex(GovernorInvocationError, "schema validation"):
            self.execute(self.default, SuccessfulGovernorAdapter())
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 5)
        self.assertFalse(
            (loaded.paths.mission_root / GOVERNOR_SUPPORTING_CONTEXT_PATH).exists()
        )

    def test_replay_and_live_transport_never_fall_back(self) -> None:
        replay_settings = GovernorRunSettings(
            mission_id=self.default.request.mission_id or "",
            artifacts_root=self.default.artifacts_root,
        )
        with self.assertRaisesRegex(GovernorInvocationError, "require --replay-fixture"):
            run_governor(
                replay_settings,
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(GovernorInvocationError, "may not receive --context-input"):
            run_governor(
                GovernorRunSettings(
                    mission_id=self.default.request.mission_id or "",
                    artifacts_root=self.default.artifacts_root,
                    replay_fixture=self.default.supporting_context,
                    context_input=self.default.supporting_context,
                ),
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )

        live = self.prepare("live", run_mode="LIVE")
        with self.assertRaisesRegex(GovernorInvocationError, "require --context-input"):
            run_governor(
                GovernorRunSettings(
                    mission_id=live.request.mission_id or "",
                    artifacts_root=live.artifacts_root,
                ),
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(GovernorInvocationError, "LIVE missions"):
            run_governor(
                GovernorRunSettings(
                    mission_id=live.request.mission_id or "",
                    artifacts_root=live.artifacts_root,
                    replay_fixture=live.supporting_context,
                ),
                adapter=SuccessfulGovernorAdapter(),
                config_loader=self.config_loader,
            )
        adapter = SuccessfulGovernorAdapter("PROCEED")
        result = self.execute(live, adapter)
        self.assertEqual(result.snapshot.stages["governor"].status, StageStatus.SUCCEEDED)
        self.assertEqual(adapter.received_mode, RunMode.LIVE)

    def test_immutable_attempt_and_snapshot_revision_collisions_do_not_overwrite(self) -> None:
        attempt_collision = self.prepare("attempt-collision")
        paths = attempt_collision.store.paths_for(attempt_collision.request.mission_id or "")
        attempt = paths.mission_root / GOVERNOR_ATTEMPT_DIRECTORY
        attempt.mkdir(parents=True)
        protected = attempt / "protected.txt"
        protected.write_bytes(b"do-not-overwrite\n")
        result = self.execute(attempt_collision, SuccessfulGovernorAdapter())
        self.assertEqual(result.snapshot.stages["governor"].status, StageStatus.FAILED)
        self.assertEqual(protected.read_bytes(), b"do-not-overwrite\n")

        revision_collision = self.prepare("revision-collision")
        paths = revision_collision.store.paths_for(revision_collision.request.mission_id or "")
        r6 = paths.snapshots_dir / "mission_snapshot-r0006.json"
        r6.write_bytes(b"do-not-overwrite\n")
        with self.assertRaises(ImmutableArtifactError):
            self.execute(revision_collision, SuccessfulGovernorAdapter())
        self.assertEqual(r6.read_bytes(), b"do-not-overwrite\n")

    def test_unsafe_adapter_path_becomes_failure_without_path_leak(self) -> None:
        result = self.execute(self.default, UnsafeGovernorAdapter())
        self.assertEqual(result.snapshot.stages["governor"].status, StageStatus.FAILED)
        serialized = json.dumps(result.snapshot.to_dict())
        self.assertNotIn("/tmp/escape.json", serialized)
        self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED)


if __name__ == "__main__":
    unittest.main()
