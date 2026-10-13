"""GET-only exact PAPER observations with synthetic credentials/transports."""
from __future__ import annotations
import copy
import io
import json
from http.client import IncompleteRead
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError

from blackpod_build_week import paper_order_capture as collector
from blackpod_build_week import trading_reconciliation as engine
from blackpod_build_week.paper_account_probe import PaperResponse, PaperTransportError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_paper_account_probe import FakeTransport, PAPER_ENV, NOW
from test_trading_reconciliation_engine import broker_order

ORDER_ID = "11111111-1111-1111-1111-111111111111"
REPLACEMENT_ID = "22222222-2222-2222-2222-222222222222"


def exact_order(identity=ORDER_ID, **changes):
    value = broker_order(identity, submitted_at=NOW, updated_at=NOW, filled_at=NOW)
    value.pop("parent_order_id"); value.pop("leg_ids")
    value["legs"] = None
    value.update(changes)
    return value


class PaperOrderCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "credentials" / "paper.env"
        self.source.parent.mkdir()
        self.source.write_bytes(PAPER_ENV)
        self.output = self.base / "observations"
        self.probe = FakeTransport()
        self.probe.values["/v2/positions"] = []
        self.probe.values["/v2/orders?status=open&limit=500&nested=true"] = []
        self.orders = {ORDER_ID: exact_order(), REPLACEMENT_ID: exact_order(REPLACEMENT_ID, client_order_id="replacement-client", replaces=ORDER_ID)}
        self.calls = []
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))

    def exact_fetch(self, identity, headers, timeout):
        self.calls.append((identity, dict(headers), timeout))
        value = self.orders[identity]
        if isinstance(value, Exception): raise value
        return value if isinstance(value, PaperResponse) else PaperResponse(200, json.dumps(value).encode())

    def capture(self, ids=(ORDER_ID,), **changes):
        options = {"probe_transport": self.probe, "order_transport": self.exact_fetch,
                   "now": lambda: NOW, "expected_account_id": "fixture-account"}
        options.update(changes)
        return collector.capture_paper_orders(self.source, "PAPER_ENV", self.output, ids, **options)

    def test_exact_get_composite_round_trips_original_evidence_without_secrets(self):
        self.orders[ORDER_ID]["unknown_field"] = "do-not-retain"
        result = self.capture()
        self.assertEqual(result["result"], "CONFIRMED")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual([item[0] for item in self.calls], [ORDER_ID])
        self.assertEqual(result["capture"]["tracked_order_requests"][0]["method"], "GET")
        self.assertEqual(result["capture"]["tracked_order_requests"][0]["path"], "/v2/orders/" + ORDER_ID)
        raw = Path(result["evidence_path"]).read_bytes()
        for secret in (b"fixture-paper-id", b"fixture-paper-secret", b"do-not-retain"):
            self.assertNotIn(secret, raw)
        snapshot = engine.snapshot_input_from_probe(raw, snapshot_id="capture-1", evidence_path="broker/composite.json")
        event = engine.build_snapshot_event(snapshot, [], {sha256_bytes(raw): raw})
        self.assertEqual(event.payload["snapshot"]["orders"][0]["id"], ORDER_ID)
        self.assertFalse(event.payload["assessment"]["readiness"])
        self.assertIsNone(event.payload["assessment"]["realized_trade_pnl"])
        self.assertEqual(engine.evidence_for_snapshot(snapshot, [], {sha256_bytes(raw): raw})["broker/composite.json"], raw)

    def test_partial_cancel_retains_nonzero_cumulative_fill(self):
        self.orders[ORDER_ID] = exact_order(status="canceled", filled_qty="1", filled_at=None, canceled_at=NOW)
        result = self.capture()
        snapshot = engine.snapshot_input_from_probe(Path(result["evidence_path"]).read_bytes(), snapshot_id="partial-1", evidence_path="broker/partial.json")
        self.assertEqual(snapshot.orders[0]["status"], "canceled")
        self.assertEqual(snapshot.orders[0]["filled_qty"], "1")
        self.assertEqual(snapshot.orders[0]["filled_avg_price"], "10")

    def test_replaced_order_and_exact_successor_retain_separate_fill_observations(self):
        self.orders[ORDER_ID] = exact_order(status="replaced", filled_qty="1", filled_at=None, replaced_at=NOW, replaced_by=REPLACEMENT_ID)
        result = self.capture((ORDER_ID, REPLACEMENT_ID))
        snapshot = engine.snapshot_input_from_probe(Path(result["evidence_path"]).read_bytes(), snapshot_id="replacement-1", evidence_path="broker/replacement.json")
        self.assertEqual(len(snapshot.orders), 2)
        self.assertEqual(snapshot.orders[0]["replaced_by"], REPLACEMENT_ID)
        self.assertEqual(snapshot.orders[1]["replaces"], ORDER_ID)
        self.assertEqual([order["filled_qty"] for order in snapshot.orders], ["1", "2"])

    def test_failed_exact_read_retains_failure_without_fabricating_absent_order(self):
        self.orders[ORDER_ID] = PaperResponse(404, b"secret-error-fixture-paper-secret")
        result = self.capture((ORDER_ID, REPLACEMENT_ID))
        self.assertEqual(result["result"], "NOT_CONFIRMED")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["capture"]["tracked_orders"], [])
        self.assertEqual(result["capture"]["tracked_order_requests"][0]["http_status"], 404)
        raw = Path(result["evidence_path"]).read_bytes()
        self.assertNotIn(b"secret-error", raw)
        with self.assertRaises(engine.TradingReconciliationError):
            engine.snapshot_input_from_probe(raw, snapshot_id="bad-1", evidence_path="broker/bad.json")

    def test_account_failure_prevents_any_exact_order_read(self):
        self.probe.values["/v2/account"] = PaperResponse(401, b"secret-error")
        result = self.capture()
        self.assertEqual(result["result"], "NOT_CONFIRMED")
        self.assertEqual(self.calls, [])
        self.assertFalse(result["report"]["account_authenticated"])

    def test_identity_mismatch_prevents_import_and_stops_further_queries(self):
        self.orders[ORDER_ID] = exact_order(REPLACEMENT_ID)
        result = self.capture((ORDER_ID, REPLACEMENT_ID))
        self.assertEqual(result["result"], "NOT_CONFIRMED")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result["capture"]["tracked_orders"], [])

    def test_credential_change_cannot_mix_two_accounts_in_one_capture(self):
        def changing_probe(path, headers, timeout):
            response = self.probe(path, headers, timeout)
            if path == "/v2/clock":
                self.source.write_bytes(PAPER_ENV.replace(b"fixture-paper-id", b"different-paper-id").replace(b"fixture-paper-secret", b"different-paper-secret"))
            return response
        try:
            self.capture(probe_transport=changing_probe)
        except ValueError:
            self.assertEqual(self.calls, [])
        for _, headers, _ in self.calls:
            self.assertEqual(headers["APCA-API-KEY-ID"], "fixture-paper-id")
            self.assertEqual(headers["APCA-API-SECRET-KEY"], "fixture-paper-secret")

    def test_malformed_selected_order_fields_retain_a_failed_capture(self):
        for value in ({"id": ORDER_ID}, exact_order(status={"malformed": True}), exact_order(filled_qty="NaN")):
            self.orders[ORDER_ID] = value
            with self.subTest(fields=list(value)):
                result = self.capture()
                self.assertEqual(result["result"], "NOT_CONFIRMED")
                self.assertTrue(Path(result["evidence_path"]).is_file())
                self.assertEqual(result["capture"]["tracked_orders"], [])

    def test_incomplete_http_body_and_malformed_nested_legs_are_sanitized_failures(self):
        for value in (IncompleteRead(b"secret-body-fixture-paper-secret"), exact_order(legs={"malformed": True})):
            self.orders[ORDER_ID] = value
            with self.subTest(kind=type(value).__name__):
                result = self.capture()
                self.assertEqual(result["result"], "NOT_CONFIRMED")
                self.assertEqual(result["capture"]["tracked_orders"], [])
                raw = Path(result["evidence_path"]).read_bytes()
                self.assertNotIn(b"secret-body", raw)
                self.assertNotIn(b"fixture-paper-secret", raw)

    def test_zero_explicit_tracked_orders_is_scoped_to_requested_set(self):
        result = self.capture(())
        snapshot = engine.snapshot_input_from_probe(Path(result["evidence_path"]).read_bytes(), snapshot_id="empty-1", evidence_path="broker/empty.json")
        self.assertEqual(result["capture"]["tracked_order_ids"], [])
        self.assertEqual(self.calls, [])
        self.assertTrue(snapshot.completeness["tracked_orders_complete"])
        self.assertEqual(snapshot.orders, [])

    def test_invalid_duplicate_or_url_order_ids_fail_before_any_get(self):
        for ids in ((ORDER_ID, ORDER_ID), ("https://evil.invalid",), ("../account",)):
            with self.subTest(ids=ids), self.assertRaises(ValueError): self.capture(ids)
        self.assertEqual(self.probe.calls, [])
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_transport_is_get_fixed_paper_host_no_proxy_redirect_or_mutation(self):
        response = MagicMock()
        response.status = 200
        response.geturl.return_value = collector.PAPER_ORIGIN + "/v2/orders/" + ORDER_ID
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        opener = Mock(); opener.open.return_value = response
        with patch.object(collector, "build_opener", return_value=opener) as build:
            collector.exact_order_get(ORDER_ID, {"APCA-API-KEY-ID": "fixture"}, 10)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, collector.PAPER_ORIGIN + "/v2/orders/" + ORDER_ID)
        self.assertEqual(build.call_args.args[0].proxies, {})
        with self.assertRaises(PaperTransportError): collector.exact_order_get("../account", {}, 10)
        response.geturl.return_value = "https://api.alpaca.markets/v2/orders/" + ORDER_ID
        with patch.object(collector, "build_opener", return_value=opener), self.assertRaises(PaperTransportError):
            collector.exact_order_get(ORDER_ID, {}, 10)

    def test_raw_http_errors_and_body_are_not_returned(self):
        error = HTTPError(collector.PAPER_ORIGIN, 401, "secret-error", {}, io.BytesIO(b"secret-body"))
        opener = Mock(); opener.open.side_effect = error
        with patch.object(collector, "build_opener", return_value=opener), self.assertRaises(PaperTransportError) as caught:
            collector.exact_order_get(ORDER_ID, {}, 10)
        self.assertEqual(caught.exception.http_status, 401)
        self.assertNotIn("secret-error", str(caught.exception))
        opener.open.side_effect = IncompleteRead(b"secret-body")
        with patch.object(collector, "build_opener", return_value=opener), self.assertRaises(PaperTransportError) as caught:
            collector.exact_order_get(ORDER_ID, {}, 10)
        self.assertNotIn("secret-body", str(caught.exception))


if __name__ == "__main__": unittest.main()
