"""Strict, process-local configuration for the ModelDock appliance.

ModelDock is deliberately configured by URL rather than a filesystem path.
Stage 2 only permits a loopback endpoint: narrative evidence must not leave the
local machine, and Build Week never starts or modifies ModelDock itself.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


MODELDOCK_BASE_URL_ENV = "MODELDOCK_BASE_URL"
MODELDOCK_TIMEOUT_SECONDS_ENV = "MODELDOCK_TIMEOUT_SECONDS"
MODELDOCK_PROFILE_ENV = "MODELDOCK_PROFILE"
MODELDOCK_MODEL_ENV = "MODELDOCK_MODEL"
MODELDOCK_PROVIDER_ENV = "MODELDOCK_PROVIDER"

DEFAULT_MODELDOCK_PROFILE = "default"
DEFAULT_MODELDOCK_PROVIDER = "mlx"
MODELDOCK_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_TIMEOUT_SECONDS = 300.0
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+-]{0,254}\Z")
_SECRET_LIKE = re.compile(
    r"(?i)(?:^|[._:@/+\-])(?:api[_-]?key|access[_-]?token|token|password|passwd|secret)"
    r"(?:$|[=._:@/+\-])|\bBearer\s+|\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}"
    r"|(?:^|[._:@/+\-])(?:hf_|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}"
)


class ModelDockConfigurationError(ValueError):
    """Raised when environment configuration violates the local-only policy."""


@dataclass(frozen=True, slots=True)
class ModelDockConfig:
    """Validated ModelDock network policy and request defaults."""

    base_url: str
    timeout_seconds: float
    profile: str = DEFAULT_MODELDOCK_PROFILE
    model: str | None = None
    provider: str = DEFAULT_MODELDOCK_PROVIDER
    max_response_bytes: int = MODELDOCK_MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        """Enforce the same safety policy for direct and environment loading."""

        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ModelDockConfigurationError(
                "ModelDock timeout_seconds must be a finite positive number"
            )
        timeout = float(self.timeout_seconds)
        if (
            not math.isfinite(timeout)
            or timeout <= 0
            or timeout > _MAX_TIMEOUT_SECONDS
        ):
            raise ModelDockConfigurationError(
                "ModelDock timeout_seconds must be greater than zero and no more "
                f"than {_MAX_TIMEOUT_SECONDS:g}"
            )
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or not 1 <= self.max_response_bytes <= MODELDOCK_MAX_RESPONSE_BYTES
        ):
            raise ModelDockConfigurationError(
                "ModelDock max_response_bytes must be a positive integer no greater "
                "than one MiB"
            )
        provider = _validate_name(self.provider, "provider")
        if provider != DEFAULT_MODELDOCK_PROVIDER:
            raise ModelDockConfigurationError(
                "ModelDock provider must be exactly 'mlx' for the local policy"
            )
        profile = _validate_name(self.profile, "profile")
        model = (
            _validate_name(self.model, "model") if self.model is not None else None
        )
        normalized_url = _validate_base_url(self.base_url)
        object.__setattr__(self, "base_url", normalized_url)
        object.__setattr__(self, "timeout_seconds", timeout)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "model", model)

    def endpoint(self, path: str) -> str:
        """Return one known absolute endpoint below the validated origin."""

        if path not in {"/health", "/models", "/text/generate"}:
            raise ModelDockConfigurationError("unsupported ModelDock endpoint")
        return f"{self.base_url}{path}"


def load_modeldock_config(
    *, environ: Mapping[str, str] | None = None
) -> ModelDockConfig:
    """Load the required endpoint and deadline plus optional MLX selection.

    Both the URL and timeout are required so a LIVE invocation can never
    inherit a surprising network target or an unbounded deadline.
    """

    environment = os.environ if environ is None else environ
    raw_url = environment.get(MODELDOCK_BASE_URL_ENV, "").strip()
    if not raw_url:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} is not configured"
        )
    raw_timeout = environment.get(MODELDOCK_TIMEOUT_SECONDS_ENV, "").strip()
    if not raw_timeout:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_TIMEOUT_SECONDS_ENV} is not configured"
        )

    base_url = _validate_base_url(raw_url)
    timeout_seconds = _validate_timeout(raw_timeout)
    profile = _validate_name(
        environment.get(MODELDOCK_PROFILE_ENV, DEFAULT_MODELDOCK_PROFILE).strip(),
        MODELDOCK_PROFILE_ENV,
    )
    raw_model = environment.get(MODELDOCK_MODEL_ENV, "").strip()
    model = _validate_name(raw_model, MODELDOCK_MODEL_ENV) if raw_model else None
    provider = _validate_name(
        environment.get(MODELDOCK_PROVIDER_ENV, DEFAULT_MODELDOCK_PROVIDER).strip(),
        MODELDOCK_PROVIDER_ENV,
    )
    if provider != DEFAULT_MODELDOCK_PROVIDER:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_PROVIDER_ENV} must be {DEFAULT_MODELDOCK_PROVIDER!r} "
            "for the local LIVE policy"
        )

    return ModelDockConfig(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        profile=profile,
        model=model,
        provider=provider,
    )


def _validate_base_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} must be a nonblank URL"
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} is not a valid URL"
        ) from exc

    if parsed.scheme not in {"http", "https"}:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} must use http or https"
        )
    if not parsed.netloc or parsed.hostname is None:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} must include a host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} must not contain credentials"
        )
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} must be an origin without path, query, or fragment"
        )
    if port is not None and not 1 <= port <= 65535:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_BASE_URL_ENV} contains an invalid port"
        )

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise ModelDockConfigurationError(
                f"{MODELDOCK_BASE_URL_ENV} must target a loopback address"
            ) from exc
        if not address.is_loopback:
            raise ModelDockConfigurationError(
                f"{MODELDOCK_BASE_URL_ENV} must target a loopback address"
            )

    # Rebuild from parsed components to discard a harmless trailing slash while
    # preserving bracketed IPv6 and the explicit port.  No DNS lookup occurs.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), "", "", ""))


def _validate_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_TIMEOUT_SECONDS_ENV} must be a finite positive number"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0 or parsed > _MAX_TIMEOUT_SECONDS:
        raise ModelDockConfigurationError(
            f"{MODELDOCK_TIMEOUT_SECONDS_ENV} must be greater than zero and no more "
            f"than {_MAX_TIMEOUT_SECONDS:g}"
        )
    return parsed


def _validate_name(value: str, variable_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not _SAFE_NAME.fullmatch(value)
        or ".." in value
        or _SECRET_LIKE.search(value)
    ):
        raise ModelDockConfigurationError(
            f"{variable_name} contains an unsupported value"
        )
    if value.startswith(("/", "~")) or "\\" in value:
        raise ModelDockConfigurationError(
            f"{variable_name} must not be an absolute filesystem path"
        )
    return value
