from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from blackpod_build_week.contracts import (
    ContractValidationError,
    CouncilTransportKind,
    MissionRequest,
    RunMode,
    StageStatus,
)
from blackpod_build_week.council_adapter import (
    COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
    EXPECTED_COUNCIL_OUTPUT_FILENAMES,
    CouncilAdapter,
    CouncilMissionContext,
    CouncilSupportingInput,
    CouncilTransportRequest,
    CouncilTransportTimeout,
    ProcessCouncilTransport,
    _validate_advisor_health_evidence,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"


def request(
    run_mode: str = "REPLAY",
    *,
    mission_id: str = "mission-council-adapter-001",
) -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-council-adapter-001",
            "mission_id": mission_id,
            "run_mode": run_mode,
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-council-adapter",
            "metadata": {},
        }
    )


def supporting_mapping(run_mode: str = "REPLAY") -> dict[str, object]:
    return {
        "schema_version": COUNCIL_SUPPORTING_INPUT_SCHEMA_VERSION,
        "input_id": "council-supporting-input-001",
        "run_mode": run_mode,
        "generated_at": OBSERVED_AT,
        "mandate": {
            "as_of": OBSERVED_AT,
            "ok": True,
            "reason": "BUILD_WEEK_POLICY_OK",
            "allowed_sides": ["BUY", "SELL"],
            "max_trades": 2,
            "risk_posture": "NORMAL",
            "source": "build-week-test",
        },
    }


class RecordingCouncilTransport:
    def __init__(
        self,
        *,
        native_state: str = "MIXED",
        error: Exception | None = None,
        malformed: bool = False,
        artifact_mismatch: bool = False,
        health_mismatch: bool = False,
    ) -> None:
        self.native_state = native_state
        self.error = error
        self.malformed = malformed
        self.artifact_mismatch = artifact_mismatch
        self.health_mismatch = health_mismatch
        self.calls: list[tuple[CouncilTransportRequest, float]] = []

    def run(
        self, invocation: CouncilTransportRequest, *, deadline_seconds: float
    ) -> dict[str, object]:
        self.calls.append((invocation, deadline_seconds))
        if self.error is not None:
            raise self.error
        output = invocation.mission_root / invocation.output_dir
        output.mkdir(parents=True, exist_ok=True)
        for filename in EXPECTED_COUNCIL_OUTPUT_FILENAMES:
            payload: dict[str, object] = {"artifact": filename}
            if filename == "council_input_packet.json":
                payload = {"packet_id": "council-input-packet-001"}
            elif filename == "council_synthesis.json":
                payload = {
                    "synthesis_id": "council-synthesis-001",
                    "input_packet_id": "council-input-packet-001",
                    "synthesis_state": self.native_state,
                    "key_conflicts": ["Senate evidence remains divided."],
                }
            elif filename == "council_executive_summary.json":
                payload = {
                    "summary_id": "council-summary-001",
                    "synthesis_id": (
                        "wrong-synthesis"
                        if self.artifact_mismatch
                        else "council-synthesis-001"
                    ),
                }
            elif filename == "council_advisor_runtime_config.json":
                payload = {
                    "advisor_manifest": [
                        {"advisor_name": name}
                        for name in (
                            "oracle_report",
                            "mandate",
                            "trading_candidate_report",
                            "senate_review_packet",
                            "senate_deliberation",
                        )
                    ]
                }
            elif filename == "council_advisor_runtime_validation.json":
                payload = {"readiness_status": "READY"}
            elif filename == "advisor_health_summary.json":
                payload = {
                    "advisor_count": 0 if self.health_mismatch else 5,
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
                }
            (output / filename).write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        result: dict[str, object] = {
            "native_state": self.native_state,
            "produced_paths": [
                f"{invocation.output_dir}/{name}"
                for name in EXPECTED_COUNCIL_OUTPUT_FILENAMES
            ],
            "input_id": "council-supporting-input-001",
            "candidate_report_id": "candidate-report-001",
            "senate_review_packet_id": "senate-review-001",
            "senate_deliberation_id": "senate-deliberation-001",
            "input_packet_id": "council-input-packet-001",
            "synthesis_id": "council-synthesis-001",
            "summary_id": "council-summary-001",
            "warnings": ["caution retained"],
            "blockers": [],
            "alignments": [],
            "conflicts": ["Senate evidence remains divided."],
            "dissent": [
                {
                    "symbol": "AAPL",
                    "deliberation_state": "UNFAVORABLE",
                    "senate_reasoning": ["evidence conflicts"],
                }
            ],
        }
        if self.malformed:
            del result["summary_id"]
        return result


class CouncilSupportingInputTests(unittest.TestCase):
    def test_exact_versioned_input_round_trips(self) -> None:
        value = supporting_mapping()
        parsed = CouncilSupportingInput.from_mapping(value)
        encoded = json.dumps(value).encode("utf-8")

        self.assertEqual(CouncilSupportingInput.from_bytes(encoded), parsed)
        self.assertIs(parsed.run_mode, RunMode.REPLAY)
        self.assertEqual(parsed.mandate.allowed_sides, ("BUY", "SELL"))

    def test_unknown_duplicate_and_unsupported_fields_are_rejected(self) -> None:
        unknown = supporting_mapping()
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            CouncilSupportingInput.from_mapping(unknown)

        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            CouncilSupportingInput.from_bytes(
                b'{"schema_version":"blackpod.council_supporting_input.v1",'
                b'"schema_version":"duplicate"}'
            )

        unsupported = supporting_mapping()
        unsupported["schema_version"] = "blackpod.council_supporting_input.v2"
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            CouncilSupportingInput.from_mapping(unsupported)

    def test_malformed_mandate_and_run_mode_are_rejected(self) -> None:
        bad_side = supporting_mapping()
        bad_side["mandate"]["allowed_sides"] = ["LONG"]  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "BUY and SELL"):
            CouncilSupportingInput.from_mapping(bad_side)

        bad_mode = supporting_mapping("SIMULATION")
        with self.assertRaises(ContractValidationError):
            CouncilSupportingInput.from_mapping(bad_mode)


class CouncilAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.battlestar_path = root / "battlestar"
        modules = (
            "blackpod/advisors/trading_candidate_generator.py",
            "blackpod/advisors/senate_candidate_intake.py",
            "blackpod/advisors/senate_deliberation.py",
            "blackpod/advisors/mandate.py",
            "blackpod/governor/council_synthesis.py",
            "blackpod/governor/council_executive_summary.py",
            "blackpod/runtime/advisor_health.py",
            "blackpod/runtime/validation_report.py",
        )
        for relative in modules:
            module = self.battlestar_path / relative
            module.parent.mkdir(parents=True, exist_ok=True)
            module.write_text("# interface sentinel\n", encoding="utf-8")

        self.mission_root = (
            root / "artifacts/missions/mission-council-adapter-001"
        )
        input_paths = (
            "oracle/attempt-0001/fleet-oracles-vapors-example_normalized.json",
            "oracle/attempt-0001/fleet-oracles-vapors-example_readiness.json",
            "oracle/attempt-0001/oracle_report_live.json",
            "oracle/attempt-0001/oracle_assessment_live.json",
            "oracle/attempt-0001/oracle_narrative_live.json",
        )
        for relative in input_paths:
            target = self.mission_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n", encoding="utf-8")
        self.context = CouncilMissionContext(
            mission_id="mission-council-adapter-001",
            mission_root=self.mission_root,
        )
        self.replay_input = CouncilSupportingInput.from_mapping(supporting_mapping())

    def adapter(self, transport) -> CouncilAdapter:
        return CouncilAdapter(
            self.battlestar_path.resolve(),
            transport=transport,
            deadline_seconds=7.5,
        )

    def test_success_preserves_correlation_lineage_and_dissent(self) -> None:
        transport = RecordingCouncilTransport(native_state="CONFLICTED")
        result = self.adapter(transport).execute(
            request(), self.context, supporting_input=self.replay_input
        )

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.mission_id, self.context.mission_id)
        self.assertEqual(result.request_id, "request-council-adapter-001")
        self.assertIs(result.run_mode, RunMode.REPLAY)
        self.assertIs(result.transport, CouncilTransportKind.REPLAY_FIXTURE)
        self.assertEqual(result.native_state, "CONFLICTED")
        self.assertEqual(result.conflicts, ("Senate evidence remains divided.",))
        self.assertEqual(result.dissent[0]["deliberation_state"], "UNFAVORABLE")
        self.assertEqual(
            result.produced_paths,
            tuple(
                f"council/attempt-0001/{name}"
                for name in EXPECTED_COUNCIL_OUTPUT_FILENAMES
            ),
        )
        self.assertEqual(
            result.source_lineage,
            (
                self.context.normalized_path,
                self.context.readiness_path,
                self.context.oracle_report_path,
                self.context.oracle_assessment_path,
                self.context.oracle_narrative_path,
                "council/inputs/council_supporting_input.json",
            ),
        )
        self.assertEqual(transport.calls[0][1], 7.5)

    def test_native_blocked_or_cautious_result_is_technical_success(self) -> None:
        result = self.adapter(
            RecordingCouncilTransport(native_state="BLOCKED")
        ).execute(request(), self.context, supporting_input=self.replay_input)

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.native_state, "BLOCKED")
        self.assertIsNone(result.failure)

    def test_technical_exception_is_structured_and_paths_are_sanitized(self) -> None:
        secret = self.mission_root / "private-candidate.json"
        result = self.adapter(
            RecordingCouncilTransport(
                error=RuntimeError(f"failed while reading {secret}")
            )
        ).execute(request(), self.context, supporting_input=self.replay_input)

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_EXECUTION_FAILED")
        self.assertEqual(result.failure.error_type, "RuntimeError")
        self.assertNotIn(str(self.mission_root), result.failure.message)
        self.assertIn("<redacted-path>", result.failure.message)

    def test_malformed_return_and_native_artifact_are_technical_failures(self) -> None:
        for transport in (
            RecordingCouncilTransport(malformed=True),
            RecordingCouncilTransport(artifact_mismatch=True),
            RecordingCouncilTransport(health_mismatch=True),
        ):
            with self.subTest(transport=type(transport).__name__):
                fresh_output = self.context.output_absolute
                if fresh_output.exists():
                    for path in fresh_output.iterdir():
                        path.unlink()
                result = self.adapter(transport).execute(
                    request(), self.context, supporting_input=self.replay_input
                )
                self.assertIs(result.status, StageStatus.FAILED)
                self.assertEqual(result.failure.code, "COUNCIL_MALFORMED_RESULT")

    def test_timeout_is_explicit_and_live_timeout_is_resumable(self) -> None:
        live_input = CouncilSupportingInput.from_mapping(supporting_mapping("LIVE"))
        result = self.adapter(
            RecordingCouncilTransport(error=CouncilTransportTimeout("expired"))
        ).execute(request("LIVE"), self.context, supporting_input=live_input)

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "COUNCIL_TIMEOUT")
        self.assertTrue(result.failure.resumable)

    def test_correlation_and_mode_mismatches_fail_before_transport(self) -> None:
        mismatched_context = CouncilMissionContext(
            mission_id="mission-council-adapter-002",
            mission_root=self.mission_root,
        )
        transport = RecordingCouncilTransport()
        correlation = self.adapter(transport).execute(
            request(), mismatched_context, supporting_input=self.replay_input
        )
        self.assertEqual(correlation.failure.code, "COUNCIL_CORRELATION_MISMATCH")
        self.assertEqual(transport.calls, [])

        live_input = CouncilSupportingInput.from_mapping(supporting_mapping("LIVE"))
        mode = self.adapter(transport).execute(
            request(), self.context, supporting_input=live_input
        )
        self.assertEqual(mode.failure.code, "COUNCIL_MODE_MISMATCH")
        self.assertEqual(transport.calls, [])

    def test_replay_and_live_use_only_their_explicit_supporting_input(self) -> None:
        replay_transport = RecordingCouncilTransport()
        replay = self.adapter(replay_transport).execute(
            request(), self.context, supporting_input=self.replay_input
        )
        self.assertIs(replay.transport, CouncilTransportKind.REPLAY_FIXTURE)
        self.assertEqual(
            replay_transport.calls[0][0].supporting_input["run_mode"], "REPLAY"
        )

        for path in self.context.output_absolute.iterdir():
            path.unlink()
        live_transport = RecordingCouncilTransport()
        live_input = CouncilSupportingInput.from_mapping(supporting_mapping("LIVE"))
        live = self.adapter(live_transport).execute(
            request("LIVE"), self.context, supporting_input=live_input
        )
        self.assertIs(live.transport, CouncilTransportKind.LIVE_MISSION_INPUTS)
        self.assertEqual(
            live_transport.calls[0][0].supporting_input["run_mode"], "LIVE"
        )

    def test_existing_immutable_artifact_is_not_overwritten(self) -> None:
        output = self.context.output_absolute
        output.mkdir(parents=True)
        sentinel = output / "council_synthesis.json"
        sentinel.write_text("immutable\n", encoding="utf-8")
        transport = RecordingCouncilTransport()

        result = self.adapter(transport).execute(
            request(), self.context, supporting_input=self.replay_input
        )

        self.assertEqual(result.failure.code, "COUNCIL_IMMUTABLE_COLLISION")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutable\n")
        self.assertEqual(transport.calls, [])

    def test_context_rejects_escape(self) -> None:
        with self.assertRaisesRegex(Exception, "beneath"):
            CouncilMissionContext(
                mission_id="mission-council-adapter-001",
                mission_root=self.mission_root,
                output_dir="../escape",
            )

    def test_adapter_source_contains_no_downstream_or_provider_calls(self) -> None:
        source = Path(__file__).parents[1] / "src/blackpod_build_week/council_adapter.py"
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported_modules = {
            alias.name.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        for forbidden_module in (
            "modeldock",
            "blackpod.governor.governor",
            "blackpod.runtime.navigator",
            "blackpod.execution",
            "yfinance",
            "alpaca",
        ):
            self.assertFalse(
                any(
                    module == forbidden_module
                    or module.startswith(f"{forbidden_module}.")
                    for module in imported_modules
                )
            )
        forbidden_calls = {
            "Governor",
            "Navigator",
            "run_governor",
            "run_navigator",
            "submit_order",
            "place_order",
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        called_names.update(
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        )
        self.assertTrue(forbidden_calls.isdisjoint(called_names))
        self.assertNotIn("AdvisorHealthSummary(", text)
        self.assertIn("advisor_health_module.build_advisor_health_summary(", text)

    def test_native_health_validation_requires_exact_correlated_evidence(self) -> None:
        names = (
            "oracle_report",
            "mandate",
            "trading_candidate_report",
            "senate_review_packet",
            "senate_deliberation",
        )
        sources = tuple(
            SimpleNamespace(
                advisor_name=name,
                path=f"council/attempt-0001/{name}.json",
                source_sha256=f"{index + 1:064x}",
            )
            for index, name in enumerate(names)
        )
        validation = SimpleNamespace(
            advisor_entries=tuple(
                SimpleNamespace(advisor_name=name) for name in names
            ),
            readiness_status="DEGRADED",
        )
        advisors = tuple(
            SimpleNamespace(
                advisor_name=source.advisor_name,
                enabled=True,
                required=True,
                loaded=True,
                healthy=True,
                severity="OK",
                freshness="fresh",
                source_path=source.path,
                source_sha256=source.source_sha256,
            )
            for source in sources
        )
        health = SimpleNamespace(
            advisors=advisors,
            advisor_count=5,
            overall_status="BLOCKED",
        )
        packet = SimpleNamespace(source_artifacts=sources)

        _validate_advisor_health_evidence(validation, health, packet)

        blocked_advisors = list(advisors)
        blocked_advisors[2] = SimpleNamespace(
            **{
                **blocked_advisors[2].__dict__,
                "loaded": False,
                "healthy": False,
                "severity": "BLOCKER",
                "freshness": "malformed",
            }
        )
        _validate_advisor_health_evidence(
            validation,
            SimpleNamespace(
                advisors=tuple(blocked_advisors),
                advisor_count=5,
                overall_status="BLOCKED",
            ),
            packet,
        )

        malformed_health = SimpleNamespace(
            advisors=advisors[:-1],
            advisor_count=4,
            overall_status="READY",
        )
        with self.assertRaisesRegex(Exception, "canonical Council evidence set"):
            _validate_advisor_health_evidence(
                validation,
                malformed_health,
                packet,
            )


class _NeverReadyReceiver:
    def poll(self, timeout: float) -> bool:
        return False

    def close(self) -> None:
        pass


class _Sender:
    def close(self) -> None:
        pass


class _Process:
    exitcode = None

    def __init__(self) -> None:
        self.alive = True

    def start(self) -> None:
        pass

    def terminate(self) -> None:
        self.alive = False

    def kill(self) -> None:
        self.alive = False

    def join(self, timeout: float | None = None) -> None:
        pass

    def is_alive(self) -> bool:
        return self.alive


class _ProcessContext:
    def Pipe(self, duplex: bool):
        return _NeverReadyReceiver(), _Sender()

    def Process(self, target, args):
        return _Process()


class CouncilProcessDeadlineTests(unittest.TestCase):
    def test_process_transport_terminates_at_hard_deadline(self) -> None:
        invocation = CouncilTransportRequest(
            battlestar_path=Path("/tmp/battlestar"),
            mission_root=Path("/tmp/mission"),
            normalized_path="oracle/normalized.json",
            readiness_path="oracle/readiness.json",
            oracle_report_path="oracle/report.json",
            oracle_assessment_path="oracle/assessment.json",
            oracle_narrative_path="oracle/narrative.json",
            output_dir="council/attempt-0001",
            generated_at=OBSERVED_AT,
            supporting_input=supporting_mapping(),
        )
        with mock.patch(
            "blackpod_build_week.council_adapter.multiprocessing.get_context",
            return_value=_ProcessContext(),
        ):
            with self.assertRaises(CouncilTransportTimeout):
                ProcessCouncilTransport().run(invocation, deadline_seconds=0.01)


if __name__ == "__main__":
    unittest.main()
