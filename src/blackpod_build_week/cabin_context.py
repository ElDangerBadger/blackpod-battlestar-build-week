"""Read-only Stage 4 presentation supplements for the Captain's Cabin.

This module deliberately sits beside, rather than inside, the canonical mission
contracts.  It validates already-produced Navigator and portfolio presentation
data, captures the exact validated bytes, and publishes one correlated wrapper.
It does not derive market indicators, portfolio values, or mission state.
"""

from __future__ import annotations

import copy
import ipaddress
import math
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .contracts.mission_request import (
    ContractValidationError,
    RunMode,
    normalize_rfc3339,
    parse_strict_json_object_bytes,
)
from .contracts.mission_snapshot import ArtifactReference
from .hashing import canonical_json_bytes, sha256_bytes
from .identifiers import IdentifierError, validate_identifier, validate_mission_id
from .mission_store import MissionStore, PersistenceError, UnsafePathError


CABIN_CONTEXT_SCHEMA_VERSION = "blackpod.cabin_context.v1"
PORTFOLIO_SNAPSHOT_SCHEMA_VERSION = "blackpod.portfolio_snapshot.v1"
NAVIGATOR_MARKET_CONTRACT_VERSION = "navigator.api.ohlc.v1"

CABIN_CONTEXT_PATH = "presentation/cabin_context.json"
NAVIGATOR_MARKET_PATH = "presentation/navigator_market.json"
PORTFOLIO_SNAPSHOT_PATH = "presentation/portfolio_snapshot.json"

ALLOWED_TIMEFRAMES = frozenset({"1h", "1d", "1wk"})
ALLOWED_MA_PERIODS = frozenset({20, 50, 100, 200, 250})
ALLOWED_MARKET_CATEGORIES = frozenset({"equity", "index", "commodity", "crypto"})
ALLOWED_POSITIONS = frozenset({"above", "near", "below"})
ALLOWED_VOLATILITY = frozenset({"glass", "gentle", "moderate", "high", "storm"})

_MARKET_FIELDS = {
    "symbol",
    "name",
    "category",
    "timeframe",
    "ma_period",
    "currency",
    "points",
    "summary",
}
_POINT_FIELDS = {"t", "o", "h", "l", "c", "v", "ma", "atr"}
_SUMMARY_FIELDS = {
    "last_price",
    "last_ma",
    "pct_vs_ma",
    "position",
    "trend_slope_pct",
    "volatility",
    "atr",
    "atr_pct",
    "ma_period",
    "bar_count",
}
_PORTFOLIO_REQUIRED_FIELDS = {
    "schema_version",
    "captured_at",
    "source_identity",
    "mode",
    "account_type",
    "currency",
    "positions",
}
_PORTFOLIO_OPTIONAL_FIELDS = {"cash", "equity", "total_exposure"}
_POSITION_REQUIRED_FIELDS = {"symbol"}
_POSITION_OPTIONAL_FIELDS = {
    "name",
    "quantity",
    "market_value",
    "allocation_percent",
    "cost_basis",
    "unrealized_pnl",
}
_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_SOURCE_IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")


class CabinContextError(RuntimeError):
    """Raised when a presentation supplement cannot be captured safely."""


class CabinContextConflictError(CabinContextError):
    """Raised rather than replacing a differing previously captured file."""


class CaptureStatus(str, Enum):
    CAPTURED = "CAPTURED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class CaptureTransport(str, Enum):
    HTTP = "HTTP"
    LOCAL_JSON = "LOCAL_JSON"


class PortfolioMode(str, Enum):
    FROZEN = "FROZEN"
    LIVE = "LIVE"


def _require_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    name: str,
) -> None:
    allowed = required | (optional or set())
    missing = required - set(value)
    unknown = set(value) - allowed
    if missing:
        raise ContractValidationError(
            f"{name} is missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ContractValidationError(
            f"{name} contains unknown fields: {', '.join(sorted(unknown))}"
        )


def _text(value: object, field_name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a nonblank string")
    if value != value.strip():
        raise ContractValidationError(f"{field_name} may not have surrounding whitespace")
    if len(value) > max_length or any(ord(character) < 32 for character in value):
        raise ContractValidationError(f"{field_name} contains unsupported text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{field_name} must be valid Unicode") from exc
    return value


def _source_identity(value: object, field_name: str) -> str:
    identity = _text(value, field_name)
    if not _SOURCE_IDENTITY_PATTERN.fullmatch(identity):
        raise ContractValidationError(
            f"{field_name} must be an opaque identity, not a filesystem path"
        )
    return identity


def _currency(value: object, field_name: str) -> str:
    currency = _text(value, field_name, max_length=3)
    if not _CURRENCY_PATTERN.fullmatch(currency):
        raise ContractValidationError(f"{field_name} must be a three-letter currency")
    return currency


def _finite_number(
    value: object,
    field_name: str,
    *,
    nonnegative: bool = False,
    positive: bool = False,
) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be a finite number")
    if not math.isfinite(value):
        raise ContractValidationError(f"{field_name} must be a finite number")
    if positive and value <= 0:
        raise ContractValidationError(f"{field_name} must be positive")
    if nonnegative and value < 0:
        raise ContractValidationError(f"{field_name} must be nonnegative")
    return value


def _optional_finite_number(
    value: object,
    field_name: str,
    *,
    nonnegative: bool = False,
) -> int | float | None:
    if value is None:
        return None
    return _finite_number(value, field_name, nonnegative=nonnegative)


def _nonnegative_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractValidationError(f"{field_name} must be a nonnegative integer")
    return value


def validate_git_revision(value: object) -> str:
    revision = _text(value, "Navigator git revision", max_length=64)
    if not _GIT_REVISION_PATTERN.fullmatch(revision):
        raise ContractValidationError(
            "Navigator git revision must be 7 to 64 lowercase hexadecimal characters"
        )
    return revision


@dataclass(frozen=True, slots=True)
class NavigatorMarket:
    """An exact, validated Navigator ``GET /api/ohlc`` response."""

    value: dict[str, Any]

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, expected_symbol: str | None = None
    ) -> "NavigatorMarket":
        if not isinstance(value, Mapping):
            raise ContractValidationError("Navigator market response must be an object")
        _require_fields(value, required=_MARKET_FIELDS, name="Navigator market response")

        symbol = _text(value["symbol"], "Navigator market symbol", max_length=64)
        if expected_symbol is not None and symbol != expected_symbol:
            raise ContractValidationError(
                "Navigator market symbol does not match the mission request"
            )
        _text(value["name"], "Navigator market name")
        category = _text(value["category"], "Navigator market category", max_length=32)
        if category not in ALLOWED_MARKET_CATEGORIES:
            raise ContractValidationError(
                f"unsupported Navigator market category: {category!r}"
            )
        timeframe = _text(value["timeframe"], "Navigator market timeframe", max_length=3)
        if timeframe not in ALLOWED_TIMEFRAMES:
            raise ContractValidationError(
                f"unsupported Navigator market timeframe: {timeframe!r}"
            )
        ma_period = value["ma_period"]
        if isinstance(ma_period, bool) or ma_period not in ALLOWED_MA_PERIODS:
            raise ContractValidationError(
                f"unsupported Navigator market ma_period: {ma_period!r}"
            )
        _currency(value["currency"], "Navigator market currency")

        points = value["points"]
        if not isinstance(points, list) or not points:
            raise ContractValidationError("Navigator market points must be a nonempty array")
        previous_time: int | None = None
        for index, point in enumerate(points):
            if not isinstance(point, Mapping):
                raise ContractValidationError(f"Navigator market points[{index}] must be an object")
            _require_fields(point, required=_POINT_FIELDS, name=f"Navigator market points[{index}]")
            timestamp = _nonnegative_integer(point["t"], f"Navigator market points[{index}].t")
            if previous_time is not None and timestamp <= previous_time:
                raise ContractValidationError(
                    "Navigator market points must be ordered by strictly increasing t"
                )
            previous_time = timestamp
            for field in ("o", "h", "l", "c"):
                _finite_number(
                    point[field],
                    f"Navigator market points[{index}].{field}",
                    positive=True,
                )
            _nonnegative_integer(point["v"], f"Navigator market points[{index}].v")
            _optional_finite_number(
                point["ma"], f"Navigator market points[{index}].ma", nonnegative=True
            )
            _optional_finite_number(
                point["atr"], f"Navigator market points[{index}].atr", nonnegative=True
            )

        summary = value["summary"]
        if not isinstance(summary, Mapping):
            raise ContractValidationError("Navigator market summary must be an object")
        _require_fields(summary, required=_SUMMARY_FIELDS, name="Navigator market summary")
        _finite_number(summary["last_price"], "Navigator market summary.last_price", positive=True)
        _optional_finite_number(
            summary["last_ma"], "Navigator market summary.last_ma", nonnegative=True
        )
        _finite_number(summary["pct_vs_ma"], "Navigator market summary.pct_vs_ma")
        position = _text(summary["position"], "Navigator market summary.position", max_length=8)
        if position not in ALLOWED_POSITIONS:
            raise ContractValidationError(f"unsupported Navigator market position: {position!r}")
        _finite_number(
            summary["trend_slope_pct"], "Navigator market summary.trend_slope_pct"
        )
        volatility = _text(
            summary["volatility"], "Navigator market summary.volatility", max_length=16
        )
        if volatility not in ALLOWED_VOLATILITY:
            raise ContractValidationError(
                f"unsupported Navigator market volatility: {volatility!r}"
            )
        _finite_number(summary["atr"], "Navigator market summary.atr", nonnegative=True)
        _finite_number(
            summary["atr_pct"], "Navigator market summary.atr_pct", nonnegative=True
        )
        if summary["ma_period"] != ma_period:
            raise ContractValidationError("Navigator market summary ma_period is inconsistent")
        if summary["bar_count"] != len(points):
            raise ContractValidationError("Navigator market summary bar_count is inconsistent")
        if summary["last_price"] != points[-1]["c"]:
            raise ContractValidationError("Navigator market summary last_price is inconsistent")
        if summary["last_ma"] != points[-1]["ma"]:
            raise ContractValidationError("Navigator market summary last_ma is inconsistent")

        return cls(value=copy.deepcopy(dict(value)))

    @classmethod
    def from_bytes(
        cls, source: bytes, *, expected_symbol: str | None = None
    ) -> "NavigatorMarket":
        return cls.from_mapping(
            parse_strict_json_object_bytes(
                source, document_name="Navigator market response"
            ),
            expected_symbol=expected_symbol,
        )

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.value)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """A strict read-only portfolio presentation input."""

    value: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PortfolioSnapshot":
        if not isinstance(value, Mapping):
            raise ContractValidationError("portfolio snapshot must be an object")
        _require_fields(
            value,
            required=_PORTFOLIO_REQUIRED_FIELDS,
            optional=_PORTFOLIO_OPTIONAL_FIELDS,
            name="portfolio snapshot",
        )
        if value["schema_version"] != PORTFOLIO_SNAPSHOT_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported portfolio schema_version: {value['schema_version']!r}"
            )
        normalize_rfc3339(value["captured_at"], "portfolio captured_at")
        _source_identity(value["source_identity"], "portfolio source_identity")
        try:
            PortfolioMode(value["mode"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported portfolio mode") from exc
        _text(value["account_type"], "portfolio account_type", max_length=64)
        _currency(value["currency"], "portfolio currency")
        for field in _PORTFOLIO_OPTIONAL_FIELDS:
            if field in value:
                _finite_number(value[field], f"portfolio {field}", nonnegative=True)

        positions = value["positions"]
        if not isinstance(positions, list):
            raise ContractValidationError("portfolio positions must be an array")
        seen_symbols: set[str] = set()
        for index, position in enumerate(positions):
            if not isinstance(position, Mapping):
                raise ContractValidationError(f"portfolio positions[{index}] must be an object")
            _require_fields(
                position,
                required=_POSITION_REQUIRED_FIELDS,
                optional=_POSITION_OPTIONAL_FIELDS,
                name=f"portfolio positions[{index}]",
            )
            symbol = _text(position["symbol"], f"portfolio positions[{index}].symbol", max_length=64)
            if symbol in seen_symbols:
                raise ContractValidationError("portfolio position symbols must be unique")
            seen_symbols.add(symbol)
            if "name" in position:
                _text(position["name"], f"portfolio positions[{index}].name")
            for field in ("quantity", "market_value", "cost_basis", "unrealized_pnl"):
                if field in position:
                    _finite_number(position[field], f"portfolio positions[{index}].{field}")
            if "allocation_percent" in position:
                allocation = _finite_number(
                    position["allocation_percent"],
                    f"portfolio positions[{index}].allocation_percent",
                    nonnegative=True,
                )
                if allocation > 100:
                    raise ContractValidationError(
                        f"portfolio positions[{index}].allocation_percent may not exceed 100"
                    )
        return cls(value=copy.deepcopy(dict(value)))

    @classmethod
    def from_bytes(cls, source: bytes) -> "PortfolioSnapshot":
        return cls.from_mapping(
            parse_strict_json_object_bytes(source, document_name="portfolio snapshot")
        )

    @property
    def source_identity(self) -> str:
        return str(self.value["source_identity"])

    @property
    def mode(self) -> PortfolioMode:
        return PortfolioMode(self.value["mode"])

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.value)


@dataclass(frozen=True, slots=True)
class CaptureProvenance:
    market_status: CaptureStatus
    market_transport: CaptureTransport | None
    market_source_identity: str | None
    navigator_git_revision: str | None
    portfolio_status: CaptureStatus
    portfolio_transport: CaptureTransport | None
    portfolio_source_identity: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CaptureProvenance":
        if not isinstance(value, Mapping):
            raise ContractValidationError("capture_provenance must be an object")
        _require_fields(value, required={"market", "portfolio"}, name="capture_provenance")
        market = value["market"]
        portfolio = value["portfolio"]
        if not isinstance(market, Mapping) or not isinstance(portfolio, Mapping):
            raise ContractValidationError("capture provenance entries must be objects")
        _require_fields(
            market,
            required={"status", "transport", "source_identity", "navigator_git_revision"},
            name="market capture provenance",
        )
        _require_fields(
            portfolio,
            required={"status", "transport", "source_identity"},
            name="portfolio capture provenance",
        )
        try:
            market_status = CaptureStatus(market["status"])
            portfolio_status = CaptureStatus(portfolio["status"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported capture status") from exc

        market_transport = None
        market_source_identity = None
        revision = None
        if market_status is CaptureStatus.CAPTURED:
            try:
                market_transport = CaptureTransport(market["transport"])
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("unsupported market capture transport") from exc
            market_source_identity = _source_identity(
                market["source_identity"], "market source_identity"
            )
            revision = validate_git_revision(market["navigator_git_revision"])
        elif any(
            market[field] is not None
            for field in ("transport", "source_identity", "navigator_git_revision")
        ):
            raise ContractValidationError(
                "NOT_CONFIGURED market provenance values must be null"
            )

        portfolio_transport = None
        portfolio_source_identity = None
        if portfolio_status is CaptureStatus.CAPTURED:
            try:
                portfolio_transport = CaptureTransport(portfolio["transport"])
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("unsupported portfolio capture transport") from exc
            if portfolio_transport is not CaptureTransport.LOCAL_JSON:
                raise ContractValidationError("portfolio transport must be LOCAL_JSON")
            portfolio_source_identity = _source_identity(
                portfolio["source_identity"], "portfolio source_identity"
            )
        elif any(portfolio[field] is not None for field in ("transport", "source_identity")):
            raise ContractValidationError(
                "NOT_CONFIGURED portfolio provenance values must be null"
            )
        return cls(
            market_status=market_status,
            market_transport=market_transport,
            market_source_identity=market_source_identity,
            navigator_git_revision=revision,
            portfolio_status=portfolio_status,
            portfolio_transport=portfolio_transport,
            portfolio_source_identity=portfolio_source_identity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": {
                "status": self.market_status.value,
                "transport": None if self.market_transport is None else self.market_transport.value,
                "source_identity": self.market_source_identity,
                "navigator_git_revision": self.navigator_git_revision,
            },
            "portfolio": {
                "status": self.portfolio_status.value,
                "transport": None if self.portfolio_transport is None else self.portfolio_transport.value,
                "source_identity": self.portfolio_source_identity,
            },
        }


def _validate_capture_artifact(
    value: object,
    *,
    expected_name: str,
    expected_path: str,
    expected_producer: str,
    expected_schema: str,
    captured_at: str,
) -> ArtifactReference | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{expected_name} reference must be an object or null")
    reference = ArtifactReference.from_mapping(value)
    if (
        reference.name != expected_name
        or reference.path != expected_path
        or reference.producer != expected_producer
        or reference.schema_version != expected_schema
        or reference.byte_size is None
        or reference.observed_at != captured_at
    ):
        raise ContractValidationError(f"{expected_name} reference is inconsistent")
    return reference


@dataclass(frozen=True, slots=True)
class CabinContext:
    schema_version: str
    mission_id: str
    request_id: str
    symbol: str
    run_mode: RunMode
    captured_at: str
    market_artifact: ArtifactReference | None
    portfolio_artifact: ArtifactReference | None
    capture_provenance: CaptureProvenance

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CabinContext":
        if not isinstance(value, Mapping):
            raise ContractValidationError("cabin context must be an object")
        _require_fields(
            value,
            required={
                "schema_version",
                "mission_id",
                "request_id",
                "symbol",
                "run_mode",
                "captured_at",
                "market_artifact",
                "portfolio_artifact",
                "capture_provenance",
            },
            name="cabin context",
        )
        if value["schema_version"] != CABIN_CONTEXT_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported cabin context schema_version: {value['schema_version']!r}"
            )
        try:
            mission_id = validate_mission_id(value["mission_id"])
            request_id = validate_identifier(value["request_id"], "request_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        symbol = _text(value["symbol"], "cabin context symbol", max_length=64)
        try:
            run_mode = RunMode(value["run_mode"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("unsupported cabin context run_mode") from exc
        captured_at = normalize_rfc3339(value["captured_at"], "cabin context captured_at")
        market_artifact = _validate_capture_artifact(
            value["market_artifact"],
            expected_name="navigator_market",
            expected_path=NAVIGATOR_MARKET_PATH,
            expected_producer="navigator",
            expected_schema=NAVIGATOR_MARKET_CONTRACT_VERSION,
            captured_at=captured_at,
        )
        portfolio_artifact = _validate_capture_artifact(
            value["portfolio_artifact"],
            expected_name="portfolio_snapshot",
            expected_path=PORTFOLIO_SNAPSHOT_PATH,
            expected_producer="portfolio",
            expected_schema=PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
            captured_at=captured_at,
        )
        provenance = CaptureProvenance.from_mapping(value["capture_provenance"])
        if (market_artifact is None) != (
            provenance.market_status is CaptureStatus.NOT_CONFIGURED
        ):
            raise ContractValidationError("market artifact and capture status disagree")
        if (portfolio_artifact is None) != (
            provenance.portfolio_status is CaptureStatus.NOT_CONFIGURED
        ):
            raise ContractValidationError("portfolio artifact and capture status disagree")
        return cls(
            schema_version=CABIN_CONTEXT_SCHEMA_VERSION,
            mission_id=mission_id,
            request_id=request_id,
            symbol=symbol,
            run_mode=run_mode,
            captured_at=captured_at,
            market_artifact=market_artifact,
            portfolio_artifact=portfolio_artifact,
            capture_provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "request_id": self.request_id,
            "symbol": self.symbol,
            "run_mode": self.run_mode.value,
            "captured_at": self.captured_at,
            "market_artifact": (
                None if self.market_artifact is None else self.market_artifact.to_dict()
            ),
            "portfolio_artifact": (
                None
                if self.portfolio_artifact is None
                else self.portfolio_artifact.to_dict()
            ),
            "capture_provenance": self.capture_provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CabinContextCapture:
    context: CabinContext
    context_path: Path
    market_path: Path | None
    portfolio_path: Path | None
    written: bool


def inspect_git_revision(repository: Path) -> str:
    """Read a sibling revision without retaining its filesystem location."""

    path = Path(repository).expanduser()
    if not path.is_dir():
        raise CabinContextError("Navigator repository is not a directory")
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CabinContextError("could not inspect Navigator git revision") from exc
    try:
        return validate_git_revision(result.stdout.strip())
    except ContractValidationError as exc:
        raise CabinContextError(str(exc)) from exc


def _validate_navigator_url(url: str, expected_symbol: str) -> str:
    raw = _text(url, "Navigator market URL", max_length=2048)
    try:
        parsed = urlsplit(raw)
        parsed.port
    except ValueError as exc:
        raise CabinContextError("Navigator market URL is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/api/ohlc"
        or parsed.fragment
    ):
        raise CabinContextError(
            "Navigator market URL must be a credential-free local /api/ohlc URL"
        )
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise CabinContextError("Navigator market URL must target loopback") from exc
        if not address.is_loopback:
            raise CabinContextError("Navigator market URL must target loopback")
    query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    if set(query) != {"symbol", "timeframe", "ma"} or any(
        len(values) != 1 for values in query.values()
    ):
        raise CabinContextError(
            "Navigator market URL requires exactly symbol, timeframe, and ma query values"
        )
    if query["symbol"][0] != expected_symbol:
        raise CabinContextError("Navigator market URL symbol conflicts with the mission")
    if query["timeframe"][0] not in ALLOWED_TIMEFRAMES:
        raise CabinContextError("Navigator market URL timeframe is unsupported")
    try:
        ma_period = int(query["ma"][0])
    except ValueError as exc:
        raise CabinContextError("Navigator market URL ma is invalid") from exc
    if str(ma_period) != query["ma"][0] or ma_period not in ALLOWED_MA_PERIODS:
        raise CabinContextError("Navigator market URL ma is unsupported")
    return raw


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def fetch_navigator_market(
    url: str,
    *,
    expected_symbol: str,
    timeout_seconds: float = 10.0,
    max_response_bytes: int = 16 * 1024 * 1024,
    opener: Any | None = None,
) -> bytes:
    """Fetch one exact local Navigator response; no retries or fallback."""

    endpoint = _validate_navigator_url(url, expected_symbol)
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or timeout_seconds > 300
    ):
        raise CabinContextError("Navigator timeout must be between 0 and 300 seconds")
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes < 1
        or max_response_bytes > 32 * 1024 * 1024
    ):
        raise CabinContextError("Navigator response limit is invalid")
    client = opener or urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json", "User-Agent": "blackpod-cabin-context/1"},
        method="GET",
    )
    try:
        with client.open(request, timeout=float(timeout_seconds)) as response:
            status = getattr(response, "status", response.getcode())
            if status != 200:
                raise CabinContextError(f"Navigator market endpoint returned HTTP {status}")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise CabinContextError("Navigator market endpoint did not return JSON")
            source = response.read(max_response_bytes + 1)
    except CabinContextError:
        raise
    except urllib.error.HTTPError as exc:
        raise CabinContextError(
            f"Navigator market endpoint returned HTTP {exc.code}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CabinContextError("Navigator market endpoint is unavailable") from exc
    if len(source) > max_response_bytes:
        raise CabinContextError("Navigator market response exceeds the configured limit")
    NavigatorMarket.from_bytes(source, expected_symbol=expected_symbol)
    return source


def _artifact_reference(
    *,
    name: str,
    path: str,
    producer: str,
    schema_version: str,
    payload: bytes,
    captured_at: str,
) -> ArtifactReference:
    return ArtifactReference.from_mapping(
        {
            "name": name,
            "path": path,
            "sha256": sha256_bytes(payload),
            "producer": producer,
            "byte_size": len(payload),
            "schema_version": schema_version,
            "observed_at": captured_at,
        }
    )


def _presentation_target(mission_root: Path, relative_path: str) -> Path:
    root = mission_root.resolve(strict=True)
    target = (root / relative_path).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError("presentation capture path escapes the mission root") from exc
    return target


def _check_existing(target: Path, payload: bytes) -> bool:
    if not target.exists() and not target.is_symlink():
        return False
    if target.is_symlink() or not target.is_file():
        raise UnsafePathError(f"presentation capture target is unsafe: {target.name}")
    try:
        existing = target.read_bytes()
    except OSError as exc:
        raise PersistenceError(f"could not inspect presentation capture: {target.name}") from exc
    if existing != payload:
        raise CabinContextConflictError(
            f"presentation capture already exists with different content: {target.name}"
        )
    return True


def _publish_once(target: Path, payload: bytes) -> bool:
    """Atomically publish bytes without ever replacing an existing target."""

    if _check_existing(target, payload):
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise UnsafePathError("presentation capture directory may not be a symlink")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o644)
            try:
                os.link(temporary, target)
            except FileExistsError:
                if _check_existing(target, payload):
                    return False
                raise
            try:
                directory = os.open(target.parent, os.O_RDONLY)
            except OSError:
                directory = None
            if directory is not None:
                try:
                    os.fsync(directory)
                except OSError:
                    pass
                finally:
                    os.close(directory)
            return True
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except (CabinContextError, UnsafePathError):
        raise
    except OSError as exc:
        raise PersistenceError(f"could not publish presentation capture: {target.name}") from exc


def capture_cabin_context(
    store: MissionStore,
    *,
    mission_id: str,
    captured_at: str,
    market_bytes: bytes | None = None,
    market_transport: CaptureTransport | str | None = None,
    market_source_identity: str | None = None,
    navigator_git_revision: str | None = None,
    portfolio_bytes: bytes | None = None,
) -> CabinContextCapture:
    """Capture optional read-only supplements for one existing mission.

    Inputs are explicit.  Omitting either source records ``NOT_CONFIGURED``;
    neither source is substituted or inferred from arbitrary artifact folders.
    """

    loaded = store.load_mission(mission_id)
    observed_at = normalize_rfc3339(captured_at, "cabin context captured_at")

    market_reference: ArtifactReference | None = None
    market_status = CaptureStatus.NOT_CONFIGURED
    parsed_market_transport: CaptureTransport | None = None
    parsed_market_identity: str | None = None
    parsed_revision: str | None = None
    if market_bytes is not None:
        if not isinstance(market_bytes, bytes):
            raise ContractValidationError("market source must be bytes")
        NavigatorMarket.from_bytes(market_bytes, expected_symbol=loaded.request.symbol)
        try:
            parsed_market_transport = CaptureTransport(market_transport)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("market transport is required and unsupported") from exc
        parsed_market_identity = _source_identity(
            market_source_identity, "market source_identity"
        )
        parsed_revision = validate_git_revision(navigator_git_revision)
        market_status = CaptureStatus.CAPTURED
        market_reference = _artifact_reference(
            name="navigator_market",
            path=NAVIGATOR_MARKET_PATH,
            producer="navigator",
            schema_version=NAVIGATOR_MARKET_CONTRACT_VERSION,
            payload=market_bytes,
            captured_at=observed_at,
        )
    elif any(
        value is not None
        for value in (market_transport, market_source_identity, navigator_git_revision)
    ):
        raise ContractValidationError(
            "market provenance may not be supplied without market bytes"
        )

    portfolio_reference: ArtifactReference | None = None
    portfolio_status = CaptureStatus.NOT_CONFIGURED
    portfolio_identity: str | None = None
    if portfolio_bytes is not None:
        if not isinstance(portfolio_bytes, bytes):
            raise ContractValidationError("portfolio source must be bytes")
        portfolio = PortfolioSnapshot.from_bytes(portfolio_bytes)
        expected_portfolio_mode = (
            PortfolioMode.LIVE
            if loaded.request.run_mode is RunMode.LIVE
            else PortfolioMode.FROZEN
        )
        if portfolio.mode is not expected_portfolio_mode:
            raise ContractValidationError(
                "portfolio mode must be LIVE for LIVE missions and FROZEN for REPLAY missions"
            )
        portfolio_identity = portfolio.source_identity
        portfolio_status = CaptureStatus.CAPTURED
        portfolio_reference = _artifact_reference(
            name="portfolio_snapshot",
            path=PORTFOLIO_SNAPSHOT_PATH,
            producer="portfolio",
            schema_version=PORTFOLIO_SNAPSHOT_SCHEMA_VERSION,
            payload=portfolio_bytes,
            captured_at=observed_at,
        )

    provenance = CaptureProvenance(
        market_status=market_status,
        market_transport=parsed_market_transport,
        market_source_identity=parsed_market_identity,
        navigator_git_revision=parsed_revision,
        portfolio_status=portfolio_status,
        portfolio_transport=(
            CaptureTransport.LOCAL_JSON
            if portfolio_status is CaptureStatus.CAPTURED
            else None
        ),
        portfolio_source_identity=portfolio_identity,
    )
    context = CabinContext.from_mapping(
        {
            "schema_version": CABIN_CONTEXT_SCHEMA_VERSION,
            "mission_id": loaded.request.mission_id,
            "request_id": loaded.request.request_id,
            "symbol": loaded.request.symbol,
            "run_mode": loaded.request.run_mode.value,
            "captured_at": observed_at,
            "market_artifact": (
                None if market_reference is None else market_reference.to_dict()
            ),
            "portfolio_artifact": (
                None if portfolio_reference is None else portfolio_reference.to_dict()
            ),
            "capture_provenance": provenance.to_dict(),
        }
    )
    context_bytes = canonical_json_bytes(context.to_dict())
    targets: list[tuple[Path, bytes]] = []
    market_path: Path | None = None
    portfolio_path: Path | None = None
    if market_bytes is not None:
        market_path = _presentation_target(loaded.paths.mission_root, NAVIGATOR_MARKET_PATH)
        targets.append((market_path, market_bytes))
    if portfolio_bytes is not None:
        portfolio_path = _presentation_target(
            loaded.paths.mission_root, PORTFOLIO_SNAPSHOT_PATH
        )
        targets.append((portfolio_path, portfolio_bytes))
    context_path = _presentation_target(loaded.paths.mission_root, CABIN_CONTEXT_PATH)
    targets.append((context_path, context_bytes))

    # Detect every conflict before publishing any missing file.  This makes the
    # common interrupted/repeat path safe while context is always published last.
    existing = [_check_existing(target, payload) for target, payload in targets]
    written = False
    for (target, payload), already_present in zip(targets, existing, strict=True):
        if not already_present:
            written = _publish_once(target, payload) or written

    return CabinContextCapture(
        context=context,
        context_path=context_path,
        market_path=market_path,
        portfolio_path=portfolio_path,
        written=written,
    )
