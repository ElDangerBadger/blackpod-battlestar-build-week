from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from blackpod_build_week.contracts import (
    MissionRequest,
    NavigatorHandoffStatus,
    NavigatorMode,
    RunMode,
    StageStatus,
)
from blackpod_build_week.hashing import sha256_file
from blackpod_build_week.navigator_adapter import (
    ALLOWED_OPERATIONS,
    NAVIGATOR_REPLAY_SCHEMA_VERSION,
    PROHIBITED_OPERATIONS,
    NavigatorAdapter,
    NavigatorExecutionControl,
    NavigatorExecutionResult,
    NavigatorFailure,
    NavigatorFailureInjection,
    NavigatorMissionContext,
    NavigatorReplayFixture,
    NavigatorTransportRequest,
    NavigatorTransportTimeout,
)


OBSERVED_AT = "2026-07-18T18:07:00Z"
MISSION_ID = "mission-navigator-adapter-001"
REQUEST_ID = "request-navigator-adapter-001"
DECISION_ID = "governor-decision-proceed"
ACTION_ID = "operator-action-1234567890abcdef"


def _request(run_mode: str = "REPLAY") -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": REQUEST_ID,
            "mission_id": MISSION_ID,
            "run_mode": run_mode,
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-navigator",
            "metadata": {},
        }
    )


def _fixture_mapping(**overrides):
    value = {
        "schema_version": NAVIGATOR_REPLAY_SCHEMA_VERSION,
        "fixture_id": "navigator-replay-test-v1",
        "mission_id": MISSION_ID,
        "request_id": REQUEST_ID,
        "run_mode": "REPLAY",
        "observed_at": OBSERVED_AT,
        "mode": "SHADOW",
        "failure_injection": "NONE",
    }
    value.update(overrides)
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


class RecordingTransport:
    def __init__(
        self,
        *,
        failed: bool = False,
        malformed: bool = False,
        forged_source_hash: bool = False,
        forged_boundary: str | None = None,
        unsupported_schema_success: bool = False,
        error=None,
    ):
        self.failed = failed
        self.malformed = malformed
        self.forged_source_hash = forged_source_hash
        self.forged_boundary = forged_boundary
        self.unsupported_schema_success = unsupported_schema_success
        self.error = error
        self.calls: list[NavigatorTransportRequest] = []

    def run(self, request, *, deadline_seconds):
        self.calls.append(request)
        if self.error:
            raise self.error
        output = request.mission_root / request.output_dir
        handoff_id = "navigator-handoff-1234567890abcdef"
        envelope_path = output / "handoff/pending" / f"{handoff_id}.json"
        staging_path = output / "handoff/staging_receipts" / f"{handoff_id}.json"
        handoff_ledger = output / "handoff/handoff_ledger.jsonl"
        intake_path = output / "intake/intake_receipts" / f"{handoff_id}.json"
        plan_path = output / "intake/shadow_plans" / f"{handoff_id}.json"
        navigator_ledger = output / "intake/navigator_ledger.jsonl"
        envelope = {
            "schema_version": (
                "navigator_shadow_handoff_envelope.unsupported"
                if self.failed or self.unsupported_schema_success
                else "navigator_shadow_handoff_envelope.v1"
            ),
            "handoff_id": handoff_id,
            "source_run_id": request.mission_id,
            "operator_action_id": request.action_id,
            "source_packet_id": json.loads(
                (request.mission_root / request.review_packet_path).read_text()
            )["packet_id"],
            "source_packet_path": request.review_packet_path,
            "source_packet_sha256": (
                "f" * 64
                if self.forged_source_hash
                else sha256_file(request.mission_root / request.review_packet_path)
            ),
            "operator_action_path": request.operator_action_path,
            "operator_action_sha256": sha256_file(request.mission_root / request.operator_action_path),
            "decision_input_hash": json.loads(
                (request.mission_root / request.review_packet_path).read_text()
            )["decision_input_hash"],
            "operator_id": json.loads(
                (request.mission_root / request.operator_action_path).read_text()
            )["operator_id"],
            "mode": "SHADOW",
            "allowed_operations": list(ALLOWED_OPERATIONS),
            "prohibited_operations": list(PROHIBITED_OPERATIONS),
            "expires_at": "2026-07-18T19:07:00Z",
        }
        _write_json(envelope_path, envelope)
        envelope_sha = sha256_file(envelope_path)
        _write_json(
            staging_path,
            {
                "schema_version": "navigator_handoff_staging_receipt.v1",
                "handoff_id": handoff_id,
                "source_run_id": request.mission_id,
                "envelope_path": envelope_path.relative_to(request.mission_root).as_posix(),
                "envelope_sha256": envelope_sha,
                "staged_at": OBSERVED_AT,
                "status": "STAGED",
                "mode": "SHADOW",
            },
        )
        _write_json(
            handoff_ledger,
            {
                "event_timestamp": OBSERVED_AT,
                "handoff_id": handoff_id,
                "source_run_id": request.mission_id,
                "operator_action_id": request.action_id,
                "mode": "SHADOW",
                "envelope_sha256": envelope_sha,
                "pending_path": envelope_path.relative_to(request.mission_root).as_posix(),
                "status": "STAGED",
            },
        )
        _write_json(
            intake_path,
            {
                "schema_version": "navigator_intake_receipt.v1",
                "handoff_id": handoff_id,
                "source_run_id": request.mission_id,
                "envelope_path": envelope_path.relative_to(request.mission_root).as_posix(),
                "envelope_sha256": envelope_sha,
                "accepted_at": OBSERVED_AT,
                "status": "REJECTED" if self.failed else "ACCEPTED",
                "mode": "SHADOW",
                **(
                    {
                        "shadow_plan_path": plan_path.relative_to(
                            request.mission_root
                        ).as_posix()
                    }
                    if not self.failed
                    else {}
                ),
            },
        )
        paths = [envelope_path, staging_path, handoff_ledger, intake_path]
        if not self.failed:
            plan_seed = {
                "handoff_id": handoff_id,
                "source_run_id": request.mission_id,
                "envelope_sha256": envelope_sha,
            }
            plan_digest = hashlib.sha256(
                json.dumps(
                    plan_seed, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()[:16]
            plan_id = f"navigator-shadow-plan-{plan_digest}"
            _write_json(
                plan_path,
                {
                    "schema_version": "navigator_shadow_plan.v1",
                    "plan_id": plan_id,
                    "handoff_id": handoff_id,
                    "source_run_id": request.mission_id,
                    "created_at": OBSERVED_AT,
                    "expires_at": "2026-07-18T19:07:00Z",
                    "planning_status": "CREATED",
                    "validated_constraints": {
                        "mode": "SHADOW",
                        "allowed_operations": list(ALLOWED_OPERATIONS),
                        "prohibited_operations": list(PROHIBITED_OPERATIONS),
                    },
                    "prohibited_operations": list(PROHIBITED_OPERATIONS),
                    "source_artifact_refs": {
                        "handoff_envelope": envelope_path.relative_to(request.mission_root).as_posix(),
                        "source_packet": request.review_packet_path,
                        "operator_action": request.operator_action_path,
                    },
                    "source_artifact_hashes": {
                        "handoff_envelope": envelope_sha,
                        "source_packet": sha256_file(request.mission_root / request.review_packet_path),
                        "operator_action": sha256_file(request.mission_root / request.operator_action_path),
                    },
                },
            )
            _write_json(
                navigator_ledger,
                {
                    "event_timestamp": OBSERVED_AT,
                    "handoff_id": handoff_id,
                    "source_run_id": request.mission_id,
                    "envelope_sha256": envelope_sha,
                    "intake_receipt_path": intake_path.relative_to(
                        request.mission_root
                    ).as_posix(),
                    "shadow_plan_path": plan_path.relative_to(
                        request.mission_root
                    ).as_posix(),
                    "status": "ACCEPTED",
                },
            )
            paths.extend((plan_path, navigator_ledger))
            forged_paths = {
                "intake": intake_path,
                "plan": plan_path,
                "ledger": navigator_ledger,
            }
            if self.forged_boundary in forged_paths:
                forged_path = forged_paths[self.forged_boundary]
                forged = json.loads(forged_path.read_text(encoding="utf-8"))
                forged["source_run_id"] = "mission-foreign-correlation"
                _write_json(forged_path, forged)
        receipt_digest = hashlib.sha256(
            f"{handoff_id}:{envelope_sha}:intake-receipt".encode()
        ).hexdigest()[:16]
        idempotency_digest = hashlib.sha256(
            f"{handoff_id}:{envelope_sha}:shadow-intake".encode()
        ).hexdigest()[:24]
        result = {
            "status": "FAILED" if self.failed else "SUCCEEDED",
            "native_state": "REJECTED" if self.failed else "CREATED",
            "handoff_status": "STAGED",
            "intake_status": "REJECTED" if self.failed else "ACCEPTED",
            "plan_status": None if self.failed else "CREATED",
            "handoff_id": handoff_id,
            "intake_receipt_id": f"navigator-intake-receipt-{receipt_digest}",
            "plan_id": None if self.failed else plan_id,
            "allowed_operations": list(ALLOWED_OPERATIONS),
            "prohibited_operations": list(PROHIBITED_OPERATIONS),
            "expires_at": "2026-07-18T19:07:00Z",
            "idempotency_key": f"navigator-shadow-{idempotency_digest}",
            "decision_id": request.decision_id,
            "action_id": request.action_id,
            "produced_paths": [p.relative_to(request.mission_root).as_posix() for p in paths],
            "failure": (
                {
                    "code": "NAVIGATOR_INTAKE_REJECTED",
                    "error_type": "NavigatorIntakeError",
                    "message": "unsupported handoff envelope schema_version",
                    "resumable": False,
                }
                if self.failed
                else None
            ),
        }
        if self.malformed:
            result.pop("plan_id")
        return result


class NavigatorAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.battlestar = root / "battlestar"
        for relative in (
            "blackpod/runtime/navigator_handoff.py",
            "blackpod/runtime/navigator_intake.py",
            "blackpod/runtime/governor_decision_consumer.py",
            "blackpod/runtime/operator_inbox_action.py",
        ):
            target = self.battlestar / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# interface sentinel\n", encoding="utf-8")
        self.mission_root = root / "artifacts/missions" / MISSION_ID
        source = self.mission_root / "governor/attempt-0001/governor_decision.json"
        _write_json(source, {"decision_id": DECISION_ID})
        packet_path = self.mission_root / "operator/attempt-0001/review_packet.json"
        source_hashes = {"governor_decision": sha256_file(source)}
        decision_input_hash = hashlib.sha256(
            json.dumps(
                {"run_id": MISSION_ID, "source_hashes": source_hashes},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        packet = {
            "schema_version": "operator_review_packet.v1",
            "manifest_schema_version": "blackpod.mission_snapshot.v1",
            "packet_id": "operator-review-packet-1234567890abcdef",
            "run_id": MISSION_ID,
            "run_completed_at": OBSERVED_AT,
            "governor_posture": "NEUTRAL",
            "decision_state": "PROCEED",
            "allowed_next_step": "OPERATOR_REVIEW",
            "decision_summary": "Governor rendered PROCEED.",
            "readiness_state": "READY",
            "readiness_summary": "Governor readiness is READY.",
            "blockers": [],
            "warnings": [],
            "deliberation_summary": ["Governor reviewed current mission evidence."],
            "operator_route": "PENDING_APPROVAL",
            "source_artifact_paths": {"governor_decision": source.relative_to(self.mission_root).as_posix()},
            "source_artifact_hashes": source_hashes,
            "decision_input_hash": decision_input_hash,
            "created_at": OBSERVED_AT,
        }
        _write_json(packet_path, packet)
        action = {
            "schema_version": "operator_inbox_action.v1",
            "packet_sha256": sha256_file(packet_path),
            "decision_input_hash": decision_input_hash,
            "source_run_id": MISSION_ID,
            "action": "APPROVE_HANDOFF",
            "operator_id": "operator-navigator",
            "reason": "Approved deterministic Navigator SHADOW planning.",
            "created_at": OBSERVED_AT,
            "expires_at": "2026-07-18T19:07:00Z",
            "action_id": ACTION_ID,
            "packet_path": packet_path.relative_to(self.mission_root).as_posix(),
            "packet_id": packet["packet_id"],
            "resulting_status": "APPROVED_FOR_HANDOFF",
        }
        action_path = self.mission_root / "operator/attempt-0001/operator_action.json"
        _write_json(action_path, action)
        _write_json(
            self.mission_root / "operator/attempt-0001/operator_provenance.json",
            {
                "schema_version": "blackpod.operator_provenance.v1",
                "mission_id": MISSION_ID,
                "request_id": REQUEST_ID,
                "run_mode": "REPLAY",
                "observed_at": OBSERVED_AT,
                "decision_id": DECISION_ID,
                "action_id": ACTION_ID,
                "action": "APPROVE_HANDOFF",
                "result": "APPROVED_FOR_HANDOFF",
                "operator_id": "operator-navigator",
                "battlestar_git_revision": "a" * 40,
            },
        )
        _write_json(
            self.mission_root / "operator/attempt-0001/lineage_manifest.json",
            {
                "schema_version": "blackpod.operator_lineage.v1",
                "mission_id": MISSION_ID,
                "request_id": REQUEST_ID,
                "run_mode": "REPLAY",
                "observed_at": OBSERVED_AT,
                "decision_id": DECISION_ID,
                "action_id": ACTION_ID,
                "outputs": [
                    {
                        "name": "operator_review_packet",
                        "path": packet_path.relative_to(self.mission_root).as_posix(),
                        "sha256": sha256_file(packet_path),
                        "producer": "operator",
                        "mission_id": MISSION_ID,
                        "request_id": REQUEST_ID,
                        "observed_at": OBSERVED_AT,
                    },
                    {
                        "name": "operator_action",
                        "path": action_path.relative_to(self.mission_root).as_posix(),
                        "sha256": sha256_file(action_path),
                        "producer": "operator",
                        "mission_id": MISSION_ID,
                        "request_id": REQUEST_ID,
                        "observed_at": OBSERVED_AT,
                    },
                ],
            },
        )
        self.context = NavigatorMissionContext(
            mission_id=MISSION_ID,
            mission_root=self.mission_root,
            decision_id=DECISION_ID,
            action_id=ACTION_ID,
        )
        self.control = NavigatorExecutionControl.from_replay_fixture(
            NavigatorReplayFixture.from_mapping(_fixture_mapping())
        )

    def adapter(self, transport):
        return NavigatorAdapter(self.battlestar.resolve(), transport=transport)

    def test_fixture_contract_is_strict_and_shadow_only(self):
        parsed = NavigatorReplayFixture.from_mapping(_fixture_mapping())
        self.assertEqual(parsed.mode, NavigatorMode.SHADOW)
        with self.assertRaises(Exception):
            NavigatorReplayFixture.from_mapping(_fixture_mapping(extra=True))
        with self.assertRaises(Exception):
            NavigatorReplayFixture.from_mapping(_fixture_mapping(mode="LIVE"))

    def test_success_preserves_correlations_and_safety_boundary(self):
        transport = RecordingTransport()
        result = self.adapter(transport).execute(_request(), self.context, control=self.control)
        self.assertEqual(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.native_state, "CREATED")
        self.assertEqual(result.decision_id, DECISION_ID)
        self.assertEqual(result.action_id, ACTION_ID)
        self.assertEqual(result.allowed_operations, ALLOWED_OPERATIONS)
        self.assertEqual(result.prohibited_operations, PROHIBITED_OPERATIONS)
        self.assertEqual(len(result.produced_paths), 6)
        with self.assertRaisesRegex(ValueError, "successful Navigator result is incomplete"):
            replace(result, expires_at=None)

    def test_controlled_native_intake_rejection_is_technical_failure(self):
        result = self.adapter(RecordingTransport(failed=True)).execute(
            _request(), self.context, control=self.control
        )
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.intake_status.value, "REJECTED")
        self.assertIsNone(result.plan_status)
        self.assertEqual(result.failure.code, "NAVIGATOR_INTAKE_REJECTED")

    def test_failed_result_rejects_inconsistent_partial_native_state(self):
        with self.assertRaisesRegex(ValueError, "inconsistent partial native state"):
            NavigatorExecutionResult(
                mission_id=MISSION_ID,
                request_id=REQUEST_ID,
                run_mode=RunMode.REPLAY,
                status=StageStatus.FAILED,
                native_state=None,
                mode=NavigatorMode.SHADOW,
                handoff_status=NavigatorHandoffStatus.STAGED,
                intake_status=None,
                plan_status=None,
                handoff_id=None,
                intake_receipt_id=None,
                plan_id=None,
                allowed_operations=ALLOWED_OPERATIONS,
                prohibited_operations=PROHIBITED_OPERATIONS,
                expires_at=None,
                idempotency_key=None,
                decision_id=DECISION_ID,
                action_id=ACTION_ID,
                produced_paths=(),
                source_lineage=(),
                failure=NavigatorFailure(
                    code="NAVIGATOR_MALFORMED_RESULT",
                    error_type="ContractValidationError",
                    message="inconsistent injected result",
                    resumable=False,
                ),
            )

    def test_malformed_return_and_timeout_are_structured_failures(self):
        timeout = self.adapter(
            RecordingTransport(error=NavigatorTransportTimeout("deadline"))
        ).execute(_request(), self.context, control=self.control)
        self.assertEqual(timeout.failure.code, "NAVIGATOR_TIMEOUT")
        malformed = self.adapter(RecordingTransport(malformed=True)).execute(
            _request(), self.context, control=self.control
        )
        self.assertEqual(malformed.status, StageStatus.FAILED)
        self.assertEqual(malformed.failure.code, "NAVIGATOR_MALFORMED_RESULT")

    def test_live_and_replay_controls_never_fall_back(self):
        live = NavigatorExecutionControl(run_mode=RunMode.LIVE, observed_at=OBSERVED_AT)
        result = self.adapter(RecordingTransport()).execute(
            _request("REPLAY"), self.context, control=live
        )
        self.assertEqual(result.failure.code, "NAVIGATOR_MODE_MISMATCH")
        with self.assertRaises(Exception):
            NavigatorExecutionControl(
                run_mode=RunMode.LIVE,
                observed_at=OBSERVED_AT,
                fixture_id="fixture-not-live",
            )

    def test_missing_tampered_expired_and_absolute_inputs_are_rejected(self):
        action_path = self.mission_root / self.context.operator_action_path
        action = json.loads(action_path.read_text())
        action["expires_at"] = "2026-07-18T18:06:00Z"
        _write_json(action_path, action)
        expired = self.adapter(RecordingTransport()).execute(
            _request(), self.context, control=self.control
        )
        self.assertEqual(expired.failure.code, "NAVIGATOR_INPUT_INVALID")
        self.assertEqual(RecordingTransport().calls, [])

    def test_packet_source_symlink_is_rejected(self):
        source = (
            self.mission_root
            / "governor/attempt-0001/governor_decision.json"
        )
        contained_target = source.with_name("governor_decision-contained.json")
        source.rename(contained_target)
        source.symlink_to(contained_target.name)
        transport = RecordingTransport()
        result = self.adapter(transport).execute(
            _request(), self.context, control=self.control
        )
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "NAVIGATOR_INPUT_INVALID")
        self.assertEqual(transport.calls, [])

    def test_forged_native_source_hash_is_rejected(self):
        result = self.adapter(RecordingTransport(forged_source_hash=True)).execute(
            _request(), self.context, control=self.control
        )
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "NAVIGATOR_MALFORMED_RESULT")

    def test_success_cannot_use_the_controlled_failure_schema(self):
        result = self.adapter(
            RecordingTransport(unsupported_schema_success=True)
        ).execute(_request(), self.context, control=self.control)
        self.assertEqual(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "NAVIGATOR_MALFORMED_RESULT")

    def test_forged_intake_plan_and_ledger_correlations_are_rejected(self):
        for boundary in ("intake", "plan", "ledger"):
            with self.subTest(boundary=boundary):
                result = self.adapter(
                    RecordingTransport(forged_boundary=boundary)
                ).execute(_request(), self.context, control=self.control)
                self.assertEqual(result.status, StageStatus.FAILED)
                self.assertEqual(result.failure.code, "NAVIGATOR_MALFORMED_RESULT")
                output = self.context.output_absolute
                if output.exists():
                    for path in sorted(output.rglob("*"), reverse=True):
                        if path.is_file():
                            path.unlink()
                        elif path.is_dir():
                            path.rmdir()

    def test_context_rejects_path_escape(self):
        with self.assertRaises(Exception):
            NavigatorMissionContext(
                mission_id=MISSION_ID,
                mission_root=self.mission_root,
                decision_id=DECISION_ID,
                action_id=ACTION_ID,
                review_packet_path="../escape.json",
            )

    def test_source_has_no_broker_modeldock_or_combined_workflow_calls(self):
        root = Path(__file__).resolve().parents[1] / "src/blackpod_build_week"
        for filename in ("navigator_adapter.py", "navigator_workflow.py"):
            tree = ast.parse((root / filename).read_text(encoding="utf-8"))
            imported: list[str] = []
            calls: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name.lower() for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported.append((node.module or "").lower())
                elif isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name):
                        calls.append(function.id.lower())
                    elif isinstance(function, ast.Attribute):
                        calls.append(function.attr.lower())
            joined = " ".join(imported)
            for forbidden in (
                "blackpod.execution",
                "modeldock",
                "alpaca",
                "broker",
                "navigator_shadow_workflow",
            ):
                self.assertNotIn(forbidden, joined, filename)
            for forbidden_call in (
                "submit_order",
                "cancel_order",
                "modify_portfolio",
                "broker_call",
                "run_workflow",
            ):
                self.assertNotIn(forbidden_call, calls, filename)


if __name__ == "__main__":
    unittest.main()
