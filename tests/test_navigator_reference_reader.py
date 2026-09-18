"""Offline current-reference transport checks; no providers or mission runs."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader, Publication
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.navigator_reference_reader import NavigatorReferenceReader


NOW = datetime(2026, 9, 15, 22, 40, tzinfo=timezone.utc)


def stamp(value):
    return value.isoformat().replace("+00:00", "Z")


def snapshot():
    market = json.loads((Path(__file__).parents[1] / "fixtures/cabin/aapl_navigator_market.live_capture.json").read_bytes())
    market["data"] = dict(provider="yfinance", stale=False, age_seconds=0, source="provider")
    return dict(schema_version="navigator.reference_snapshot.v1", symbol="AAPL", timeframe="1d", ma_period=250,
                captured_at=stamp(NOW), provider_fetched_at=stamp(NOW), valid_until=stamp(NOW + timedelta(hours=20)),
                bar_policy="completed_regular_session", latest_bar_at=market["points"][-1]["t"],
                expected_bar_at=market["points"][-1]["t"], calendar_id="sentry-session-calendar-" + "a" * 64,
                provider="yfinance", adjustment="auto_adjust=True", market=market)


class ReferenceReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # macOS /var is a symlink: exercise the real normalized artifact root.
        self.root = Path(self.temp.name).resolve()
        (self.root / "snapshots").mkdir()
        self.reader = NavigatorReferenceReader(self.root)

    def publish(self, value=None, status="READY"):
        value = snapshot() if value is None else value
        raw = canonical_json_bytes(value)
        digest = sha256_bytes(raw)
        target = self.root / "snapshots" / (digest + ".json")
        target.write_bytes(raw)
        entry = dict(symbol="AAPL", timeframe="1d", ma_period=250, status=status,
                     reason="VERIFIED" if status == "READY" else "PROVIDER_UNAVAILABLE",
                     last_attempt_at=stamp(NOW), snapshot=dict(path="snapshots/" + target.name,
                                                               sha256=digest, byte_size=len(raw)))
        index = dict(schema_version="navigator.reference_index.v1", generated_at=stamp(NOW), entries=[entry])
        (self.root / "current.json").write_bytes(canonical_json_bytes(index))
        return target, index

    def current(self, now=NOW):
        return self.reader.current("AAPL", "1d", 250, now=now)

    def test_unconfigured_and_missing_are_explicit_without_writes(self):
        self.assertEqual(NavigatorReferenceReader().current("AAPL", "1d", 250)["status"], "NOT_CONFIGURED")
        self.assertEqual(self.current()["status"], "UNAVAILABLE")
        self.assertEqual(list(self.root.iterdir()), [self.root / "snapshots"])

    def test_valid_snapshot_integrity_and_expiry_not_retrieval_clock(self):
        target, _ = self.publish()
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        value = self.current()
        self.assertEqual(value["status"], "READY")
        self.assertEqual(value["snapshot"]["snapshot_id"], target.stem)
        expired = self.current(NOW + timedelta(hours=21))
        self.assertEqual(expired["status"], "STALE")
        self.assertEqual(expired["snapshot"], value["snapshot"])
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_provider_failure_retains_snapshot_after_reader_restart(self):
        self.publish(status="STALE")
        result = self.current()
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["snapshot"]["symbol"], "AAPL")

    def test_hash_tamper_keeps_only_previously_verified_snapshot(self):
        target, _ = self.publish()
        prior = self.current()["snapshot"]
        target.write_bytes(b'{"secret":"private diagnostic"}')
        result = self.current()
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["snapshot"], prior)
        self.assertNotIn("private diagnostic", json.dumps(result))
        self.assertEqual(NavigatorReferenceReader(self.root).current("AAPL", "1d", 250, now=NOW)["status"], "UNAVAILABLE")

    def test_selected_pair_and_symbol_do_not_borrow_other_data(self):
        self.publish()
        self.current()
        for symbol, timeframe, period in (("SPY", "1d", 250), ("AAPL", "1h", 250), ("AAPL", "1d", 20)):
            with self.subTest(symbol=symbol, timeframe=timeframe, period=period):
                result = self.reader.current(symbol, timeframe, period, now=NOW)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertIsNone(result["snapshot"])

    def test_malformed_snapshots_rejected_even_with_matching_hash(self):
        variants = [dict(symbol="SPY"), dict(provider="synthetic"), dict(adjustment="unknown"),
                    dict(bar_policy="forming"), dict(expected_bar_at=1), dict(ma_period=True),
                    dict(captured_at=stamp(NOW + timedelta(minutes=1))), dict(valid_until=stamp(NOW)),
                    dict(valid_until=stamp(NOW + timedelta(days=90))), dict(calendar_id="../private"),
                    dict(calendar_id="abc"), dict(provider_fetched_at="2020-01-01T00:00:00Z")]
        for update in variants:
            with self.subTest(update=update):
                self.reader = NavigatorReferenceReader(self.root)
                self.publish({**snapshot(), **update})
                self.assertEqual(self.current()["status"], "UNAVAILABLE")
        value = snapshot()
        value["market"]["points"][-1]["h"] = 0.01
        self.publish(value)
        self.assertEqual(self.current()["status"], "UNAVAILABLE")

    def test_snapshot_symlink_and_traversal_descriptors_rejected(self):
        target, index = self.publish()
        alternate = self.root / "source.json"
        target.rename(alternate)
        target.symlink_to(alternate)
        self.assertEqual(self.current()["status"], "UNAVAILABLE")
        index["entries"][0]["snapshot"]["path"] = "../source.json"
        (self.root / "current.json").write_bytes(canonical_json_bytes(index))
        self.assertEqual(self.current()["status"], "UNAVAILABLE")

    def test_duplicate_index_identity_and_nonstandard_json_rejected(self):
        _, index = self.publish()
        index["entries"].append(deepcopy(index["entries"][0]))
        (self.root / "current.json").write_bytes(canonical_json_bytes(index))
        self.assertEqual(self.current()["status"], "UNAVAILABLE")
        (self.root / "current.json").write_bytes(b'{"schema_version":1,"schema_version":2}')
        self.assertEqual(self.current()["status"], "UNAVAILABLE")

    def test_rollback_and_racing_pointer_never_presented_as_current(self):
        self.publish()
        prior = self.current()["snapshot"]
        older = snapshot()
        older["captured_at"] = older["provider_fetched_at"] = stamp(NOW - timedelta(minutes=1))
        self.publish(older)
        self.assertEqual(self.current()["snapshot"], prior)
        self.assertEqual(self.current()["status"], "STALE")
        self.reader = NavigatorReferenceReader(self.root)
        target, index = self.publish()
        from blackpod_build_week.navigator_reference_reader import _read_regular
        reads = 0
        def read(path, limit):
            nonlocal reads
            if path.name == "current.json":
                reads += 1
                if reads == 2:
                    return b"{}"
            return _read_regular(path, limit)
        with patch("blackpod_build_week.navigator_reference_reader._read_regular", side_effect=read):
            self.assertEqual(self.current()["status"], "UNAVAILABLE")


class ReferenceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.reader = CabinReader()
        self.reader._publications["a" * 64] = Publication("a" * 64, "mission-test", stamp(NOW), {
            "presentation/navigator_market.json": b'{"symbol":"AAPL"}',
            "mission_snapshot.json": b'{"artifacts":[]}',
        })
        self.server = CabinHTTPServer(self.reader, Path(self.temp.name).resolve(), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)
        self.route = "/live/navigator/reference/" + "a" * 64 + "/AAPL/1d/250"

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

    def test_opt_in_read_only_and_publication_bound(self):
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["status"], "NOT_CONFIGURED")
        for path in (self.route.replace("AAPL", "MSFT"), self.route.replace("a" * 64, "b" * 64),
                     self.route.replace("/1d/", "/1s/"), self.route.replace("/250", "/999"), self.route + "?url=private"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request(method="POST")[0], 405)
        self.assertEqual(self.request(headers={"Origin": "https://bad.invalid"})[0], 403)
        self.assertEqual(self.request(headers={"Host": "bad.invalid"})[0], 403)
