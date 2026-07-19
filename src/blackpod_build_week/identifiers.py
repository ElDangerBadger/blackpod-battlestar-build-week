"""Validation and deterministic allocation of mission identifiers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .hashing import canonical_json_bytes, sha256_bytes


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_MISSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class IdentifierError(ValueError):
    """Raised when an identifier violates the submission contract."""


def validate_identifier(value: object, field_name: str) -> str:
    """Validate a non-path identifier without silently normalizing it."""

    if not isinstance(value, str) or not value:
        raise IdentifierError(f"{field_name} must be a nonblank string")
    if value != value.strip():
        raise IdentifierError(f"{field_name} may not have surrounding whitespace")
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise IdentifierError(
            f"{field_name} must start with an alphanumeric character and contain "
            "only alphanumerics, '.', '_', ':', '@', or '-'"
        )
    return value


def validate_mission_id(value: object) -> str:
    """Validate a mission identifier as exactly one safe path segment."""

    if not isinstance(value, str) or not value:
        raise IdentifierError("mission_id must be a nonblank string")
    if value != value.strip():
        raise IdentifierError("mission_id may not have surrounding whitespace")
    if not _MISSION_ID_PATTERN.fullmatch(value):
        raise IdentifierError(
            "mission_id must be one path-safe segment containing only "
            "alphanumerics, '_' or '-'"
        )
    return value


def allocate_mission_id(
    canonical_request: Mapping[str, Any],
    *,
    request_id: str,
    run_mode: str,
    supplied_mission_id: str | None,
) -> str:
    """Return an explicit mission ID or deterministically derive one."""

    validate_identifier(request_id, "request_id")
    if supplied_mission_id is not None:
        mission_id = validate_mission_id(supplied_mission_id)
    else:
        digest = sha256_bytes(canonical_json_bytes(dict(canonical_request)))[:24]
        mission_id = validate_mission_id(f"mission-{run_mode.lower()}-{digest}")

    if mission_id == request_id:
        raise IdentifierError("mission_id must be distinct from request_id")
    return mission_id

