"""Strict local HTTP client for ModelDock ``POST /text/generate``.

The client has no retry or provider-fallback behavior.  It validates the real
ModelDock MLX envelope before exposing a deliberately projected response that
cannot serialize ModelDock's absolute ``model_path``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol

from .hashing import canonical_json_bytes, sha256_bytes
from .modeldock_config import ModelDockConfig


MODELDOCK_TEXT_GENERATE_PATH = "/text/generate"
MODELDOCK_REQUEST_TYPE = "text.generate"
MODELDOCK_CORRELATION_FIELD = "blackpod_correlation"
_ENVELOPE_FIELDS = frozenset(
    {
        "status",
        "request_type",
        "profile",
        "provider",
        "model",
        "content",
        "data",
        "metadata",
        "trace_id",
        "mocked",
    }
)
_REQUEST_FIELDS = frozenset(
    {
        "profile",
        "model",
        "capabilities",
        "response_format",
        "timeout",
        "metadata",
        "prompt",
        "max_tokens",
    }
)
_REQUIRED_REQUEST_FIELDS = frozenset(
    {"profile", "capabilities", "response_format", "timeout", "metadata", "prompt"}
)
_CORRELATION_FIELDS = frozenset(
    {"mission_id", "request_id", "symbol", "run_mode"}
)
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,254}\Z")
_SAFE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SECRET_LIKE = re.compile(
    r"(?i)(?:^|[._:@/+\-])(?:api[_-]?key|access[_-]?token|token|password|passwd|secret)"
    r"(?:$|[=._:@/+\-])|\bBearer\s+|\bsk-(?:proj-)?[A-Za-z0-9_-]{8,}"
    r"|(?:^|[._:@/+\-])(?:hf_|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}"
)
MODELDOCK_MAX_PROMPT_BYTES = 512 * 1024
MODELDOCK_MLX_TEXT_ENGINES = frozenset({"mlx-lm", "mlx-vlm"})
_READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Bounded response returned by an injected or standard-library transport."""

    status: int
    headers: Mapping[str, str]
    body: bytes
    complete: bool = True


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrlLibTransport:
    """One-shot urllib transport with bounded reads and a monotonic deadline."""

    def __init__(
        self, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )
        self._monotonic = monotonic

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> HttpResponse:
        started = self._monotonic()
        deadline = started + timeout_seconds
        request = urllib.request.Request(
            url=url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            response = self._opener.open(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            # HTTPError proves the endpoint responded; do not read or reflect an
            # untrusted error body into mission artifacts.
            try:
                response_headers = dict(exc.headers.items()) if exc.headers else {}
            finally:
                exc.close()
            return HttpResponse(
                status=int(exc.code),
                headers=response_headers,
                body=b"",
            )
        with response:
            response_headers = dict(response.headers.items())
            declared = _content_length(response_headers)
            if declared is not None and declared > max_response_bytes:
                return HttpResponse(
                    status=int(response.status),
                    headers=response_headers,
                    body=b"",
                    complete=False,
                )
            chunks: list[bytes] = []
            byte_count = 0
            while byte_count <= max_response_bytes:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    raise TimeoutError("ModelDock response read exceeded deadline")
                _set_response_socket_timeout(response, remaining)
                chunk = response.read(
                    min(_READ_CHUNK_BYTES, max_response_bytes + 1 - byte_count)
                )
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise OSError("ModelDock response stream returned non-bytes data")
                chunks.append(chunk)
                byte_count += len(chunk)
            payload = b"".join(chunks)
            return HttpResponse(
                status=int(response.status),
                headers=response_headers,
                body=payload,
                complete=(
                    len(payload) <= max_response_bytes
                    and (declared is None or declared == len(payload))
                ),
            )


def _set_response_socket_timeout(response: Any, remaining_seconds: float) -> None:
    """Best-effort per-read timeout while retaining the monotonic hard check."""

    candidates = [response]
    current = response
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            break
        candidates.append(current)
    for candidate in reversed(candidates):
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(max(0.001, remaining_seconds))
            except (OSError, ValueError):
                pass
            return


@dataclass(frozen=True, slots=True)
class ModelDockFailure:
    """Sanitized technical failure suitable for canonical provenance."""

    code: str
    error_type: str
    message: str
    resumable: bool
    latency_ms: float
    started_at: str
    observed_at: str
    raw_response_sha256: str | None = None
    response_byte_size: int | None = None
    safe_response: Mapping[str, Any] | None = None
    safe_response_bytes: bytes | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "error_type": self.error_type,
            "message": self.message,
            "resumable": self.resumable,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
            "observed_at": self.observed_at,
            "raw_response_sha256": self.raw_response_sha256,
            "response_byte_size": self.response_byte_size,
            "safe_response": (
                copy.deepcopy(dict(self.safe_response))
                if self.safe_response is not None
                else None
            ),
        }


class ModelDockClientError(RuntimeError):
    """Raised with a complete sanitized ``ModelDockFailure`` record."""

    def __init__(self, failure: ModelDockFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure
        self.code = failure.code
        self.error_type = failure.error_type
        self.resumable = failure.resumable
        self.latency_ms = failure.latency_ms
        self.safe_response = failure.safe_response
        self.raw_response_sha256 = failure.raw_response_sha256
        self.response_byte_size = failure.response_byte_size


@dataclass(frozen=True, slots=True)
class ModelDockCallResult:
    """Validated narrative call plus immutable wire-level provenance."""

    request_bytes: bytes
    request_sha256: str
    raw_response_sha256: str
    response_byte_size: int
    safe_response: Mapping[str, Any]
    safe_response_bytes: bytes
    provider: str
    model: str
    model_revision: str | None
    trace_id: str
    mocked: bool
    latency_ms: float
    started_at: str
    observed_at: str
    parsed_content: Any


ContentValidator = Callable[[Mapping[str, Any]], Any]


class ModelDockClient:
    """Validate one ModelDock text generation without retries or fallback."""

    def __init__(
        self,
        config: ModelDockConfig,
        *,
        transport: HttpTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
        live_model_route_verified: bool = False,
    ) -> None:
        self.config = config
        self.transport = transport or UrlLibTransport(monotonic=monotonic)
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._live_model_route_verified = live_model_route_verified

    def generate_text(
        self,
        request_payload: Mapping[str, Any],
        *,
        mission_id: str,
        request_id: str,
        symbol: str,
        run_mode: object,
        content_validator: ContentValidator | None = None,
        content_requires_correlation: bool = True,
    ) -> ModelDockCallResult:
        """Generate and validate one correlated narrative.

        ``symbol`` is an independently supplied expected value; it is not
        trusted from request metadata. Callers that deterministically apply the
        already-validated envelope correlation may set
        ``content_requires_correlation=False``; the default preserves the
        standalone canonical-narrative contract. ``timeout_seconds`` covers
        request validation, one transport attempt, bounded response reads, and
        response validation. The method never retries or changes provider or
        run mode.
        """

        started_at = _timestamp(self._now())
        started = self._monotonic()
        response_hash: str | None = None
        response_size: int | None = None
        safe_response: dict[str, Any] | None = None

        try:
            normalized_mode = _run_mode(run_mode)
            (
                normalized_request,
                expected_correlation,
                expected_max_tokens,
            ) = self._validate_request(
                request_payload,
                mission_id=mission_id,
                request_id=request_id,
                symbol=symbol,
                run_mode=normalized_mode,
            )
            if normalized_mode == "LIVE" and not self._live_model_route_verified:
                self._validate_live_model_route(started)
            request_bytes = canonical_json_bytes(normalized_request)
            remaining = self.config.timeout_seconds - (
                self._monotonic() - started
            )
            if remaining <= 0:
                raise TimeoutError("ModelDock deadline elapsed before transport")
            response = self.transport.request(
                method="POST",
                url=self.config.endpoint(MODELDOCK_TEXT_GENERATE_PATH),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json; charset=utf-8",
                },
                body=request_bytes,
                timeout_seconds=remaining,
                max_response_bytes=self.config.max_response_bytes,
            )
            if self._monotonic() - started > self.config.timeout_seconds:
                raise TimeoutError("ModelDock transport exceeded total deadline")
            if not isinstance(response, HttpResponse):
                raise _ProtocolIssue(
                    "transport_contract",
                    "ModelDockProtocolError",
                    "ModelDock transport returned an unsupported response",
                )
            if not isinstance(response.body, bytes):
                raise _ProtocolIssue(
                    "transport_contract",
                    "ModelDockProtocolError",
                    "ModelDock transport response body must be bytes",
                )
            response_size = len(response.body)
            response_hash = sha256_bytes(response.body)
            if response.status != 200:
                raise _ProtocolIssue(
                    "http_status",
                    "ModelDockHttpError",
                    f"ModelDock returned HTTP status {response.status}",
                    resumable=response.status >= 500 or response.status in {408, 429},
                )
            declared = _content_length(response.headers)
            if response_size > self.config.max_response_bytes or (
                declared is not None and declared > self.config.max_response_bytes
            ):
                raise _ProtocolIssue(
                    "response_oversized",
                    "ModelDockProtocolError",
                    "ModelDock response exceeds the configured one MiB limit",
                )
            if not response.complete or (
                declared is not None and declared != response_size
            ):
                raise _ProtocolIssue(
                    "response_truncated",
                    "ModelDockProtocolError",
                    "ModelDock response was truncated",
                    resumable=True,
                )
            envelope = _strict_json_object(response.body, "ModelDock response")
            safe_response = _safe_response_projection(envelope, include_content=False)
            parsed_content, model_revision = self._validate_envelope(
                envelope,
                expected_correlation=expected_correlation,
                expected_max_tokens=expected_max_tokens,
                run_mode=normalized_mode,
                content_validator=content_validator,
                content_requires_correlation=content_requires_correlation,
            )
            safe_response = _safe_response_projection(envelope, include_content=True)
            safe_response_bytes = canonical_json_bytes(safe_response)
            finished = self._monotonic()
            if finished - started > self.config.timeout_seconds:
                raise TimeoutError("ModelDock validation exceeded total deadline")
            latency = _latency_ms(started, finished)
            observed_at = _timestamp(self._now())
            return ModelDockCallResult(
                request_bytes=request_bytes,
                request_sha256=hashlib.sha256(request_bytes).hexdigest(),
                raw_response_sha256=response_hash,
                response_byte_size=response_size,
                safe_response=MappingProxyType(copy.deepcopy(safe_response)),
                safe_response_bytes=safe_response_bytes,
                provider=envelope["provider"],
                model=envelope["model"],
                model_revision=model_revision,
                trace_id=envelope["trace_id"],
                mocked=envelope["mocked"],
                latency_ms=latency,
                started_at=started_at,
                observed_at=observed_at,
                parsed_content=parsed_content,
            )
        except ModelDockClientError:
            raise
        except _ProtocolIssue as exc:
            raise self._error(
                exc.code,
                exc.error_type,
                exc.message,
                exc.resumable,
                started,
                started_at,
                raw_response_sha256=response_hash,
                response_byte_size=response_size,
                safe_response=safe_response,
            ) from None

        except (TimeoutError, socket.timeout) as exc:
            raise self._error(
                "timeout",
                type(exc).__name__,
                "ModelDock request exceeded its client-side deadline",
                True,
                started,
                started_at,
            ) from None
        except (urllib.error.URLError, ConnectionError, OSError) as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise self._error(
                    "timeout",
                    type(reason).__name__,
                    "ModelDock request exceeded its client-side deadline",
                    True,
                    started,
                    started_at,
                ) from None
            raise self._error(
                "connection_failure",
                type(exc).__name__,
                "ModelDock could not be reached at the configured local endpoint",
                True,
                started,
                started_at,
            ) from None
        except (TypeError, ValueError) as exc:
            # Configuration/request failures are intentionally terse: exception
            # messages from injected validators can contain prompt material.
            raise self._error(
                "request_invalid",
                type(exc).__name__,
                "ModelDock request failed strict client validation",
                False,
                started,
                started_at,
                raw_response_sha256=response_hash,
                response_byte_size=response_size,
                safe_response=safe_response,
            ) from None

    def _validate_live_model_route(self, started: float) -> None:
        """Prove the selected model routes to local MLX before sending facts."""

        model = self.config.model
        if model is None:  # The request validator normally catches this first.
            raise _ProtocolIssue(
                "live_model_required",
                "ModelDockRequestValidationError",
                "LIVE ModelDock narrative requires an explicitly configured MLX model",
            )
        remaining = self.config.timeout_seconds - (self._monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("ModelDock deadline elapsed before route validation")
        response = self.transport.request(
            method="GET",
            url=self.config.endpoint("/models"),
            headers={"Accept": "application/json"},
            body=None,
            timeout_seconds=remaining,
            max_response_bytes=self.config.max_response_bytes,
        )
        if self._monotonic() - started > self.config.timeout_seconds:
            raise TimeoutError("ModelDock route validation exceeded total deadline")
        if not isinstance(response, HttpResponse) or not isinstance(response.body, bytes):
            raise _ProtocolIssue(
                "live_model_route_contract",
                "ModelDockProtocolError",
                "ModelDock model registry returned an unsupported response",
            )
        if response.status != 200:
            raise _ProtocolIssue(
                "live_model_route_http_status",
                "ModelDockHttpError",
                f"ModelDock model registry returned HTTP status {response.status}",
                resumable=response.status >= 500 or response.status in {408, 429},
            )
        declared = _content_length(response.headers)
        if (
            len(response.body) > self.config.max_response_bytes
            or (declared is not None and declared > self.config.max_response_bytes)
            or not response.complete
            or (declared is not None and declared != len(response.body))
        ):
            raise _ProtocolIssue(
                "live_model_route_response_invalid",
                "ModelDockProtocolError",
                "ModelDock model registry response is truncated or oversized",
            )
        registry = _strict_json_object(response.body, "ModelDock model registry")
        if set(registry) != {"models"} or not isinstance(registry.get("models"), list):
            raise _ProtocolIssue(
                "live_model_route_contract",
                "ModelDockProtocolError",
                "ModelDock model registry failed strict validation",
            )
        matches = [
            candidate
            for candidate in registry["models"]
            if isinstance(candidate, Mapping) and candidate.get("name") == model
        ]
        if len(matches) != 1:
            raise _ProtocolIssue(
                "live_model_route_unavailable",
                "ModelDockProtocolError",
                "Configured ModelDock model is not uniquely registered",
            )
        selected = matches[0]
        capabilities = selected.get("capabilities")
        if (
            selected.get("provider") != self.config.provider
            or not isinstance(capabilities, list)
            or "text" not in capabilities
        ):
            raise _ProtocolIssue(
                "live_model_route_policy",
                "ModelDockProtocolError",
                "Configured ModelDock model is not registered for local MLX text generation",
            )

    def _validate_request(
        self,
        value: Mapping[str, Any],
        *,
        mission_id: str,
        request_id: str,
        symbol: str,
        run_mode: str,
    ) -> tuple[dict[str, Any], dict[str, str], int | None]:
        if not isinstance(value, Mapping):
            raise _ProtocolIssue(
                "request_schema",
                "ModelDockRequestValidationError",
                "ModelDock request must be a JSON object",
            )
        fields = set(value)
        if fields - _REQUEST_FIELDS or _REQUIRED_REQUEST_FIELDS - fields:
            raise _ProtocolIssue(
                "request_schema",
                "ModelDockRequestValidationError",
                "ModelDock request fields do not match the text.generate contract",
            )
        profile = value.get("profile")
        if profile != self.config.profile:
            raise _ProtocolIssue(
                "request_profile_mismatch",
                "ModelDockRequestValidationError",
                "ModelDock request profile conflicts with configuration",
            )
        model = value.get("model")
        if run_mode == "LIVE" and self.config.model is None:
            raise _ProtocolIssue(
                "live_model_required",
                "ModelDockRequestValidationError",
                "LIVE ModelDock narrative requires an explicitly configured MLX model",
            )
        if model is not None:
            _safe_token(model, "request model")
        if self.config.model is not None and model != self.config.model:
            raise _ProtocolIssue(
                "request_model_mismatch",
                "ModelDockRequestValidationError",
                "ModelDock request model conflicts with configuration",
            )
        prompt = value.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise _ProtocolIssue(
                "request_prompt_invalid",
                "ModelDockRequestValidationError",
                "ModelDock prompt must be a nonblank string",
            )
        if len(prompt.encode("utf-8")) > MODELDOCK_MAX_PROMPT_BYTES:
            raise _ProtocolIssue(
                "request_prompt_oversized",
                "ModelDockRequestValidationError",
                "ModelDock prompt exceeds the client input limit",
            )
        capabilities = value.get("capabilities")
        if capabilities != ["text"]:
            raise _ProtocolIssue(
                "request_capabilities_invalid",
                "ModelDockRequestValidationError",
                "ModelDock narrative capabilities must be exactly ['text']",
            )
        if value.get("response_format") != {"type": "json"}:
            raise _ProtocolIssue(
                "request_format_invalid",
                "ModelDockRequestValidationError",
                "ModelDock response_format must request JSON",
            )
        request_timeout = value.get("timeout")
        if (
            isinstance(request_timeout, bool)
            or not isinstance(request_timeout, int)
            or request_timeout <= 0
            or request_timeout > max(1, math.ceil(self.config.timeout_seconds))
        ):
            raise _ProtocolIssue(
                "request_timeout_invalid",
                "ModelDockRequestValidationError",
                "ModelDock request timeout exceeds the configured client deadline",
            )
        max_tokens = value.get("max_tokens")
        if max_tokens is not None and (
            isinstance(max_tokens, bool)
            or not isinstance(max_tokens, int)
            or not 1 <= max_tokens <= 16384
        ):
            raise _ProtocolIssue(
                "request_max_tokens_invalid",
                "ModelDockRequestValidationError",
                "ModelDock max_tokens is outside the supported range",
            )
        metadata = value.get("metadata")
        if not isinstance(metadata, Mapping):
            raise _ProtocolIssue(
                "request_metadata_invalid",
                "ModelDockRequestValidationError",
                "ModelDock metadata must be an object",
            )
        if set(metadata) != {MODELDOCK_CORRELATION_FIELD}:
            raise _ProtocolIssue(
                "request_metadata_invalid",
                "ModelDockRequestValidationError",
                "ModelDock request metadata may contain only mission correlation",
            )
        correlation = metadata.get(MODELDOCK_CORRELATION_FIELD)
        if not isinstance(correlation, Mapping) or set(correlation) != _CORRELATION_FIELDS:
            raise _ProtocolIssue(
                "request_correlation_invalid",
                "ModelDockRequestValidationError",
                "ModelDock request correlation metadata is incomplete",
            )
        expected = {
            "mission_id": mission_id,
            "request_id": request_id,
            "symbol": symbol,
            "run_mode": run_mode,
        }
        if correlation.get("mission_id") != mission_id or correlation.get(
            "request_id"
        ) != request_id or correlation.get("symbol") != symbol or correlation.get(
            "run_mode"
        ) != run_mode:
            raise _ProtocolIssue(
                "request_correlation_mismatch",
                "ModelDockRequestValidationError",
                "ModelDock request correlation does not match the mission",
            )
        _safe_token(mission_id, "mission_id")
        _safe_token(request_id, "request_id")
        _safe_token(symbol, "symbol")
        _validate_json_value(value, "ModelDock request")
        # A JSON round trip creates a plain, immutable-at-the-boundary value and
        # rejects exotic Mapping/list subclasses.
        normalized = json.loads(json.dumps(value, allow_nan=False))
        return normalized, expected, max_tokens  # type: ignore[return-value]

    def _validate_envelope(
        self,
        value: dict[str, Any],
        *,
        expected_correlation: Mapping[str, str],
        expected_max_tokens: int | None,
        run_mode: str,
        content_validator: ContentValidator | None,
        content_requires_correlation: bool,
    ) -> tuple[Any, str | None]:
        if set(value) != _ENVELOPE_FIELDS:
            raise _ProtocolIssue(
                "response_schema_mismatch",
                "ModelDockProtocolError",
                "ModelDock response fields do not match the ApiResponse contract",
            )
        if value["status"] != "ok":
            raise _ProtocolIssue(
                "response_status_not_ok",
                "ModelDockProtocolError",
                "ModelDock response status is not ok",
            )
        if value["request_type"] != MODELDOCK_REQUEST_TYPE:
            raise _ProtocolIssue(
                "response_request_type_mismatch",
                "ModelDockProtocolError",
                "ModelDock response request_type is not text.generate",
            )
        if value["profile"] != self.config.profile:
            raise _ProtocolIssue(
                "response_profile_mismatch",
                "ModelDockProtocolError",
                "ModelDock response profile conflicts with the request",
            )
        provider = value["provider"]
        if not isinstance(provider, str) or not provider:
            raise _ProtocolIssue(
                "response_provider_missing",
                "ModelDockProtocolError",
                "ModelDock response provider is missing",
            )
        if provider != self.config.provider:
            raise _ProtocolIssue(
                "response_provider_mismatch",
                "ModelDockProtocolError",
                "ModelDock returned a provider outside the configured policy",
            )
        if run_mode == "LIVE" and provider != "mlx":
            raise _ProtocolIssue(
                "live_provider_policy",
                "ModelDockProtocolError",
                "LIVE ModelDock narrative requires the local MLX provider",
            )
        mocked = value["mocked"]
        if not isinstance(mocked, bool):
            raise _ProtocolIssue(
                "response_mocked_invalid",
                "ModelDockProtocolError",
                "ModelDock mocked state must be boolean",
            )
        if run_mode == "LIVE" and mocked:
            raise _ProtocolIssue(
                "mocked_live_response",
                "ModelDockProtocolError",
                "LIVE ModelDock narrative rejected a mocked response",
            )
        model = _safe_token(value["model"], "response model")
        if self.config.model is not None and model != self.config.model:
            raise _ProtocolIssue(
                "response_model_mismatch",
                "ModelDockProtocolError",
                "ModelDock returned a model outside the configured policy",
            )
        _safe_token(value["trace_id"], "trace_id")
        data = value["data"]
        metadata = value["metadata"]
        if not isinstance(data, Mapping) or not isinstance(metadata, Mapping):
            raise _ProtocolIssue(
                "response_schema_mismatch",
                "ModelDockProtocolError",
                "ModelDock response data and metadata must be objects",
            )
        # ModelDock supports text.generate through both native MLX engines.
        # Its current Gemma configuration deliberately routes text-only input
        # through mlx-vlm, so engine identity is evidence—not a reason to
        # reject an otherwise real, non-mocked MLX response.
        if (
            data.get("engine") not in MODELDOCK_MLX_TEXT_ENGINES
            or data.get("profile") != self.config.profile
        ):
            raise _ProtocolIssue(
                "response_mlx_data_invalid",
                "ModelDockProtocolError",
                "ModelDock response lacks the real MLX text-generation data",
            )
        model_path = data.get("model_path")
        if not isinstance(model_path, str) or not model_path.strip():
            raise _ProtocolIssue(
                "response_mlx_data_invalid",
                "ModelDockProtocolError",
                "ModelDock response lacks its MLX model reference",
            )
        if metadata.get("stop_reason") != "completed_or_eos":
            raise _ProtocolIssue(
                "response_truncated_generation",
                "ModelDockProtocolError",
                "ModelDock generation did not complete normally",
            )
        effective = metadata.get("effective_max_tokens")
        generated = metadata.get("generated_token_count")
        requested = metadata.get("requested_max_tokens")
        if (
            isinstance(effective, bool)
            or not isinstance(effective, int)
            or effective <= 0
            or isinstance(generated, bool)
            or not isinstance(generated, int)
            or generated < 0
            or generated > effective
            or (
                requested is not None
                and (
                    isinstance(requested, bool)
                    or not isinstance(requested, int)
                    or requested <= 0
                )
            )
            or not isinstance(metadata.get("generation_options"), Mapping)
        ):
            raise _ProtocolIssue(
                "response_mlx_metadata_invalid",
                "ModelDockProtocolError",
                "ModelDock response lacks the real MLX generation metadata",
            )
        if requested != expected_max_tokens or (
            expected_max_tokens is not None and effective != expected_max_tokens
        ):
            raise _ProtocolIssue(
                "response_token_budget_mismatch",
                "ModelDockProtocolError",
                "ModelDock response token budget conflicts with the request",
            )
        echoed = metadata.get(MODELDOCK_CORRELATION_FIELD)
        if not isinstance(echoed, Mapping) or dict(echoed) != dict(
            expected_correlation
        ):
            raise _ProtocolIssue(
                "response_correlation_mismatch",
                "ModelDockProtocolError",
                "ModelDock response correlation does not match the mission",
            )
        content = value["content"]
        if not isinstance(content, str) or not content.strip():
            raise _ProtocolIssue(
                "response_content_missing",
                "ModelDockProtocolError",
                "ModelDock response content is missing",
            )
        content_bytes = content.encode("utf-8")
        parsed_mapping = _strict_json_object(content_bytes, "ModelDock narrative content")
        if content_requires_correlation:
            for key in ("mission_id", "request_id", "symbol"):
                if parsed_mapping.get(key) != expected_correlation[key]:
                    raise _ProtocolIssue(
                        "narrative_correlation_mismatch",
                        "ModelDockNarrativeValidationError",
                        "ModelDock narrative correlation does not match the mission",
                    )
        validator = content_validator or _default_content_validator
        try:
            parsed_content = validator(parsed_mapping)
        except _ProtocolIssue:
            raise
        except Exception as exc:
            raise _ProtocolIssue(
                "narrative_schema_invalid",
                type(exc).__name__,
                "ModelDock narrative failed its versioned contract validation",
            ) from None
        return parsed_content, _model_revision(value)

    def _error(
        self,
        code: str,
        error_type: str,
        message: str,
        resumable: bool,
        started: float,
        started_at: str,
        *,
        raw_response_sha256: str | None = None,
        response_byte_size: int | None = None,
        safe_response: Mapping[str, Any] | None = None,
    ) -> ModelDockClientError:
        safe_bytes = (
            canonical_json_bytes(dict(safe_response))
            if safe_response is not None
            else None
        )
        return ModelDockClientError(
            ModelDockFailure(
                code=code,
                error_type=_safe_error_type(error_type),
                message=message,
                resumable=resumable,
                latency_ms=_latency_ms(started, self._monotonic()),
                started_at=started_at,
                observed_at=_timestamp(self._now()),
                raw_response_sha256=raw_response_sha256,
                response_byte_size=response_byte_size,
                safe_response=(
                    MappingProxyType(copy.deepcopy(dict(safe_response)))
                    if safe_response is not None
                    else None
                ),
                safe_response_bytes=safe_bytes,
            )
        )


@dataclass(frozen=True, slots=True)
class _ProtocolIssue(Exception):
    code: str
    error_type: str
    message: str
    resumable: bool = False


def _default_content_validator(value: Mapping[str, Any]) -> Any:
    try:
        from .contracts.oracle_narrative import OracleNarrative
    except (ImportError, ModuleNotFoundError) as exc:
        raise _ProtocolIssue(
            "narrative_validator_missing",
            type(exc).__name__,
            "Oracle narrative contract validator is unavailable",
        ) from None
    return OracleNarrative.from_mapping(value)


def _strict_json_object(source: bytes, document_name: str) -> dict[str, Any]:
    try:
        text = source.decode("utf-8")
    except UnicodeError:
        raise _ProtocolIssue(
            "response_invalid_utf8",
            "ModelDockProtocolError",
            f"{document_name} is not valid UTF-8",
        ) from None

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise _ProtocolIssue(
                    "response_duplicate_field",
                    "ModelDockProtocolError",
                    f"{document_name} contains a duplicate field",
                )
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise _ProtocolIssue(
            "response_nonstandard_json",
            "ModelDockProtocolError",
            f"{document_name} contains a non-standard JSON number",
        )

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=pairs_hook,
            parse_constant=reject_constant,
        )
    except _ProtocolIssue:
        raise
    except json.JSONDecodeError:
        raise _ProtocolIssue(
            "response_malformed_json",
            "ModelDockProtocolError",
            f"{document_name} is malformed JSON",
        ) from None
    if not isinstance(parsed, dict):
        raise _ProtocolIssue(
            "response_schema_mismatch",
            "ModelDockProtocolError",
            f"{document_name} must be a JSON object",
        )
    return parsed


def _safe_response_projection(
    value: Mapping[str, Any], *, include_content: bool
) -> dict[str, Any]:
    """Project only validated/public fields; never copy ``data.model_path``."""

    data = value.get("data")
    metadata = value.get("metadata")
    projected_data: dict[str, Any] = {}
    if isinstance(data, Mapping):
        for field_name in ("engine", "profile"):
            projected = _safe_projected_scalar(data.get(field_name))
            if projected is not None:
                projected_data[field_name] = projected
    revision = _model_revision(value)
    if revision is not None:
        projected_data["model_revision"] = revision

    projected_metadata: dict[str, Any] = {}
    if isinstance(metadata, Mapping):
        correlation = metadata.get(MODELDOCK_CORRELATION_FIELD)
        if isinstance(correlation, Mapping) and set(correlation) == _CORRELATION_FIELDS:
            projected_correlation = {
                key: _safe_projected_scalar(correlation.get(key))
                for key in sorted(_CORRELATION_FIELDS)
            }
            if all(value is not None for value in projected_correlation.values()):
                projected_metadata[MODELDOCK_CORRELATION_FIELD] = projected_correlation
        for field_name in (
            "requested_max_tokens",
            "effective_max_tokens",
            "generated_token_count",
            "stop_reason",
        ):
            if field_name in metadata:
                candidate = metadata[field_name]
                if candidate is None or (
                    isinstance(candidate, int) and not isinstance(candidate, bool)
                ):
                    projected_metadata[field_name] = candidate
                elif field_name == "stop_reason":
                    projected = _safe_projected_scalar(candidate)
                    if projected is not None:
                        projected_metadata[field_name] = projected

    content = value.get("content")
    projection: dict[str, Any] = {
        "status": _safe_projected_scalar(value.get("status")),
        "request_type": _safe_projected_scalar(value.get("request_type")),
        "profile": _safe_projected_scalar(value.get("profile")),
        "provider": _safe_projected_scalar(value.get("provider")),
        "model": _safe_projected_scalar(value.get("model")),
        "data": projected_data,
        "metadata": projected_metadata,
        "trace_id": _safe_projected_scalar(value.get("trace_id")),
        "mocked": value.get("mocked") if isinstance(value.get("mocked"), bool) else None,
    }
    if include_content:
        projection["content"] = content
    elif isinstance(content, str):
        encoded = content.encode("utf-8")
        projection["content_sha256"] = sha256_bytes(encoded)
        projection["content_byte_size"] = len(encoded)
    return projection


def _safe_projected_scalar(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 512:
        return None
    if _unsafe_sensitive_token(value):
        return None
    if any(ord(character) < 32 for character in value):
        return None
    return value


def _model_revision(value: Mapping[str, Any]) -> str | None:
    metadata = value.get("metadata")
    data = value.get("data")
    for container in (metadata, data):
        if isinstance(container, Mapping):
            candidate = container.get("model_revision")
            if candidate is not None:
                if (
                    not isinstance(candidate, str)
                    or not _SAFE_REVISION.fullmatch(candidate)
                    or _unsafe_sensitive_token(candidate)
                ):
                    raise _ProtocolIssue(
                        "response_model_revision_invalid",
                        "ModelDockProtocolError",
                        "ModelDock model revision is missing or unsafe",
                    )
                return candidate
    if isinstance(data, Mapping):
        model_path = data.get("model_path")
        if isinstance(model_path, str):
            normalized = model_path.replace("\\", "/").rstrip("/")
            parts = normalized.split("/")
            if len(parts) >= 2 and parts[-2] == "snapshots":
                candidate = parts[-1]
                if _SAFE_REVISION.fullmatch(candidate) and not _unsafe_sensitive_token(
                    candidate
                ):
                    return candidate
    model = value.get("model")
    if isinstance(model, str) and "@" in model:
        candidate = model.rsplit("@", 1)[1]
        if _SAFE_REVISION.fullmatch(candidate) and not _unsafe_sensitive_token(
            candidate
        ):
            return candidate
    return None


def _content_length(headers: Mapping[str, str]) -> int | None:
    value: str | None = None
    for name, candidate in headers.items():
        if name.lower() == "content-length":
            value = candidate
            break
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise _ProtocolIssue(
            "response_content_length_invalid",
            "ModelDockProtocolError",
            "ModelDock response Content-Length is invalid",
        )
    return int(value)


def _run_mode(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value not in {"LIVE", "REPLAY"}:
        raise _ProtocolIssue(
            "run_mode_invalid",
            "ModelDockRequestValidationError",
            "ModelDock run mode must be LIVE or REPLAY",
        )
    return str(value)


def _safe_token(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not _SAFE_TOKEN.fullmatch(value)
        or _unsafe_sensitive_token(value)
    ):
        raise _ProtocolIssue(
            "response_schema_mismatch",
            "ModelDockProtocolError",
            f"ModelDock {field_name} is missing or unsafe",
        )
    return value


def _unsafe_sensitive_token(value: str) -> bool:
    lowered = value.lower()
    return (
        value.startswith(("/", "~"))
        or "\\" in value
        or ".." in value
        or lowered.startswith("file:")
        or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value) is not None
        or re.match(r"^[^/@:\s]+:[^/@\s]+@[^/\s]+$", value) is not None
        or _SECRET_LIKE.search(value) is not None
    )


def _validate_json_value(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            raise _ProtocolIssue(
                "request_schema",
                "ModelDockRequestValidationError",
                f"{field_name} contains a non-finite number",
            )
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _ProtocolIssue(
                    "request_schema",
                    "ModelDockRequestValidationError",
                    f"{field_name} contains a non-string field name",
                )
            _validate_json_value(item, field_name)
        return
    raise _ProtocolIssue(
        "request_schema",
        "ModelDockRequestValidationError",
        f"{field_name} contains a non-JSON value",
    )


def _latency_ms(started: float, finished: float) -> float:
    return round(max(0.0, finished - started) * 1000.0, 3)


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    normalized = value.astimezone(UTC).isoformat(timespec="microseconds")
    return normalized.replace("+00:00", "Z")


def _safe_error_type(value: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        return value
    return "ModelDockError"
