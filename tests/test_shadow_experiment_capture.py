"""Fixed GET boundary tests; every response is an authored offline fixture."""
from contextlib import nullcontext
import json
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from blackpod_build_week import shadow_experiment_capture as capture
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.hashing import sha256_bytes


CREDS = PaperCredentials("fixture-pilot-key", "fixture-pilot-secret")
QUERY = {"start": "2026-10-13", "end": "2026-11-30"}


class Response:
    status = 200
    def __init__(self, url, raw):
        self.url, self.raw = url, raw
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, size):
        part, self.raw = self.raw[:size], self.raw[size:]
        return part


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))

    def run_capture(self, raw=b"[]", change=None):
        seen = []
        def open_request(request, timeout):
            seen.append(request)
            response = Response(request.full_url, raw)
            if change:
                change(response)
            return response
        opener = Mock(open=open_request)
        with patch.object(capture, "build_opener", return_value=opener) as factory:
            result = capture.market_get("calendar", QUERY, CREDS)
        return result, seen, factory

    def test_exact_get_body_and_receipt_without_credentials(self):
        (raw, receipt_raw), seen, factory = self.run_capture()
        self.assertEqual(raw, b"[]")
        receipt = json.loads(receipt_raw)
        self.assertEqual(receipt["body_sha256"], sha256_bytes(raw))
        self.assertEqual(receipt["size_bytes"], 2)
        self.assertEqual(receipt["method"], "GET")
        self.assertEqual(receipt["url"], capture.URLS["calendar"])
        self.assertEqual(receipt["query"], QUERY)
        request = seen[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Apca-api-key-id"), CREDS.key_id)
        self.assertNotIn(CREDS.key_id.encode(), receipt_raw)
        handlers = factory.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], capture._RefuseRedirects)
        self.assertEqual(handlers[2]._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(handlers[2]._context.check_hostname)

    def test_redirect_status_invalid_json_and_size_refused(self):
        cases = [(b"[]", lambda r: setattr(r, "url", "https://example.com"), "REDIRECT_REFUSED"),
                 (b"secret error", lambda r: setattr(r, "status", 401), "HTTP_ERROR"),
                 (b"x" * (capture.MAX_BYTES + 1), None, "RESPONSE_TOO_LARGE"),
                 (b'{"x":1,"x":2}', None, "INVALID_RESPONSE"),
                 (b'{"x":NaN}', None, "INVALID_RESPONSE"),
                 (b"", None, "SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")]
        for raw, change, code in cases:
            with self.subTest(code=code), self.assertRaises(capture.ExperimentCaptureError) as caught:
                self.run_capture(raw, change)
            self.assertEqual(caught.exception.code, code)

    def test_literal_and_escaped_secret_echo_refused(self):
        for raw in (b'{"x":"fixture-pilot-secret"}', b'{"x":"fixture-pilot-secr\\u0065t"}'):
            with self.subTest(raw=raw), self.assertRaises(capture.ExperimentCaptureError) as caught:
                self.run_capture(raw)
            self.assertEqual(caught.exception.code, "SENSITIVE_OR_EMPTY_RESPONSE_REFUSED")

    def test_arbitrary_endpoints_and_queries_never_open_network(self):
        cases = [("orders", QUERY), ("calendar", {**QUERY, "url": "https://example.com"}),
                 ("calendar", {"start": "2026-01-01", "end": "2026-11-30"}),
                 ("bars", {"start": "2026-01-01", "end": "2026-11-30"})]
        for kind, query in cases:
            with self.subTest(kind=kind, query=query), patch.object(capture, "build_opener") as factory:
                with self.assertRaises(capture.ExperimentCaptureError):
                    capture.market_get(kind, query, CREDS)
                factory.assert_not_called()

    def test_only_two_symbols_daily_iex_raw_bars_allowed(self):
        from blackpod_build_week.shadow_experiment_cli import _bars_query
        base = _bars_query("2026-10-13", "2026-11-30")
        self.assertEqual(capture.validate_query("bars", base), base)
        for field, value in (("symbols", "AAPL"), ("feed", "sip"), ("adjustment", "all"),
                             ("timeframe", "1Min"), ("sort", "desc"), ("limit", 10000)):
            with self.subTest(field=field), self.assertRaises(capture.ExperimentCaptureError):
                capture.validate_query("bars", {**base, field: value})

    def test_native_exceptions_are_sanitized(self):
        for error, code in ((URLError("fixture-pilot-secret"), "URL_ERROR"),
                            (OSError("fixture-pilot-secret"), "TRANSPORT_ERROR"),
                            (TimeoutError("fixture-pilot-secret"), "TIMEOUT"),
                            (HTTPError("https://host", 403, "fixture-pilot-secret", {}, None), "HTTP_ERROR")):
            with self.subTest(code=code), patch.object(capture, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaises(capture.ExperimentCaptureError) as caught:
                    capture.market_get("calendar", QUERY, CREDS)
                self.assertEqual(str(caught.exception), code)
                self.assertNotIn("secret", str(caught.exception))

    def test_timeouts_and_noncredential_objects_refused(self):
        for credentials, timeout in ((None, 20), (CREDS, 0), (CREDS, True), (CREDS, 31)):
            with self.subTest(timeout=timeout), patch.object(capture, "build_opener") as factory:
                with self.assertRaises(capture.ExperimentCaptureError):
                    capture.market_get("calendar", QUERY, credentials, timeout=timeout)
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
