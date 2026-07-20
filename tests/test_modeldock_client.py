from __future__ import annotations

import copy
import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import (
    HttpResponse,
    ModelDockClient,
    ModelDockClientError,
    UrlLibTransport,
)
from blackpod_build_week.modeldock_config import ModelDockConfig


MISSION_ID = "mission-modeldock-test"
REQUEST_ID = "request-modeldock-test"
SYMBOL = "SPY"
MODEL = "mlx-community/test-model"


@dataclass
class FakeTransport:
    response: HttpResponse | Exception
    model_provider: str = "mlx"
    calls: int = 0
    last_request: dict[str, Any] | None = None

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls += 1
        self.last_request = kwargs
        if kwargs.get("url", "").endswith("/models"):
            payload = canonical_json_bytes(
                {
                    "models": [
                        {
                            "name": MODEL,
                            "provider": self.model_provider,
                            "capabilities": ["text"],
                        }
                    ]
                }
            )
            return HttpResponse(
                200,
                {"Content-Length": str(len(payload))},
                payload,
            )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class StepClock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        current = self.value
        self.value += 0.125
        return current


def correlation(run_mode: str = "LIVE") -> dict[str, str]:
    return {
        "mission_id": MISSION_ID,
        "request_id": REQUEST_ID,
        "symbol": SYMBOL,
        "run_mode": run_mode,
    }


def request_payload(run_mode: str = "LIVE") -> dict[str, Any]:
    return {
        "profile": "default",
        "model": MODEL,
        "capabilities": ["text"],
        "response_format": {"type": "json"},
        "timeout": 10,
        "metadata": {"blackpod_correlation": correlation(run_mode)},
        "prompt": "Return only the validated Oracle narrative JSON.",
        "max_tokens": 256,
    }


def narrative() -> dict[str, Any]:
    return {
        "schema_version": "blackpod.oracle_narrative.v1",
        "mission_id": MISSION_ID,
        "request_id": REQUEST_ID,
        "symbol": SYMBOL,
        "summary": "Validated test narrative.",
    }


def response_envelope(
    *,
    run_mode: str = "LIVE",
    mocked: bool = False,
    engine: str = "mlx-lm",
) -> dict[str, Any]:
    return {
        "status": "ok",
        "request_type": "text.generate",
        "profile": "default",
        "provider": "mlx",
        "model": MODEL,
        "content": json.dumps(narrative(), separators=(",", ":")),
        "data": {
            "engine": engine,
            "model_path": "/Users/private/.cache/models/snapshots/revision-abc123",
            "profile": "default",
        },
        "metadata": {
            "blackpod_correlation": correlation(run_mode),
            "requested_max_tokens": 256,
            "effective_max_tokens": 256,
            "generated_token_count": 72,
            "stop_reason": "completed_or_eos",
            "generation_options": {"temperature": 0.0},
        },
        "trace_id": "trace-modeldock-test",
        "mocked": mocked,
    }


def http_response(value: dict[str, Any]) -> HttpResponse:
    body = canonical_json_bytes(value)
    return HttpResponse(200, {"Content-Length": str(len(body))}, body)


class ModelDockClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
            model=MODEL,
        )

    def client(self, transport: FakeTransport) -> ModelDockClient:
        return ModelDockClient(
            self.config,
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

    def invoke(
        self,
        transport: FakeTransport,
        *,
        run_mode: str = "LIVE",
        payload: dict[str, Any] | None = None,
    ):
        return self.client(transport).generate_text(
            payload or request_payload(run_mode),
            mission_id=MISSION_ID,
            request_id=REQUEST_ID,
            symbol=SYMBOL,
            run_mode=run_mode,
            content_validator=lambda value: copy.deepcopy(dict(value)),
        )

    def assert_code(self, code: str, transport: FakeTransport, **kwargs: Any) -> None:
        with self.assertRaises(ModelDockClientError) as caught:
            self.invoke(transport, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("/Users/private", str(caught.exception))

    def test_valid_real_mlx_response_and_provenance(self) -> None:
        envelope = response_envelope()
        transport = FakeTransport(http_response(envelope))
        result = self.invoke(transport)

        self.assertEqual(result.provider, "mlx")
        self.assertEqual(result.model, MODEL)
        self.assertEqual(result.model_revision, "revision-abc123")
        self.assertEqual(result.trace_id, "trace-modeldock-test")
        self.assertFalse(result.mocked)
        self.assertEqual(result.latency_ms, 625.0)
        self.assertEqual(result.request_sha256, sha256_bytes(result.request_bytes))
        self.assertEqual(
            result.raw_response_sha256,
            sha256_bytes(transport.response.body),  # type: ignore[union-attr]
        )
        self.assertEqual(result.response_byte_size, len(transport.response.body))  # type: ignore[union-attr]
        self.assertEqual(result.parsed_content["summary"], "Validated test narrative.")
        self.assertNotIn("model_path", str(result.safe_response))
        self.assertNotIn("/Users/private", result.safe_response_bytes.decode())
        self.assertEqual(result.started_at, "2026-07-19T12:00:00.000000Z")
        self.assertEqual(transport.calls, 2)
        self.assertEqual(transport.last_request["url"], "http://127.0.0.1:8000/text/generate")
        self.assertEqual(transport.last_request["timeout_seconds"], 9.625)
        self.assertNotIn("Authorization", transport.last_request["headers"])

    def test_current_mlx_vlm_text_engine_is_a_real_supported_response(self) -> None:
        transport = FakeTransport(http_response(response_envelope(engine="mlx-vlm")))

        result = self.invoke(transport)

        self.assertEqual(result.safe_response["data"]["engine"], "mlx-vlm")
        self.assertFalse(result.mocked)

        unsupported = response_envelope(engine="other-engine")
        self.assert_code(
            "response_mlx_data_invalid",
            FakeTransport(http_response(unsupported)),
        )

    def test_validated_envelope_correlation_can_be_applied_deterministically(self) -> None:
        envelope = response_envelope()
        envelope["content"] = json.dumps(
            {
                "schema_version": "blackpod.oracle_narrative_selection.v1",
                "selected_fact_ids": ["oracle.measurements.breadth_score"],
            }
        )
        transport = FakeTransport(http_response(envelope))

        result = self.client(transport).generate_text(
            request_payload("LIVE"),
            mission_id=MISSION_ID,
            request_id=REQUEST_ID,
            symbol=SYMBOL,
            run_mode="LIVE",
            content_validator=lambda value: copy.deepcopy(dict(value)),
            content_requires_correlation=False,
        )

        self.assertEqual(
            result.parsed_content["selected_fact_ids"],
            ["oracle.measurements.breadth_score"],
        )
        self.assertEqual(
            result.safe_response["metadata"]["blackpod_correlation"],
            request_payload("LIVE")["metadata"]["blackpod_correlation"],
        )

        with self.assertRaises(ModelDockClientError) as caught:
            self.invoke(FakeTransport(http_response(envelope)))
        self.assertEqual(caught.exception.code, "narrative_correlation_mismatch")

    def test_non_200_timeout_and_connection_failure_are_sanitized(self) -> None:
        self.assert_code("http_status", FakeTransport(HttpResponse(503, {}, b"secret")))
        self.assert_code("timeout", FakeTransport(TimeoutError("private deadline detail")))
        self.assert_code(
            "connection_failure",
            FakeTransport(ConnectionError("http://user:secret@somewhere")),
        )

    def test_envelope_status_request_type_provider_and_mock_policy(self) -> None:
        cases = (
            ("response_status_not_ok", "status", "error"),
            ("response_request_type_mismatch", "request_type", "prompt.execute"),
            ("response_provider_missing", "provider", ""),
            ("response_provider_mismatch", "provider", "ollama"),
            ("mocked_live_response", "mocked", True),
        )
        for expected, field, replacement in cases:
            envelope = response_envelope()
            envelope[field] = replacement
            with self.subTest(field=field):
                self.assert_code(expected, FakeTransport(http_response(envelope)))

    def test_malformed_outer_and_content_json_are_rejected(self) -> None:
        malformed = HttpResponse(200, {}, b'{"status":')
        self.assert_code("response_malformed_json", FakeTransport(malformed))

        envelope = response_envelope()
        envelope["content"] = "not-json"
        self.assert_code("response_malformed_json", FakeTransport(http_response(envelope)))

        duplicate = canonical_json_bytes(response_envelope()).replace(
            b'{\n  "content":', b'{\n  "status":"ok",\n  "content":', 1
        )
        self.assert_code(
            "response_duplicate_field",
            FakeTransport(HttpResponse(200, {}, duplicate)),
        )

    def test_schema_and_correlation_mismatch_are_rejected(self) -> None:
        envelope = response_envelope()
        envelope["unknown"] = True
        self.assert_code("response_schema_mismatch", FakeTransport(http_response(envelope)))

        envelope = response_envelope()
        envelope["metadata"]["blackpod_correlation"]["mission_id"] = "other"
        self.assert_code(
            "response_correlation_mismatch", FakeTransport(http_response(envelope))
        )

        envelope = response_envelope()
        parsed = narrative()
        parsed["request_id"] = "other"
        envelope["content"] = json.dumps(parsed)
        self.assert_code(
            "narrative_correlation_mismatch", FakeTransport(http_response(envelope))
        )

        with self.assertRaises(ModelDockClientError) as caught:
            self.client(FakeTransport(http_response(response_envelope()))).generate_text(
                request_payload(),
                mission_id=MISSION_ID,
                request_id=REQUEST_ID,
                symbol="MSFT",
                run_mode="LIVE",
                content_validator=lambda value: value,
            )
        self.assertEqual(caught.exception.code, "request_correlation_mismatch")

    def test_validator_failure_is_sanitized(self) -> None:
        transport = FakeTransport(http_response(response_envelope()))
        with self.assertRaises(ModelDockClientError) as caught:
            self.client(transport).generate_text(
                request_payload(),
                mission_id=MISSION_ID,
                request_id=REQUEST_ID,
                symbol=SYMBOL,
                run_mode="LIVE",
                content_validator=lambda _: (_ for _ in ()).throw(
                    ValueError("/Users/private secret narrative")
                ),
            )
        self.assertEqual(caught.exception.code, "narrative_schema_invalid")
        self.assertNotIn("private", str(caught.exception))
        self.assertIsNotNone(caught.exception.safe_response)
        self.assertNotIn("/Users/private", str(caught.exception.safe_response))

    def test_truncated_and_oversized_responses_are_rejected(self) -> None:
        body = canonical_json_bytes(response_envelope())
        self.assert_code(
            "response_truncated",
            FakeTransport(
                HttpResponse(200, {"Content-Length": str(len(body) + 2)}, body)
            ),
        )
        oversized = b"x" * (1024 * 1024 + 1)
        self.assert_code(
            "response_oversized", FakeTransport(HttpResponse(200, {}, oversized))
        )

    def test_generation_metadata_must_prove_completion(self) -> None:
        envelope = response_envelope()
        envelope["metadata"]["stop_reason"] = "max_tokens"
        self.assert_code(
            "response_truncated_generation", FakeTransport(http_response(envelope))
        )
        envelope = response_envelope()
        del envelope["data"]["model_path"]
        self.assert_code(
            "response_mlx_data_invalid", FakeTransport(http_response(envelope))
        )

    def test_response_token_budget_must_equal_request(self) -> None:
        for field, value in (
            ("requested_max_tokens", 128),
            ("effective_max_tokens", 512),
        ):
            envelope = response_envelope()
            envelope["metadata"][field] = value
            with self.subTest(field=field):
                self.assert_code(
                    "response_token_budget_mismatch",
                    FakeTransport(http_response(envelope)),
                )

        envelope = response_envelope()
        envelope["metadata"]["generated_token_count"] = 257
        self.assert_code(
            "response_mlx_metadata_invalid", FakeTransport(http_response(envelope))
        )

    def test_identity_and_revision_fields_reject_paths_uris_and_secrets(self) -> None:
        cases = (
            ("model", "file://private/model"),
            ("trace_id", "sk-proj-abcdefghijk"),
            ("trace_id", "user:pass@host"),
            ("profile", "/private/profile"),
            ("provider", "api-key=private"),
        )
        for field, value in cases:
            envelope = response_envelope()
            envelope[field] = value
            with self.subTest(field=field):
                transport = FakeTransport(http_response(envelope))
                with self.assertRaises(ModelDockClientError) as caught:
                    self.invoke(transport)
                self.assertNotIn(value, str(caught.exception.safe_response))

        envelope = response_envelope()
        envelope["metadata"]["model_revision"] = "/private/revision"
        with self.assertRaises(ModelDockClientError) as caught:
            self.invoke(FakeTransport(http_response(envelope)))
        self.assertEqual(caught.exception.code, "response_model_revision_invalid")
        self.assertNotIn("/private/revision", str(caught.exception.safe_response))

    def test_client_total_deadline_includes_transport(self) -> None:
        values = iter((0.0, 0.1, 1.1, 1.2))
        client = ModelDockClient(
            ModelDockConfig(
                base_url="http://127.0.0.1:8000",
                timeout_seconds=1.0,
                model=MODEL,
            ),
            transport=FakeTransport(http_response(response_envelope())),
            monotonic=lambda: next(values),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )
        payload = request_payload()
        payload["timeout"] = 1
        with self.assertRaises(ModelDockClientError) as caught:
            client.generate_text(
                payload,
                mission_id=MISSION_ID,
                request_id=REQUEST_ID,
                symbol=SYMBOL,
                run_mode="LIVE",
                content_validator=lambda value: value,
            )
        self.assertEqual(caught.exception.code, "timeout")

    def test_urllib_transport_checks_remaining_deadline_between_chunks(self) -> None:
        class StreamingResponse:
            status = 200
            headers: dict[str, str] = {}

            def __init__(self) -> None:
                self.read_count = 0

            def __enter__(self):
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def read(self, _: int) -> bytes:
                self.read_count += 1
                return b"x"

        class Opener:
            def __init__(self, response: StreamingResponse) -> None:
                self.response = response

            def open(self, *args: Any, **kwargs: Any) -> StreamingResponse:
                return self.response

        stream = StreamingResponse()
        times = iter((0.0, 0.1, 1.1))
        transport = UrlLibTransport(monotonic=lambda: next(times))
        transport._opener = Opener(stream)  # type: ignore[assignment]
        with self.assertRaises(TimeoutError):
            transport.request(
                method="GET",
                url="http://127.0.0.1:8000/health",
                headers={},
                body=None,
                timeout_seconds=1.0,
                max_response_bytes=1024,
            )
        self.assertEqual(stream.read_count, 1)

    def test_replay_accepts_fixture_but_never_invokes_another_transport(self) -> None:
        envelope = response_envelope(run_mode="REPLAY", mocked=True)
        transport = FakeTransport(http_response(envelope))
        result = self.invoke(transport, run_mode="REPLAY")
        self.assertTrue(result.mocked)
        self.assertEqual(transport.calls, 1)

    def test_request_contract_and_mode_are_strict(self) -> None:
        payload = request_payload()
        payload["unknown"] = "value"
        self.assert_code(
            "request_schema", FakeTransport(http_response(response_envelope())), payload=payload
        )
        self.assert_code(
            "run_mode_invalid",
            FakeTransport(http_response(response_envelope())),
            run_mode="live",
        )

        payload = request_payload()
        payload["prompt"] = "x" * (512 * 1024 + 1)
        self.assert_code(
            "request_prompt_oversized",
            FakeTransport(http_response(response_envelope())),
            payload=payload,
        )

    def test_live_requires_explicit_model_before_oracle_facts_are_sent(self) -> None:
        transport = FakeTransport(http_response(response_envelope()))
        client = ModelDockClient(
            ModelDockConfig(
                base_url="http://127.0.0.1:8000",
                timeout_seconds=10.0,
            ),
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

        with self.assertRaises(ModelDockClientError) as caught:
            client.generate_text(
                {**request_payload(), "model": None},
                mission_id=MISSION_ID,
                request_id=REQUEST_ID,
                symbol=SYMBOL,
                run_mode="LIVE",
                content_validator=lambda value: value,
            )

        self.assertEqual(caught.exception.code, "live_model_required")
        self.assertEqual(transport.calls, 0)

    def test_live_rejects_non_mlx_registered_route_before_post(self) -> None:
        transport = FakeTransport(
            http_response(response_envelope()),
            model_provider="ollama",
        )

        with self.assertRaises(ModelDockClientError) as caught:
            self.invoke(transport)

        self.assertEqual(caught.exception.code, "live_model_route_policy")
        self.assertEqual(transport.calls, 1)
        self.assertTrue(transport.last_request["url"].endswith("/models"))
        self.assertEqual(transport.last_request["method"], "GET")


if __name__ == "__main__":
    unittest.main()
