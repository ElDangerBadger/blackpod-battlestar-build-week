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


def smoke(*, mocked: bool = False, engine: str = "mlx-vlm", model: str = "mlx-community/test-model") -> HttpResponse:
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
            "model": model,
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
        )

    def run_preflight(self, transport: QueueTransport):
        return run_modeldock_preflight(
            self.config,
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

    def test_real_structured_smoke_inference_passes_readiness(self) -> None:
        transport = QueueTransport([health(), smoke()])
        report = self.run_preflight(transport)
        self.assertTrue(report.ready)
        self.assertTrue(report.health_ready)
        self.assertIsNone(report.models_endpoint_ready)
        self.assertIsNone(report.selected_model_available)
        self.assertIsNone(report.to_dict()["models_endpoint_ready"])
        self.assertIsNone(report.to_dict()["selected_model_available"])
        self.assertTrue(report.text_generate_endpoint_available)
        self.assertTrue(report.inference_ready)
        self.assertEqual(report.provider, "mlx")
        self.assertEqual(report.model, "mlx-community/test-model")
        self.assertEqual(report.model_revision, "rev-preflight")
        self.assertEqual(report.trace_id, "trace-preflight")
        self.assertFalse(report.mocked)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.calls[0]["url"], "http://127.0.0.1:8000/health")
        self.assertEqual(
            transport.calls[1]["url"], "http://127.0.0.1:8000/text/generate"
        )
        self.assertEqual([call["method"] for call in transport.calls], ["GET", "POST"])
        payload = json.loads(transport.calls[1]["body"])
        self.assertNotIn("model", payload)
        self.assertNotIn("provider", payload)
        self.assertEqual(payload["profile"], "default")
        self.assertEqual(payload["capabilities"], ["text"])
        self.assertEqual(payload["response_format"], {"type": "json"})

    def test_shallow_health_without_inference_is_not_ready(self) -> None:
        report = self.run_preflight(
            QueueTransport([health(), ConnectionError("offline")])
        )
        self.assertTrue(report.health_ready)
        self.assertFalse(report.inference_ready)
        self.assertFalse(report.ready)
        self.assertEqual(report.issues[-1]["code"], "connection_failure")
        self.assertIsNone(report.model)
        self.assertIsNone(report.provider)

    def test_current_health_requires_real_inference_for_ready_and_busy_states(self) -> None:
        for state in ("READY", "BUSY"):
            with self.subTest(state=state):
                current_health = {
                    "status": "ok", "service": "modeldock", "version": "1.0.0",
                    "state": state, "ready": True, "provider_available": True,
                }
                transport = QueueTransport([response(current_health), smoke()])
                report = self.run_preflight(transport)
                self.assertTrue(report.ready)
                self.assertTrue(report.health_ready)
                self.assertTrue(report.inference_ready)
                self.assertEqual(report.health_response, current_health)
                self.assertEqual(len(transport.calls), 2)
                self.assertEqual(transport.calls[-1]["method"], "POST")

                failed_transport = QueueTransport([
                    response(current_health), ConnectionError("offline")
                ])
                failed = self.run_preflight(failed_transport)
                self.assertTrue(failed.health_ready)
                self.assertFalse(failed.inference_ready)
                self.assertFalse(failed.ready)

    def test_current_health_remains_strict_and_fail_closed(self) -> None:
        current_health = {
            "status": "ok", "service": "modeldock", "version": "1.0.0",
            "state": "READY", "ready": True, "provider_available": True,
        }
        invalid_responses = [
            {**current_health, "status": "degraded"},
            {**current_health, "state": "STARTING"},
            {**current_health, "state": []},
            {**current_health, "ready": False},
            {**current_health, "ready": 1},
            {**current_health, "ready": "true"},
            {**current_health, "provider_available": False},
            {**current_health, "provider_available": 1},
            {**current_health, "unexpected": True},
            {key: value for key, value in current_health.items() if key != "state"},
        ]
        for candidate in invalid_responses:
            with self.subTest(health=candidate):
                transport = QueueTransport([response(candidate)])
                report = self.run_preflight(transport)
                self.assertFalse(report.health_ready)
                self.assertFalse(report.inference_ready)
                self.assertFalse(report.ready)
                self.assertEqual(report.issues[-1]["code"], "health_contract_invalid")
                self.assertEqual(len(transport.calls), 1)

    def test_mocked_smoke_fails_live_readiness(self) -> None:
        report = self.run_preflight(
            QueueTransport([health(), smoke(mocked=True)])
        )
        self.assertFalse(report.ready)
        self.assertTrue(report.text_generate_endpoint_available)
        self.assertFalse(report.inference_ready)
        self.assertTrue(report.mocked)
        self.assertEqual(report.issues[-1]["code"], "mocked_live_response")

    def test_invalid_health_stops_before_inference(self) -> None:
        invalid_health = response(
            {"status": "ok", "service": "other", "version": "0.1.0"}
        )
        transport = QueueTransport([invalid_health])
        report = self.run_preflight(transport)
        self.assertTrue(report.service_reachable)
        self.assertFalse(report.health_ready)
        self.assertFalse(report.ready)
        self.assertEqual(len(transport.calls), 1)

    def test_legacy_config_model_does_not_select_or_limit_service_model(self) -> None:
        self.config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=10.0,
                                      model="legacy-configured-model")
        transport = QueueTransport([health(), smoke(model="service-selected-other-model")])
        report = self.run_preflight(transport)
        self.assertTrue(report.ready)
        self.assertEqual(report.model, "service-selected-other-model")
        self.assertIsNone(report.models_endpoint_ready)
        self.assertIsNone(report.selected_model_available)
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("model", json.loads(transport.calls[-1]["body"]))
        self.assertFalse(any(call["url"].endswith("/models") for call in transport.calls))

    def test_service_routed_model_without_client_pin_dispatches_one_smoke_prompt(self) -> None:
        config = ModelDockConfig(
            base_url="http://127.0.0.1:8000",
            timeout_seconds=10.0,
        )
        transport = QueueTransport([health(), smoke()])

        report = run_modeldock_preflight(
            config,
            transport=transport,
            monotonic=StepClock(),
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

        self.assertTrue(report.ready)
        self.assertIsNone(report.models_endpoint_ready)
        self.assertIsNone(report.selected_model_available)
        self.assertTrue(report.text_generate_endpoint_available)
        self.assertEqual(report.issues, ())
        self.assertEqual(len(transport.calls), 2)
        self.assertNotIn("model", json.loads(transport.calls[-1]["body"]))

    def test_no_client_model_or_provenance_is_invented_when_health_fails(self) -> None:
        self.config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=10.0,
                                      model="legacy-configured-model")
        transport = QueueTransport([ConnectionError("offline")])
        report = self.run_preflight(transport)
        self.assertFalse(report.ready)
        self.assertIsNone(report.model)
        self.assertIsNone(report.provider)
        self.assertIsNone(report.models_endpoint_ready)
        self.assertIsNone(report.selected_model_available)
        self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
