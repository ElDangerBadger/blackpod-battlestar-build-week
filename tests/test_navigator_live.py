"""Offline price relay tests. No real keys, accounts, or market services."""
from __future__ import annotations

import io
import json
import unittest
import http.client
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from unittest.mock import patch, MagicMock

from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader, Publication
from blackpod_build_week.navigator_live import (
    LivePriceUnavailable, NavigatorLiveBridge, encode_event,
    unavailable_event, validate_live_price,
)


def frame(**updates):
    now = datetime.now(timezone.utc)
    stamp = now.isoformat().replace("+00:00", "Z")
    value = {"schema_version": "navigator.live_price.v1", "symbol": "AAPL", "provider": "alpaca",
             "feed": "iex", "status": "LIVE", "price": 200.1,
             "trade_at": stamp, "received_at": stamp, "checked_at": stamp,
             "message": "Last streamed trade; not a bar close."}
    value.update(updates)
    return value


def payload(value):
    return json.dumps(value).encode()


class LivePriceContractTests(unittest.TestCase):
    def test_live_and_null_statuses(self):
        value = frame()
        self.assertEqual(validate_live_price(payload(value), "AAPL"), value)
        for status in ("CONNECTING", "WAITING", "STALE", "UNAVAILABLE"):
            value = frame(status=status, price=None, trade_at=None, received_at=None)
            self.assertEqual(validate_live_price(payload(value), "AAPL"), value)

    def test_invalid_fields_identity_and_numbers_fail_closed(self):
        for update in ({"symbol": "SPY"}, {"provider": "yfinance"}, {"feed": "delayed_sip"},
                       {"status": "TRADING"}, {"price": 0}, {"price": -1}, {"price": True},
                       {"price": float("inf")}, {"price": None}, {"trade_at": None},
                       {"received_at": None}, {"feed": []}, {"status": {}}, {"price": 10**1000}, {"message": "bad\nmessage"},
                       {"message": "x" * 201}, {"secret": "never-forward"},
                       {"checked_at": "2026-01-01T00:00:00"}):
            with self.subTest(update=list(update)):
                with self.assertRaises(ValueError):
                    validate_live_price(payload(frame(**update)), "AAPL")
        with self.assertRaises(ValueError):
            validate_live_price(b" " * 4097, "AAPL")
        with self.assertRaises(ValueError):
            validate_live_price(b'{"symbol":"AAPL","symbol":"SPY"}', "AAPL")

    def test_trade_age_not_heartbeat_controls_freshness(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat().replace("+00:00", "Z")
        value = validate_live_price(payload(frame(trade_at=past)), "AAPL")
        self.assertEqual(value["status"], "STALE")
        self.assertEqual(value["price"], 200.1)

    def test_future_and_stale_heartbeat_rejected(self):
        for seconds in (15, -90):
            stamp = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
            with self.assertRaises(ValueError):
                validate_live_price(payload(frame(checked_at=stamp)), "AAPL")
        future = (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat().replace("+00:00", "Z")
        with self.assertRaises(ValueError):
            validate_live_price(payload(frame(trade_at=future)), "AAPL")

    def test_disconnection_retains_last_price_but_never_live(self):
        previous = frame(feed="sip")
        value = json.loads(unavailable_event("AAPL", previous)[6:])
        self.assertEqual(value["status"], "UNAVAILABLE")
        self.assertEqual(value["feed"], "sip")
        self.assertEqual(value["trade_at"], previous["trade_at"])
        self.assertEqual(value["price"], previous["price"])


class LivePriceBridgeTests(unittest.TestCase):
    def test_only_loopback_explicit_origin_accepted(self):
        self.assertEqual(NavigatorLiveBridge("http://localhost:8001").port, 8001)
        for url in ("https://data.alpaca.markets", "http://example.com:80", "http://127.0.0.1",
                    "http://127.0.0.1:8001/orders", "http://key:secret@127.0.0.1:8001",
                    "http://127.0.0.1:8001/?feed=sip", "http://127.0.0.1:8001/#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                NavigatorLiveBridge(url)

    def connection(self, body, status=200, content_type="text/event-stream"):
        response = MagicMock()
        response.status = status
        response.getheader.return_value = content_type
        response.readline.side_effect = io.BytesIO(body).readline
        connection = MagicMock()
        connection.getresponse.return_value = response
        return connection

    def test_fixed_data_route_no_auth_redirects_or_credentials(self):
        value = frame()
        connection = self.connection(encode_event(value))
        with patch("blackpod_build_week.navigator_live.http.client.HTTPConnection", return_value=connection) as factory:
            events = NavigatorLiveBridge("http://localhost:8001").events("AAPL")
            self.assertEqual(next(events), value)
            events.close()
        factory.assert_called_once_with("127.0.0.1", 8001, timeout=15)
        connection.request.assert_called_once_with("GET", "/api/live-price/AAPL", headers={"Accept": "text/event-stream"})
        connection.close.assert_called_once()

    def test_malformed_source_never_forwarded(self):
        for body, status, content_type in ((b"", 302, "text/event-stream"),
                (b"private failure", 500, "text/plain"), (b"", 200, "text/html"),
                (b"data: {private failure}\n\n", 200, "text/event-stream"),
                (b"data: " + b"x" * 5000, 200, "text/event-stream"),
                (encode_event(frame(symbol="SPY")), 200, "text/event-stream")):
            with self.subTest(status=status, size=len(body)):
                connection = self.connection(body, status, content_type)
                with patch("blackpod_build_week.navigator_live.http.client.HTTPConnection", return_value=connection):
                    with self.assertRaises(LivePriceUnavailable) as caught:
                        next(NavigatorLiveBridge("http://127.0.0.1:8001").events("AAPL"))
                    self.assertNotIn("private", str(caught.exception))
                connection.close.assert_called_once()

    def test_late_tick_ignored_and_feed_change_rejected(self):
        previous = frame()
        older = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        connection = self.connection(encode_event(previous) + encode_event(frame(trade_at=older)) + encode_event(frame(feed="sip")))
        with patch("blackpod_build_week.navigator_live.http.client.HTTPConnection", return_value=connection):
            events = NavigatorLiveBridge("http://127.0.0.1:8001").events("AAPL")
            self.assertEqual(next(events), previous)
            with self.assertRaises(LivePriceUnavailable):
                next(events)
        connection.close.assert_called_once()

    def test_invalid_symbol_never_connects(self):
        with patch("blackpod_build_week.navigator_live.http.client.HTTPConnection") as factory:
            with self.assertRaises(LivePriceUnavailable):
                next(NavigatorLiveBridge("http://127.0.0.1:8001").events("../orders"))
            factory.assert_not_called()


class LivePriceMembershipTests(unittest.TestCase):
    def test_only_original_or_verified_observed_fleet_is_allowed(self):
        reader = CabinReader()
        files = {"presentation/navigator_market.json": payload({"symbol": "AAPL"}),
                 "mission_snapshot.json": payload({"artifacts": [{"name": "oracle_normalized_snapshot", "path": "oracle/normalized.json"}]}),
                 "oracle/normalized.json": payload({"symbols": [{"symbol": "XLK"}, {"symbol": "SPY"}]})}
        reader._publications["a" * 64] = Publication("a" * 64, "mission-test", "2026-01-01T00:00:00Z", MappingProxyType(files))
        before = dict(files)
        for symbol in ("AAPL", "XLK", "SPY"):
            self.assertTrue(reader.permits_live_symbol("a" * 64, symbol))
        for symbol in ("ZZZZ", "../AAPL", "aapl", "AAPL?secret"):
            self.assertFalse(reader.permits_live_symbol("a" * 64, symbol))
        self.assertFalse(reader.permits_live_symbol("b" * 64, "AAPL"))
        self.assertEqual(files, before)


class LivePriceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reader = CabinReader()
        self.reader._publications["a" * 64] = Publication("a" * 64, "mission-test", "2026-01-01T00:00:00Z", {
            "presentation/navigator_market.json": payload({"symbol": "AAPL"}),
            "mission_snapshot.json": payload({"artifacts": []}),
        })
        self.server = CabinHTTPServer(self.reader, Path(self.temp.name), 0, navigator_live_url="http://127.0.0.1:8001")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.route = "/live/navigator/price/" + "a" * 64 + "/AAPL"

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path=None, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path or self.route, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_stream_no_store_and_no_evidence_mutation(self):
        before = dict(self.reader._publications["a" * 64].files)
        def events(_symbol):
            yield frame()
            raise LivePriceUnavailable("upstream-private-diagnostic")
        with patch.object(self.server.navigator_live, "events", side_effect=events):
            status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("text/event-stream", headers["Content-Type"])
        self.assertIn(b'"status":"LIVE"', body)
        self.assertIn(b'"status":"UNAVAILABLE"', body)
        self.assertNotIn(b"upstream-private", body)
        self.assertEqual(self.reader._publications["a" * 64].files, before)
        self.assertTrue(self.server.live_slots.acquire(blocking=False))
        self.server.live_slots.release()

    def test_unknown_publication_symbol_queries_and_mutations_do_not_connect(self):
        with patch.object(self.server.navigator_live, "events") as events:
            for path, method in ((self.route.replace("a" * 64, "b" * 64), "GET"),
                                 (self.route.replace("AAPL", "MSFT"), "GET"),
                                 (self.route + "?url=https://bad.invalid", "GET"),
                                 (self.route, "HEAD"), (self.route, "POST")):
                with self.subTest(path=path, method=method):
                    status, _, _ = self.request(path, method)
                    self.assertIn(status, {404, 405})
            events.assert_not_called()

    def test_cross_origin_denied_before_upstream(self):
        with patch.object(self.server.navigator_live, "events") as events:
            self.assertEqual(self.request(headers={"Origin": "https://bad.invalid"})[0], 403)
            self.assertEqual(self.request(headers={"Host": "bad.invalid"})[0], 403)
            events.assert_not_called()

    def test_disabled_and_connection_failure_are_sanitized(self):
        def events(_symbol):
            raise LivePriceUnavailable("private-upstream-failure")
            yield  # generator interface, intentionally never reached
        with patch.object(self.server.navigator_live, "events", side_effect=events):
            status, _, body = self.request()
            self.assertEqual(status, 503)
            self.assertNotIn(b"private", body)
        self.server.navigator_live = None
        self.assertEqual(self.request()[0], 503)


if __name__ == "__main__":
    unittest.main()
