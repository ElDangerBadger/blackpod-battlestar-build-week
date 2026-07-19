"""Narrow Build Week adapter for Battlestar's existing Oracle pipeline.

The adapter deliberately owns transport, validation, correlation, and artifact
discovery only.  Oracle calculations remain in Battlestar's
``run_oracle_pipeline`` entry point.
"""

from __future__ import annotations

import importlib
import json
import math
import multiprocessing
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from .battlestar_config import ORACLE_ENTRY_POINT, ORACLE_MODULE_RELATIVE_PATH
from .contracts.mission_request import (
    ContractValidationError,
    MissionRequest,
    RunMode,
    load_strict_json_object,
    normalize_rfc3339,
    parse_strict_json_object_bytes,
)
from .contracts.mission_snapshot import OracleTransportKind, StageStatus
from .identifiers import IdentifierError, validate_identifier, validate_mission_id

ORACLE_REPLAY_SCHEMA_VERSION = "blackpod.oracle_replay_input.v1"
ORACLE_FLEET_ID = "fleet-oracles-vapors-example"
ORACLE_SYMBOLS = (
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLI",
    "XLP",
    "XLY",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
    "SPY",
    "QQQ",
    "DIA",
    "VXZ",
    "IWF",
    "IWD",
    "IWM",
    "MTUM",
    "USMV",
    "QUAL",
)
ORACLE_QUOTE_FIELDS = (
    "last_price",
    "previous_close",
    "open",
    "day_high",
    "day_low",
    "last_volume",
)
EXPECTED_ORACLE_OUTPUT_FILENAMES = (
    "fleet-oracles-vapors-example_snapshot.json",
    "fleet-oracles-vapors-example_provider_run_manifest.json",
    "fleet-oracles-vapors-example_normalized.json",
    "fleet-oracles-vapors-example_quality.json",
    "fleet-oracles-vapors-example_readiness.json",
    "oracle_advisor_snapshot_input.json",
    "oracle_measurements_live.json",
    "oracle_measurement_diagnostics_live.json",
    "oracle_assessment_live.json",
    "oracle_narrative_live.json",
    "oracle_report_live.json",
    "provider_run_ledger.jsonl",
    "oracle_pipeline_run_manifest.json",
    "oracle_pipeline_run_ledger.jsonl",
)
_DECLARED_PATH_FIELDS = {
    "snapshot_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[0],
    "provider_manifest_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[1],
    "normalized_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[2],
    "quality_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[3],
    "readiness_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[4],
    "advisor_snapshot_input_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[5],
    "oracle_measurements_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[6],
    "oracle_diagnostics_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[7],
    "oracle_assessment_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[8],
    "oracle_narrative_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[9],
    "oracle_report_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[10],
    "pipeline_manifest_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[12],
    "pipeline_ledger_path": EXPECTED_ORACLE_OUTPUT_FILENAMES[13],
}
_TRANSPORT_RESULT_FIELDS = frozenset(
    {
        "run_id",
        "fleet_id",
        "readiness_state",
        "downstream_ready",
        "live_oracle_headline",
        "blocker_count",
        "warning_count",
        "declared_paths",
    }
)
_ABSOLUTE_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>|]+)")
_ABSOLUTE_WINDOWS_PATH = re.compile(r"(?i)(?<![A-Za-z0-9_.-])[A-Z]:\\[^\s\"'<>|]+")


class OracleAdapterValidationError(ValueError):
    """Raised before execution when an adapter-owned value is unsafe."""


class OracleMalformedResultError(RuntimeError):
    """Raised when Battlestar's returned value or output set is malformed."""


class OracleTransportTimeout(TimeoutError):
    """Raised when the isolated Oracle worker exceeds its deadline."""


class OracleRemoteExecutionError(RuntimeError):
    """An exception raised by Battlestar inside the isolated worker."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass(frozen=True, slots=True)
class OracleQuote:
    last_price: int | float
    previous_close: int | float
    open: int | float
    day_high: int | float
    day_low: int | float
    last_volume: int | float

    @classmethod
    def from_mapping(cls, value: object, symbol: str) -> "OracleQuote":
        if not isinstance(value, Mapping):
            raise ContractValidationError(f"quotes.{symbol} must be an object")
        _require_exact_fields(value, set(ORACLE_QUOTE_FIELDS), f"quotes.{symbol}")
        numbers: dict[str, int | float] = {}
        for field_name in ORACLE_QUOTE_FIELDS:
            candidate = value[field_name]
            if (
                isinstance(candidate, bool)
                or not isinstance(candidate, (int, float))
                or not math.isfinite(float(candidate))
            ):
                raise ContractValidationError(
                    f"quotes.{symbol}.{field_name} must be a finite number"
                )
            if field_name == "last_volume":
                if candidate < 0:
                    raise ContractValidationError(
                        f"quotes.{symbol}.last_volume must be nonnegative"
                    )
            elif candidate <= 0:
                raise ContractValidationError(
                    f"quotes.{symbol}.{field_name} must be greater than zero"
                )
            numbers[field_name] = candidate

        market_values = (
            numbers["last_price"],
            numbers["previous_close"],
            numbers["open"],
        )
        if numbers["day_high"] < max(market_values):
            raise ContractValidationError(
                f"quotes.{symbol}.day_high may not be below price, close, or open"
            )
        if numbers["day_low"] > min(market_values):
            raise ContractValidationError(
                f"quotes.{symbol}.day_low may not exceed price, close, or open"
            )
        return cls(**numbers)

    def to_dict(self) -> dict[str, int | float]:
        return {field_name: getattr(self, field_name) for field_name in ORACLE_QUOTE_FIELDS}


@dataclass(frozen=True, slots=True)
class ReplayOracleInput:
    schema_version: str
    fixture_id: str
    generated_at: str
    fleet_id: str
    quotes: tuple[tuple[str, OracleQuote], ...]

    @classmethod
    def from_file(cls, path: Path) -> "ReplayOracleInput":
        return cls.from_mapping(load_strict_json_object(path))

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ReplayOracleInput":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                payload,
                document_name="Oracle replay input",
            )
        )

    @classmethod
    def from_mapping(cls, value: object) -> "ReplayOracleInput":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Oracle replay input must be an object")
        _require_exact_fields(
            value,
            {"schema_version", "fixture_id", "generated_at", "fleet_id", "quotes"},
            "Oracle replay input",
        )
        if value["schema_version"] != ORACLE_REPLAY_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported Oracle replay schema_version: {value['schema_version']!r}; "
                f"expected {ORACLE_REPLAY_SCHEMA_VERSION!r}"
            )
        try:
            fixture_id = validate_identifier(value["fixture_id"], "fixture_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if value["fleet_id"] != ORACLE_FLEET_ID:
            raise ContractValidationError(
                f"Oracle replay fleet_id must be {ORACLE_FLEET_ID!r}"
            )
        quotes_value = value["quotes"]
        if not isinstance(quotes_value, Mapping):
            raise ContractValidationError("Oracle replay quotes must be an object")
        if set(quotes_value) != set(ORACLE_SYMBOLS):
            missing = set(ORACLE_SYMBOLS) - set(quotes_value)
            unknown = set(quotes_value) - set(ORACLE_SYMBOLS)
            details: list[str] = []
            if missing:
                details.append("missing " + ", ".join(sorted(missing)))
            if unknown:
                details.append("unknown " + ", ".join(sorted(unknown)))
            raise ContractValidationError(
                "Oracle replay quotes must contain the exact fleet symbols ("
                + "; ".join(details)
                + ")"
            )
        return cls(
            schema_version=ORACLE_REPLAY_SCHEMA_VERSION,
            fixture_id=fixture_id,
            generated_at=normalize_rfc3339(value["generated_at"], "generated_at"),
            fleet_id=ORACLE_FLEET_ID,
            quotes=tuple(
                (symbol, OracleQuote.from_mapping(quotes_value[symbol], symbol))
                for symbol in ORACLE_SYMBOLS
            ),
        )

    def quote_payload(self) -> dict[str, dict[str, int | float]]:
        return {symbol: quote.to_dict() for symbol, quote in self.quotes}


@dataclass(frozen=True, slots=True)
class OracleMissionContext:
    mission_id: str
    mission_root: Path
    fleet_path: str = "oracle/inputs/oracles_vapors.example.yaml"
    output_dir: str = "oracle/attempt-0001"

    def __post_init__(self) -> None:
        try:
            mission_id = validate_mission_id(self.mission_id)
        except IdentifierError as exc:
            raise OracleAdapterValidationError(str(exc)) from exc
        root_input = Path(self.mission_root)
        if not root_input.is_absolute():
            raise OracleAdapterValidationError("mission_root must be an absolute path")
        if root_input.is_symlink() or not root_input.exists() or not root_input.is_dir():
            raise OracleAdapterValidationError(
                "mission_root must exist as a non-symlink directory"
            )
        root = root_input.resolve(strict=True)
        fleet_path = _validate_relative_path(self.fleet_path, "fleet_path")
        output_dir = _validate_relative_path(self.output_dir, "output_dir")
        fleet_absolute = (root / fleet_path).resolve(strict=False)
        output_absolute = (root / output_dir).resolve(strict=False)
        if not _is_relative_to(fleet_absolute, root) or not _is_relative_to(
            output_absolute, root
        ):
            raise OracleAdapterValidationError(
                "Oracle paths must remain beneath the mission root"
            )
        if fleet_absolute == output_absolute or _is_relative_to(fleet_absolute, output_absolute):
            raise OracleAdapterValidationError("fleet_path may not be inside output_dir")
        object.__setattr__(self, "mission_id", mission_id)
        object.__setattr__(self, "mission_root", root)
        object.__setattr__(self, "fleet_path", fleet_path)
        object.__setattr__(self, "output_dir", output_dir)

    @property
    def fleet_absolute(self) -> Path:
        return self.mission_root / self.fleet_path

    @property
    def output_absolute(self) -> Path:
        return self.mission_root / self.output_dir


@dataclass(frozen=True, slots=True)
class OracleTransportRequest:
    battlestar_path: Path
    mission_root: Path
    fleet_path: str
    output_dir: str
    run_mode: RunMode
    generated_at: str | None
    replay_quotes: dict[str, dict[str, int | float]] | None


class OracleTransport(Protocol):
    def run(
        self, request: OracleTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]: ...


OracleTransportCallable = Callable[[OracleTransportRequest, float], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class OracleFailure:
    code: str
    error_type: str
    message: str
    resumable: bool


@dataclass(frozen=True, slots=True)
class OracleExecutionResult:
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    transport: OracleTransportKind
    status: StageStatus
    native_state: str | None
    produced_paths: tuple[str, ...]
    failure: OracleFailure | None
    run_id: str | None = None
    fleet_id: str | None = None
    readiness_state: str | None = None
    downstream_ready: bool | None = None
    headline: str | None = None
    blocker_count: int | None = None
    warning_count: int | None = None

    def __post_init__(self) -> None:
        if self.status is StageStatus.SUCCEEDED:
            if self.failure is not None or self.native_state is None:
                raise ValueError("successful Oracle result requires native state and no failure")
        elif self.status is StageStatus.FAILED:
            if self.failure is None:
                raise ValueError("failed Oracle result requires a structured failure")
        else:
            raise ValueError("Oracle execution result status must be SUCCEEDED or FAILED")


class ProcessOracleTransport:
    """Execute Oracle in a terminable spawned process with a hard deadline."""

    def run(
        self, request: OracleTransportRequest, *, deadline_seconds: float
    ) -> Mapping[str, object]:
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_oracle_worker, args=(sender, request))
        process.start()
        sender.close()
        try:
            if not receiver.poll(deadline_seconds):
                process.terminate()
                process.join(timeout=2.0)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2.0)
                raise OracleTransportTimeout(
                    f"Oracle exceeded its {deadline_seconds:g}-second deadline"
                )
            try:
                payload = receiver.recv()
            except EOFError as exc:
                raise RuntimeError(
                    f"Oracle worker exited without a result (exit code {process.exitcode})"
                ) from exc
        finally:
            receiver.close()

        process.join(timeout=2.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        if not isinstance(payload, Mapping) or set(payload) not in (
            {"ok", "result"},
            {"ok", "error_type", "message"},
        ):
            raise OracleMalformedResultError("Oracle worker returned a malformed envelope")
        if payload["ok"] is True:
            result = payload["result"]
            if not isinstance(result, Mapping):
                raise OracleMalformedResultError("Oracle worker result must be an object")
            return result
        if payload["ok"] is False:
            raise OracleRemoteExecutionError(
                str(payload["error_type"]), str(payload["message"])
            )
        raise OracleMalformedResultError("Oracle worker envelope has an invalid ok value")


class OracleAdapter:
    """Invoke Battlestar Oracle without duplicating any analytical logic."""

    def __init__(
        self,
        battlestar_path: Path,
        *,
        transport: OracleTransport | OracleTransportCallable | None = None,
        deadline_seconds: float = 60.0,
    ) -> None:
        path_input = Path(battlestar_path)
        if not path_input.is_absolute():
            raise OracleAdapterValidationError("Battlestar path must be absolute")
        if not path_input.exists() or not path_input.is_dir():
            raise OracleAdapterValidationError("Battlestar path must be an existing directory")
        path = path_input.resolve(strict=True)
        module_path = path / ORACLE_MODULE_RELATIVE_PATH
        if module_path.is_symlink() or not module_path.is_file():
            raise OracleAdapterValidationError("Battlestar Oracle module is missing")
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(float(deadline_seconds))
            or deadline_seconds <= 0
        ):
            raise OracleAdapterValidationError("deadline_seconds must be finite and positive")
        self.battlestar_path = path
        self.transport = transport or ProcessOracleTransport()
        self.deadline_seconds = float(deadline_seconds)

    def execute(
        self,
        request: MissionRequest,
        context: OracleMissionContext,
        *,
        replay_input: ReplayOracleInput | None = None,
    ) -> OracleExecutionResult:
        if not isinstance(request, MissionRequest):
            raise OracleAdapterValidationError("request must be a validated MissionRequest")
        if not isinstance(context, OracleMissionContext):
            raise OracleAdapterValidationError("context must be an OracleMissionContext")
        transport_kind = (
            OracleTransportKind.REPLAY_FIXTURE
            if request.run_mode is RunMode.REPLAY
            else OracleTransportKind.LIVE_YFINANCE
        )
        if request.mission_id is None or request.mission_id != context.mission_id:
            return self._failure(
                request,
                context,
                transport_kind,
                code="ORACLE_CORRELATION_MISMATCH",
                error_type="CorrelationError",
                message="request mission_id does not match the Oracle mission context",
                resumable=False,
            )
        if request.run_mode is RunMode.LIVE and replay_input is not None:
            return self._failure(
                request,
                context,
                transport_kind,
                code="ORACLE_MODE_MISMATCH",
                error_type="RunModeError",
                message="LIVE Oracle execution may not receive a replay fixture",
                resumable=False,
            )
        if request.run_mode is RunMode.REPLAY and replay_input is None:
            return self._failure(
                request,
                context,
                transport_kind,
                code="ORACLE_REPLAY_INPUT_REQUIRED",
                error_type="RunModeError",
                message="REPLAY Oracle execution requires a validated replay fixture",
                resumable=False,
            )

        preparation_error = self._validate_execution_paths(context)
        if preparation_error is not None:
            return self._failure(
                request,
                context,
                transport_kind,
                code=preparation_error[0],
                error_type=preparation_error[1],
                message=preparation_error[2],
                resumable=False,
            )

        transport_request = OracleTransportRequest(
            battlestar_path=self.battlestar_path,
            mission_root=context.mission_root,
            fleet_path=context.fleet_path,
            output_dir=context.output_dir,
            run_mode=request.run_mode,
            generated_at=(replay_input.generated_at if replay_input is not None else None),
            replay_quotes=(
                replay_input.quote_payload() if replay_input is not None else None
            ),
        )
        try:
            raw_result = self._run_transport(transport_request)
            parsed = self._validate_transport_result(raw_result, context)
            produced_paths = self._validate_complete_output_set(context)
            native_state = self._read_native_state(context)
        except OracleTransportTimeout as exc:
            return self._failure_from_exception(
                request,
                context,
                transport_kind,
                "ORACLE_TIMEOUT",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )
        except OracleRemoteExecutionError as exc:
            return self._failure(
                request,
                context,
                transport_kind,
                code="ORACLE_EXECUTION_FAILED",
                error_type=_safe_error_type(exc.error_type),
                message=_sanitize_message(str(exc), self.battlestar_path, context.mission_root),
                resumable=request.run_mode is RunMode.LIVE,
                produced_paths=self._discover_outputs(context),
            )
        except OracleMalformedResultError as exc:
            return self._failure_from_exception(
                request,
                context,
                transport_kind,
                "ORACLE_MALFORMED_RESULT",
                exc,
                resumable=False,
            )
        except Exception as exc:
            return self._failure_from_exception(
                request,
                context,
                transport_kind,
                "ORACLE_EXECUTION_FAILED",
                exc,
                resumable=request.run_mode is RunMode.LIVE,
            )

        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport_kind,
            status=StageStatus.SUCCEEDED,
            native_state=native_state,
            produced_paths=produced_paths,
            failure=None,
            run_id=parsed["run_id"],
            fleet_id=parsed["fleet_id"],
            readiness_state=parsed["readiness_state"],
            downstream_ready=parsed["downstream_ready"],
            headline=parsed["live_oracle_headline"],
            blocker_count=parsed["blocker_count"],
            warning_count=parsed["warning_count"],
        )

    def _run_transport(self, request: OracleTransportRequest) -> Mapping[str, object]:
        runner = getattr(self.transport, "run", None)
        if callable(runner):
            return runner(request, deadline_seconds=self.deadline_seconds)
        if callable(self.transport):
            return self.transport(request, self.deadline_seconds)
        raise OracleAdapterValidationError("Oracle transport is not callable")

    def _validate_execution_paths(
        self, context: OracleMissionContext
    ) -> tuple[str, str, str] | None:
        fleet_path = context.fleet_absolute
        if (
            fleet_path.is_symlink()
            or not fleet_path.exists()
            or not fleet_path.is_file()
            or not _is_relative_to(fleet_path.resolve(strict=True), context.mission_root)
        ):
            return (
                "ORACLE_INPUT_INVALID",
                "PathValidationError",
                "Oracle fleet input must be a contained regular file",
            )
        output_path = context.output_absolute
        if output_path.exists():
            if output_path.is_symlink() or not output_path.is_dir():
                return (
                    "ORACLE_OUTPUT_INVALID",
                    "PathValidationError",
                    "Oracle output path must be a contained directory",
                )
            try:
                if any(output_path.iterdir()):
                    return (
                        "ORACLE_IMMUTABLE_COLLISION",
                        "ArtifactCollisionError",
                        "Oracle output directory already contains immutable artifacts",
                    )
            except OSError:
                return (
                    "ORACLE_OUTPUT_INVALID",
                    "PathValidationError",
                    "Oracle output directory cannot be inspected",
                )
        if not _is_relative_to(output_path.resolve(strict=False), context.mission_root):
            return (
                "ORACLE_OUTPUT_INVALID",
                "PathValidationError",
                "Oracle output path must remain beneath the mission root",
            )
        return None

    def _validate_transport_result(
        self, raw: object, context: OracleMissionContext
    ) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise OracleMalformedResultError("Oracle return must be an object")
        _require_result_fields(raw, _TRANSPORT_RESULT_FIELDS, "Oracle return")
        parsed: dict[str, Any] = {}
        for field_name in (
            "run_id",
            "fleet_id",
            "readiness_state",
            "live_oracle_headline",
        ):
            value = raw[field_name]
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise OracleMalformedResultError(
                    f"Oracle return {field_name} must be a nonblank string"
                )
            parsed[field_name] = value
        if parsed["fleet_id"] != ORACLE_FLEET_ID:
            raise OracleMalformedResultError("Oracle returned the wrong fleet_id")
        if type(raw["downstream_ready"]) is not bool:
            raise OracleMalformedResultError(
                "Oracle return downstream_ready must be a boolean"
            )
        parsed["downstream_ready"] = raw["downstream_ready"]
        for field_name in ("blocker_count", "warning_count"):
            value = raw[field_name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise OracleMalformedResultError(
                    f"Oracle return {field_name} must be a nonnegative integer"
                )
            parsed[field_name] = value

        declared = raw["declared_paths"]
        if not isinstance(declared, Mapping) or set(declared) != set(_DECLARED_PATH_FIELDS):
            raise OracleMalformedResultError(
                "Oracle return declared_paths does not match the supported contract"
            )
        for field_name, filename in _DECLARED_PATH_FIELDS.items():
            value = declared[field_name]
            relative = _validate_native_relative_path(value)
            expected = f"{context.output_dir}/{filename}"
            if relative != expected:
                raise OracleMalformedResultError(
                    f"Oracle return {field_name} does not identify its expected artifact"
                )
        return parsed

    def _validate_complete_output_set(
        self, context: OracleMissionContext
    ) -> tuple[str, ...]:
        discovered = self._discover_outputs(context, reject_unsafe=True)
        expected = tuple(
            f"{context.output_dir}/{filename}"
            for filename in EXPECTED_ORACLE_OUTPUT_FILENAMES
        )
        if set(discovered) != set(expected):
            missing = set(expected) - set(discovered)
            unknown = set(discovered) - set(expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(Path(item).name for item in sorted(missing)))
            if unknown:
                details.append("unexpected " + ", ".join(Path(item).name for item in sorted(unknown)))
            raise OracleMalformedResultError(
                "Oracle output set is incomplete or unsupported (" + "; ".join(details) + ")"
            )
        return expected

    def _read_native_state(self, context: OracleMissionContext) -> str:
        report_path = context.output_absolute / "oracle_report_live.json"
        try:
            report = load_strict_json_object(report_path)
        except ContractValidationError as exc:
            raise OracleMalformedResultError("Oracle report is not valid strict JSON") from exc
        native_state = report.get("diagnostics_state")
        if (
            not isinstance(native_state, str)
            or not native_state.strip()
            or native_state != native_state.strip()
            or len(native_state) > 128
        ):
            raise OracleMalformedResultError(
                "Oracle report diagnostics_state must be a nonblank string"
            )
        return native_state

    def _discover_outputs(
        self, context: OracleMissionContext, *, reject_unsafe: bool = False
    ) -> tuple[str, ...]:
        output = context.output_absolute
        if not output.exists() or not output.is_dir() or output.is_symlink():
            return ()
        found: list[str] = []
        try:
            candidates = sorted(output.rglob("*"), key=lambda item: item.as_posix())
            for candidate in candidates:
                if candidate.is_symlink():
                    if reject_unsafe:
                        raise OracleMalformedResultError(
                            "Oracle output contains a symbolic link"
                        )
                    continue
                if candidate.is_dir():
                    continue
                if not candidate.is_file():
                    if reject_unsafe:
                        raise OracleMalformedResultError(
                            "Oracle output contains a non-regular artifact"
                        )
                    continue
                resolved = candidate.resolve(strict=True)
                if not _is_relative_to(resolved, context.mission_root):
                    if reject_unsafe:
                        raise OracleMalformedResultError(
                            "Oracle artifact escaped the mission root"
                        )
                    continue
                found.append(candidate.relative_to(context.mission_root).as_posix())
        except OSError as exc:
            if reject_unsafe:
                raise OracleMalformedResultError(
                    "Oracle output artifacts cannot be inspected"
                ) from exc
        expected_order = {
            f"{context.output_dir}/{name}": index
            for index, name in enumerate(EXPECTED_ORACLE_OUTPUT_FILENAMES)
        }
        return tuple(
            sorted(found, key=lambda item: (expected_order.get(item, len(expected_order)), item))
        )

    def _failure_from_exception(
        self,
        request: MissionRequest,
        context: OracleMissionContext,
        transport: OracleTransportKind,
        code: str,
        exception: Exception,
        *,
        resumable: bool,
    ) -> OracleExecutionResult:
        return self._failure(
            request,
            context,
            transport,
            code=code,
            error_type=_safe_error_type(type(exception).__name__),
            message=_sanitize_message(
                str(exception), self.battlestar_path, context.mission_root
            ),
            resumable=resumable,
            produced_paths=self._discover_outputs(context),
        )

    def _failure(
        self,
        request: MissionRequest,
        context: OracleMissionContext,
        transport: OracleTransportKind,
        *,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        produced_paths: tuple[str, ...] = (),
    ) -> OracleExecutionResult:
        return OracleExecutionResult(
            mission_id=context.mission_id,
            request_id=request.request_id,
            symbol=request.symbol,
            run_mode=request.run_mode,
            transport=transport,
            status=StageStatus.FAILED,
            native_state=None,
            produced_paths=produced_paths,
            failure=OracleFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=_sanitize_message(
                    message, self.battlestar_path, context.mission_root
                ),
                resumable=resumable,
            ),
        )


class _ReplayTicker:
    def __init__(self, fast_info: Mapping[str, int | float]) -> None:
        self.fast_info = dict(fast_info)


class _ReplayYFinance:
    def __init__(self, quotes: Mapping[str, Mapping[str, int | float]]) -> None:
        self._quotes = {symbol: dict(value) for symbol, value in quotes.items()}

    def Ticker(self, symbol: str) -> _ReplayTicker:  # noqa: N802 - native API spelling
        if symbol not in self._quotes:
            raise KeyError(f"replay fixture has no quote for {symbol}")
        return _ReplayTicker(self._quotes[symbol])


def _oracle_worker(sender: Any, request: OracleTransportRequest) -> None:
    try:
        sys.dont_write_bytecode = True
        os.chdir(request.mission_root)
        sys.path.insert(0, str(request.battlestar_path))
        module = importlib.import_module("blackpod.runtime.oracle_pipeline")
        module_file = getattr(module, "__file__", None)
        expected_module = (
            request.battlestar_path / ORACLE_MODULE_RELATIVE_PATH
        ).resolve(strict=True)
        if module_file is None or Path(module_file).resolve(strict=True) != expected_module:
            raise RuntimeError("imported Oracle module does not match BATTLESTAR_PATH")
        entry_point = getattr(module, "run_oracle_pipeline", None)
        if not callable(entry_point):
            raise RuntimeError("Battlestar Oracle entry point is not callable")

        if request.run_mode is RunMode.REPLAY:
            if request.replay_quotes is None or request.generated_at is None:
                raise RuntimeError("REPLAY worker requires deterministic quote input")
            yf_module: Any | None = _ReplayYFinance(request.replay_quotes)
            generated_at = request.generated_at
        elif request.run_mode is RunMode.LIVE:
            if request.replay_quotes is not None or request.generated_at is not None:
                raise RuntimeError("LIVE worker may not receive replay input")
            yf_module = None
            generated_at = None
        else:  # pragma: no cover - RunMode prevents this in the parent
            raise RuntimeError("unsupported Oracle run mode")

        result = entry_point(
            fleet_path=request.fleet_path,
            out_dir=request.output_dir,
            yf_module=yf_module,
            generated_at=generated_at,
        )
        payload = {
            "run_id": result.run_id,
            "fleet_id": result.fleet_id,
            "readiness_state": result.readiness_state,
            "downstream_ready": result.downstream_ready,
            "live_oracle_headline": result.live_oracle_headline,
            "blocker_count": result.blocker_count,
            "warning_count": result.warning_count,
            "declared_paths": {
                field_name: str(getattr(result, field_name))
                for field_name in _DECLARED_PATH_FIELDS
            },
        }
        sender.send({"ok": True, "result": payload})
    except Exception as exc:
        sender.send(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
    finally:
        sender.close()


def _require_exact_fields(
    value: Mapping[str, object], expected: set[str], field_name: str
) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise ContractValidationError(
            f"{field_name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{field_name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _require_result_fields(
    value: Mapping[str, object], expected: frozenset[str], field_name: str
) -> None:
    if set(value) != set(expected):
        raise OracleMalformedResultError(
            f"{field_name} does not match the supported Battlestar contract"
        )


def _validate_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OracleAdapterValidationError(f"{field_name} must be a relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or any(part in {"", "."} for part in path.parts)
    ):
        raise OracleAdapterValidationError(
            f"{field_name} must remain beneath the mission root"
        )
    return value


def _validate_native_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise OracleMalformedResultError("Oracle returned an unsafe artifact path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise OracleMalformedResultError("Oracle returned an unsafe artifact path")
    return value


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_error_type(value: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._:@-]", "_", str(value).strip())[:128]
    if not candidate or not candidate[0].isalnum():
        return "OracleError"
    return candidate


def _sanitize_message(message: str, *known_roots: Path) -> str:
    sanitized = " ".join(str(message).split())
    for root in known_roots:
        sanitized = sanitized.replace(str(root), "<path>")
    sanitized = _ABSOLUTE_WINDOWS_PATH.sub("<path>", sanitized)
    sanitized = _ABSOLUTE_POSIX_PATH.sub("<path>", sanitized)
    sanitized = sanitized.strip() or "Oracle execution failed without a message"
    return sanitized[:512]
