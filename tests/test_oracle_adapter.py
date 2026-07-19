from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import ContractValidationError, MissionRequest, RunMode
from blackpod_build_week.contracts.mission_snapshot import OracleTransportKind, StageStatus
from blackpod_build_week.oracle_adapter import (
    EXPECTED_ORACLE_OUTPUT_FILENAMES,
    ORACLE_FLEET_ID,
    ORACLE_REPLAY_SCHEMA_VERSION,
    ORACLE_SYMBOLS,
    OracleAdapter,
    OracleMissionContext,
    OracleTransportRequest,
    OracleTransportTimeout,
    ProcessOracleTransport,
    ReplayOracleInput,
)


def _request(run_mode: str = "REPLAY", *, mission_id: str = "mission-oracle-001") -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-oracle-001",
            "mission_id": mission_id,
            "run_mode": run_mode,
            "symbol": "SPY",
            "requested_at": "2026-07-18T18:05:00Z",
            "operator_id": "operator-001",
            "metadata": {},
        }
    )


def _replay_mapping() -> dict[str, object]:
    quotes: dict[str, object] = {}
    for symbol in ORACLE_SYMBOLS:
        base = 100.0 + (sum(ord(character) for character in symbol) % 17)
        quotes[symbol] = {
            "last_price": base,
            "previous_close": base - 1.0,
            "open": base - 0.5,
            "day_high": base + 1.5,
            "day_low": base - 1.5,
            "last_volume": 1_000_000,
        }
    return {
        "schema_version": ORACLE_REPLAY_SCHEMA_VERSION,
        "fixture_id": "oracle-replay-build-week-v1",
        "generated_at": "2026-07-18T18:05:00Z",
        "fleet_id": ORACLE_FLEET_ID,
        "quotes": quotes,
    }


def _native_result(request: OracleTransportRequest) -> dict[str, object]:
    path_fields = (
        "snapshot_path",
        "provider_manifest_path",
        "normalized_path",
        "quality_path",
        "readiness_path",
        "advisor_snapshot_input_path",
        "oracle_measurements_path",
        "oracle_diagnostics_path",
        "oracle_assessment_path",
        "oracle_narrative_path",
        "oracle_report_path",
        "pipeline_manifest_path",
        "pipeline_ledger_path",
    )
    filenames = (
        EXPECTED_ORACLE_OUTPUT_FILENAMES[0],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[1],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[2],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[3],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[4],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[5],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[6],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[7],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[8],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[9],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[10],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[12],
        EXPECTED_ORACLE_OUTPUT_FILENAMES[13],
    )
    return {
        "run_id": "oracle-pipeline-test-run",
        "fleet_id": ORACLE_FLEET_ID,
        "readiness_state": "READY",
        "downstream_ready": True,
        "live_oracle_headline": "Deterministic Oracle headline",
        "blocker_count": 0,
        "warning_count": 2,
        "declared_paths": {
            field_name: f"{request.output_dir}/{filename}"
            for field_name, filename in zip(path_fields, filenames, strict=True)
        },
    }


class _RecordingTransport:
    def __init__(
        self,
        *,
        native_state: str = "READY",
        error: Exception | None = None,
        malformed: bool = False,
    ) -> None:
        self.native_state = native_state
        self.error = error
        self.malformed = malformed
        self.calls: list[tuple[OracleTransportRequest, float]] = []

    def run(
        self, request: OracleTransportRequest, *, deadline_seconds: float
    ) -> dict[str, object]:
        self.calls.append((request, deadline_seconds))
        if self.error is not None:
            raise self.error
        output_dir = request.mission_root / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES:
            (output_dir / filename).write_text("{}\n", encoding="utf-8")
        (output_dir / "oracle_report_live.json").write_text(
            json.dumps({"diagnostics_state": self.native_state}) + "\n",
            encoding="utf-8",
        )
        result = _native_result(request)
        if self.malformed:
            del result["run_id"]
        return result


class ReplayOracleInputTests(unittest.TestCase):
    def test_fixture_contract_accepts_exact_deterministic_fleet(self) -> None:
        fixture = ReplayOracleInput.from_mapping(_replay_mapping())

        self.assertEqual(fixture.fixture_id, "oracle-replay-build-week-v1")
        self.assertEqual(fixture.generated_at, "2026-07-18T18:05:00Z")
        self.assertEqual(tuple(fixture.quote_payload()), ORACLE_SYMBOLS)

        encoded = json.dumps(_replay_mapping()).encode("utf-8")
        self.assertEqual(ReplayOracleInput.from_bytes(encoded), fixture)

    def test_fixture_exact_bytes_reject_duplicate_fields(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            ReplayOracleInput.from_bytes(
                b'{"schema_version":"blackpod.oracle_replay_input.v1",'
                b'"schema_version":"duplicate"}'
            )

    def test_fixture_rejects_unknown_fields_and_inexact_symbols(self) -> None:
        extra_field = _replay_mapping()
        extra_field["unexpected"] = True
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            ReplayOracleInput.from_mapping(extra_field)

        missing_symbol = _replay_mapping()
        del missing_symbol["quotes"]["SPY"]  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "exact fleet symbols"):
            ReplayOracleInput.from_mapping(missing_symbol)

    def test_fixture_rejects_malformed_quote_values(self) -> None:
        malformed = _replay_mapping()
        malformed["quotes"]["SPY"]["last_price"] = float("nan")  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "finite number"):
            ReplayOracleInput.from_mapping(malformed)

        malformed = _replay_mapping()
        malformed["quotes"]["SPY"]["extra"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            ReplayOracleInput.from_mapping(malformed)


class OracleAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.battlestar_path = root / "battlestar"
        oracle_module = self.battlestar_path / "blackpod" / "runtime" / "oracle_pipeline.py"
        oracle_module.parent.mkdir(parents=True)
        oracle_module.write_text("# interface sentinel\n", encoding="utf-8")
        self.mission_root = root / "artifacts" / "missions" / "mission-oracle-001"
        fleet = self.mission_root / "oracle" / "inputs" / "oracles_vapors.example.yaml"
        fleet.parent.mkdir(parents=True)
        fleet.write_text("fleet_id: fleet-oracles-vapors-example\n", encoding="utf-8")
        self.context = OracleMissionContext(
            mission_id="mission-oracle-001", mission_root=self.mission_root
        )
        self.fixture = ReplayOracleInput.from_mapping(_replay_mapping())

    def test_successful_replay_preserves_correlation_and_captures_outputs(self) -> None:
        transport = _RecordingTransport()
        result = OracleAdapter(
            self.battlestar_path, transport=transport, deadline_seconds=7.5
        ).execute(_request(), self.context, replay_input=self.fixture)

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.mission_id, "mission-oracle-001")
        self.assertEqual(result.request_id, "request-oracle-001")
        self.assertEqual(result.symbol, "SPY")
        self.assertIs(result.run_mode, RunMode.REPLAY)
        self.assertIs(result.transport, OracleTransportKind.REPLAY_FIXTURE)
        self.assertEqual(result.native_state, "READY")
        self.assertEqual(result.warning_count, 2)
        self.assertIsNone(result.failure)
        self.assertEqual(
            result.produced_paths,
            tuple(
                f"oracle/attempt-0001/{filename}"
                for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES
            ),
        )
        self.assertTrue(all(not Path(path).is_absolute() for path in result.produced_paths))
        self.assertEqual(transport.calls[0][1], 7.5)

    def test_native_degraded_warning_result_is_not_technical_failure(self) -> None:
        transport = _RecordingTransport(native_state="DEGRADED")
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request(), self.context, replay_input=self.fixture
        )

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        self.assertEqual(result.native_state, "DEGRADED")
        self.assertEqual(result.warning_count, 2)
        self.assertIsNone(result.failure)

    def test_technical_exception_is_structured_and_absolute_paths_are_sanitized(self) -> None:
        source_path = self.mission_root / "secret-provider-cache.json"
        transport = _RecordingTransport(
            error=RuntimeError(f"provider failed while reading {source_path}")
        )
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request(), self.context, replay_input=self.fixture
        )

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "ORACLE_EXECUTION_FAILED")
        self.assertEqual(result.failure.error_type, "RuntimeError")
        self.assertFalse(result.failure.resumable)
        self.assertNotIn(str(self.mission_root), result.failure.message)
        self.assertIn("<path>", result.failure.message)

    def test_malformed_oracle_return_is_technical_failure(self) -> None:
        result = OracleAdapter(
            self.battlestar_path, transport=_RecordingTransport(malformed=True)
        ).execute(_request(), self.context, replay_input=self.fixture)

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "ORACLE_MALFORMED_RESULT")
        self.assertEqual(len(result.produced_paths), len(EXPECTED_ORACLE_OUTPUT_FILENAMES))

    def test_timeout_is_explicit_and_live_timeout_is_resumable(self) -> None:
        transport = _RecordingTransport(error=OracleTransportTimeout("deadline expired"))
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request("LIVE"), self.context
        )

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "ORACLE_TIMEOUT")
        self.assertTrue(result.failure.resumable)

    def test_process_transport_enforces_a_hard_deadline(self) -> None:
        package = self.battlestar_path / "blackpod"
        runtime = package / "runtime"
        (package / "__init__.py").write_text("", encoding="utf-8")
        (runtime / "__init__.py").write_text("", encoding="utf-8")
        (runtime / "oracle_pipeline.py").write_text(
            "import time\n"
            "def run_oracle_pipeline(**kwargs):\n"
            "    time.sleep(10)\n",
            encoding="utf-8",
        )
        request = OracleTransportRequest(
            battlestar_path=self.battlestar_path.resolve(),
            mission_root=self.mission_root.resolve(),
            fleet_path=self.context.fleet_path,
            output_dir=self.context.output_dir,
            run_mode=RunMode.REPLAY,
            generated_at=self.fixture.generated_at,
            replay_quotes=self.fixture.quote_payload(),
        )

        with self.assertRaises(OracleTransportTimeout):
            ProcessOracleTransport().run(request, deadline_seconds=0.1)

    def test_correlation_mismatch_fails_before_transport(self) -> None:
        transport = _RecordingTransport()
        mismatched = OracleMissionContext(
            mission_id="mission-oracle-002", mission_root=self.mission_root
        )
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request(), mismatched, replay_input=self.fixture
        )

        self.assertIs(result.status, StageStatus.FAILED)
        self.assertEqual(result.failure.code, "ORACLE_CORRELATION_MISMATCH")
        self.assertEqual(transport.calls, [])

    def test_live_never_receives_replay_transport_or_generated_timestamp(self) -> None:
        transport = _RecordingTransport()
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request("LIVE"), self.context
        )

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        invocation = transport.calls[0][0]
        self.assertIs(invocation.run_mode, RunMode.LIVE)
        self.assertIsNone(invocation.replay_quotes)
        self.assertIsNone(invocation.generated_at)
        self.assertIs(result.transport, OracleTransportKind.LIVE_YFINANCE)

    def test_replay_never_uses_live_acquisition_input(self) -> None:
        transport = _RecordingTransport()
        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request(), self.context, replay_input=self.fixture
        )

        self.assertIs(result.status, StageStatus.SUCCEEDED)
        invocation = transport.calls[0][0]
        self.assertIs(invocation.run_mode, RunMode.REPLAY)
        self.assertEqual(invocation.generated_at, self.fixture.generated_at)
        self.assertEqual(tuple(invocation.replay_quotes), ORACLE_SYMBOLS)

    def test_modes_never_fall_back_when_required_input_is_wrong(self) -> None:
        for request, replay_input, code in (
            (_request("LIVE"), self.fixture, "ORACLE_MODE_MISMATCH"),
            (_request("REPLAY"), None, "ORACLE_REPLAY_INPUT_REQUIRED"),
        ):
            with self.subTest(code=code):
                transport = _RecordingTransport()
                result = OracleAdapter(
                    self.battlestar_path, transport=transport
                ).execute(request, self.context, replay_input=replay_input)
                self.assertIs(result.status, StageStatus.FAILED)
                self.assertEqual(result.failure.code, code)
                self.assertEqual(transport.calls, [])

    def test_existing_immutable_output_is_not_overwritten(self) -> None:
        output = self.context.output_absolute
        output.mkdir(parents=True)
        sentinel = output / EXPECTED_ORACLE_OUTPUT_FILENAMES[0]
        sentinel.write_text("immutable\n", encoding="utf-8")
        transport = _RecordingTransport()

        result = OracleAdapter(self.battlestar_path, transport=transport).execute(
            _request(), self.context, replay_input=self.fixture
        )

        self.assertEqual(result.failure.code, "ORACLE_IMMUTABLE_COLLISION")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutable\n")
        self.assertEqual(transport.calls, [])

    def test_context_rejects_paths_that_escape_mission_root(self) -> None:
        with self.assertRaisesRegex(Exception, "beneath"):
            OracleMissionContext(
                mission_id="mission-oracle-001",
                mission_root=self.mission_root,
                output_dir="../escaped",
            )


if __name__ == "__main__":
    unittest.main()
