from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import (
    MODELDOCK_FAILURE_ARTIFACT_NAMES,
    MODELDOCK_REQUEST_ARTIFACT_NAME,
    MODELDOCK_SUCCESS_ARTIFACT_NAMES,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    ApprovalScope,
    ArtifactReference,
    ComponentProvenance,
    ContractValidationError,
    CouncilComponentProvenance,
    CouncilTransportKind,
    CurrentPhase,
    GovernorComponentProvenance,
    GovernorTransportKind,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    ModelDockCall,
    ModelDockCallStatus,
    ModelDockComponentProvenance,
    ModelDockTransportKind,
    NavigatorHandoffStatus,
    NavigatorIntakeStatus,
    NavigatorMode,
    NavigatorPlanStatus,
    NavigatorState,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    OperatorRoute,
    OperatorState,
    RunMode,
    StageError,
    StageStatus,
)
from blackpod_build_week.identifiers import allocate_mission_id


def valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "blackpod.mission_request.v1",
        "request_id": "request-contract-001",
        "run_mode": "LIVE",
        "symbol": "AAPL",
        "requested_at": "2026-07-18T11:00:00-07:00",
        "operator_id": "operator-001",
        "metadata": {"purpose": "contract-test"},
    }
    request.update(overrides)
    return request


class MissionRequestContractTests(unittest.TestCase):
    def test_valid_live_request(self) -> None:
        request = MissionRequest.from_mapping(valid_request())

        self.assertIs(request.run_mode, RunMode.LIVE)
        self.assertEqual(request.requested_at, "2026-07-18T18:00:00Z")
        self.assertIsNone(request.mission_id)

    def test_valid_replay_request_is_deterministic(self) -> None:
        first = MissionRequest.from_mapping(
            valid_request(
                run_mode="REPLAY",
                metadata={"z": 2, "a": 1},
            )
        )
        second = MissionRequest.from_mapping(
            {
                "metadata": {"a": 1, "z": 2},
                "operator_id": "operator-001",
                "requested_at": "2026-07-18T18:00:00Z",
                "symbol": "AAPL",
                "run_mode": "REPLAY",
                "request_id": "request-contract-001",
                "schema_version": "blackpod.mission_request.v1",
            }
        )

        first_id = allocate_mission_id(
            first.identity_payload(),
            request_id=first.request_id,
            run_mode=first.run_mode.value,
            supplied_mission_id=first.mission_id,
        )
        second_id = allocate_mission_id(
            second.identity_payload(),
            request_id=second.request_id,
            run_mode=second.run_mode.value,
            supplied_mission_id=second.mission_id,
        )

        self.assertEqual(first_id, second_id)
        self.assertTrue(first_id.startswith("mission-replay-"))

    def test_malformed_request_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_text('{"schema_version": ', encoding="utf-8")

            with self.assertRaisesRegex(ContractValidationError, "not valid JSON"):
                MissionRequest.from_file(request_path)

    def test_duplicate_json_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_text(
                '{"schema_version":"blackpod.mission_request.v1",'
                '"schema_version":"blackpod.mission_request.v1"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
                MissionRequest.from_file(request_path)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "unsupported schema_version"):
            MissionRequest.from_mapping(valid_request(schema_version="future.v2"))

    def test_invalid_run_mode_is_rejected_without_coercion(self) -> None:
        for run_mode in ("live", "REPLAY ", "DRY_RUN"):
            with self.subTest(run_mode=run_mode):
                with self.assertRaisesRegex(ContractValidationError, "unsupported run_mode"):
                    MissionRequest.from_mapping(valid_request(run_mode=run_mode))

    def test_malformed_timestamps_are_rejected(self) -> None:
        for timestamp in (
            "2026-07-18",
            "2026-07-18 18:00:00Z",
            "2026-07-18T18:00:00",
            "0001-01-01T00:00:00+14:00",
            "not-a-time",
        ):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ContractValidationError):
                    MissionRequest.from_mapping(valid_request(requested_at=timestamp))

    def test_blank_identifiers_and_unknown_fields_are_rejected(self) -> None:
        for field in ("request_id", "operator_id"):
            with self.subTest(field=field):
                with self.assertRaises(ContractValidationError):
                    MissionRequest.from_mapping(valid_request(**{field: "   "}))

        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            MissionRequest.from_mapping(valid_request(typo_field=True))

    def test_metadata_is_the_open_extension_point(self) -> None:
        request = MissionRequest.from_mapping(
            valid_request(metadata={"nested": {"free_form": [1, True, None]}})
        )
        self.assertEqual(request.metadata["nested"]["free_form"], [1, True, None])

    def test_non_utf8_unicode_scalar_values_are_rejected_cleanly(self) -> None:
        for overrides in (
            {"symbol": "\ud800"},
            {"metadata": {"invalid": "\ud800"}},
        ):
            with self.subTest(overrides=repr(overrides)):
                with self.assertRaisesRegex(ContractValidationError, "Unicode|UTF-8"):
                    MissionRequest.from_mapping(valid_request(**overrides))


class MissionSnapshotContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = MissionSnapshot.create_phase1(
            mission_id="mission-contract-001",
            request_id="request-contract-001",
            run_mode=RunMode.REPLAY,
            started_at="2026-07-18T18:00:00Z",
            observed_at="2026-07-18T18:00:00Z",
            request_artifact=ArtifactReference.from_mapping(
                {
                    "name": "mission_request",
                    "path": "request/mission_request.json",
                    "sha256": "0" * 64,
                }
            ),
        )

    def test_all_stages_are_always_present(self) -> None:
        self.assertEqual(
            set(self.snapshot.stages),
            {"harbormaster", "oracle", "council", "governor", "navigator"},
        )

    def test_phase1_state_derives_incomplete(self) -> None:
        self.assertIs(
            self.snapshot.stages["harbormaster"].status,
            StageStatus.SUCCEEDED,
        )
        self.assertEqual(
            self.snapshot.stages["harbormaster"].native_state,
            "INITIALIZED",
        )
        for stage_name in ("oracle", "council", "governor", "navigator"):
            with self.subTest(stage=stage_name):
                self.assertIs(
                    self.snapshot.stages[stage_name].status,
                    StageStatus.NOT_STARTED,
                )
                self.assertIsNone(self.snapshot.stages[stage_name].native_state)
        self.assertIs(self.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertIs(self.snapshot.current_phase, CurrentPhase.ORACLE)
        self.assertFalse(self.snapshot.terminal)
        self.assertIsNone(self.snapshot.previous_snapshot_sha256)
        self.assertEqual(self.snapshot.operator, OperatorState.empty())
        self.assertEqual(self.snapshot.navigator, NavigatorState.empty())
        self.assertIsNone(self.snapshot.approval_scope)

    def test_operator_state_is_backward_compatible_and_rejects_partial_actions(self) -> None:
        legacy = self.snapshot.to_dict()
        legacy["operator"] = {
            "route": None,
            "action": None,
            "result": None,
            "operator_id": None,
            "acted_at": None,
        }
        del legacy["navigator"]
        del legacy["approval_scope"]

        parsed = MissionSnapshot.from_mapping(legacy)

        self.assertEqual(parsed.operator, OperatorState.empty())
        self.assertEqual(
            parsed.to_dict()["operator"],
            {
                "route": None,
                "action_status": "NOT_STARTED",
                "action": None,
                "result": None,
                "action_id": None,
                "operator_id": None,
                "acted_at": None,
                "error": None,
            },
        )
        self.assertEqual(parsed.navigator, NavigatorState.empty())
        self.assertIsNone(parsed.approval_scope)

        action = self.snapshot.to_dict()
        action["operator"]["action"] = "APPROVE_HANDOFF"
        with self.assertRaisesRegex(ContractValidationError, "NOT_STARTED"):
            MissionSnapshot.from_mapping(action)

    def test_operator_action_states_are_strict_and_typed(self) -> None:
        running = OperatorState.from_mapping(
            {
                "route": "PENDING_APPROVAL",
                "action_status": "RUNNING",
                "action": "APPROVE_HANDOFF",
                "result": None,
                "action_id": None,
                "operator_id": "operator-reviewer",
                "acted_at": None,
                "error": None,
            }
        )
        self.assertIs(running.action_status, OperatorActionStatus.RUNNING)
        self.assertIs(running.action, OperatorAction.APPROVE_HANDOFF)
        self.assertIsNone(running.action_id)

        succeeded = OperatorState.from_mapping(
            {
                "route": "PENDING_APPROVAL",
                "action_status": "SUCCEEDED",
                "action": "APPROVE_HANDOFF",
                "result": "APPROVED_FOR_HANDOFF",
                "action_id": "operator-action-001",
                "operator_id": "operator-reviewer",
                "acted_at": "2026-07-18T18:06:00Z",
                "error": None,
            }
        )
        self.assertIs(succeeded.result, OperatorResult.APPROVED_FOR_HANDOFF)

        failed_error = StageError.from_mapping(
            {
                "code": "OPERATOR_TIMEOUT",
                "error_type": "TimeoutError",
                "message": "operator action recording timed out",
                "resumable": False,
                "observed_at": "2026-07-18T18:06:00Z",
            }
        )
        failed = OperatorState.from_mapping(
            {
                "route": "PENDING_APPROVAL",
                "action_status": "FAILED",
                "action": "APPROVE_HANDOFF",
                "result": None,
                "action_id": None,
                "operator_id": "operator-reviewer",
                "acted_at": "2026-07-18T18:06:00Z",
                "error": failed_error.to_dict(),
            }
        )
        self.assertIs(failed.action_status, OperatorActionStatus.FAILED)
        self.assertIsNone(failed.action_id)

        inconsistent = succeeded.to_dict()
        inconsistent["result"] = "REJECTED"
        with self.assertRaisesRegex(ContractValidationError, "inconsistent"):
            OperatorState.from_mapping(inconsistent)

    def test_navigator_state_enforces_shadow_non_execution_envelope(self) -> None:
        running = NavigatorState.shadow_running()
        self.assertIs(running.mode, NavigatorMode.SHADOW)
        self.assertEqual(running.allowed_operations, NAVIGATOR_ALLOWED_OPERATIONS)
        self.assertEqual(
            running.prohibited_operations,
            NAVIGATOR_PROHIBITED_OPERATIONS,
        )

        completed = NavigatorState.from_mapping(
            {
                "mode": "SHADOW",
                "handoff_status": "STAGED",
                "intake_status": "ACCEPTED",
                "plan_status": "CREATED",
                "handoff_id": "handoff-contract-001",
                "intake_receipt_id": "intake-contract-001",
                "plan_id": "plan-contract-001",
                "expires_at": "2026-07-18T19:06:00Z",
                "idempotency_key": "navigator-contract-001",
                "allowed_operations": ["VALIDATE", "PLAN_ONLY"],
                "prohibited_operations": [
                    "SUBMIT_ORDER",
                    "CANCEL_ORDER",
                    "MODIFY_PORTFOLIO",
                    "BROKER_CALL",
                ],
            }
        )
        self.assertIs(completed.handoff_status, NavigatorHandoffStatus.STAGED)
        self.assertIs(completed.intake_status, NavigatorIntakeStatus.ACCEPTED)
        self.assertIs(completed.plan_status, NavigatorPlanStatus.CREATED)

        expanded = completed.to_dict()
        expanded["allowed_operations"].append("SUBMIT_ORDER")
        with self.assertRaisesRegex(ContractValidationError, "exactly"):
            NavigatorState.from_mapping(expanded)

        rejected_with_plan = completed.to_dict()
        rejected_with_plan["intake_status"] = "REJECTED"
        with self.assertRaisesRegex(ContractValidationError, "accepted intake"):
            NavigatorState.from_mapping(rejected_with_plan)

    def test_snapshot_contract_can_represent_all_outcome_enum_values(self) -> None:
        base = self.snapshot.to_dict()
        for outcome in MissionOutcome:
            with self.subTest(outcome=outcome.value):
                candidate = json.loads(json.dumps(base))
                candidate["mission_outcome"] = outcome.value
                parsed = MissionSnapshot.from_mapping(candidate)
                self.assertIs(parsed.mission_outcome, outcome)

    def test_snapshot_rejects_missing_or_extra_stage(self) -> None:
        missing = self.snapshot.to_dict()
        del missing["stages"]["council"]
        with self.assertRaisesRegex(ContractValidationError, "exactly"):
            MissionSnapshot.from_mapping(missing)

        extra = self.snapshot.to_dict()
        extra["stages"]["operator"] = {
            "status": "NOT_STARTED",
            "native_state": None,
        }
        with self.assertRaisesRegex(ContractValidationError, "exactly"):
            MissionSnapshot.from_mapping(extra)

    def test_snapshot_rejects_unsafe_artifact_path(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["artifacts"][0]["path"] = "../outside.json"
        with self.assertRaisesRegex(ContractValidationError, "beneath"):
            MissionSnapshot.from_mapping(candidate)

    def test_snapshot_round_trips_oracle_and_council_component_types(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["components"] = {
            "battlestar": {
                "git_revision": "a" * 40,
                "git_branch": "main",
                "dirty_worktree": False,
                "oracle_entry_point": (
                    "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
                ),
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": "oracle-fixture-v1",
                "replay_fixture_sha256": "b" * 64,
            },
            "battlestar_council": {
                "git_revision": "a" * 40,
                "git_branch": "main",
                "dirty_worktree": False,
                "candidate_entry_point": "native.candidate",
                "senate_review_entry_point": "native.senate_review",
                "senate_deliberation_entry_point": "native.senate_deliberation",
                "mandate_entry_point": "native.mandate",
                "runtime_validation_entry_point": "native.runtime_validation",
                "advisor_health_entry_point": "native.advisor_health",
                "council_synthesis_entry_point": "native.council_synthesis",
                "council_executive_summary_entry_point": "native.council_summary",
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": "council-fixture-v1",
                "replay_fixture_sha256": "c" * 64,
            },
        }

        parsed = MissionSnapshot.from_mapping(candidate)

        self.assertIsInstance(parsed.components["battlestar"], ComponentProvenance)
        council = parsed.components["battlestar_council"]
        self.assertIsInstance(council, CouncilComponentProvenance)
        self.assertIs(council.transport, CouncilTransportKind.REPLAY_FIXTURE)
        self.assertEqual(
            council.runtime_validation_entry_point,
            "native.runtime_validation",
        )
        self.assertEqual(council.advisor_health_entry_point, "native.advisor_health")
        self.assertEqual(parsed.to_dict()["components"], candidate["components"])

    def test_council_provenance_enforces_transport_identity_rules(self) -> None:
        base = {
            "git_revision": "a" * 40,
            "git_branch": None,
            "dirty_worktree": True,
            "candidate_entry_point": "native.candidate",
            "senate_review_entry_point": "native.senate_review",
            "senate_deliberation_entry_point": "native.senate_deliberation",
            "mandate_entry_point": "native.mandate",
            "runtime_validation_entry_point": "native.runtime_validation",
            "advisor_health_entry_point": "native.advisor_health",
            "council_synthesis_entry_point": "native.council_synthesis",
            "council_executive_summary_entry_point": "native.council_summary",
            "run_mode": "LIVE",
            "transport": "LIVE_MISSION_INPUTS",
            "replay_fixture_id": None,
            "replay_fixture_sha256": None,
        }
        live = CouncilComponentProvenance.from_mapping(base)
        self.assertIs(live.transport, CouncilTransportKind.LIVE_MISSION_INPUTS)

        invalid = dict(base)
        invalid.update(
            {
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": None,
                "replay_fixture_sha256": None,
            }
        )
        with self.assertRaisesRegex(ContractValidationError, "fixture identity"):
            CouncilComponentProvenance.from_mapping(invalid)

    def test_council_component_requires_oracle_and_matching_mission_mode(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["components"] = {
            "battlestar_council": {
                "git_revision": "a" * 40,
                "git_branch": "main",
                "dirty_worktree": False,
                "candidate_entry_point": "native.candidate",
                "senate_review_entry_point": "native.senate_review",
                "senate_deliberation_entry_point": "native.senate_deliberation",
                "mandate_entry_point": "native.mandate",
                "runtime_validation_entry_point": "native.runtime_validation",
                "advisor_health_entry_point": "native.advisor_health",
                "council_synthesis_entry_point": "native.council_synthesis",
                "council_executive_summary_entry_point": "native.council_summary",
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": "fixture-v1",
                "replay_fixture_sha256": "b" * 64,
            }
        }
        with self.assertRaisesRegex(ContractValidationError, "requires Battlestar Oracle"):
            MissionSnapshot.from_mapping(candidate)

        candidate["components"]["battlestar"] = {
            "git_revision": "a" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "oracle_entry_point": "native.oracle",
            "run_mode": "LIVE",
            "transport": "LIVE_YFINANCE",
            "replay_fixture_id": None,
            "replay_fixture_sha256": None,
        }
        with self.assertRaisesRegex(ContractValidationError, "run_mode must match"):
            MissionSnapshot.from_mapping(candidate)

    def test_governor_provenance_transport_and_dependency_rules(self) -> None:
        governor_mapping = {
            "git_revision": "d" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "senate_intake_entry_point": "native.governor_senate_intake",
            "preparation_entry_point": "native.governor_preparation",
            "deliberation_entry_point": "native.governor_deliberation",
            "readiness_entry_point": "native.governor_readiness",
            "rendering_entry_point": "native.governor_rendering",
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "governor-fixture-v1",
            "replay_fixture_sha256": "e" * 64,
        }
        provenance = GovernorComponentProvenance.from_mapping(governor_mapping)
        self.assertIs(provenance.transport, GovernorTransportKind.REPLAY_FIXTURE)

        candidate = self.snapshot.to_dict()
        candidate["components"] = {"battlestar_governor": governor_mapping}
        with self.assertRaisesRegex(
            ContractValidationError, "requires Battlestar Oracle and Council"
        ):
            MissionSnapshot.from_mapping(candidate)

        invalid = dict(governor_mapping)
        invalid.update(
            {
                "run_mode": "LIVE",
                "transport": "LIVE_MISSION_INPUTS",
            }
        )
        with self.assertRaisesRegex(ContractValidationError, "no replay fixture"):
            GovernorComponentProvenance.from_mapping(invalid)

    def test_operator_routes_require_matching_rendered_governor_state(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["operator"] = {
            "route": OperatorRoute.PENDING_APPROVAL.value,
            "action": None,
            "result": None,
            "operator_id": None,
            "acted_at": None,
        }
        with self.assertRaisesRegex(
            ContractValidationError, "successful Governor stage"
        ):
            MissionSnapshot.from_mapping(candidate)

    def test_phase5_cross_state_requires_scope_and_delays_approval(self) -> None:
        phase4 = self.snapshot.to_dict()
        phase4["stages"]["governor"] = {
            "status": "SUCCEEDED",
            "native_state": "PROCEED",
            "inputs": [],
            "outputs": [],
            "error": None,
        }
        phase4["current_phase"] = "OPERATOR"
        phase4["mission_outcome"] = "HELD"
        phase4["operator"] = {
            "route": "PENDING_APPROVAL",
            "action": None,
            "result": None,
            "operator_id": None,
            "acted_at": None,
        }
        del phase4["navigator"]
        del phase4["approval_scope"]
        parsed_phase4 = MissionSnapshot.from_mapping(phase4)
        self.assertIs(parsed_phase4.operator.action_status, OperatorActionStatus.NOT_STARTED)

        approved = parsed_phase4.to_dict()
        approved["revision"] = 2
        approved["snapshot_id"] = "mission-contract-001-r0002"
        approved["previous_snapshot_sha256"] = "f" * 64
        approved["operator"] = {
            "route": "PENDING_APPROVAL",
            "action_status": "SUCCEEDED",
            "action": "APPROVE_HANDOFF",
            "result": "APPROVED_FOR_HANDOFF",
            "action_id": "operator-action-contract",
            "operator_id": "operator-reviewer",
            "acted_at": "2026-07-18T18:06:00Z",
            "error": None,
        }
        approved["observed_at"] = "2026-07-18T18:06:00Z"
        approved["current_phase"] = "NAVIGATOR"
        approved["mission_outcome"] = "HELD"
        approved["approval_scope"] = ApprovalScope.NAVIGATOR_SHADOW_HANDOFF.value
        parsed_approval = MissionSnapshot.from_mapping(approved)
        self.assertIs(parsed_approval.mission_outcome, MissionOutcome.HELD)
        self.assertIs(
            parsed_approval.stages["navigator"].status,
            StageStatus.NOT_STARTED,
        )

        premature = parsed_approval.to_dict()
        premature["mission_outcome"] = "APPROVED"
        premature["current_phase"] = "COMPLETE"
        premature["terminal"] = True
        with self.assertRaisesRegex(ContractValidationError, "approved Navigator"):
            MissionSnapshot.from_mapping(premature)

    def test_modeldock_call_contract_is_typed_and_terminal_states_are_strict(self) -> None:
        running_mapping = {
            "call_id": "modeldock-call-contract-001",
            "status": "RUNNING",
            "mission_id": "mission-contract-001",
            "request_id": "request-contract-001",
            "run_mode": "REPLAY",
            "endpoint": "http://127.0.0.1:8000/text/generate",
            "provider": None,
            "model": None,
            "model_revision": None,
            "trace_id": None,
            "mocked": None,
            "latency_ms": None,
            "request_sha256": "a" * 64,
            "response_sha256": None,
            "response_byte_size": None,
            "started_at": "2026-07-18T18:01:00Z",
            "observed_at": "2026-07-18T18:01:00Z",
            "artifacts": [MODELDOCK_REQUEST_ARTIFACT_NAME],
            "error": None,
        }
        running = ModelDockCall.from_mapping(running_mapping)
        self.assertIs(running.status, ModelDockCallStatus.RUNNING)

        illegal_running = dict(running_mapping, provider="mlx")
        with self.assertRaisesRegex(ContractValidationError, "RUNNING"):
            ModelDockCall.from_mapping(illegal_running)

        succeeded_mapping = dict(
            running_mapping,
            status="SUCCEEDED",
            provider="mlx",
            model="mlx-community/test-model",
            model_revision="revision-001",
            trace_id="trace-contract-001",
            mocked=False,
            latency_ms=12.5,
            response_sha256="b" * 64,
            response_byte_size=128,
            observed_at="2026-07-18T18:02:00Z",
            artifacts=list(MODELDOCK_SUCCESS_ARTIFACT_NAMES),
        )
        succeeded = ModelDockCall.from_mapping(succeeded_mapping)
        self.assertIs(succeeded.status, ModelDockCallStatus.SUCCEEDED)
        self.assertEqual(succeeded.latency_ms, 12.5)

        mocked_live = dict(succeeded_mapping, run_mode="LIVE", mocked=True)
        with self.assertRaisesRegex(ContractValidationError, "mocked"):
            ModelDockCall.from_mapping(mocked_live)

        failed_without_error = dict(running_mapping, status="FAILED")
        with self.assertRaisesRegex(ContractValidationError, "structured error"):
            ModelDockCall.from_mapping(failed_without_error)

        failure_error = {
            "code": "MODELDOCK_TIMEOUT",
            "error_type": "TimeoutError",
            "message": "ModelDock timed out",
            "resumable": True,
            "observed_at": "2026-07-18T18:02:00Z",
        }
        failed = ModelDockCall.from_mapping(
            dict(
                running_mapping,
                status="FAILED",
                observed_at="2026-07-18T18:02:00Z",
                artifacts=list(MODELDOCK_FAILURE_ARTIFACT_NAMES),
                error=failure_error,
            )
        )
        self.assertIs(failed.status, ModelDockCallStatus.FAILED)

        leaked_metadata = (
            ("provider", "/Users/demo/provider"),
            ("model", "/Users/demo/model"),
            ("model", "../outside/model"),
            ("model_revision", "token=secret-value"),
            ("trace_id", "sk-secret-value"),
        )
        for field_name, unsafe_value in leaked_metadata:
            with self.subTest(field=field_name, value=unsafe_value):
                candidate = dict(succeeded_mapping, **{field_name: unsafe_value})
                with self.assertRaises(ContractValidationError):
                    ModelDockCall.from_mapping(candidate)

    def test_modeldock_component_provenance_enforces_strict_transport_rules(self) -> None:
        replay_mapping = {
            "endpoint": "http://127.0.0.1:8000/text/generate",
            "profile": "local-demo",
            "expected_provider": "mlx",
            "requested_model": None,
            "timeout_seconds": 15,
            "max_response_bytes": 262144,
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "modeldock-contract-fixture-v1",
            "replay_fixture_sha256": "c" * 64,
            "failure_policy": "STRICT_REQUIRED",
        }
        provenance = ModelDockComponentProvenance.from_mapping(replay_mapping)
        self.assertIs(provenance.transport, ModelDockTransportKind.REPLAY_FIXTURE)
        self.assertEqual(provenance.timeout_seconds, 15.0)

        live_mapping = dict(
            replay_mapping,
            run_mode="LIVE",
            transport="LIVE_HTTP",
            replay_fixture_id=None,
            replay_fixture_sha256=None,
        )
        live = ModelDockComponentProvenance.from_mapping(live_mapping)
        self.assertIs(live.transport, ModelDockTransportKind.LIVE_HTTP)

        for invalid in (
            dict(replay_mapping, failure_policy="OPTIONAL"),
            dict(replay_mapping, replay_fixture_id=None),
            dict(live_mapping, expected_provider="mock"),
            dict(live_mapping, endpoint="file:///tmp/text/generate"),
            dict(live_mapping, endpoint="https://modeldock.example/text/generate"),
            dict(replay_mapping, profile="/Users/demo/profile"),
            dict(replay_mapping, requested_model="../../outside/model"),
            dict(replay_mapping, requested_model="api_key=secret-value"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ContractValidationError):
                    ModelDockComponentProvenance.from_mapping(invalid)

    def test_modeldock_stage_field_is_backward_compatible_and_oracle_only(self) -> None:
        legacy = self.snapshot.to_dict()
        for stage in legacy["stages"].values():
            del stage["modeldock_calls"]

        parsed = MissionSnapshot.from_mapping(legacy)

        self.assertEqual(parsed.stages["oracle"].modeldock_calls, ())
        self.assertIn("modeldock_calls", parsed.to_dict()["stages"]["oracle"])

        wrong_stage = self.snapshot.to_dict()
        running_call = {
            "call_id": "modeldock-call-contract-002",
            "status": "RUNNING",
            "mission_id": "mission-contract-001",
            "request_id": "request-contract-001",
            "run_mode": "REPLAY",
            "endpoint": "http://127.0.0.1:8000/text/generate",
            "provider": None,
            "model": None,
            "model_revision": None,
            "trace_id": None,
            "mocked": None,
            "latency_ms": None,
            "request_sha256": "a" * 64,
            "response_sha256": None,
            "response_byte_size": None,
            "started_at": "2026-07-18T18:00:00Z",
            "observed_at": "2026-07-18T18:00:00Z",
            "artifacts": [MODELDOCK_REQUEST_ARTIFACT_NAME],
            "error": None,
        }
        wrong_stage["stages"]["council"]["modeldock_calls"] = [running_call]
        wrong_stage["stages"]["council"]["status"] = "RUNNING"
        with self.assertRaisesRegex(ContractValidationError, "only inside the Oracle"):
            MissionSnapshot.from_mapping(wrong_stage)

        duplicate = self.snapshot.to_dict()
        duplicate["stages"]["oracle"].update(
            {
                "status": "RUNNING",
                "modeldock_calls": [running_call, running_call],
            }
        )
        with self.assertRaisesRegex(ContractValidationError, "at most one"):
            MissionSnapshot.from_mapping(duplicate)


if __name__ == "__main__":
    unittest.main()
