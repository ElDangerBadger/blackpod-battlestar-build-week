"""Deep ModelDock readiness check including one real structured inference."""

from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .modeldock_client import (
    HttpResponse,
    HttpTransport,
    ModelDockClient,
    ModelDockClientError,
    UrlLibTransport,
    _content_length,
    _strict_json_object,
)
from .modeldock_config import ModelDockConfig


MODELDOCK_SMOKE_SCHEMA_VERSION = "blackpod.modeldock_smoke.v1"
_SMOKE_MISSION_ID = "modeldock-preflight"
_SMOKE_REQUEST_ID = "modeldock-preflight-request"
_SMOKE_SYMBOL = "SMOKE"


@dataclass(frozen=True, slots=True)
class ModelDockPreflightReport:
    base_url: str
    timeout_seconds: float
    service_reachable: bool
    health_ready: bool
    health_response: Mapping[str, Any] | None
    models_endpoint_ready: bool
    selected_model_available: bool | None
    text_generate_endpoint_available: bool
    inference_ready: bool
    provider: str | None
    model: str | None
    model_revision: str | None
    trace_id: str | None
    mocked: bool | None
    latency_ms: float | None
    observed_at: str
    issues: tuple[dict[str, Any], ...]

    @property
    def ready(self) -> bool:
        return self.inference_ready and not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "service_reachable": self.service_reachable,
            "health_ready": self.health_ready,
            "health_response": (
                copy.deepcopy(dict(self.health_response))
                if self.health_response is not None
                else None
            ),
            "models_endpoint_ready": self.models_endpoint_ready,
            "selected_model_available": self.selected_model_available,
            "text_generate_endpoint_available": self.text_generate_endpoint_available,
            "inference_ready": self.inference_ready,
            "provider": self.provider,
            "model": self.model,
            "model_revision": self.model_revision,
            "trace_id": self.trace_id,
            "mocked": self.mocked,
            "latency_ms": self.latency_ms,
            "observed_at": self.observed_at,
            "issues": copy.deepcopy(list(self.issues)),
            "ready": self.ready,
        }


def run_modeldock_preflight(
    config: ModelDockConfig,
    *,
    transport: HttpTransport | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] | None = None,
) -> ModelDockPreflightReport:
    """Check health, registry visibility, and one non-mocked MLX inference.

    A valid shallow health response never sets ``ready`` by itself.
    Failures are returned as sanitized issues rather than raised so CLI callers
    can report partial readiness without exposing response bodies.
    """

    active_transport = transport or UrlLibTransport(monotonic=monotonic)
    clock = now or (lambda: datetime.now(UTC))
    issues: list[dict[str, Any]] = []
    service_reachable = False
    health_ready = False
    health_response: dict[str, Any] | None = None
    models_ready = False
    selected_available: bool | None = None
    endpoint_available = False
    inference_ready = False
    provider: str | None = None
    model: str | None = None
    revision: str | None = None
    trace_id: str | None = None
    mocked: bool | None = None
    latency: float | None = None

    try:
        candidate_health = _get_json(
            active_transport,
            config,
            "/health",
        )
        service_reachable = True
        if set(candidate_health) != {"status", "service", "version"} or (
            candidate_health.get("status") != "ok"
            or candidate_health.get("service") != "modeldock"
            or not isinstance(candidate_health.get("version"), str)
            or not candidate_health["version"]
        ):
            raise _PreflightIssue(
                "health_contract_invalid",
                "ModelDock health response failed strict validation",
            )
        health_response = candidate_health
        health_ready = True
    except _PreflightIssue as exc:
        if exc.code not in {
            "preflight_transport_failure",
            "preflight_transport_contract",
        }:
            service_reachable = True
        issues.append(exc.to_dict())

    if health_ready:
        try:
            models_payload = _get_json(
                active_transport,
                config,
                "/models",
            )
            if set(models_payload) != {"models"} or not isinstance(
                models_payload.get("models"), list
            ):
                raise _PreflightIssue(
                    "models_contract_invalid",
                    "ModelDock models response failed strict validation",
                )
            models_ready = True
            if config.model is None:
                selected_available = None
            else:
                selected_available = any(
                    isinstance(candidate, Mapping)
                    and candidate.get("name") == config.model
                    and candidate.get("provider") == config.provider
                    and isinstance(candidate.get("capabilities"), list)
                    and "text" in candidate["capabilities"]
                    for candidate in models_payload["models"]
                )
                if not selected_available:
                    raise _PreflightIssue(
                        "selected_model_unavailable",
                        "Configured ModelDock model is not registered for MLX text generation",
                    )
        except _PreflightIssue as exc:
            issues.append(exc.to_dict())

    if health_ready and models_ready and config.model is None:
        issues.append(
            {
                "code": "live_model_required",
                "message": (
                    "Deep LIVE preflight requires MODELDOCK_MODEL to pin a "
                    "registered local MLX route before inference"
                ),
                "resumable": False,
            }
        )

    if (
        health_ready
        and models_ready
        and config.model is not None
        and selected_available is not False
    ):
        client = ModelDockClient(
            config,
            transport=active_transport,
            monotonic=monotonic,
            now=clock,
            live_model_route_verified=True,
        )
        request_payload: dict[str, Any] = {
            "profile": config.profile,
            "capabilities": ["text"],
            "response_format": {"type": "json"},
            "timeout": max(1, math.ceil(config.timeout_seconds)),
            "metadata": {
                "blackpod_correlation": {
                    "mission_id": _SMOKE_MISSION_ID,
                    "request_id": _SMOKE_REQUEST_ID,
                    "symbol": _SMOKE_SYMBOL,
                    "run_mode": "LIVE",
                }
            },
            "prompt": (
                "Return only compact JSON with exactly these fields and values: "
                '{"schema_version":"blackpod.modeldock_smoke.v1",'
                '"mission_id":"modeldock-preflight",'
                '"request_id":"modeldock-preflight-request",'
                '"symbol":"SMOKE","status":"ready"}. '
                "Do not use Markdown fences or add commentary."
            ),
            "max_tokens": 128,
        }
        if config.model is not None:
            request_payload["model"] = config.model
        try:
            result = client.generate_text(
                request_payload,
                mission_id=_SMOKE_MISSION_ID,
                request_id=_SMOKE_REQUEST_ID,
                symbol=_SMOKE_SYMBOL,
                run_mode="LIVE",
                content_validator=_validate_smoke_content,
            )
            endpoint_available = True
            inference_ready = True
            provider = result.provider
            model = result.model
            revision = result.model_revision
            trace_id = result.trace_id
            mocked = result.mocked
            latency = result.latency_ms
        except ModelDockClientError as exc:
            failure = exc.failure
            endpoint_available = failure.raw_response_sha256 is not None
            latency = failure.latency_ms
            issues.append(
                {
                    "code": failure.code,
                    "message": failure.message,
                    "resumable": failure.resumable,
                }
            )
            response = failure.safe_response
            if response is not None:
                provider = _optional_string(response.get("provider"))
                model = _optional_string(response.get("model"))
                trace_id = _optional_string(response.get("trace_id"))
                mocked_value = response.get("mocked")
                mocked = mocked_value if isinstance(mocked_value, bool) else None

    return ModelDockPreflightReport(
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        service_reachable=service_reachable,
        health_ready=health_ready,
        health_response=health_response,
        models_endpoint_ready=models_ready,
        selected_model_available=selected_available,
        text_generate_endpoint_available=endpoint_available,
        inference_ready=inference_ready,
        provider=provider,
        model=model,
        model_revision=revision,
        trace_id=trace_id,
        mocked=mocked,
        latency_ms=latency,
        observed_at=_timestamp(clock()),
        issues=tuple(copy.deepcopy(issues)),
    )


def _get_json(
    transport: HttpTransport,
    config: ModelDockConfig,
    path: str,
) -> dict[str, Any]:
    try:
        response = transport.request(
            method="GET",
            url=config.endpoint(path),
            headers={"Accept": "application/json"},
            body=None,
            timeout_seconds=config.timeout_seconds,
            max_response_bytes=config.max_response_bytes,
        )
    except (TimeoutError, OSError):
        raise _PreflightIssue(
            "preflight_transport_failure",
            "ModelDock preflight could not reach the configured local endpoint",
            resumable=True,
        ) from None
    if not isinstance(response, HttpResponse):
        raise _PreflightIssue(
            "preflight_transport_contract",
            "ModelDock preflight transport returned an unsupported response",
        )
    if response.status != 200:
        raise _PreflightIssue(
            "preflight_http_status",
            f"ModelDock preflight endpoint returned HTTP status {response.status}",
            resumable=response.status >= 500,
        )
    try:
        declared = _content_length(response.headers)
        if (
            len(response.body) > config.max_response_bytes
            or (declared is not None and declared > config.max_response_bytes)
            or not response.complete
            or (declared is not None and declared != len(response.body))
        ):
            raise _PreflightIssue(
                "preflight_response_invalid",
                "ModelDock preflight response is truncated or oversized",
            )
        return _strict_json_object(response.body, "ModelDock preflight response")
    except _PreflightIssue:
        raise
    except Exception:
        raise _PreflightIssue(
            "preflight_response_invalid",
            "ModelDock preflight response failed strict JSON validation",
        ) from None


def _validate_smoke_content(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version": MODELDOCK_SMOKE_SCHEMA_VERSION,
        "mission_id": _SMOKE_MISSION_ID,
        "request_id": _SMOKE_REQUEST_ID,
        "symbol": _SMOKE_SYMBOL,
        "status": "ready",
    }
    if dict(value) != expected:
        raise ValueError("smoke output does not match its versioned contract")
    return copy.deepcopy(expected)


@dataclass(frozen=True, slots=True)
class _PreflightIssue(Exception):
    code: str
    message: str
    resumable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "resumable": self.resumable,
        }


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
