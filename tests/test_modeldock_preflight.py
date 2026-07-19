from __future__ import annotations

import json
import unittest
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.modeldock_client import HttpResponse
from blackpod_build_week.modeldock_config import ModelDockConfig
from blackpod_build_week.modeldock_preflight import run_modeldock_preflight


@dataclass
class QueueTransport:
    responses: list[HttpResponse | Exception]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(self, **kwargs: Any) -> HttpResponse:
        self.calls.append(kwargs)
        if not self.responses:
            raise ConnectionError("no fake inference response")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def response(value: dict[str, Any]) -> HttpResponse:
    body = canonical_json_bytes(value)
    return HttpResponse(200, {"Content-Length": str(len(body))}, body)


def health() -> HttpResponse:
    return response({"status": "ok", "service": "modeldock", "version": "0.1.0"})


def models() -> HttpResponse:
    return response(
        {
            "models": [
                {
                    "name": "mlx-community/test-model",
                    "provider": "mlx",
                    "capabilities": ["text"],
                    "context_length": 4096,
                    "vision_support": False,
                    "priority": 1,
                    "memory_requirements": None,
                    "preferred_use_cases": [],
                }
            ]
        }
    )


def smoke(*, mocked: bool = False, engine: str = "mlx-vlm") -> HttpResponse:
    correlation = {
        "mission_id": "modeldock-preflight",
        "request_id": "modeldock-preflight-request",
        "symbol": "SMOKE",
        "run_mode": "LIVE",
    }
    content = {
        "schema_version": "blackpod.modeldock_smoke.v1",
        "mission_id": "modeldock-preflight",
        "request_id": "modeldock-preflight-request",
        "symbol": "SMOKE",
        "status": "ready",
    }
    return response(
        {
            "status": "ok",
            "request_type": "text.generate",
            "profile": "default",
            "provider": "mlx",
            "model": "mlx-community/test-model",
            "content": json.dumps(content),
            "data": {
                "engine": engine,
                "model_path": "/private/models/snapshots/rev-preflight",
                "profile": "default",
            },
            "metadata": {
                "blackpod_correlation": correlation,
                "requested_max_tokens": 128,
                "effective_max_tokens": 128,
                "generated_token_count": 30,
                "stop_reason": "completed_or_eos",
                "generation_options": {},
            },
            "trace_id": "trace-preflight",
            "mocked": mocked,
        }
    )


class StepClock:
    def __init__(self) -> None:
        self.current = 1.0

    def __call__(self) -> float:
        result = self.current
        self.current += 0.05
        return result


class ModelDockPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
            model="mlx-community/test-model",
        )

    def run_preflight(self, transport: QueueTransport):
        return run_modeldock_preflight(
            self.config,
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

    def test_real_structured_smoke_inference_passes_readiness(self) -> None:
        transport = QueueTransport([health(), models(), smoke()])
        report = self.run_preflight(transport)
        self.assertTrue(report.ready)
        self.assertTrue(report.health_ready)
        self.assertTrue(report.models_endpoint_ready)
        self.assertTrue(report.selected_model_available)
        self.assertTrue(report.text_generate_endpoint_available)
        self.assertTrue(report.inference_ready)
        self.assertEqual(report.provider, "mlx")
        self.assertEqual(report.model, "mlx-community/test-model")
        self.assertEqual(report.model_revision, "rev-preflight")
        self.assertEqual(report.trace_id, "trace-preflight")
        self.assertFalse(report.mocked)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(transport.calls[0]["url"], "http://127.0.0.1:8000/health")
        self.assertEqual(transport.calls[1]["url"], "http://127.0.0.1:8000/models")
        self.assertEqual(
            transport.calls[2]["url"], "http://127.0.0.1:8000/text/generate"
        )

    def test_shallow_health_without_inference_is_not_ready(self) -> None:
        report = self.run_preflight(
            QueueTransport([health(), models(), ConnectionError("offline")])
        )
        self.assertTrue(report.health_ready)
        self.assertFalse(report.inference_ready)
        self.assertFalse(report.ready)
        self.assertEqual(report.issues[-1]["code"], "connection_failure")

    def test_mocked_smoke_fails_live_readiness(self) -> None:
        report = self.run_preflight(
            QueueTransport([health(), models(), smoke(mocked=True)])
        )
        self.assertFalse(report.ready)
        self.assertTrue(report.text_generate_endpoint_available)
        self.assertFalse(report.inference_ready)
        self.assertTrue(report.mocked)
        self.assertEqual(report.issues[-1]["code"], "mocked_live_response")

    def test_invalid_health_stops_before_models_or_inference(self) -> None:
        invalid_health = response(
            {"status": "ok", "service": "other", "version": "0.1.0"}
        )
        transport = QueueTransport([invalid_health])
        report = self.run_preflight(transport)
        self.assertTrue(report.service_reachable)
        self.assertFalse(report.health_ready)
        self.assertFalse(report.ready)
        self.assertEqual(len(transport.calls), 1)

    def test_unregistered_selected_model_fails_before_inference(self) -> None:
        empty_models = response({"models": []})
        transport = QueueTransport([health(), empty_models])
        report = self.run_preflight(transport)
        self.assertTrue(report.models_endpoint_ready)
        self.assertFalse(report.selected_model_available)
        self.assertFalse(report.ready)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(report.issues[-1]["code"], "selected_model_unavailable")

    def test_missing_live_model_never_dispatches_smoke_prompt(self) -> None:
        config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
        )
        transport = QueueTransport([health(), models()])

        report = run_modeldock_preflight(
            config,
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

        self.assertFalse(report.ready)
        self.assertIsNone(report.selected_model_available)
        self.assertFalse(report.text_generate_endpoint_available)
        self.assertEqual(report.issues[-1]["code"], "live_model_required")
        self.assertEqual(len(transport.calls), 2)


if __name__ == "__main__":
    unittest.main()
