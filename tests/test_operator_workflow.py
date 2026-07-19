from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import (
    ApprovalScope,
    CurrentPhase,
    GovernorTransportKind,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    RunMode,
    StageStatus,
)
from blackpod_build_week.governor_adapter import GovernorExecutionResult
from blackpod_build_week.governor_workflow import (
    GOVERNOR_ATTEMPT_DIRECTORY,
    GOVERNOR_NATIVE_OUTPUT_ARTIFACTS,
    GOVERNOR_SUPPORTING_CONTEXT_PATH,
    REQUIRED_GOVERNOR_INPUTS,
    GovernorRunSettings,
    run_governor,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_store import (
    MissionNotFoundError,
    MissionStore,
    PersistenceError,
)
from blackpod_build_week.operator_adapter import (
    EXPECTED_OPERATOR_OUTPUT_PATHS,
    OPERATOR_ACTION_PATH,
    OPERATOR_ACTION_SCHEMA_VERSION,
    OPERATOR_ATTEMPT_DIRECTORY,
    OPERATOR_LEDGER_ENTRY_PATH,
    OPERATOR_LINEAGE_PATH,
    OPERATOR_LINEAGE_SCHEMA_VERSION,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_PROVENANCE_SCHEMA_VERSION,
    OPERATOR_RECEIPT_PATH,
    OPERATOR_RECEIPT_SCHEMA_VERSION,
    OPERATOR_REPLAY_INPUT_PATH,
    OPERATOR_REVIEW_PACKET_PATH,
    OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
    OperatorExecutionResult,
    OperatorFailure,
)
from blackpod_build_week.operator_workflow import (
    REQUIRED_OPERATOR_INPUTS_PATHS,
    OperatorInvocationError,
    OperatorPreconditionError,
    OperatorRunSettings,
    OperatorStateConflictError,
    OperatorWorkflowDisposition,
    run_operator_action,
)
from tests.test_governor_workflow import (
    GOVERNOR_REVISION,
    OBSERVED_AT,
    _build_council_completed_mission,
    _request,
    _supporting_context_bytes,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
APPROVE_FIXTURE = FIXTURES / "operator_replay_action.approve.v1.json"
REJECT_FIXTURE = FIXTURES / "operator_replay_action.reject.v1.json"
ACTION_ID = "operator-action-workflow-001"


@dataclass(frozen=True)
class PreparedOperatorMission:
    store: MissionStore
    request: MissionRequest
    artifacts_root: Path


class OperatorReadyGovernorAdapter:
    """Phase 4 fake whose immutable outputs satisfy the operator seam."""

    def __init__(self, *, rendered_request_id: str | None = None) -> None:
        self.rendered_request_id = rendered_request_id

    def execute(self, request, context, *, supporting_context):
        output = context.mission_root / context.output_dir
        decision_id = "governor-decision-operator-ready"
        deliberation_id = "governor-deliberation-operator-ready"
        readiness_id = "governor-readiness-operator-ready"
        for filename, (_name, contract) in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS.items():
            payload: dict[str, object] = {
                "schema_version": contract,
                "artifact": filename,
            }
            if filename == "governor_deliberation.json":
                payload.update({"deliberation_id": deliberation_id})
            elif filename == "governor_decision_readiness.json":
                payload.update(
                    {
                        "readiness_id": readiness_id,
                        "deliberation_id": deliberation_id,
                        "readiness_state": "READY",
                    }
                )
            elif filename == "governor_decision.json":
                payload.update(
                    {
                        "decision_id": decision_id,
                        "deliberation_id": deliberation_id,
                        "readiness_id": readiness_id,
                        "decision_state": "PROCEED",
                        "decision_status": "RENDERED",
                        "allowed_next_step": "OPERATOR_REVIEW",
                        "warnings": [],
                        "blockers": [],
                    }
                )
            elif filename == "governor_rendered_decision.json":
                payload.update(
                    {
                        "mission_id": context.mission_id,
                        "request_id": self.rendered_request_id or request.request_id,
                        "run_mode": request.run_mode.value,
                        "decision_id": decision_id,
                        "disposition": "PROCEED",
                        "native_disposition": "PROCEED",
                        "readiness_state": "READY",
                        "allowed_next_step": "OPERATOR_REVIEW",
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
            native_disposition="PROCEED",
            readiness_state="READY",
            decision_id=decision_id,
            allowed_next_step="OPERATOR_REVIEW",
            produced_paths=tuple(
                f"{context.output_dir}/{filename}"
                for filename in GOVERNOR_NATIVE_OUTPUT_ARTIFACTS
            ),
            failure=None,
            context_id=supporting_context.context_id,
            source_lineage=(
                *(REQUIRED_GOVERNOR_INPUTS[name][0] for name in REQUIRED_GOVERNOR_INPUTS),
                GOVERNOR_SUPPORTING_CONTEXT_PATH,
            ),
        )


class SuccessfulOperatorExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, context, *, action_input):
        self.calls += 1
        result = (
            OperatorResult.APPROVED_FOR_HANDOFF
            if action_input.action is OperatorAction.APPROVE_HANDOFF
            else OperatorResult.REJECTED
        )
        output = context.mission_root / context.output_dir
        source_paths = {
            "governor_decision": context.governor_decision_path,
            "governor_decision_readiness": context.governor_readiness_path,
            "governor_deliberation": context.governor_deliberation_path,
            "governor_rendered_decision": context.governor_rendered_path,
            "governor_provenance": context.governor_provenance_path,
            "governor_lineage_manifest": context.governor_lineage_path,
        }
        source_hashes = {
            name: sha256_file(context.mission_root / path)
            for name, path in source_paths.items()
        }
        decision_input_hash = hashlib.sha256(
            json.dumps(
                {"run_id": context.mission_id, "source_hashes": source_hashes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        packet = {
            "schema_version": OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
            "manifest_schema_version": "blackpod.mission_snapshot.v1",
            "packet_id": "operator-review-packet-workflow-001",
            "run_id": context.mission_id,
            "run_completed_at": action_input.acted_at,
            "governor_posture": "NEUTRAL",
            "decision_state": "PROCEED",
            "allowed_next_step": "OPERATOR_REVIEW",
            "decision_summary": "Governor rendered PROCEED.",
            "readiness_state": "READY",
            "readiness_summary": "Governor readiness is READY.",
            "blockers": [],
            "warnings": [],
            "deliberation_summary": ["Governor reviewed current mission evidence."],
            "operator_route": OperatorRoute.PENDING_APPROVAL.value,
            "source_artifact_paths": source_paths,
            "source_artifact_hashes": source_hashes,
            "decision_input_hash": decision_input_hash,
            "created_at": action_input.acted_at,
        }
        _write(output / "review_packet.json", packet)
        _write(
            output / "operator_action.json",
            {
                "schema_version": OPERATOR_ACTION_SCHEMA_VERSION,
                "packet_sha256": sha256_file(output / "review_packet.json"),
                "decision_input_hash": decision_input_hash,
                "source_run_id": context.mission_id,
                "action": action_input.action.value,
                "operator_id": action_input.operator_id,
                "reason": action_input.reason,
                "created_at": action_input.acted_at,
                "expires_at": (
                    None
                    if action_input.expires_in_minutes is None
                    else (
                        datetime.fromisoformat(
                            action_input.acted_at.replace("Z", "+00:00")
                        )
                        + timedelta(minutes=action_input.expires_in_minutes)
                    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                ),
                "action_id": ACTION_ID,
                "packet_path": OPERATOR_REVIEW_PACKET_PATH,
                "packet_id": packet["packet_id"],
                "resulting_status": result.value,
            },
        )
        audit = {
            "event_timestamp": action_input.acted_at,
            "run_id": context.mission_id,
            "decision_input_hash": decision_input_hash,
            "operator_route": OperatorRoute.PENDING_APPROVAL.value,
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "result_status": "CONSUMED",
        }
        _write(
            output / "operator_receipt.json",
            {"schema_version": OPERATOR_RECEIPT_SCHEMA_VERSION, **audit},
        )
        _write(output / "operator_ledger_entry.json", audit)
        _write(
            output / "operator_provenance.json",
            {
                "schema_version": OPERATOR_PROVENANCE_SCHEMA_VERSION,
                "mission_id": context.mission_id,
                "request_id": request.request_id,
                "run_mode": request.run_mode.value,
                "observed_at": action_input.acted_at,
                "decision_id": "governor-decision-operator-ready",
                "action_id": ACTION_ID,
                "action": action_input.action.value,
                "result": result.value,
                "operator_id": action_input.operator_id,
                "battlestar_git_revision": context.battlestar_git_revision,
                "battlestar_git_branch": context.battlestar_git_branch,
                "battlestar_dirty_worktree": context.battlestar_dirty_worktree,
            },
        )
        _write(
            output / "lineage_manifest.json",
            {
                "schema_version": OPERATOR_LINEAGE_SCHEMA_VERSION,
                "mission_id": context.mission_id,
                "request_id": request.request_id,
                "run_mode": request.run_mode.value,
                "observed_at": action_input.acted_at,
                "decision_id": "governor-decision-operator-ready",
                "action_id": ACTION_ID,
            },
        )
        return OperatorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode,
            technical_status=OperatorActionStatus.SUCCEEDED,
            route=OperatorRoute.PENDING_APPROVAL,
            action=action_input.action,
            result=result,
            native_status="RECORDED",
            action_id=ACTION_ID,
            operator_id=action_input.operator_id,
            acted_at=action_input.acted_at,
            warnings=(),
            review_packet_path=OPERATOR_REVIEW_PACKET_PATH,
            produced_paths=EXPECTED_OPERATOR_OUTPUT_PATHS,
            source_lineage=(
                *REQUIRED_OPERATOR_INPUTS_PATHS,
                *((OPERATOR_REPLAY_INPUT_PATH,) if request.run_mode is RunMode.REPLAY else ()),
            ),
            fixture_id=action_input.fixture_id,
            failure=None,
        )


class FailedOperatorExecutor:
    def execute(self, request, context, *, action_input):
        return OperatorExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            run_mode=request.run_mode,
            technical_status=OperatorActionStatus.FAILED,
            route=OperatorRoute.PENDING_APPROVAL,
            action=action_input.action,
            result=None,
            native_status=None,
            action_id=None,
            operator_id=action_input.operator_id,
            acted_at=action_input.acted_at,
            warnings=(),
            review_packet_path=None,
            produced_paths=(),
            source_lineage=(
                *REQUIRED_OPERATOR_INPUTS_PATHS,
                *((OPERATOR_REPLAY_INPUT_PATH,) if request.run_mode is RunMode.REPLAY else ()),
            ),
            fixture_id=action_input.fixture_id,
            failure=OperatorFailure(
                code="OPERATOR_RECORDING_FAILED",
                error_type="FixtureFailure",
                message="deterministic operator technical failure",
                resumable=False,
            ),
        )


class InterruptedOperatorExecutor:
    def execute(self, request, context, *, action_input):
        raise KeyboardInterrupt("simulated interruption after r0008")


class OperatorWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        battlestar = self.base / "battlestar"
        battlestar.mkdir()
        oracle = battlestar / "oracle.py"
        oracle.write_text("# fixture\n", encoding="utf-8")
        fleet = battlestar / "fleet.yaml"
        fleet.write_text("fleet_id: fixture\n", encoding="utf-8")
        self.config = BattlestarConfig(
            root=battlestar.resolve(),
            oracle_module_path=oracle.resolve(),
            fleet_path=fleet.resolve(),
            git_revision=GOVERNOR_REVISION,
            git_branch="fixture-operator",
            dirty_worktree=False,
        )
        self.default = self.prepare("default")

    def config_loader(self, **_kwargs) -> BattlestarConfig:
        return self.config

    def prepare(
        self,
        suffix: str,
        *,
        run_mode: str = "REPLAY",
        rendered_request_id: str | None = None,
    ) -> PreparedOperatorMission:
        request = _request(f"mission-operator-{suffix}", run_mode=run_mode)
        root = self.base / f"artifacts-{suffix}"
        store = MissionStore(root)
        _build_council_completed_mission(store, request)
        context = self.base / f"governor-context-{suffix}.json"
        context.write_bytes(_supporting_context_bytes(request))
        run_governor(
            GovernorRunSettings(
                mission_id=request.mission_id or "",
                artifacts_root=root,
                replay_fixture=context if request.run_mode is RunMode.REPLAY else None,
                context_input=context if request.run_mode is RunMode.LIVE else None,
            ),
            adapter=OperatorReadyGovernorAdapter(
                rendered_request_id=rendered_request_id
            ),
            config_loader=self.config_loader,
            clock=lambda: datetime(2026, 7, 18, 18, 5, tzinfo=UTC),
        )
        loaded = store.load_mission(request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 7)
        self.assertEqual(loaded.snapshot.current_phase, CurrentPhase.OPERATOR)
        return PreparedOperatorMission(store, request, root)

    def execute(
        self,
        prepared: PreparedOperatorMission,
        executor,
        *,
        fixture: Path = APPROVE_FIXTURE,
        action: str | None = None,
    ):
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        return run_operator_action(
            OperatorRunSettings(
                mission_id=prepared.request.mission_id or "",
                artifacts_root=prepared.artifacts_root,
                action=action or payload["action"],
                operator_id=payload["operator_id"],
                reason=payload["reason"],
                replay_fixture=fixture,
                expires_in_minutes=payload["expires_in_minutes"],
            ),
            adapter=executor,
            config_loader=self.config_loader,
        )

    def test_approval_writes_running_and_success_revisions(self) -> None:
        r7 = self.default.store.paths_for(
            self.default.request.mission_id or ""
        ).snapshots_dir / "mission_snapshot-r0007.json"
        r7_before = r7.read_bytes()
        result = self.execute(self.default, SuccessfulOperatorExecutor())
        r8 = result.paths.snapshots_dir / "mission_snapshot-r0008.json"
        r9 = result.paths.snapshots_dir / "mission_snapshot-r0009.json"
        running = json.loads(r8.read_text(encoding="utf-8"))
        final = json.loads(r9.read_text(encoding="utf-8"))
        self.assertEqual(result.snapshot.revision, 9)
        self.assertEqual(running["operator"]["action_status"], "RUNNING")
        self.assertEqual(final["operator"]["action_status"], "SUCCEEDED")
        self.assertEqual(running["previous_snapshot_sha256"], sha256_file(r7))
        self.assertEqual(final["previous_snapshot_sha256"], sha256_file(r8))
        self.assertEqual(r7.read_bytes(), r7_before)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.NAVIGATOR)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.HELD)
        self.assertFalse(result.snapshot.terminal)
        self.assertEqual(
            result.snapshot.operator.result, OperatorResult.APPROVED_FOR_HANDOFF
        )
        self.assertEqual(
            result.snapshot.approval_scope,
            ApprovalScope.NAVIGATOR_SHADOW_HANDOFF,
        )
        self.assertEqual(
            result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED
        )

    def test_operator_accepts_semantic_boundary_after_extra_prior_revisions(self) -> None:
        """ModelDock adds two revisions without changing operator eligibility."""

        prepared = self.prepare("modeldock-revision-offset")
        loaded = prepared.store.load_mission(prepared.request.mission_id or "")
        for revision in (8, 9):
            value = loaded.snapshot.to_dict()
            value.update(
                {
                    "snapshot_id": f"{loaded.snapshot.mission_id}-r{revision:04d}",
                    "revision": revision,
                    "previous_snapshot_sha256": loaded.current_snapshot_sha256,
                }
            )
            prepared.store.commit_snapshot(
                loaded.paths, MissionSnapshot.from_mapping(value)
            )
            loaded = prepared.store.load_mission(prepared.request.mission_id or "")

        self.assertEqual(loaded.snapshot.revision, 9)
        result = self.execute(prepared, SuccessfulOperatorExecutor())
        self.assertEqual(result.snapshot.revision, 11)
        self.assertEqual(
            result.snapshot.operator.result, OperatorResult.APPROVED_FOR_HANDOFF
        )

    def test_rejection_is_terminal_veto_without_navigator(self) -> None:
        prepared = self.prepare("reject")
        result = self.execute(
            prepared,
            SuccessfulOperatorExecutor(),
            fixture=REJECT_FIXTURE,
        )
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COMPLETE)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.VETOED)
        self.assertTrue(result.snapshot.terminal)
        self.assertEqual(result.snapshot.operator.result, OperatorResult.REJECTED)
        self.assertIsNone(result.snapshot.approval_scope)
        self.assertEqual(
            result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED
        )

    def test_technical_failure_is_recorded_and_does_not_advance(self) -> None:
        result = self.execute(self.default, FailedOperatorExecutor())
        self.assertEqual(result.technical_status, OperatorActionStatus.FAILED)
        self.assertEqual(result.snapshot.operator.action_status, OperatorActionStatus.FAILED)
        self.assertEqual(result.snapshot.operator.error.code, "OPERATOR_RECORDING_FAILED")
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.OPERATOR)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertTrue(result.snapshot.terminal)
        self.assertEqual(
            result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED
        )

    def test_identical_repeat_is_no_op_and_conflicting_repeat_is_rejected(self) -> None:
        executor = SuccessfulOperatorExecutor()
        first = self.execute(self.default, executor)
        r9 = (first.paths.snapshots_dir / "mission_snapshot-r0009.json").read_bytes()
        second = self.execute(self.default, executor)
        self.assertEqual(
            second.disposition,
            OperatorWorkflowDisposition.NO_OP_ALREADY_SUCCEEDED,
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(
            (first.paths.snapshots_dir / "mission_snapshot-r0009.json").read_bytes(),
            r9,
        )
        with self.assertRaisesRegex(OperatorStateConflictError, "conflicts"):
            self.execute(
                self.default,
                executor,
                fixture=REJECT_FIXTURE,
            )

    def test_identical_repeat_after_downstream_time_is_still_no_op(self) -> None:
        executor = SuccessfulOperatorExecutor()
        first = self.execute(self.default, executor)
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        object.__setattr__(loaded.snapshot, "observed_at", "2026-07-18T18:10:00Z")
        with patch(
            "blackpod_build_week.operator_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            repeated = self.execute(self.default, executor)
        self.assertEqual(
            repeated.disposition,
            OperatorWorkflowDisposition.NO_OP_ALREADY_SUCCEEDED,
        )
        self.assertEqual(executor.calls, 1)
        self.assertFalse(
            (first.paths.snapshots_dir / "mission_snapshot-r0010.json").exists()
        )

    def test_interrupted_and_failed_attempts_are_restart_conflicts(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            self.execute(self.default, InterruptedOperatorExecutor())
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        self.assertEqual(loaded.snapshot.revision, 8)
        self.assertEqual(loaded.snapshot.operator.action_status, OperatorActionStatus.RUNNING)
        with self.assertRaisesRegex(OperatorStateConflictError, "already RUNNING"):
            self.execute(self.default, SuccessfulOperatorExecutor())

        failed = self.prepare("failed-restart")
        self.execute(failed, FailedOperatorExecutor())
        with self.assertRaisesRegex(OperatorStateConflictError, "previously FAILED"):
            self.execute(failed, SuccessfulOperatorExecutor())

    def test_replay_inputs_are_exact_and_live_never_uses_a_fixture(self) -> None:
        payload = json.loads(APPROVE_FIXTURE.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(OperatorInvocationError, "requires --replay-fixture"):
            run_operator_action(
                OperatorRunSettings(
                    mission_id=self.default.request.mission_id or "",
                    artifacts_root=self.default.artifacts_root,
                    action=payload["action"],
                    operator_id=payload["operator_id"],
                    reason=payload["reason"],
                    expires_in_minutes=payload["expires_in_minutes"],
                ),
                adapter=SuccessfulOperatorExecutor(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(OperatorInvocationError, "conflict"):
            self.execute(
                self.default,
                SuccessfulOperatorExecutor(),
                action="REJECT",
            )

        live = self.prepare("live", run_mode="LIVE")
        with self.assertRaisesRegex(OperatorInvocationError, "requires a positive"):
            run_operator_action(
                OperatorRunSettings(
                    mission_id=live.request.mission_id or "",
                    artifacts_root=live.artifacts_root,
                    action="APPROVE_HANDOFF",
                    operator_id="live-operator",
                    reason="Reviewed the live Governor evidence.",
                ),
                adapter=SuccessfulOperatorExecutor(),
                config_loader=self.config_loader,
                clock=lambda: datetime(2026, 7, 18, 18, 6, tzinfo=UTC),
            )
        with self.assertRaisesRegex(OperatorInvocationError, "forbids replay fixtures"):
            run_operator_action(
                OperatorRunSettings(
                    mission_id=live.request.mission_id or "",
                    artifacts_root=live.artifacts_root,
                    action="APPROVE_HANDOFF",
                    operator_id="live-operator",
                    reason="Reviewed the live Governor evidence.",
                    replay_fixture=APPROVE_FIXTURE,
                ),
                adapter=SuccessfulOperatorExecutor(),
                config_loader=self.config_loader,
            )

    def test_invalid_governor_inputs_and_correlation_fail_before_r0008(self) -> None:
        missing = self.prepare("missing-governor")
        loaded = missing.store.load_mission(missing.request.mission_id or "")
        decision = next(
            artifact
            for artifact in loaded.snapshot.artifacts
            if artifact.name == "governor_decision"
        )
        (loaded.paths.mission_root / decision.path).unlink()
        with self.assertRaises(PersistenceError):
            self.execute(missing, SuccessfulOperatorExecutor())

        mismatched = self.prepare(
            "bad-correlation",
            rendered_request_id="request-unrelated-operator",
        )
        with self.assertRaisesRegex(OperatorPreconditionError, "correlation"):
            self.execute(mismatched, SuccessfulOperatorExecutor())
        self.assertFalse(
            (
                mismatched.store.paths_for(mismatched.request.mission_id or "").snapshots_dir
                / "mission_snapshot-r0008.json"
            ).exists()
        )

    def test_outputs_are_relative_hash_exact_and_immutable_collision_fails_closed(self) -> None:
        result = self.execute(self.default, SuccessfulOperatorExecutor())
        root = result.paths.mission_root
        for artifact in result.snapshot.artifacts:
            self.assertFalse(Path(artifact.path).is_absolute())
            target = root / artifact.path
            self.assertTrue(target.resolve().is_relative_to(root.resolve()))
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        self.assertEqual(
            (root / OPERATOR_REPLAY_INPUT_PATH).read_bytes(),
            APPROVE_FIXTURE.read_bytes(),
        )
        serialized = json.dumps(result.snapshot.to_dict())
        self.assertNotIn(str(self.config.root), serialized)
        self.assertNotIn(str(APPROVE_FIXTURE.resolve()), serialized)

        collision = self.prepare("collision")
        attempt = (
            collision.store.paths_for(collision.request.mission_id or "").mission_root
            / OPERATOR_ATTEMPT_DIRECTORY
        )
        attempt.mkdir(parents=True)
        protected = attempt / "protected.txt"
        protected.write_bytes(b"do-not-overwrite\n")
        failed = self.execute(collision, SuccessfulOperatorExecutor())
        self.assertEqual(failed.snapshot.operator.action_status, OperatorActionStatus.FAILED)
        self.assertEqual(protected.read_bytes(), b"do-not-overwrite\n")

    def test_wrong_phase_is_rejected_without_operator_write(self) -> None:
        loaded = self.default.store.load_mission(self.default.request.mission_id or "")
        object.__setattr__(loaded.snapshot, "current_phase", CurrentPhase.GOVERNOR)
        with patch(
            "blackpod_build_week.operator_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            with self.assertRaisesRegex(OperatorPreconditionError, "PROCEED"):
                self.execute(self.default, SuccessfulOperatorExecutor())

    def test_missing_mission_is_rejected_before_adapter_invocation(self) -> None:
        executor = SuccessfulOperatorExecutor()
        payload = json.loads(APPROVE_FIXTURE.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(MissionNotFoundError, "mission does not exist"):
            run_operator_action(
                OperatorRunSettings(
                    mission_id="mission-operator-missing",
                    artifacts_root=self.base / "missing-artifacts",
                    action=payload["action"],
                    operator_id=payload["operator_id"],
                    reason=payload["reason"],
                    replay_fixture=APPROVE_FIXTURE,
                    expires_in_minutes=payload["expires_in_minutes"],
                ),
                adapter=executor,
                config_loader=self.config_loader,
            )
        self.assertEqual(executor.calls, 0)

    def test_incomplete_hold_and_stand_down_governors_cannot_reach_operator(self) -> None:
        cases = (
            ("incomplete", StageStatus.FAILED, "PROCEED", "technically successful"),
            ("hold", StageStatus.SUCCEEDED, "HOLD", "Governor PROCEED"),
            ("stand-down", StageStatus.SUCCEEDED, "STAND_DOWN", "Governor PROCEED"),
        )
        for suffix, status, native_state, message in cases:
            with self.subTest(native_state=native_state):
                prepared = self.prepare(f"guard-{suffix}")
                loaded = prepared.store.load_mission(prepared.request.mission_id or "")
                object.__setattr__(loaded.snapshot.stages["governor"], "status", status)
                object.__setattr__(
                    loaded.snapshot.stages["governor"], "native_state", native_state
                )
                executor = SuccessfulOperatorExecutor()
                with patch(
                    "blackpod_build_week.operator_workflow.MissionStore.load_mission",
                    return_value=loaded,
                ):
                    with self.assertRaisesRegex(OperatorPreconditionError, message):
                        self.execute(prepared, executor)
                self.assertEqual(executor.calls, 0)
                self.assertFalse(
                    (
                        prepared.store.paths_for(
                            prepared.request.mission_id or ""
                        ).snapshots_dir
                        / "mission_snapshot-r0008.json"
                    ).exists()
                )

    def test_blank_operator_id_and_tampered_governor_hash_fail_closed(self) -> None:
        payload = json.loads(APPROVE_FIXTURE.read_text(encoding="utf-8"))
        with self.assertRaises(OperatorInvocationError):
            run_operator_action(
                OperatorRunSettings(
                    mission_id=self.default.request.mission_id or "",
                    artifacts_root=self.default.artifacts_root,
                    action=payload["action"],
                    operator_id=" ",
                    reason=payload["reason"],
                    replay_fixture=APPROVE_FIXTURE,
                    expires_in_minutes=payload["expires_in_minutes"],
                ),
                adapter=SuccessfulOperatorExecutor(),
                config_loader=self.config_loader,
            )

        tampered = self.prepare("tampered-governor")
        loaded = tampered.store.load_mission(tampered.request.mission_id or "")
        decision = next(
            artifact
            for artifact in loaded.snapshot.artifacts
            if artifact.name == "governor_decision"
        )
        target = loaded.paths.mission_root / decision.path
        target.write_bytes(target.read_bytes() + b"tampered\n")
        with self.assertRaisesRegex(PersistenceError, "artifact hash mismatch"):
            self.execute(tampered, SuccessfulOperatorExecutor())
        self.assertFalse(
            (loaded.paths.snapshots_dir / "mission_snapshot-r0008.json").exists()
        )

    def test_operator_action_never_invokes_navigator(self) -> None:
        executor = SuccessfulOperatorExecutor()
        with patch(
            "blackpod_build_week.navigator_workflow.run_navigator"
        ) as navigator_runner:
            result = self.execute(self.default, executor)
        navigator_runner.assert_not_called()
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.NAVIGATOR)
        self.assertEqual(
            result.snapshot.stages["navigator"].status, StageStatus.NOT_STARTED
        )


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(payload))


if __name__ == "__main__":
    unittest.main()
