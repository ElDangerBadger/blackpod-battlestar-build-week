"""Read-only Sentry transport tests; no scanner, broker, or data providers."""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch

from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader, main
from blackpod_build_week.sentry_reader import (
    MAX_ARCHIVE_BYTES, MAX_ROW_BYTES, MAX_ROWS, SentryReader,
)


def snapshot(event_id="event-one", observed_at="2026-07-15T12:00:00Z", **updates):
    value = {
        "schema_version": "microcap_sentry.snapshot.v1", "event_id": event_id,
        "observed_at": observed_at, "symbol": "TEST", "classification": "WATCH",
        "eligibility": {"eligible": True, "reasons": [], "warnings": [], "missing_fields": []},
        "features": {}, "powder_keg": {"total_score": 25}, "ignition": {"total_score": 15},
        "reasons": ["Synthetic transport test only."], "observation_only": True,
        "order_submission_enabled": False,
    }
    value.update(updates)
    return value


def jsonl(*records):
    return b"".join(json.dumps(record, allow_nan=True).encode() + b"\n" for record in records)


class SentryReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "observations.jsonl"
        self.archive.write_bytes(jsonl(snapshot()))
        self.validator = Mock()

    def reader(self, **overrides):
        config = {"archive": self.archive, "source_kind": "research", "source_label": "Synthetic test archive",
                  "canonical_root": self.root / "canonical", "validator": self.validator}
        config.update(overrides)
        return SentryReader(**config)

    def assertUnavailable(self, feed):
        self.assertEqual(feed["status"], "UNAVAILABLE")
        self.assertIsNone(feed["source"])
        self.assertEqual(feed["observations"], [])
        self.assertNotIn(str(self.root), json.dumps(feed))

    def test_default_is_unconfigured_without_reading_any_source(self):
        with patch("blackpod_build_week.sentry_reader._read_regular") as read:
            feed = SentryReader().current()
        read.assert_not_called()
        self.assertEqual(feed["status"], "NOT_CONFIGURED")
        self.assertIsNone(feed["source"])
        self.assertEqual(feed["observations"], [])
        self.assertEqual(set(feed), {"schema_version", "status", "checked_at", "message", "source", "observations"})

    def test_explicit_complete_configuration_required(self):
        for config in ({"archive": self.archive}, {"source_kind": "research"}, {"source_label": "Archive"},
                       {"canonical_root": self.root}, {"archive": self.archive, "source_kind": "research", "source_label": "Archive"}):
            with self.subTest(config=list(config)), self.assertRaisesRegex(ValueError, "together"):
                SentryReader(**config)
        for override in ({"source_kind": "live"}, {"source_label": ""}, {"source_label": "Private\npath"},
                         {"source_label": str(self.root)}, {"source_label": "x" * 121},
                         {"archive": self.root / "../private.jsonl" / "..name.jsonl"},
                         {"archive": self.root / "bad\\file.jsonl"}):
            with self.subTest(override=list(override)), self.assertRaises(ValueError):
                self.reader(**override)

    def test_ready_preserves_raw_records_deduplicates_and_sorts_deterministically(self):
        early = snapshot("earlier")
        later = snapshot("later", "2026-07-15T13:00:00+00:00", powder_keg={"total_score": 25, "contributions": [
            {"factor": "raw_factor", "contribution": 2.5, "reason": "Unchanged reason."}]})
        tied = snapshot("tied", "2026-07-15T13:00:00Z")
        self.archive.write_bytes(jsonl(early, tied, early, later))
        original = self.archive.read_bytes()
        self.validator.side_effect = lambda record: record.update({"not_canonical_output": True})
        feed = self.reader().current()
        self.assertEqual(feed["status"], "READY")
        self.assertEqual(feed["observations"], [later, tied, early])
        self.assertNotIn("configured_weight", feed["observations"][0]["powder_keg"]["contributions"][0])
        self.assertEqual(feed["source"], {
            "label": "Synthetic test archive", "kind": "RESEARCH", "file_name": "observations.jsonl",
            "sha256": hashlib.sha256(original).hexdigest(), "byte_size": len(original),
            "latest_observed_at": "2026-07-15T13:00:00Z", "raw_count": 4, "duplicate_count": 1,
        })
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertEqual(self.validator.call_count, 4)

    def test_conflicting_event_identity_fails_entire_capture(self):
        self.archive.write_bytes(jsonl(snapshot(), snapshot(classification="IGNITION")))
        self.assertUnavailable(self.reader().current())

    def test_empty_archive_is_valid_and_does_not_invent_observations(self):
        self.archive.write_bytes(b"")
        feed = self.reader().current()
        self.assertEqual(feed["status"], "READY")
        self.assertEqual(feed["source"]["raw_count"], 0)
        self.assertIsNone(feed["source"]["latest_observed_at"])
        self.assertEqual(feed["observations"], [])

    def test_missing_or_unsafe_source_fails_closed(self):
        self.archive.unlink()
        self.assertUnavailable(self.reader().current())
        self.archive.mkdir()
        self.assertUnavailable(self.reader().current())
        self.archive.rmdir()
        actual = self.root / "actual.jsonl"
        actual.write_bytes(jsonl(snapshot()))
        self.archive.symlink_to(actual)
        self.assertUnavailable(self.reader().current())
        self.archive.unlink()
        os.mkfifo(self.archive)
        self.assertUnavailable(self.reader().current())

    def test_symlink_parent_rejected(self):
        indirect = self.root / "indirect"
        indirect.symlink_to(self.root, target_is_directory=True)
        self.assertUnavailable(self.reader(archive=indirect / self.archive.name).current())

    def test_source_replacement_during_read_fails_closed(self):
        real_read = os.read
        changed = False
        def mutate(descriptor, count):
            nonlocal changed
            chunk = real_read(descriptor, count)
            if not changed:
                changed = True
                replacement = self.root / "replacement.jsonl"
                replacement.write_bytes(jsonl(snapshot()))
                replacement.replace(self.archive)
            return chunk
        with patch("blackpod_build_week.sentry_reader.os.read", side_effect=mutate):
            self.assertUnavailable(self.reader().current())

    def test_failed_validation_never_reuses_previous_ready_data(self):
        reader = self.reader()
        self.assertEqual(reader.current()["status"], "READY")
        self.validator.side_effect = ValueError("private source path or raw diagnostic")
        feed = reader.current()
        self.assertUnavailable(feed)
        self.assertNotIn("private source", json.dumps(feed))

    def test_strict_json_duplicate_keys_nonfinite_unsafe_numbers_and_types(self):
        invalid = [b"[]\n", b"\xff\n", b"\n", b'{"event_id":"one","event_id":"two"}\n',
                   jsonl(snapshot(extra=float("nan"))), jsonl(snapshot(extra=float("inf"))),
                   jsonl(snapshot(extra=2**53)), jsonl(snapshot(extra="\ud800")),
                   jsonl(snapshot(extra="x" * 4001)), jsonl(snapshot(extra=[0] * 1001)),
                   jsonl(snapshot(event_id="x" * 257)), jsonl(snapshot(symbol="../TEST")),
                   jsonl(snapshot(schema_version="microcap_sentry.snapshot.v2"))]
        nested = "leaf"
        for _ in range(35):
            nested = [nested]
        invalid.append(jsonl(snapshot(extra=nested)))
        for body in invalid:
            with self.subTest(length=len(body)):
                self.archive.write_bytes(body)
                self.assertUnavailable(self.reader().current())

    def test_explicit_safety_flags_required_not_defaults_or_truthiness(self):
        for key in ("observation_only", "order_submission_enabled"):
            for value in (None, "true", 1, 0, [], {}):
                record = snapshot()
                record[key] = value
                self.archive.write_bytes(jsonl(record))
                self.assertUnavailable(self.reader().current())
            record = snapshot()
            del record[key]
            self.archive.write_bytes(jsonl(record))
            self.assertUnavailable(self.reader().current())

    def test_row_count_size_and_archive_size_bounds(self):
        for data in (b"x" * (MAX_ARCHIVE_BYTES + 1), b"x" * (MAX_ROW_BYTES + 1),
                     jsonl(*([snapshot()] * (MAX_ROWS + 1)))):
            self.archive.write_bytes(data)
            self.assertUnavailable(self.reader().current())

    def test_timestamp_validation(self):
        for value in (None, [], "not-a-time", "2026-07-15T12:00:00", "9999-07-15T12:00:00Z"):
            self.archive.write_bytes(jsonl(snapshot(observed_at=value)))
            self.assertUnavailable(self.reader().current())

    def test_offset_observed_time_preserved_with_utc_source_summary(self):
        record = snapshot(observed_at="2026-07-15T09:00:00-05:00")
        self.archive.write_bytes(jsonl(record))
        feed = self.reader().current()
        self.assertEqual(feed["status"], "READY")
        self.assertEqual(feed["observations"][0]["observed_at"], record["observed_at"])
        self.assertEqual(feed["source"]["latest_observed_at"], "2026-07-15T14:00:00Z")

    def test_loads_only_explicit_pure_canonical_module_without_bytecode(self):
        canonical = self.root / "canonical"
        package = canonical / "microcap_sentry"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("raise RuntimeError('package initializer must not run')\n")
        model = package / "models.py"
        model.write_text('''from dataclasses import dataclass
SNAPSHOT_SCHEMA_VERSION = "microcap_sentry.snapshot.v1"
@dataclass
class SentrySnapshot:
    event_id: str
    @classmethod
    def from_dict(cls, value):
        if value.get("classification") != "WATCH":
            raise ValueError("canonical contract rejected the snapshot")
        return cls(value["event_id"])
''')
        reader = self.reader(validator=None)
        self.assertEqual(reader.current()["status"], "READY")
        self.assertFalse((package / "__pycache__").exists())
        self.archive.write_bytes(jsonl(snapshot(classification="WRONG")))
        self.assertUnavailable(reader.current())
        model.write_text("import subprocess\n")
        self.assertUnavailable(self.reader(validator=None).current())

    @unittest.skipUnless(os.environ.get("BATTLESTAR_PATH"), "explicit canonical checkout required for compatibility check")
    def test_real_canonical_contract_compatibility(self):
        canonical = Path(os.environ["BATTLESTAR_PATH"])
        reader = self.reader(canonical_root=canonical, validator=None)
        self.assertEqual(reader.current()["status"], "READY")
        for update in ({"classification": "WRONG"}, {"powder_keg": {"total_score": 101}},
                       {"features": {"new_session_high": "yes"}}):
            self.archive.write_bytes(jsonl(snapshot(**update)))
            self.assertUnavailable(reader.current())


class SentryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "events.jsonl"
        self.archive.write_bytes(jsonl(snapshot()))
        self.sentry = SentryReader(self.archive, "research", "Synthetic tests", self.root, validator=lambda record: None)
        self.mission = CabinReader()
        self.server = CabinHTTPServer(self.mission, self.root, 0, sentry_reader=self.sentry)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path="/live/sentry/current.json", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_independent_read_only_no_store_feed_without_mission(self):
        before = self.archive.read_bytes()
        with patch.object(self.mission, "current") as mission_read:
            status, headers, body = self.request()
        mission_read.assert_not_called()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertEqual(json.loads(body)["status"], "READY")
        self.assertNotIn(str(self.root).encode(), body)
        self.assertEqual(self.archive.read_bytes(), before)
        self.assertEqual(self.mission._publications, {})

    def test_default_server_returns_not_configured(self):
        self.server.sentry_reader = SentryReader()
        status, _, body = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "NOT_CONFIGURED")

    def test_origin_host_method_query_and_path_guards(self):
        with patch.object(self.sentry, "current") as read:
            for headers in ({"Origin": "https://evil.invalid"}, {"Host": "evil.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
                self.assertEqual(self.request(headers=headers)[0], 403)
            for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
                self.assertEqual(self.request(method=method)[0], 405)
            for path in ("/live/sentry/current.json?path=/private", "/live/sentry/../current.json", "/live/sentry/%2e%2e/current.json",
                         "/live/sentry/events.jsonl", "/live/sentry/current.json/anything"):
                self.assertEqual(self.request(path=path)[0], 404)
        read.assert_not_called()

    def test_head_has_no_payload(self):
        status, _, body = self.request(method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")


class SentryCLITests(unittest.TestCase):
    def test_partial_config_fails_before_server_creation(self):
        error = io.StringIO()
        with patch("blackpod_build_week.cabin_reader.CabinHTTPServer") as server, redirect_stderr(error):
            with self.assertRaises(SystemExit) as caught:
                main(["--sentry-archive", "/private/not-a-real-file.jsonl"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("together", error.getvalue())
        server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
