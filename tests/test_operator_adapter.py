from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from blackpod_build_week.contracts import ContractValidationError, MissionRequest, RunMode
from blackpod_build_week.contracts.mission_snapshot import (
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.operator_adapter import (
    EXPECTED_OPERATOR_OUTPUT_PATHS,
    GOVERNOR_DECISION_LOADER_ENTRY_POINT,
    GOVERNOR_DELIBERATION_LOADER_ENTRY_POINT,
    GOVERNOR_READINESS_LOADER_ENTRY_POINT,
    OPERATOR_ACTION_PATH,
    OPERATOR_ACTION_ENTRY_POINT,
    OPERATOR_ACTION_SCHEMA_VERSION,
    OPERATOR_LEDGER_ENTRY_PATH,
    OPERATOR_LEDGER_SCHEMA_VERSION,
    OPERATOR_LINEAGE_PATH,
    OPERATOR_LINEAGE_SCHEMA_VERSION,
    OPERATOR_PROVENANCE_PATH,
    OPERATOR_PROVENANCE_SCHEMA_VERSION,
    OPERATOR_PACKET_ADAPTER_ENTRY_POINT,
    OPERATOR_RECEIPT_PATH,
    OPERATOR_RECEIPT_SCHEMA_VERSION,
    OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
    OPERATOR_REPLAY_INPUT_PATH,
    OPERATOR_REVIEW_PACKET_PATH,
    OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
    NATIVE_OPERATOR_ACTION_FIELDS,
    NATIVE_OPERATOR_LEDGER_FIELDS,
    NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
    NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
    NATIVE_OPERATOR_RECEIPT_FIELDS,
    OperatorActionInput,
    OperatorAdapter,
    OperatorMissionContext,
    OperatorTransportRequest,
    OperatorTransportTimeout,
    _read_contained_native_action,
)


MISSION_ID = "mission-operator-adapter-001"
REQUEST_ID = "request-operator-adapter-001"
ACTED_AT = "2026-07-18T18:06:00Z"


def mission_request(run_mode: str = "REPLAY") -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": REQUEST_ID,
            "mission_id": MISSION_ID,
            "run_mode": run_mode,
            "symbol": "AAPL",
            "requested_at": "2026-07-18T18:05:00Z",
            "operator_id": "operator-adapter-request",
            "metadata": {},
        }
    )


def replay_mapping(
    *, action: str = "APPROVE_HANDOFF", operator_id: str = "operator-adapter"
) -> dict[str, object]:
    return {
        "schema_version": OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
        "fixture_id": "operator-fixture-001",
        "run_mode": "REPLAY",
        "action": action,
        "operator_id": operator_id,
        "reason": "Reviewed the deterministic Governor decision.",
        "acted_at": ACTED_AT,
        "expires_in_minutes": 60 if action == "APPROVE_HANDOFF" else None,
    }


class RecordingOperatorTransport:
    def __init__(
        self,
        *,
        error: Exception | None = None,
        malformed: bool = False,
        malformed_artifact: bool = False,
        absolute_leak: bool = False,
        symlink_directory: bool = False,
    ) -> None:
        self.error = error
        self.malformed = malformed
        self.malformed_artifact = malformed_artifact
        self.absolute_leak = absolute_leak
        self.symlink_directory = symlink_directory
        self.calls: list[tuple[OperatorTransportRequest, float]] = []

    def run(
        self, invocation: OperatorTransportRequest, *, deadline_seconds: float
    ) -> dict[str, object]:
        self.calls.append((invocation, deadline_seconds))
        if self.error is not None:
            raise self.error
        action = OperatorAction(invocation.action_input["action"])
        result = {
            OperatorAction.APPROVE_HANDOFF: OperatorResult.APPROVED_FOR_HANDOFF,
            OperatorAction.REJECT: OperatorResult.REJECTED,
        }[action]
        output = invocation.mission_root / invocation.output_dir
        output.mkdir(parents=True, exist_ok=True)
        action_id = "operator-action-1234567890abcdef"
        decision_id = "governor-decision-001"
        source_paths = {
            "governor_decision": invocation.governor_decision_path,
            "governor_decision_readiness": invocation.governor_readiness_path,
            "governor_deliberation": invocation.governor_deliberation_path,
            "governor_rendered_decision": invocation.governor_rendered_path,
            "governor_provenance": invocation.governor_provenance_path,
            "governor_lineage_manifest": invocation.governor_lineage_path,
        }
        source_hashes = {
            name: sha256_file(invocation.mission_root / path)
            for name, path in source_paths.items()
        }
        decision_input_hash = _canonical_sha256(
            {"run_id": invocation.mission_id, "source_hashes": source_hashes}
        )
        packet = {
            "schema_version": OPERATOR_REVIEW_PACKET_SCHEMA_VERSION,
            "manifest_schema_version": "blackpod.mission_snapshot.v1",
            "packet_id": "operator-review-packet-001",
            "run_id": invocation.mission_id,
            "run_completed_at": invocation.action_input["acted_at"],
            "governor_posture": "NEUTRAL",
            "decision_state": "PROCEED",
            "allowed_next_step": "OPERATOR_REVIEW",
            "decision_summary": (
                "/tmp/leak" if self.absolute_leak else "Governor rendered PROCEED."
            ),
            "readiness_state": "READY",
            "readiness_summary": "Governor readiness is READY.",
            "blockers": [],
            "warnings": [],
            "deliberation_summary": ["Governor reviewed the evidence."],
            "operator_route": "PENDING_APPROVAL",
            "source_artifact_paths": source_paths,
            "source_artifact_hashes": source_hashes,
            "decision_input_hash": decision_input_hash,
            "created_at": invocation.action_input["acted_at"],
        }
        _write(output / "review_packet.json", packet)
        expiry = None
        minutes = invocation.action_input["expires_in_minutes"]
        if minutes is not None:
            expiry = (
                datetime.fromisoformat(
                    str(invocation.action_input["acted_at"]).replace("Z", "+00:00")
                )
                + timedelta(minutes=int(minutes))
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        action_payload = {
            "schema_version": OPERATOR_ACTION_SCHEMA_VERSION,
            "packet_sha256": sha256_file(output / "review_packet.json"),
            "decision_input_hash": decision_input_hash,
            "source_run_id": invocation.mission_id,
            "action": action.value,
            "operator_id": invocation.action_input["operator_id"],
            "reason": invocation.action_input["reason"],
            "created_at": invocation.action_input["acted_at"],
            "expires_at": expiry,
            "action_id": action_id,
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "packet_id": packet["packet_id"],
            "resulting_status": result.value,
        }
        _write(output / "operator_action.json", action_payload)
        audit = {
            "event_timestamp": invocation.action_input["acted_at"],
            "run_id": invocation.mission_id,
            "decision_input_hash": decision_input_hash,
            "operator_route": "PENDING_APPROVAL",
            "packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "result_status": "CONSUMED",
        }
        _write(
            output / "operator_receipt.json",
            {
                "schema_version": OPERATOR_RECEIPT_SCHEMA_VERSION,
                **audit,
            },
        )
        _write(
            output / "operator_ledger_entry.json",
            audit,
        )
        fixture_sha = (
            sha256_file(invocation.mission_root / OPERATOR_REPLAY_INPUT_PATH)
            if invocation.run_mode == "REPLAY"
            else None
        )
        _write(
            output / "operator_provenance.json",
            {
                "schema_version": OPERATOR_PROVENANCE_SCHEMA_VERSION,
                "mission_id": invocation.mission_id,
                "request_id": invocation.request_id,
                "run_mode": invocation.run_mode,
                "observed_at": invocation.action_input["acted_at"],
                "decision_id": decision_id,
                "action_id": action_id,
                "action": action.value,
                "result": result.value,
                "operator_id": invocation.action_input["operator_id"],
                "battlestar_git_revision": invocation.battlestar_git_revision,
                "battlestar_git_branch": invocation.battlestar_git_branch,
                "battlestar_dirty_worktree": invocation.battlestar_dirty_worktree,
                "governor_decision_loader_entry_point": GOVERNOR_DECISION_LOADER_ENTRY_POINT,
                "governor_readiness_loader_entry_point": GOVERNOR_READINESS_LOADER_ENTRY_POINT,
                "governor_deliberation_loader_entry_point": GOVERNOR_DELIBERATION_LOADER_ENTRY_POINT,
                "packet_adapter_entry_point": OPERATOR_PACKET_ADAPTER_ENTRY_POINT,
                "operator_action_entry_point": OPERATOR_ACTION_ENTRY_POINT,
                "native_status": "RECORDED",
                "fixture_id": invocation.action_input["fixture_id"],
                "fixture_sha256": fixture_sha,
            },
        )
        governor_revision = json.loads(
            (invocation.mission_root / invocation.governor_provenance_path).read_text(
                encoding="utf-8"
            )
        )["component"]["git_revision"]
        lineage_inputs = [
            _lineage_entry(
                invocation,
                name=name,
                path=path,
                producer="governor",
                schema_version=_governor_schema(name),
                revision=governor_revision,
            )
            for name, path in source_paths.items()
        ]
        if invocation.run_mode == "REPLAY":
            lineage_inputs.append(
                _lineage_entry(
                    invocation,
                    name="operator_replay_action",
                    path=OPERATOR_REPLAY_INPUT_PATH,
                    producer="harbormaster",
                    schema_version=OPERATOR_REPLAY_ACTION_SCHEMA_VERSION,
                    revision=f"sha256:{fixture_sha}",
                )
            )
        output_specs = (
            ("operator_review_packet", OPERATOR_REVIEW_PACKET_PATH, OPERATOR_REVIEW_PACKET_SCHEMA_VERSION),
            ("operator_action", OPERATOR_ACTION_PATH, OPERATOR_ACTION_SCHEMA_VERSION),
            ("operator_receipt", OPERATOR_RECEIPT_PATH, OPERATOR_RECEIPT_SCHEMA_VERSION),
            ("operator_ledger_entry", OPERATOR_LEDGER_ENTRY_PATH, OPERATOR_LEDGER_SCHEMA_VERSION),
            ("operator_provenance", OPERATOR_PROVENANCE_PATH, OPERATOR_PROVENANCE_SCHEMA_VERSION),
        )
        output_sources = {
            "operator_review_packet": list(source_paths),
            "operator_action": [
                "operator_review_packet",
                *(("operator_replay_action",) if invocation.run_mode == "REPLAY" else ()),
            ],
            "operator_receipt": ["operator_action", "operator_review_packet"],
            "operator_ledger_entry": ["operator_action", "operator_review_packet"],
            "operator_provenance": [
                "operator_action",
                *(("operator_replay_action",) if invocation.run_mode == "REPLAY" else ()),
            ],
        }
        lineage_outputs = []
        for name, path, schema in output_specs:
            entry = _lineage_entry(
                invocation,
                name=name,
                path=path,
                producer="operator",
                schema_version=schema,
                revision=invocation.battlestar_git_revision,
            )
            entry["source_input_names"] = output_sources[name]
            lineage_outputs.append(entry)
        _write(
            output / "lineage_manifest.json",
            {
                "schema_version": OPERATOR_LINEAGE_SCHEMA_VERSION,
                "mission_id": invocation.mission_id,
                "request_id": invocation.request_id,
                "run_mode": invocation.run_mode,
                "observed_at": invocation.action_input["acted_at"],
                "decision_id": decision_id,
                "action_id": action_id,
                "inputs": lineage_inputs,
                "outputs": lineage_outputs,
            },
        )
        if self.malformed_artifact:
            receipt = json.loads(
                (output / "operator_receipt.json").read_text(encoding="utf-8")
            )
            receipt["action_id"] = "operator-action-unrelated"
            (output / "operator_receipt.json").write_bytes(
                canonical_json_bytes(receipt)
            )
        if self.symlink_directory:
            outside = invocation.mission_root / "outside-operator-attempt"
            outside.mkdir(exist_ok=True)
            (output / "escape").symlink_to(outside, target_is_directory=True)
        raw: dict[str, object] = {
            "route": "PENDING_APPROVAL",
            "action": action.value,
            "result": result.value,
            "native_status": "RECORDED",
            "action_id": action_id,
            "operator_id": invocation.action_input["operator_id"],
            "acted_at": invocation.action_input["acted_at"],
            "warnings": [],
            "review_packet_path": OPERATOR_REVIEW_PACKET_PATH,
            "produced_paths": list(EXPECTED_OPERATOR_OUTPUT_PATHS),
        }
        if self.malformed:
            raw["result"] = "APPROVED_FOR_HANDOFF" if action is OperatorAction.REJECT else "REJECTED"
        return raw


class OperatorReplayInputTests(unittest.TestCase):
    def test_strict_replay_fixture_round_trips(self) -> None:
        value = replay_mapping()
        parsed = OperatorActionInput.from_replay_mapping(value)
        self.assertEqual(
            OperatorActionInput.from_replay_bytes(json.dumps(value).encode()), parsed
        )
        self.assertIs(parsed.action, OperatorAction.APPROVE_HANDOFF)
        self.assertEqual(parsed.expires_in_minutes, 60)

    def test_unknown_duplicate_version_mode_and_blank_fields_are_rejected(self) -> None:
        unknown = replay_mapping()
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            OperatorActionInput.from_replay_mapping(unknown)
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            OperatorActionInput.from_replay_bytes(
                b'{"schema_version":"blackpod.operator_action_replay.v1",'
                b'"schema_version":"duplicate"}'
            )
        wrong_version = replay_mapping()
        wrong_version["schema_version"] = "blackpod.operator_action_replay.v2"
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            OperatorActionInput.from_replay_mapping(wrong_version)
        wrong_mode = replay_mapping()
        wrong_mode["run_mode"] = "LIVE"
        with self.assertRaisesRegex(ContractValidationError, "REPLAY"):
            OperatorActionInput.from_replay_mapping(wrong_mode)
        blank = replay_mapping()
        blank["operator_id"] = ""
        with self.assertRaises(ContractValidationError):
            OperatorActionInput.from_replay_mapping(blank)

    def test_approval_requires_a_positive_expiry(self) -> None:
        missing = replay_mapping()
        missing["expires_in_minutes"] = None
        with self.assertRaisesRegex(ContractValidationError, "requires a positive"):
            OperatorActionInput.from_replay_mapping(missing)
        rejected = replay_mapping(action="REJECT")
        rejected["expires_in_minutes"] = None
        self.assertIs(
            OperatorActionInput.from_replay_mapping(rejected).action,
            OperatorAction.REJECT,
        )


class NativeActionPathTests(unittest.TestCase):
    def test_native_relative_action_path_resolves_inside_temporary_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            action = root / "operator_action_relative.json"
            _write(action, {"schema_version": OPERATOR_ACTION_SCHEMA_VERSION})
            self.assertEqual(
                _read_contained_native_action(action.name, root),
                {"schema_version": OPERATOR_ACTION_SCHEMA_VERSION},
            )

    def test_native_action_path_outside_temporary_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root, tempfile.TemporaryDirectory() as raw_other:
            root = Path(raw_root)
            outside = Path(raw_other) / "operator_action_outside.json"
            _write(outside, {"schema_version": OPERATOR_ACTION_SCHEMA_VERSION})
            with self.assertRaisesRegex(Exception, "escaped"):
                _read_contained_native_action(outside, root)


class OperatorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.battlestar = root / "battlestar"
        for relative in (
            "blackpod/governor/governor_decision.py",
            "blackpod/governor/governor_decision_readiness.py",
            "blackpod/governor/governor_deliberation.py",
            "blackpod/runtime/governor_decision_consumer.py",
            "blackpod/runtime/operator_inbox_action.py",
        ):
            path = self.battlestar / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# native interface sentinel\n", encoding="utf-8")
        self.mission_root = root / "artifacts" / "missions" / MISSION_ID
        self.mission_root.mkdir(parents=True)
        self.context = OperatorMissionContext(
            mission_id=MISSION_ID,
            mission_root=self.mission_root,
            battlestar_git_revision="a" * 40,
        )
        for relative in self.context.input_paths:
            path = self.mission_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        (self.mission_root / self.context.governor_decision_path).write_bytes(
            canonical_json_bytes({"decision_id": "governor-decision-001"})
        )
        (self.mission_root / self.context.governor_provenance_path).write_bytes(
            canonical_json_bytes(
                {
                    "schema_version": "blackpod.governor_provenance.v1",
                    "mission_id": MISSION_ID,
                    "request_id": REQUEST_ID,
                    "run_mode": "REPLAY",
                    "component": {
                        "git_revision": "b" * 40,
                    },
                }
            )
        )
        replay_path = self.mission_root / OPERATOR_REPLAY_INPUT_PATH
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        replay_path.write_bytes(canonical_json_bytes(replay_mapping()))
        self.action_input = OperatorActionInput.from_replay_mapping(replay_mapping())

    def adapter(self, transport) -> OperatorAdapter:
        return OperatorAdapter(
            self.battlestar.resolve(), transport=transport, deadline_seconds=4.5
        )

    def clear_outputs(self) -> None:
        output = self.context.output_absolute
        if output.exists():
            for path in output.iterdir():
                path.unlink()

    def test_approval_and_rejection_are_typed_technical_successes(self) -> None:
        for action in (OperatorAction.APPROVE_HANDOFF, OperatorAction.REJECT):
            with self.subTest(action=action):
                self.clear_outputs()
                mapping = replay_mapping(action=action.value)
                action_input = OperatorActionInput.from_replay_mapping(mapping)
                transport = RecordingOperatorTransport()
                result = self.adapter(transport).execute(
                    mission_request(), self.context, action_input=action_input
                )
                self.assertIs(result.technical_status, OperatorActionStatus.SUCCEEDED)
                self.assertIs(result.action, action)
                self.assertIs(
                    result.result,
                    OperatorResult.APPROVED_FOR_HANDOFF
                    if action is OperatorAction.APPROVE_HANDOFF
                    else OperatorResult.REJECTED,
                )
                self.assertEqual(result.produced_paths, EXPECTED_OPERATOR_OUTPUT_PATHS)
                self.assertEqual(transport.calls[0][1], 4.5)

                packet = json.loads(
                    (self.mission_root / OPERATOR_REVIEW_PACKET_PATH).read_text()
                )
                native_action = json.loads(
                    (self.mission_root / OPERATOR_ACTION_PATH).read_text()
                )
                receipt = json.loads(
                    (self.mission_root / OPERATOR_RECEIPT_PATH).read_text()
                )
                ledger = json.loads(
                    (self.mission_root / OPERATOR_LEDGER_ENTRY_PATH).read_text()
                )
                provenance = json.loads(
                    (self.mission_root / OPERATOR_PROVENANCE_PATH).read_text()
                )
                lineage = json.loads(
                    (self.mission_root / OPERATOR_LINEAGE_PATH).read_text()
                )
                self.assertIn(
                    frozenset(packet),
                    {
                        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS,
                        NATIVE_OPERATOR_PACKET_REQUIRED_FIELDS
                        | NATIVE_OPERATOR_PACKET_OPTIONAL_FIELDS,
                    },
                )
                self.assertEqual(frozenset(native_action), NATIVE_OPERATOR_ACTION_FIELDS)
                self.assertEqual(frozenset(receipt), NATIVE_OPERATOR_RECEIPT_FIELDS)
                self.assertEqual(frozenset(ledger), NATIVE_OPERATOR_LEDGER_FIELDS)
                for native_payload in (packet, native_action, receipt, ledger):
                    self.assertNotIn("mission_id", native_payload)
                    self.assertNotIn("request_id", native_payload)
                    self.assertNotIn("decision_id", native_payload)
                self.assertEqual(provenance["decision_id"], "governor-decision-001")
                self.assertEqual(provenance["action_id"], result.action_id)
                self.assertEqual(provenance["observed_at"], ACTED_AT)
                self.assertEqual(lineage["decision_id"], "governor-decision-001")
                self.assertEqual(lineage["action_id"], result.action_id)
                self.assertEqual(lineage["observed_at"], ACTED_AT)

    def test_correlation_and_mode_fail_before_transport(self) -> None:
        transport = RecordingOperatorTransport()
        wrong_context = OperatorMissionContext(
            mission_id="mission-operator-adapter-other",
            mission_root=self.mission_root,
            battlestar_git_revision="a" * 40,
        )
        result = self.adapter(transport).execute(
            mission_request(), wrong_context, action_input=self.action_input
        )
        self.assertEqual(result.failure.code, "OPERATOR_CORRELATION_MISMATCH")
        self.assertEqual(transport.calls, [])

        live_input = OperatorActionInput.live(
            action="APPROVE_HANDOFF",
            operator_id="operator-adapter",
            reason="Reviewed live Governor evidence.",
            acted_at=ACTED_AT,
            expires_in_minutes=60,
        )
        result = self.adapter(transport).execute(
            mission_request(), self.context, action_input=live_input
        )
        self.assertEqual(result.failure.code, "OPERATOR_MODE_MISMATCH")
        self.assertEqual(transport.calls, [])

    def test_malformed_exception_timeout_and_absolute_leak_fail_closed(self) -> None:
        cases = (
            (RecordingOperatorTransport(malformed=True), "OPERATOR_MALFORMED_RESULT"),
            (
                RecordingOperatorTransport(malformed_artifact=True),
                "OPERATOR_MALFORMED_RESULT",
            ),
            (
                RecordingOperatorTransport(symlink_directory=True),
                "OPERATOR_MALFORMED_RESULT",
            ),
            (
                RecordingOperatorTransport(error=RuntimeError(str(self.mission_root / "secret"))),
                "OPERATOR_EXECUTION_FAILED",
            ),
            (
                RecordingOperatorTransport(error=OperatorTransportTimeout("expired")),
                "OPERATOR_TIMEOUT",
            ),
            (RecordingOperatorTransport(absolute_leak=True), "OPERATOR_MALFORMED_RESULT"),
        )
        for transport, code in cases:
            with self.subTest(code=code):
                self.clear_outputs()
                result = self.adapter(transport).execute(
                    mission_request(), self.context, action_input=self.action_input
                )
                self.assertIs(result.technical_status, OperatorActionStatus.FAILED)
                self.assertEqual(result.failure.code, code)
                self.assertNotIn(str(self.mission_root), result.failure.message)

    def test_missing_input_collision_and_path_escape_never_overwrite(self) -> None:
        transport = RecordingOperatorTransport()
        missing = self.mission_root / self.context.governor_rendered_path
        missing.unlink()
        result = self.adapter(transport).execute(
            mission_request(), self.context, action_input=self.action_input
        )
        self.assertEqual(result.failure.code, "OPERATOR_INPUT_INVALID")
        self.assertEqual(transport.calls, [])

        missing.write_text("{}\n", encoding="utf-8")
        self.context.output_absolute.mkdir(parents=True)
        sentinel = self.context.output_absolute / "operator_action.json"
        sentinel.write_text("immutable\n", encoding="utf-8")
        result = self.adapter(transport).execute(
            mission_request(), self.context, action_input=self.action_input
        )
        self.assertEqual(result.failure.code, "OPERATOR_IMMUTABLE_COLLISION")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutable\n")

        with self.assertRaisesRegex(Exception, "beneath"):
            OperatorMissionContext(
                mission_id=MISSION_ID,
                mission_root=self.mission_root,
                output_dir="../escape",
            )

    def test_source_contains_no_navigator_modeldock_broker_or_execution_calls(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "blackpod_build_week"
            / "operator_adapter.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        for forbidden in ("navigator", "modeldock", "broker", "blackpod.execution"):
            self.assertFalse(any(forbidden in name.lower() for name in imports))
        source = source_path.read_text(encoding="utf-8").lower()
        for forbidden in ("stage_navigator_handoff(", "submit_order(", "broker_call("):
            self.assertNotIn(forbidden, source)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(canonical_json_bytes(payload))


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _lineage_entry(
    invocation: OperatorTransportRequest,
    *,
    name: str,
    path: str,
    producer: str,
    schema_version: str | None,
    revision: str,
) -> dict[str, object]:
    target = invocation.mission_root / path
    return {
        "name": name,
        "path": path,
        "producer": producer,
        "sha256": sha256_file(target),
        "byte_size": target.stat().st_size,
        "schema_version": schema_version,
        "originating_component_revision": revision,
        "mission_id": invocation.mission_id,
        "request_id": invocation.request_id,
        "observed_at": str(invocation.action_input["acted_at"]),
    }


def _governor_schema(name: str) -> str:
    return {
        "governor_decision": "blackpod.contracts.governor_decision.GovernorDecision",
        "governor_decision_readiness": "blackpod.contracts.GovernorDecisionReadiness",
        "governor_deliberation": "blackpod.contracts.GovernorDeliberation",
        "governor_rendered_decision": "blackpod.governor_rendered_decision.v1",
        "governor_provenance": "blackpod.governor_provenance.v1",
        "governor_lineage_manifest": "blackpod.governor_lineage.v1",
    }[name]


if __name__ == "__main__":
    unittest.main()
