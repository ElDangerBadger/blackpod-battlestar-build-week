"""Simulated time and transport only: never sleep or contact ModelDock."""
from copy import deepcopy
from datetime import UTC, datetime
import io
import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.modeldock_client import (
    HttpResponse, ModelDockClient, ModelDockClientError, UrlLibTransport,
)
from blackpod_build_week.modeldock_config import ModelDockConfig
from test_modeldock_client import (
    FakeTransport, MISSION_ID, REQUEST_ID, SYMBOL, http_response, request_payload, response_envelope,
)


def invoke(transport, *, grace=30, times=(0, 0.1, 301, 301.1), mode="LIVE", payload=None,
           request_id=REQUEST_ID, validator=None):
    ticks = iter(times)
    client = ModelDockClient(ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=300,
                                            delivery_grace_seconds=grace),
        transport=transport, monotonic=lambda: next(ticks), now=lambda:datetime(2026,9,21,tzinfo=UTC))
    wire = payload or request_payload(mode)
    wire["timeout"] = 300
    return client.generate_text(wire,mission_id=MISSION_ID,request_id=request_id,symbol=SYMBOL,
                               run_mode=mode,content_validator=validator or (lambda value:value))


class TimedResponse:
    status = 200
    headers = {}
    def __init__(self):
        self.reads = 0
        self.closed = False
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.closed = True
    def read(self, size):
        self.reads += 1
        if self.reads == 1:
            return b"private-incomplete-prose"
        raise TimeoutError("secret local timeout details")


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = 0
    def open(self, *args, **kwargs):
        self.calls += 1
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class ModelDockDeliveryTests(unittest.TestCase):
    def setUp(self):
        def denied(*args, **kwargs):
            raise AssertionError("Delivery regression must not contact a service")

        self.enterContext(patch.object(socket, "create_connection", denied))
        self.enterContext(patch.object(socket.socket, "connect", denied))

    def test_delivery_grace_receives_terminal_http_timeout_instead_of_losing_it(self):
        terminal = HttpResponse(504, {"X-Request-ID": REQUEST_ID}, b"")
        legacy, revised = FakeTransport(terminal), FakeTransport(terminal)
        with self.assertRaises(ModelDockClientError) as old:
            invoke(legacy, grace=0)
        self.assertEqual(old.exception.code, "timeout")
        with self.assertRaises(ModelDockClientError) as new:
            invoke(revised)
        failure = new.exception.failure.to_dict()
        self.assertEqual(failure["code"], "http_status")
        self.assertEqual(failure["delivery"]["http_status"], 504)
        self.assertIs(failure["delivery"]["response_request_id_matched"], True)
        self.assertEqual(failure["delivery"]["server_completion"], "UNKNOWN")
        self.assertIs(failure["delivery"]["automatic_retry_allowed"], False)
        self.assertEqual(revised.calls, 1)
        self.assertEqual(legacy.calls, 1)
        self.assertEqual(json.loads(revised.last_request["body"])["timeout"], 300)
        self.assertEqual(revised.last_request["timeout_seconds"], 329.9)

    def test_success_after_service_budget_before_delivery_deadline_preserves_wire(self):
        wire = request_payload()
        wire["timeout"] = 300
        before = deepcopy(wire)
        transport = FakeTransport(http_response(response_envelope()))
        value = invoke(transport, payload=wire)
        self.assertEqual(wire, before)
        self.assertEqual(before, json.loads(transport.last_request["body"]))
        self.assertEqual(transport.last_request["headers"]["X-Request-ID"], REQUEST_ID)
        self.assertEqual(value.delivery["provider_timeout_seconds"], 300)
        self.assertEqual(value.delivery["client_deadline_seconds"], 330)
        self.assertEqual(value.delivery["phase"], "COMPLETE")
        self.assertEqual(value.delivery["request_sha256"], value.request_sha256)
        self.assertEqual(value.delivery["server_completion"], "VALIDATED_RESPONSE_RECEIVED")
        self.assertEqual(transport.calls, 1)

    def test_grace_is_not_an_unbounded_deadline_or_permission_to_retry(self):
        transport = FakeTransport(http_response(response_envelope()))
        with self.assertRaises(ModelDockClientError) as error:
            invoke(transport, times=(0, 0.1, 330.1, 330.2))
        value = error.exception.failure.to_dict()
        self.assertEqual(value["code"], "timeout")
        self.assertEqual(transport.calls, 1)
        self.assertEqual(value["delivery"]["phase"], "RESPONSE_RECEIVED")
        self.assertIs(value["delivery"]["response_complete"], True)
        self.assertEqual(value["raw_response_sha256"], sha256_bytes(transport.response.body))
        self.assertIsNone(value["safe_response"])
        self.assertEqual(value["delivery"]["server_completion"], "UNKNOWN")

    def test_validation_time_is_bounded_and_late_prose_is_not_leaked(self):
        transport = FakeTransport(http_response(response_envelope()))
        with self.assertRaises(ModelDockClientError) as error:
            invoke(transport, times=(0, 0.1, 329, 331, 331.1))
        value = error.exception.failure.to_dict()
        self.assertEqual(value["delivery"]["phase"], "RESPONSE_VALIDATION")
        self.assertEqual(value["raw_response_sha256"], sha256_bytes(transport.response.body))
        self.assertNotIn("content", value["safe_response"])
        self.assertTrue(value["safe_response"]["content_sha256"])
        self.assertNotIn("Validated test narrative.", json.dumps(value))

    def test_replay_keeps_historical_deadline_and_no_new_header(self):
        transport = FakeTransport(http_response(response_envelope(run_mode="REPLAY", mocked=True)))
        with self.assertRaises(ModelDockClientError) as error:
            invoke(transport, mode="REPLAY")
        self.assertEqual(error.exception.code, "timeout")
        self.assertEqual(transport.last_request["timeout_seconds"], 299.9)
        self.assertNotIn("X-Request-ID", transport.last_request["headers"])
        self.assertEqual(json.loads(transport.last_request["body"])["timeout"], 300)

    def test_replay_success_has_no_live_http_request_or_server_completion_claim(self):
        transport = FakeTransport(http_response(response_envelope(run_mode="REPLAY", mocked=True)))
        result = invoke(transport, mode="REPLAY", times=(0, 0.1, 1, 1.1))
        self.assertEqual(transport.calls, 1)
        self.assertEqual(transport.last_request["timeout_seconds"], 299.9)
        self.assertNotIn("X-Request-ID", transport.last_request["headers"])
        self.assertIsNone(result.delivery["http_request_id"])
        self.assertEqual(result.delivery["server_completion"], "VALIDATED_REPLAY_RECEIVED")

    def test_delivery_grace_cannot_enlarge_provider_request_budget(self):
        transport = FakeTransport(http_response(response_envelope()))
        ticks = iter((0, 0.1))
        client = ModelDockClient(
            ModelDockConfig(
                base_url="http://127.0.0.1:8000", timeout_seconds=300,
                delivery_grace_seconds=30,
            ),
            transport=transport, monotonic=lambda: next(ticks),
            now=lambda: datetime(2026, 9, 21, tzinfo=UTC),
        )
        wire = request_payload()
        wire["timeout"] = 331
        with self.assertRaises(ModelDockClientError) as caught:
            client.generate_text(
                wire, mission_id=MISSION_ID, request_id=REQUEST_ID, symbol=SYMBOL,
                run_mode="LIVE", content_validator=lambda value: value,
            )
        self.assertEqual(caught.exception.code, "request_timeout_invalid")
        self.assertEqual(transport.calls, 0)

    def test_header_uses_safe_stable_hash_without_mutating_correlation(self):
        for value in ("long-" + "x" * 150, "scope/request:identifier"):
            with self.subTest(request_id=value):
                wire = request_payload()
                wire["metadata"]["blackpod_correlation"]["request_id"] = value
                envelope = response_envelope()
                envelope["metadata"]["blackpod_correlation"]["request_id"] = value
                prose = json.loads(envelope["content"])
                prose["request_id"] = value
                envelope["content"] = json.dumps(prose)
                transport = FakeTransport(http_response(envelope))
                result = invoke(transport, payload=wire, request_id=value)
                expected = "blackpod-" + sha256_bytes(value.encode())
                self.assertEqual(transport.last_request["headers"]["X-Request-ID"], expected)
                self.assertEqual(result.delivery["http_request_id"], expected)
                self.assertEqual(
                    json.loads(transport.last_request["body"])["metadata"]["blackpod_correlation"]["request_id"],
                    value,
                )

    def test_no_headers_timeout_is_distinct_from_slow_body(self):
        for exc in (TimeoutError("private details"), urllib.error.URLError(TimeoutError("private details"))):
            with self.subTest(exception_type=type(exc).__name__):
                transport = UrlLibTransport(monotonic=lambda: 0)
                opener = Opener(exc)
                transport._opener = opener
                with self.assertRaises(ModelDockClientError) as caught:
                    invoke(transport, times=(0, 0.1, 330.2))
                failure = caught.exception.failure.to_dict()
                self.assertEqual(failure["delivery"]["phase"], "CONNECT_OR_WAIT_HEADERS")
                self.assertIsNone(failure["delivery"]["http_status"])
                self.assertEqual(failure["delivery"]["response_bytes_received"], 0)
                self.assertEqual(failure["delivery"]["server_completion"], "UNKNOWN")
                self.assertNotIn("private details", json.dumps(failure))
                self.assertEqual(opener.calls, 1)

    def test_partial_response_timeout_preserves_phase_and_hash_not_prose(self):
        response = TimedResponse()
        transport = UrlLibTransport(monotonic=lambda: 0)
        transport._opener = Opener(response)
        with self.assertRaises(ModelDockClientError) as caught:
            invoke(transport, times=(0, 0.1, 330.2))
        failure = caught.exception.failure.to_dict()
        self.assertEqual(failure["delivery"]["phase"], "READING_RESPONSE_BODY")
        self.assertEqual(failure["delivery"]["http_status"], 200)
        self.assertIs(failure["delivery"]["response_complete"], False)
        self.assertEqual(failure["delivery"]["partial_response_sha256"], sha256_bytes(b"private-incomplete-prose"))
        self.assertEqual(failure["delivery"]["response_bytes_received"], len(b"private-incomplete-prose"))
        self.assertIsNone(failure["raw_response_sha256"])
        self.assertNotIn("private-incomplete-prose", json.dumps(failure))
        self.assertTrue(response.closed)
        self.assertEqual(transport._opener.calls, 1)

    def test_untrusted_http_error_body_is_not_read_or_retained(self):
        class ForbiddenBody(io.BytesIO):
            def read(self, *args):
                raise AssertionError("Never read untrusted server error prose")

        response = urllib.error.HTTPError(
            "http://localhost", 504, "private reason",
            {"X-Request-ID": REQUEST_ID}, ForbiddenBody(b"private prose"),
        )
        transport = UrlLibTransport(monotonic=lambda: 0)
        transport._opener = Opener(response)
        with self.assertRaises(ModelDockClientError) as caught:
            invoke(transport)
        failure = caught.exception.failure.to_dict()
        self.assertEqual(failure["code"], "http_status")
        self.assertEqual(failure["delivery"]["http_status"], 504)
        self.assertIs(failure["delivery"]["response_request_id_matched"], True)
        self.assertIs(failure["delivery"]["response_complete"], False)
        self.assertIsNone(failure["raw_response_sha256"])
        self.assertNotIn("private", json.dumps(failure))


if __name__ == "__main__":
    unittest.main()
