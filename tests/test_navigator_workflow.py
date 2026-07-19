from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import (
    CurrentPhase,
    MissionOutcome,
    OperatorAction,
    OperatorResult,
    StageStatus,
)
from blackpod_build_week.governor_workflow import GOVERNOR_NATIVE_OUTPUT_ARTIFACTS
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_store import (
    MissionNotFoundError,
    MissionStore,
    PersistenceError,
)
from blackpod_build_week.mission_transitions import (
    begin_operator_action,
    complete_operator_action,
)
from blackpod_build_week.navigator_adapter import NavigatorAdapter
from blackpod_build_week.navigator_workflow import (
    NAVIGATOR_ATTEMPT_DIRECTORY,
    NAVIGATOR_LINEAGE_PATH,
    NavigatorAction,
    NavigatorInvocationError,
    NavigatorPreconditionError,
    NavigatorRunSettings,
    NavigatorStateConflictError,
    run_navigator,
)
from blackpod_build_week.operator_adapter import (
    OPERATOR_ACTION_PATH,
    OPERATOR_LINEAGE_PATH,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_REVIEW_PACKET_PATH,
)
from tests import test_governor_workflow as governor_tests
from tests.test_navigator_adapter import RecordingTransport


OBSERVED_AT = "2026-07-18T18:07:00Z"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class NavigatorWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        # Reuse the established Phase 1-4 test builder, but place its temporary
        # filesystem under this test's lifecycle.
        governor_case = governor_tests.GovernorWorkflowTests(methodName="runTest")
        governor_case.temporary_directory = self.temp
        governor_case.base = self.base
        battlestar_root = self.base / "battlestar"
        battlestar_root.mkdir(exist_ok=True)
        oracle_module = battlestar_root / "oracle.py"
        oracle_module.write_text("# fixture\n", encoding="utf-8")
        fleet = battlestar_root / "fleet.yaml"
        fleet.write_text("fleet_id: fixture\n", encoding="utf-8")
        governor_case.config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=oracle_module.resolve(),
            fleet_path=fleet.resolve(),
            git_revision="c" * 40,
            git_branch="fixture-governor",
            dirty_worktree=False,
        )
        prepared = governor_case.prepare("navigator")
        governor = governor_case.execute(
            prepared, governor_tests.SuccessfulGovernorAdapter("PROCEED")
        )
        self.store = prepared.store
        self.request = prepared.request
        self.artifacts_root = prepared.artifacts_root
        self.paths = governor.paths
        self._approve_operator(governor.snapshot)

        for relative in (
            "blackpod/runtime/navigator_handoff.py",
            "blackpod/runtime/navigator_intake.py",
            "blackpod/runtime/governor_decision_consumer.py",
            "blackpod/runtime/operator_inbox_action.py",
        ):
            target = battlestar_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# interface sentinel\n", encoding="utf-8")
        self.config = BattlestarConfig(
            root=battlestar_root.resolve(),
            oracle_module_path=oracle_module.resolve(),
            fleet_path=fleet.resolve(),
            git_revision="d" * 40,
            git_branch="fixture-navigator",
            dirty_worktree=False,
        )
        self.success_fixture = self.base / "navigator-success.json"
        self.failure_fixture = self.base / "navigator-failure.json"
        self._write_fixture(self.success_fixture, "NONE")
        self._write_fixture(self.failure_fixture, "UNSUPPORTED_HANDOFF_SCHEMA")

    def _approve_operator(self, governor_snapshot):
        mission_id = self.request.mission_id or ""
        source_artifacts = {
            item.name: item
            for item in governor_snapshot.artifacts
            if item.name in {
                "governor_decision",
                "governor_decision_readiness",
                "governor_deliberation",
                "governor_rendered_decision",
                "governor_provenance",
                "governor_lineage_manifest",
            }
        }
        source_paths = {name: artifact.path for name, artifact in source_artifacts.items()}
        source_hashes = {name: artifact.sha256 for name, artifact in source_artifacts.items()}
        decision_hash = hashlib.sha256(
            json.dumps(
                {"run_id": mission_id, "source_hashes": source_hashes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        decision_id = "governor-decision-proceed"
        packet = {
            "schema_version": "operator_review_packet.v1",
            "manifest_schema_version": "blackpod.mission_snapshot.v1",
            "packet_id": "operator-review-packet-1234567890abcdef",
            "run_id": mission_id,
            "run_completed_at": OBSERVED_AT,
            "governor_posture": "NEUTRAL",
            "decision_state": "PROCEED",
            "allowed_next_step": "OPERATOR_REVIEW",
            "decision_summary": "Governor rendered PROCEED.",
            "readiness_state": "READY",
            "readiness_summary": "Governor readiness is READY.",
            "blockers": [],
            "warnings": [],
            "deliberation_summary": ["Governor reviewed the evidence."],
            "operator_route": "PENDING_APPROVAL",
            "source_artifact_paths": source_paths,
            "source_artifact_hashes": source_hashes,
            "decision_input_hash": decision_hash,
            "created_at": OBSERVED_AT,
        }
        running = begin_operator_action(
            governor_snapshot,
            previous_snapshot_sha256=sha256_file(self.paths.current_snapshot),
            observed_at=OBSERVED_AT,
            action=OperatorAction.APPROVE_HANDOFF,
            operator_id="demo-operator",
        )
        running_digest = self.store.commit_snapshot(self.paths, running)
        packet_ref = self.store.write_immutable_artifact(
            mission_id,
            relative_path=OPERATOR_REVIEW_PACKET_PATH,
            payload=canonical_json_bytes(packet),
            name="operator_review_packet",
            producer="operator",
            schema_version="operator_review_packet.v1",
            observed_at=OBSERVED_AT,
        )
        action_id = "operator-action-1234567890abcdef"
        action = {
            "schema_version": "operator_inbox_action.v1",
            "packet_sha256": packet_ref.sha256,
            "decision_input_hash": decision_hash,
            "source_run_id": mission_id,
            "action": "APPROVE_HANDOFF",
            "operator_id": "demo-operator",
            "reason": "Approved for deterministic Navigator SHADOW planning.",
            "created_at": OBSERVED_AT,
            "expires_at": "2026-07-18T19:07:00Z",
            "action_id": action_id,
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "packet_id": packet["packet_id"],
            "resulting_status": "APPROVED_FOR_HANDOFF",
        }
        action_ref = self.store.write_immutable_artifact(
            mission_id,
            relative_path=OPERATOR_ACTION_PATH,
            payload=canonical_json_bytes(action),
            name="operator_action",
            producer="operator",
            schema_version="operator_inbox_action.v1",
            observed_at=OBSERVED_AT,
        )
        provenance_ref = self.store.write_immutable_artifact(
            mission_id,
            relative_path=OPERATOR_PROVENANCE_PATH,
            payload=canonical_json_bytes(
                {
                    "schema_version": "blackpod.operator_provenance.v1",
                    "mission_id": mission_id,
                    "request_id": self.request.request_id,
                    "observed_at": OBSERVED_AT,
                    "run_mode": self.request.run_mode.value,
                    "decision_id": decision_id,
                    "action_id": action_id,
                    "action": "APPROVE_HANDOFF",
                    "result": "APPROVED_FOR_HANDOFF",
                    "operator_id": "demo-operator",
                    "observed_at": OBSERVED_AT,
                    "battlestar_git_revision": "c" * 40,
                }
            ),
            name="operator_provenance",
            producer="operator",
            schema_version="blackpod.operator_provenance.v1",
            observed_at=OBSERVED_AT,
        )
        lineage_payload = {
            "schema_version": "blackpod.operator_lineage.v1",
            "mission_id": mission_id,
            "request_id": self.request.request_id,
            "run_mode": self.request.run_mode.value,
            "decision_id": decision_id,
            "action_id": action_id,
            "observed_at": OBSERVED_AT,
            "outputs": [
                {
                    "name": artifact.name,
                    "path": artifact.path,
                    "sha256": artifact.sha256,
                    "byte_size": artifact.byte_size,
                    "producer": artifact.producer,
                    "mission_id": mission_id,
                    "request_id": self.request.request_id,
                    "observed_at": OBSERVED_AT,
                }
                for artifact in (packet_ref, action_ref)
            ],
        }
        lineage_ref = self.store.write_immutable_artifact(
            mission_id,
            relative_path=OPERATOR_LINEAGE_PATH,
            payload=canonical_json_bytes(lineage_payload),
            name="operator_lineage_manifest",
            producer="operator",
            schema_version="blackpod.operator_lineage.v1",
            observed_at=OBSERVED_AT,
        )
        complete = complete_operator_action(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            result=OperatorResult.APPROVED_FOR_HANDOFF,
            action_id=action_id,
            operator_id="demo-operator",
            acted_at=OBSERVED_AT,
            output_artifacts=(packet_ref, action_ref, provenance_ref, lineage_ref),
        )
        self.store.commit_snapshot(self.paths, complete)

    def _write_fixture(self, path: Path, injection: str):
        path.write_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "blackpod.navigator_replay.v1",
                    "fixture_id": f"navigator-{injection.lower().replace('_', '-')}-v1",
                    "mission_id": self.request.mission_id,
                    "request_id": self.request.request_id,
                    "run_mode": "REPLAY",
                    "observed_at": OBSERVED_AT,
                    "mode": "SHADOW",
                    "failure_injection": injection,
                }
            )
        )

    def config_loader(self, **kwargs):
        return self.config

    def execute(self, fixture: Path, *, transport=None):
        adapter = NavigatorAdapter(
            self.config.root,
            transport=transport or RecordingTransport(),
        )
        return run_navigator(
            NavigatorRunSettings(
                mission_id=self.request.mission_id or "",
                artifacts_root=self.artifacts_root,
                replay_fixture=fixture,
            ),
            adapter=adapter,
            config_loader=self.config_loader,
        )

    def fresh_case(self):
        case = type(self)(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_success_writes_running_and_final_approved_revisions(self):
        before = (self.paths.snapshots_dir / "mission_snapshot-r0009.json").read_bytes()
        result = self.execute(self.success_fixture)
        self.assertEqual(result.snapshot.revision, 11)
        self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.SUCCEEDED)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COMPLETE)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.APPROVED)
        self.assertTrue(result.snapshot.terminal)
        self.assertEqual(result.snapshot.navigator.allowed_operations, ("VALIDATE", "PLAN_ONLY"))
        self.assertEqual(result.snapshot.operator.result, OperatorResult.APPROVED_FOR_HANDOFF)
        self.assertEqual((self.paths.snapshots_dir / "mission_snapshot-r0009.json").read_bytes(), before)
        r10 = self.paths.snapshots_dir / "mission_snapshot-r0010.json"
        r11 = self.paths.snapshots_dir / "mission_snapshot-r0011.json"
        self.assertEqual(json.loads(r10.read_text())["stages"]["navigator"]["status"], "RUNNING")
        self.assertEqual(json.loads(r11.read_text())["previous_snapshot_sha256"], sha256_file(r10))

    def test_controlled_intake_rejection_commits_failed_without_plan(self):
        result = self.execute(self.failure_fixture, transport=RecordingTransport(failed=True))
        self.assertEqual(result.snapshot.stages["navigator"].status, StageStatus.FAILED)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.NAVIGATOR)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertEqual(result.snapshot.navigator.intake_status.value, "REJECTED")
        self.assertIsNone(result.snapshot.navigator.plan_status)
        self.assertFalse(any(a.name == "navigator_shadow_plan" for a in result.snapshot.artifacts))

    def test_repeat_success_is_explicit_no_op_and_immutable(self):
        first = self.execute(self.success_fixture)
        final_before = self.paths.current_snapshot.read_bytes()
        second = self.execute(self.success_fixture)
        self.assertEqual(second.action, NavigatorAction.NO_OP_ALREADY_SUCCEEDED)
        self.assertEqual(second.snapshot.revision, first.snapshot.revision)
        self.assertEqual(self.paths.current_snapshot.read_bytes(), final_before)
        self.assertFalse((self.paths.snapshots_dir / "mission_snapshot-r0012.json").exists())

    def test_repeat_rejects_tampered_completed_native_artifact(self):
        result = self.execute(self.success_fixture)
        plan = next(
            artifact
            for artifact in result.snapshot.artifacts
            if artifact.name == "navigator_shadow_plan"
        )
        target = result.paths.mission_root / plan.path
        target.write_bytes(target.read_bytes() + b"tampered\n")
        with self.assertRaises(PersistenceError):
            self.execute(self.success_fixture)

    def test_running_and_failed_attempts_conflict_on_restart(self):
        class Interrupt:
            def execute(self, *args, **kwargs):
                raise KeyboardInterrupt("interrupted")

        with self.assertRaises(KeyboardInterrupt):
            run_navigator(
                NavigatorRunSettings(
                    mission_id=self.request.mission_id or "",
                    artifacts_root=self.artifacts_root,
                    replay_fixture=self.success_fixture,
                ),
                adapter=Interrupt(),
                config_loader=self.config_loader,
            )
        with self.assertRaisesRegex(NavigatorStateConflictError, "already RUNNING"):
            self.execute(self.success_fixture)

    def test_partial_staging_and_intake_artifacts_remain_immutable_on_restart(self):
        handoff_id = "navigator-handoff-partial-001"
        cases = {
            "handoff-staged": {
                f"handoff/pending/{handoff_id}.json": {
                    "schema_version": "navigator_shadow_handoff_envelope.v1",
                    "handoff_id": handoff_id,
                },
                f"handoff/staging_receipts/{handoff_id}.json": {
                    "schema_version": "navigator_handoff_staging_receipt.v1",
                    "handoff_id": handoff_id,
                    "status": "STAGED",
                },
            },
            "intake-accepted": {
                f"handoff/pending/{handoff_id}.json": {
                    "schema_version": "navigator_shadow_handoff_envelope.v1",
                    "handoff_id": handoff_id,
                },
                f"handoff/staging_receipts/{handoff_id}.json": {
                    "schema_version": "navigator_handoff_staging_receipt.v1",
                    "handoff_id": handoff_id,
                    "status": "STAGED",
                },
                f"intake/intake_receipts/{handoff_id}.json": {
                    "schema_version": "navigator_intake_receipt.v1",
                    "handoff_id": handoff_id,
                    "status": "ACCEPTED",
                },
            },
        }

        class InterruptAfterPartialArtifacts:
            def __init__(self, payloads):
                self.payloads = payloads

            def execute(self, request, context, *, control):
                for relative_path, payload in self.payloads.items():
                    target = (
                        context.mission_root / context.output_dir / relative_path
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(canonical_json_bytes(payload))
                raise KeyboardInterrupt("interrupted after partial Navigator progress")

        for label, payloads in cases.items():
            with self.subTest(label=label):
                case = self.fresh_case()
                with self.assertRaises(KeyboardInterrupt):
                    run_navigator(
                        NavigatorRunSettings(
                            mission_id=case.request.mission_id or "",
                            artifacts_root=case.artifacts_root,
                            replay_fixture=case.success_fixture,
                        ),
                        adapter=InterruptAfterPartialArtifacts(payloads),
                        config_loader=case.config_loader,
                    )
                r10 = case.paths.snapshots_dir / "mission_snapshot-r0010.json"
                protected = {
                    r10: r10.read_bytes(),
                    **{
                        case.paths.mission_root
                        / NAVIGATOR_ATTEMPT_DIRECTORY
                        / relative_path: (
                            case.paths.mission_root
                            / NAVIGATOR_ATTEMPT_DIRECTORY
                            / relative_path
                        ).read_bytes()
                        for relative_path in payloads
                    },
                }
                with self.assertRaisesRegex(
                    NavigatorStateConflictError, "already RUNNING"
                ):
                    case.execute(case.success_fixture)
                for path, original in protected.items():
                    self.assertEqual(path.read_bytes(), original)
                self.assertFalse(
                    (case.paths.snapshots_dir / "mission_snapshot-r0011.json").exists()
                )

    def test_missing_approval_and_tampered_artifact_are_rejected(self):
        loaded = self.store.load_mission(self.request.mission_id or "")
        object.__setattr__(loaded.snapshot.operator, "result", None)

        with patch(
            "blackpod_build_week.navigator_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            with self.assertRaisesRegex(NavigatorPreconditionError, "APPROVED_FOR_HANDOFF"):
                self.execute(self.success_fixture)

        action = self.paths.mission_root / OPERATOR_ACTION_PATH
        action.write_bytes(action.read_bytes() + b"tampered\n")
        with self.assertRaises(PersistenceError):
            self.execute(self.success_fixture)

    def test_lineage_hashes_containment_and_no_absolute_paths(self):
        result = self.execute(self.success_fixture)
        for artifact in result.snapshot.artifacts:
            target = result.paths.mission_root / artifact.path
            self.assertFalse(Path(artifact.path).is_absolute())
            self.assertEqual(artifact.sha256, sha256_file(target))
            self.assertEqual(artifact.byte_size, target.stat().st_size)
        lineage = json.loads((result.paths.mission_root / NAVIGATOR_LINEAGE_PATH).read_text())
        names = {entry["name"] for entry in lineage["outputs"]}
        self.assertIn("navigator_handoff_envelope", names)
        self.assertIn("navigator_shadow_plan", names)
        serialized = json.dumps(result.snapshot.to_dict())
        self.assertNotIn(str(self.config.root), serialized)

    def test_missing_mission_is_rejected_before_adapter_invocation(self):
        transport = RecordingTransport()
        with self.assertRaisesRegex(MissionNotFoundError, "mission does not exist"):
            run_navigator(
                NavigatorRunSettings(
                    mission_id="mission-navigator-missing",
                    artifacts_root=self.base / "missing-artifacts",
                    replay_fixture=self.success_fixture,
                ),
                adapter=NavigatorAdapter(self.config.root, transport=transport),
                config_loader=self.config_loader,
            )
        self.assertEqual(transport.calls, [])

    def test_wrong_operator_result_and_wrong_phase_are_rejected(self):
        cases = (
            ("operator-result", "operator", OperatorResult.REJECTED),
            ("phase", "snapshot", CurrentPhase.OPERATOR),
        )
        for label, target, value in cases:
            with self.subTest(label=label):
                loaded = self.store.load_mission(self.request.mission_id or "")
                if target == "operator":
                    object.__setattr__(loaded.snapshot.operator, "result", value)
                else:
                    object.__setattr__(loaded.snapshot, "current_phase", value)
                transport = RecordingTransport()
                with patch(
                    "blackpod_build_week.navigator_workflow.MissionStore.load_mission",
                    return_value=loaded,
                ):
                    with self.assertRaises(NavigatorPreconditionError):
                        self.execute(self.success_fixture, transport=transport)
                self.assertEqual(transport.calls, [])
                self.assertFalse(
                    (self.paths.snapshots_dir / "mission_snapshot-r0010.json").exists()
                )

    def test_missing_operator_input_and_correlation_mismatch_fail_closed(self):
        action_path = self.paths.mission_root / OPERATOR_ACTION_PATH
        original = action_path.read_bytes()
        action_path.unlink()
        with self.assertRaisesRegex(PersistenceError, "does not exist"):
            self.execute(self.success_fixture)
        action_path.write_bytes(original)

        loaded = self.store.load_mission(self.request.mission_id or "")
        object.__setattr__(
            loaded.snapshot.operator,
            "action_id",
            "operator-action-foreign-correlation",
        )
        transport = RecordingTransport()
        with patch(
            "blackpod_build_week.navigator_workflow.MissionStore.load_mission",
            return_value=loaded,
        ):
            with self.assertRaisesRegex(NavigatorPreconditionError, "correlation"):
                self.execute(self.success_fixture, transport=transport)
        self.assertEqual(transport.calls, [])

    def test_expired_approval_and_unsupported_mode_are_rejected(self):
        expired = self.base / "navigator-expired.json"
        expired_payload = json.loads(self.success_fixture.read_text(encoding="utf-8"))
        expired_payload["observed_at"] = "2026-07-18T19:08:00Z"
        expired.write_bytes(canonical_json_bytes(expired_payload))
        transport = RecordingTransport()
        with self.assertRaisesRegex(NavigatorPreconditionError, "expired"):
            self.execute(expired, transport=transport)
        self.assertEqual(transport.calls, [])
        self.assertFalse(
            (self.paths.snapshots_dir / "mission_snapshot-r0010.json").exists()
        )

        unsupported = self.base / "navigator-unsupported-mode.json"
        unsupported_payload = json.loads(
            self.success_fixture.read_text(encoding="utf-8")
        )
        unsupported_payload["mode"] = "LIVE"
        unsupported.write_bytes(canonical_json_bytes(unsupported_payload))
        with self.assertRaisesRegex(NavigatorInvocationError, "fixture is invalid"):
            self.execute(unsupported)

    def test_existing_attempt_directory_and_failed_restart_are_conflicts(self):
        attempt = self.paths.mission_root / NAVIGATOR_ATTEMPT_DIRECTORY
        attempt.mkdir(parents=True)
        sentinel = attempt / "immutable.txt"
        sentinel.write_bytes(b"do-not-overwrite\n")
        with self.assertRaisesRegex(
            NavigatorStateConflictError, "attempt directory already exists"
        ):
            self.execute(self.success_fixture)
        self.assertEqual(sentinel.read_bytes(), b"do-not-overwrite\n")
        self.assertFalse(
            (self.paths.snapshots_dir / "mission_snapshot-r0010.json").exists()
        )

        # A separate fixture-backed mission verifies that FAILED is immutable
        # and cannot be silently retried.
        case = self.fresh_case()
        failed = case.execute(
            case.failure_fixture, transport=RecordingTransport(failed=True)
        )
        self.assertEqual(failed.snapshot.stages["navigator"].status, StageStatus.FAILED)
        with self.assertRaisesRegex(NavigatorStateConflictError, "previously FAILED"):
            case.execute(
                case.failure_fixture, transport=RecordingTransport(failed=True)
            )


if __name__ == "__main__":
    unittest.main()
