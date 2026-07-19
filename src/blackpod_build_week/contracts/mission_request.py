"""Strict versioned mission request contract."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..identifiers import IdentifierError, validate_identifier, validate_mission_id


MISSION_REQUEST_SCHEMA_VERSION = "blackpod.mission_request.v1"
_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "run_mode",
        "symbol",
        "requested_at",
        "operator_id",
    }
)
_OPTIONAL_FIELDS = frozenset({"mission_id", "metadata"})
_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class ContractValidationError(ValueError):
    """Raised when a versioned contract fails strict validation."""


class RunMode(str, Enum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"


def _reject_json_constant(value: str) -> None:
    raise ContractValidationError(f"non-standard JSON constant is not allowed: {value}")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def load_strict_json_object(path: Path) -> dict[str, Any]:
    """Load one strict JSON object, rejecting duplicates and NaN values."""

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractValidationError(f"cannot read request file {path}: {exc}") from exc

    try:
        value = json.loads(
            source,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ContractValidationError(f"request is not valid JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise ContractValidationError("mission request root must be a JSON object")
    return value


def parse_rfc3339(value: object, field_name: str) -> datetime:
    """Parse the supported timezone-aware RFC 3339 representation."""

    if not isinstance(value, str) or not _RFC3339_PATTERN.fullmatch(value):
        raise ContractValidationError(
            f"{field_name} must be an RFC 3339 timestamp with a timezone"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ContractValidationError(f"{field_name} must include a timezone")
        return parsed.astimezone(UTC)
    except ContractValidationError:
        raise
    except (ValueError, OverflowError) as exc:
        raise ContractValidationError(f"{field_name} is not a valid timestamp") from exc


def format_rfc3339(value: datetime) -> str:
    """Format an aware datetime as canonical UTC RFC 3339."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractValidationError("timestamp value must include a timezone")
    try:
        utc_value = value.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ContractValidationError("timestamp is outside the supported UTC range") from exc
    timespec = "microseconds" if utc_value.microsecond else "seconds"
    return utc_value.isoformat(timespec=timespec).replace("+00:00", "Z")


def normalize_rfc3339(value: object, field_name: str) -> str:
    return format_rfc3339(parse_rfc3339(value, field_name))


def _validate_symbol(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError("symbol must be a nonblank string")
    if value != value.strip():
        raise ContractValidationError("symbol may not have surrounding whitespace")
    if len(value) > 64 or any(ord(character) < 32 for character in value):
        raise ContractValidationError("symbol contains unsupported characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("symbol must contain valid Unicode text") from exc
    return value


def _validate_json_value(
    value: object,
    field_name: str,
    active_containers: set[int] | None = None,
) -> None:
    """Require programmatic metadata to have the same shape as strict JSON."""

    if value is None or type(value) is bool or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractValidationError(f"{field_name} contains a non-finite number")
        return
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ContractValidationError(
                f"{field_name} contains text that is not valid UTF-8"
            ) from exc
        return
    if not isinstance(value, (dict, list)):
        raise ContractValidationError(f"{field_name} contains a non-JSON value")

    active = active_containers if active_containers is not None else set()
    identity = id(value)
    if identity in active:
        raise ContractValidationError(f"{field_name} contains a circular value")
    active.add(identity)
    try:
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ContractValidationError(
                        f"{field_name} object keys must be strings"
                    )
                _validate_json_value(key, f"{field_name} key", active)
                _validate_json_value(child, f"{field_name}.{key}", active)
        else:
            for index, child in enumerate(value):
                _validate_json_value(child, f"{field_name}[{index}]", active)
    finally:
        active.remove(identity)


@dataclass(frozen=True, slots=True)
class MissionRequest:
    schema_version: str
    request_id: str
    run_mode: RunMode
    symbol: str
    requested_at: str
    operator_id: str
    metadata: dict[str, Any]
    mission_id: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> "MissionRequest":
        return cls.from_mapping(load_strict_json_object(path))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MissionRequest":
        if not isinstance(value, Mapping):
            raise ContractValidationError("mission request must be an object")

        fields = set(value)
        missing = _REQUIRED_FIELDS - fields
        unknown = fields - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
        if missing:
            raise ContractValidationError(
                f"mission request is missing fields: {', '.join(sorted(missing))}"
            )
        if unknown:
            raise ContractValidationError(
                f"mission request contains unknown fields: {', '.join(sorted(unknown))}"
            )

        schema_version = value["schema_version"]
        if schema_version != MISSION_REQUEST_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported schema_version: {schema_version!r}; expected "
                f"{MISSION_REQUEST_SCHEMA_VERSION!r}"
            )

        try:
            request_id = validate_identifier(value["request_id"], "request_id")
            operator_id = validate_identifier(value["operator_id"], "operator_id")
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc

        run_mode_value = value["run_mode"]
        if not isinstance(run_mode_value, str):
            raise ContractValidationError("run_mode must be LIVE or REPLAY")
        try:
            run_mode = RunMode(run_mode_value)
        except ValueError as exc:
            raise ContractValidationError(
                f"unsupported run_mode: {run_mode_value!r}; expected LIVE or REPLAY"
            ) from exc

        metadata_value = value.get("metadata", {})
        if not isinstance(metadata_value, dict):
            raise ContractValidationError("metadata must be a JSON object")
        _validate_json_value(metadata_value, "metadata")
        try:
            json.dumps(metadata_value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("metadata must contain valid JSON values") from exc

        mission_id_value = value.get("mission_id")
        if mission_id_value is not None:
            try:
                mission_id_value = validate_mission_id(mission_id_value)
            except IdentifierError as exc:
                raise ContractValidationError(str(exc)) from exc
            if mission_id_value == request_id:
                raise ContractValidationError(
                    "mission_id must be distinct from request_id"
                )

        return cls(
            schema_version=MISSION_REQUEST_SCHEMA_VERSION,
            request_id=request_id,
            run_mode=run_mode,
            symbol=_validate_symbol(value["symbol"]),
            requested_at=normalize_rfc3339(value["requested_at"], "requested_at"),
            operator_id=operator_id,
            metadata=copy.deepcopy(metadata_value),
            mission_id=mission_id_value,
        )

    def with_mission_id(self, mission_id: str) -> "MissionRequest":
        try:
            validated = validate_mission_id(mission_id)
        except IdentifierError as exc:
            raise ContractValidationError(str(exc)) from exc
        if validated == self.request_id:
            raise ContractValidationError("mission_id must be distinct from request_id")
        return replace(self, mission_id=validated)

    def to_dict(self, *, include_mission_id: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "run_mode": self.run_mode.value,
            "symbol": self.symbol,
            "requested_at": self.requested_at,
            "operator_id": self.operator_id,
            "metadata": copy.deepcopy(self.metadata),
        }
        if include_mission_id and self.mission_id is not None:
            result["mission_id"] = self.mission_id
        return result

    def identity_payload(self) -> dict[str, Any]:
        """Return canonical request data used for deterministic allocation."""

        return self.to_dict(include_mission_id=False)
