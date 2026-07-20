from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from blackpod_build_week.contracts import (
    MISSION_SUMMARY_ARTIFACT_LINKS,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ApprovalScope,
    DemoManifest,
    MissionRequest,
    ModelDockCallStatus,
    ModelDockTransportKind,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    RunMode,
    StageStatus,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.live_demo_packager import (
    LiveDemoPackageAction,
    LiveDemoPackagingError,
    main,
    package_live_demo,
)
from blackpod_build_week.mission_store import MissionPaths, MissionStore
from blackpod_build_week.repository_state import GitWorktreeState


MISSION_ID = "mission-live-package-001"
REQUEST_ID = "request-live-package-001"
OBSERVED_AT = "2026-07-20T06:00:00Z"
SNAPSHOT_PATH = "snapshots/mission_snapshot-r0001.json"


class _LoadedStore(MissionStore):
    def __init__(self, artifacts_root: Path, loaded: object) -> None:
        super().__init__(artifacts_root)
        self._loaded = loaded

    def load_mission(self, mission_id: str):
        if mission_id != self._loaded.snapshot.mission_id:
            raise AssertionError("unexpected mission id")
        return self._loaded


class LiveDemoPackagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.artifacts_root = self.base / "artifacts"
        self.mission_root = self.artifacts_root / "missions" / MISSION_ID
        (self.mission_root / "request").mkdir(parents=True)
        (self.mission_root / "snapshots").mkdir()
        (self.mission_root / "presentation").mkdir()

        snapshot_bytes = b'{"canonical":"snapshot"}\n'
        (self.mission_root / SNAPSHOT_PATH).write_bytes(snapshot_bytes)
        (self.mission_root / "mission_snapshot.json").write_bytes(snapshot_bytes)
        snapshot_reference = {
            "name": "mission_snapshot_r0001",
            "path": SNAPSHOT_PATH,
            "sha256": sha256_bytes(snapshot_bytes),
            "producer": "harbormaster",
            "byte_size": len(snapshot_bytes),
            "schema_version": "blackpod.mission_snapshot.v1",
            "observed_at": OBSERVED_AT,
        }

        self.request = MissionRequest.from_mapping(
            {
                "schema_version": "blackpod.mission_request.v1",
                "mission_id": MISSION_ID,
                "request_id": REQUEST_ID,
                "run_mode": "LIVE",
                "symbol": "AAPL",
                "requested_at": "2026-07-20T05:55:00Z",
                "operator_id": "demo-operator",
                "metadata": {},
            }
        )
        (self.mission_root / "request/mission_request.json").write_bytes(
            canonical_json_bytes(self.request.to_dict())
        )

        call = SimpleNamespace(
            status=ModelDockCallStatus.SUCCEEDED,
            mission_id=MISSION_ID,
            request_id=REQUEST_ID,
            run_mode=RunMode.LIVE,
            endpoint="http://127.0.0.1:8000/text/generate",
            provider="mlx",
            model="gemma-4-e4b-it-4bit",
            trace_id="trace-live-package-001",
            mocked=False,
        )
        self.snapshot = SimpleNamespace(
            mission_id=MISSION_ID,
            request_id=REQUEST_ID,
            revision=1,
            run_mode=RunMode.LIVE,
            observed_at=OBSERVED_AT,
            mission_outcome=SimpleNamespace(value="APPROVED"),
            current_phase=SimpleNamespace(value="COMPLETE"),
            terminal=True,
            stages={
                "harbormaster": SimpleNamespace(
                    status=StageStatus.SUCCEEDED,
                    native_state="INITIALIZED",
                    modeldock_calls=(),
                ),
                "oracle": SimpleNamespace(
                    status=StageStatus.SUCCEEDED,
                    native_state="READY",
                    modeldock_calls=(call,),
                ),
                "council": SimpleNamespace(
                    status=StageStatus.SUCCEEDED,
                    native_state="ALIGNED",
                    modeldock_calls=(),
                ),
                "governor": SimpleNamespace(
                    status=StageStatus.SUCCEEDED,
                    native_state="PROCEED",
                    modeldock_calls=(),
                ),
                "navigator": SimpleNamespace(
                    status=StageStatus.SUCCEEDED,
                    native_state="CREATED",
                    modeldock_calls=(),
                ),
            },
            components={
                "battlestar": SimpleNamespace(
                    git_revision="b" * 40,
                    dirty_worktree=False,
                ),
                "modeldock": SimpleNamespace(
                    endpoint=call.endpoint,
                    expected_provider="mlx",
                    run_mode=RunMode.LIVE,
                    transport=ModelDockTransportKind.LIVE_HTTP,
                    replay_fixture_id=None,
                ),
            },
            operator=SimpleNamespace(
                route=OperatorRoute.PENDING_APPROVAL,
                action_status=OperatorActionStatus.SUCCEEDED,
                action=OperatorAction.APPROVE_HANDOFF,
                result=OperatorResult.APPROVED_FOR_HANDOFF,
            ),
            navigator=SimpleNamespace(
                mode=NavigatorMode.SHADOW,
                handoff_status=NavigatorHandoffStatus.STAGED,
                intake_status=NavigatorIntakeStatus.ACCEPTED,
                plan_status=NavigatorPlanStatus.CREATED,
                allowed_operations=NAVIGATOR_ALLOWED_OPERATIONS,
                prohibited_operations=NAVIGATOR_PROHIBITED_OPERATIONS,
            ),
            approval_scope=ApprovalScope.NAVIGATOR_SHADOW_HANDOFF,
        )
        # The packager compares canonical enums by identity. Use the real enum
        # values while keeping this fixture intentionally narrower than a full
        # workflow construction.
        from blackpod_build_week.contracts import CurrentPhase, MissionOutcome

        self.snapshot.current_phase = CurrentPhase.COMPLETE
        self.snapshot.mission_outcome = MissionOutcome.APPROVED

        stage_names = (
            "HARBORMASTER",
            "ORACLE",
            "MODELDOCK",
            "COUNCIL",
            "GOVERNOR",
            "OPERATOR",
            "NAVIGATOR",
            "MISSION",
        )
        display = {
            "HARBORMASTER": "SUCCEEDED",
            "ORACLE": "SUCCEEDED",
            "MODELDOCK": "SUCCEEDED",
            "COUNCIL": "SUCCEEDED",
            "GOVERNOR": "PROCEED",
            "OPERATOR": "APPROVED_FOR_HANDOFF",
            "NAVIGATOR": "CREATED",
            "MISSION": "APPROVED",
        }
        log = {
            "schema_version": "blackpod.captains_log.v1",
            "mission_id": MISSION_ID,
            "request_id": REQUEST_ID,
            "symbol": "AAPL",
            "run_mode": "LIVE",
            "generated_at": OBSERVED_AT,
            "generated_from_snapshot": snapshot_reference,
            "entries": [
                {
                    "stage": stage,
                    "timestamp": OBSERVED_AT,
                    "status": display[stage],
                    "summary": f"{stage.title()} canonical event.",
                    "source_artifacts": [snapshot_reference],
                }
                for stage in stage_names
            ],
        }
        summary = {
            "schema_version": "blackpod.mission_summary.v2",
            "mission_id": MISSION_ID,
            "request_id": REQUEST_ID,
            "symbol": "AAPL",
            "run_mode": "LIVE",
            "generated_at": OBSERVED_AT,
            "generated_from_snapshot": snapshot_reference,
            "current_phase": "COMPLETE",
            "terminal": True,
            "stages": {
                name: {
                    "technical_status": "SUCCEEDED",
                    "native_state": self.snapshot.stages[name].native_state,
                }
                for name in (
                    "harbormaster",
                    "oracle",
                    "council",
                    "governor",
                    "navigator",
                )
            },
            "modeldock": {
                "status": "SUCCEEDED",
                "provider": "mlx",
                "model": "gemma-4-e4b-it-4bit",
                "trace_id": "trace-live-package-001",
            },
            "governor_disposition": "PROCEED",
            "operator": {
                "route": "PENDING_APPROVAL",
                "action_status": "SUCCEEDED",
                "action": "APPROVE_HANDOFF",
                "result": "APPROVED_FOR_HANDOFF",
            },
            "navigator": {
                "technical_status": "SUCCEEDED",
                "native_state": "CREATED",
                "mode": "SHADOW",
                "handoff_status": "STAGED",
                "intake_status": "ACCEPTED",
                "plan_status": "CREATED",
            },
            "approval_scope": "NAVIGATOR_SHADOW_HANDOFF",
            "final_outcome": "APPROVED",
            "important_warnings": [],
            "snapshot_count": 1,
            "canonical_snapshot_path": "mission_snapshot.json",
            "display_title": "AAPL mission",
            "subtitle": "Verified LIVE SHADOW mission",
            "ordered_stages": [
                {
                    "stage": stage,
                    "display_state": display[stage],
                    "summary": f"{stage.title()} canonical event.",
                    "artifact_paths": [SNAPSHOT_PATH],
                }
                for stage in stage_names[:-1]
            ],
            "resumable": False,
            "event_count": 8,
            "artifact_links": dict(MISSION_SUMMARY_ARTIFACT_LINKS),
        }
        (self.mission_root / "presentation/captains_log.json").write_bytes(
            canonical_json_bytes(log)
        )
        self.summary_path = self.mission_root / "presentation/mission_summary.json"
        self.summary_path.write_bytes(canonical_json_bytes(summary))

        paths = MissionPaths(
            mission_root=self.mission_root,
            request_path=self.mission_root / "request/mission_request.json",
            snapshots_dir=self.mission_root / "snapshots",
            revision_snapshot=self.mission_root / SNAPSHOT_PATH,
            current_snapshot=self.mission_root / "mission_snapshot.json",
        )
        self.loaded = SimpleNamespace(
            request=self.request,
            snapshot=self.snapshot,
            snapshot_history=(self.snapshot,),
            paths=paths,
        )
        self.store = _LoadedStore(self.artifacts_root, self.loaded)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _package(self):
        return package_live_demo(
            mission_id=MISSION_ID,
            artifacts_root=self.artifacts_root,
            repository_root=self.base,
            store=self.store,
            worktree_inspector=lambda root: GitWorktreeState(
                root=root,
                revision="a" * 40,
                branch="stage-4-live-demo-integration",
                dirty=False,
            ),
        )

    def test_packages_existing_contract_as_immutable_live_manifest(self) -> None:
        result = self._package()

        self.assertIs(result.action, LiveDemoPackageAction.CREATED)
        manifest = DemoManifest.from_mapping(json.loads(result.path.read_text()))
        self.assertEqual(manifest.run_mode, RunMode.LIVE)
        self.assertEqual(manifest.modeldock_mode.value, "LIVE")
        self.assertEqual(manifest.modeldock_provider, "mlx")
        self.assertEqual(
            manifest.modeldock_revision_or_service_identity,
            "http://127.0.0.1:8000/text/generate",
        )
        self.assertEqual(manifest.allowed_operations, NAVIGATOR_ALLOWED_OPERATIONS)
        self.assertEqual(manifest.prohibited_operations, NAVIGATOR_PROHIBITED_OPERATIONS)

    def test_identical_repeat_is_noop_and_conflict_is_rejected(self) -> None:
        first = self._package()
        original = first.path.read_bytes()
        second = self._package()
        self.assertIs(second.action, LiveDemoPackageAction.NO_OP_ALREADY_SATISFIED)
        self.assertEqual(second.path.read_bytes(), original)

        second.path.write_bytes(b'{"conflict":true}\n')
        with self.assertRaisesRegex(LiveDemoPackagingError, "different content"):
            self._package()

    def test_replay_mission_is_rejected(self) -> None:
        self.snapshot.run_mode = RunMode.REPLAY
        with self.assertRaisesRegex(LiveDemoPackagingError, "requires a LIVE mission"):
            self._package()

    def test_mocked_modeldock_response_is_rejected(self) -> None:
        self.snapshot.stages["oracle"].modeldock_calls[0].mocked = True
        with self.assertRaisesRegex(LiveDemoPackagingError, "non-mocked MLX"):
            self._package()

    def test_dirty_build_week_or_battlestar_state_is_not_frozen(self) -> None:
        with self.assertRaisesRegex(LiveDemoPackagingError, "Build Week worktree"):
            package_live_demo(
                mission_id=MISSION_ID,
                artifacts_root=self.artifacts_root,
                repository_root=self.base,
                store=self.store,
                worktree_inspector=lambda root: GitWorktreeState(
                    root=root,
                    revision="a" * 40,
                    branch="stage-4-live-demo-integration",
                    dirty=True,
                ),
            )

        self.snapshot.components["battlestar"].dirty_worktree = True
        with self.assertRaisesRegex(LiveDemoPackagingError, "Battlestar worktree"):
            self._package()

    def test_summary_correlation_mismatch_is_rejected(self) -> None:
        summary = json.loads(self.summary_path.read_text())
        summary["modeldock"]["trace_id"] = "different-live-trace"
        self.summary_path.write_bytes(canonical_json_bytes(summary))
        with self.assertRaisesRegex(LiveDemoPackagingError, "ModelDock identity"):
            self._package()

    def test_cli_returns_nonzero_for_packaging_failure(self) -> None:
        with mock.patch(
            "blackpod_build_week.live_demo_packager.package_live_demo",
            side_effect=LiveDemoPackagingError("not approved"),
        ):
            self.assertEqual(
                main(
                    [
                        "--mission-id",
                        MISSION_ID,
                        "--artifacts-root",
                        str(self.artifacts_root),
                        "--repository-root",
                        str(self.base),
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
