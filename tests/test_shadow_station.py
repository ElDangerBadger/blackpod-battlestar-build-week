"""Offline standalone station boundaries; no launchd, providers, or real journals."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from email.parser import BytesHeaderParser
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import shadow_station as module
from blackpod_build_week.decision_journal_store import JournalStoreError


def config_fixture(base):
    repo = base / "repository"
    paths = {"repo_root": repo, "python_executable": repo / ".venv/bin/python3.11",
             "experiment_root": repo / "output/experiment/journal",
             "runtime_root": repo / "output/runtime",
             "historical_root": repo / "output/history", "ui_root": repo / "ui/dist",
             "credentials_file": base / "private/credentials.yaml",
             "station_root": repo / "output/station"}
    for name, path in paths.items():
        if name in {"python_executable", "credentials_file"}:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture, not credentials")
            path.chmod(0o700 if name == "python_executable" else 0o600)
        else:
            path.mkdir(parents=True, exist_ok=True)
    return {"schema_version": "blackpod.shadow_station.v1",
            **{name: str(path) for name, path in paths.items()},
            "credential_format": "GALACTICA_YAML",
            "experiment_id": "prospective-reversal-pilot-2026-10-14",
            "protocol_sha256": "b965ec0e8e1ad2cd57e356b8ecdcdd1fb1b352f54a7bc041f5a7cf3ddf0a111c"}


class StationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = config_fixture(self.root)

    def validate(self, document):
        return module.validate_config(document, expected_repo=Path(self.config["repo_root"]))

    def test_exact_frozen_config_roundtrip_does_not_read_credentials(self):
        before = Path(self.config["credentials_file"]).read_bytes()
        self.assertEqual(self.validate(deepcopy(self.config)), self.config)
        self.assertEqual(Path(self.config["credentials_file"]).read_bytes(), before)

    def test_unknown_missing_and_versioned_fields_fail_closed(self):
        cases = [{**self.config, "enable_auto_trading": True},
                 {**self.config, "schema_version": "blackpod.shadow_station.v2"},
                 {**self.config, "experiment_id": "another-trial"},
                 {**self.config, "protocol_sha256": "0" * 64},
                 {**self.config, "credential_format": "LIVE_ENV"},
                 {**self.config, "port": 1234}]
        for key in self.config:
            case = dict(self.config)
            del case[key]
            cases.append(case)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.validate(case)

    def test_paths_cannot_select_another_repo_runtime_or_code(self):
        mutations = [("repo_root", str(self.root / "another-repo")),
                     ("python_executable", "/usr/bin/python3"),
                     ("ui_root", str(self.root / "unrelated-ui")),
                     ("station_root", str(self.root / "outside-station")),
                     ("station_root", self.config["experiment_root"]),
                     ("station_root", str(Path(self.config["runtime_root"]) / "station")),
                     ("station_root", str(Path(self.config["historical_root"]) / "station")),
                     ("experiment_root", self.config["runtime_root"]),
                     ("historical_root", self.config["experiment_root"]),
                     ("credentials_file", str(Path(self.config["station_root"]) / "keys.yaml"))]
        for key in ("repo_root", "python_executable", "experiment_root", "runtime_root", "historical_root", "ui_root", "credentials_file", "station_root"):
            mutations.extend([(key, "relative/path"), (key, "/unsafe/../elsewhere"), (key, "/unsafe\npath")])
        for key, value in mutations:
            with self.subTest(key=key, value=value), self.assertRaises((ValueError, JournalStoreError)):
                self.validate({**self.config, key: value})

    def test_symlink_root_cannot_hide_overlap(self):
        alias = Path(self.config["repo_root"]) / "output/station-alias"
        alias.symlink_to(self.config["experiment_root"], target_is_directory=True)
        with self.assertRaises((ValueError, JournalStoreError)):
            self.validate({**self.config, "station_root": str(alias)})

    def test_load_config_rejects_wrong_parent_partial_and_duplicate_json(self):
        # expected_repo is intentionally not overridable through the document.
        path = Path(self.config["station_root"]) / "config.json"
        for raw in (b'{"schema_version":', b'{"schema_version":"a","schema_version":"b"}', b'[]'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    module.load_config(path)
        path.write_text(json.dumps(self.config))
        alias = path.with_name("alias.json")
        alias.symlink_to(path)
        with self.assertRaises(ValueError):
            module.load_config(alias)

    def test_load_config_requires_its_own_station_directory(self):
        path = Path(self.config["station_root"]) / "config.json"
        path.write_text(json.dumps(self.config))
        validator = module.validate_config
        with patch.object(module, "validate_config", side_effect=lambda document: validator(
                document, expected_repo=Path(self.config["repo_root"]))):
            self.assertEqual(module.load_config(path), self.config)
            unrelated = self.root / "config.json"
            unrelated.write_text(json.dumps(self.config))
            with self.assertRaises(ValueError):
                module.load_config(unrelated)


class StationStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "state.json"

    def test_absent_state_is_empty_without_creating_directories(self):
        self.assertEqual(module.read_state(self.path), {})
        self.assertFalse(self.path.exists())

    def test_atomic_replacement_roundtrip_and_private_permissions(self):
        original = {"heartbeat_at": "2026-10-14T22:00:00Z", "generation": 1}
        replacement = {**original, "generation": 2}
        module.atomic_state(self.path, original)
        self.assertEqual(module.read_state(self.path), original)
        module.atomic_state(self.path, replacement)
        self.assertEqual(module.read_state(self.path), replacement)
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_interrupted_publish_preserves_last_complete_state(self):
        original = {"generation": 1}
        module.atomic_state(self.path, original)
        before = self.path.read_bytes()
        with patch.object(module.os, "replace", side_effect=OSError("synthetic interrupted publish")):
            with self.assertRaises(OSError):
                module.atomic_state(self.path, {"generation": 2})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(module.read_state(self.path), original)
        module.atomic_state(self.path, {"generation": 3})
        self.assertEqual(module.read_state(self.path), {"generation": 3})

    def test_symlink_cannot_read_or_overwrite_another_state(self):
        target = self.root / "unrelated.json"
        target.write_text('{"preserve":true}')
        self.path.symlink_to(target)
        for operation in (lambda: module.read_state(self.path),
                          lambda: module.atomic_state(self.path, {"overwrite": True})):
            with self.subTest(operation=operation), self.assertRaises((ValueError, OSError, RuntimeError)):
                operation()
        self.assertEqual(target.read_text(), '{"preserve":true}')
        self.assertTrue(self.path.is_symlink())

    def test_partial_duplicate_or_non_object_json_is_rejected(self):
        for raw in (b'{"heartbeat_at":', b'{"x":1,"x":2}', b'[1,2]', b'{"x":NaN}'):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    module.read_state(self.path)

    def test_single_service_lock_recovers_after_normal_or_failed_owner(self):
        with module.service_lock(self.root):
            with self.assertRaises((ValueError, OSError, RuntimeError)):
                with module.service_lock(self.root):
                    self.fail("a second station obtained the same service lock")
        with self.assertRaisesRegex(RuntimeError, "synthetic owner failure"):
            with module.service_lock(self.root):
                raise RuntimeError("synthetic owner failure")
        with module.service_lock(self.root):
            pass

    def test_service_lock_recovers_after_process_dies_without_cleanup(self):
        child = subprocess.run([sys.executable, "-c", """from pathlib import Path
import os, sys
from blackpod_build_week.shadow_station import service_lock
with service_lock(Path(sys.argv[1])):
    os._exit(0)
""", str(self.root)], capture_output=True, timeout=10, check=False)
        self.assertEqual(child.returncode, 0, child.stderr.decode(errors="replace"))
        with module.service_lock(self.root):
            pass

    def test_operational_logs_reject_symlinks_without_touching_evidence(self):
        target = self.root / "immutable-evidence.txt"
        target.write_text("preserve original evidence")
        before = target.read_bytes()
        for name in ("service.log", "service.log.1", "service.log.2"):
            alias = self.root / name
            alias.symlink_to(target)
            try:
                with self.subTest(name=name), self.assertRaises((ValueError, OSError, RuntimeError)):
                    handler = module._log_handler(self.root)
                    handler.close()
                self.assertEqual(target.read_bytes(), before)
                self.assertTrue(alias.is_symlink())
            finally:
                alias.unlink()

    def test_operational_logs_reject_hardlinks_without_touching_evidence(self):
        import os
        target = self.root / "immutable-evidence.txt"
        target.write_text("preserve original evidence")
        before = target.read_bytes()
        for name in ("service.log", "service.log.1", "service.log.2"):
            alias = self.root / name
            os.link(target, alias)
            try:
                with self.subTest(name=name), self.assertRaises((ValueError, OSError, RuntimeError)):
                    handler = module._log_handler(self.root)
                    handler.close()
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(target.stat().st_ino, alias.stat().st_ino)
            finally:
                alias.unlink()


class StationPublicStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = config_fixture(Path(self.temp.name).resolve())

    def test_public_projection_retains_counts_and_discards_private_fields(self):
        now = datetime(2026, 10, 14, 22, 1, tzinfo=timezone.utc)
        state = {"schema_version": "blackpod.shadow_station_state.v1",
                 "heartbeat_at": "2026-10-14T22:00:59Z", "serving": True,
                 "auto_trading": {"state": "OFF", "requested_entries_enabled": False,
                                  "entries_enabled": False, "worker_active": False,
                                  "auto_restart_enabled": False, "capital_transfers_permitted": False,
                                  "checked_at": "2026-10-14T22:00:59Z"},
                 "experiment": {"id": self.config["experiment_id"],
                                "recorded_prediction_count": 2, "observed_outcome_count": 0,
                                "conclusion": "PENDING", "latest_captured_at": "2026-10-14T22:00:00Z"},
                 "collector": {"schedule": "18:30 America/Los_Angeles", "reason": "WAITING",
                               "next_attempt_at": "2026-10-15T01:30:00Z", "attempt_state": {},
                               "last_result": {"raw_error": "private-secret /private/source", "stdout": "private-secret"},
                               "review_required": False},
                 "credentials_file": self.config["credentials_file"], "API_SECRET": "private-secret",
                 "raw_error": "private-secret /private/source"}
        before = deepcopy(state)
        result = module.public_status(self.config, state, now=now)
        encoded = json.dumps(result)
        self.assertNotIn("private-secret", encoded)
        self.assertNotIn("/private/source", encoded)
        for key in ("repo_root", "experiment_root", "runtime_root", "historical_root", "ui_root", "credentials_file", "station_root"):
            self.assertNotIn(self.config[key], encoded)
        self.assertEqual(result["experiment"]["recorded_prediction_count"], 2)
        self.assertEqual(result["experiment"]["observed_outcome_count"], 0)
        self.assertEqual(result["auto_trading"]["state"], "OFF")
        self.assertEqual(state, before)

    def test_missing_off_verification_never_claims_off(self):
        now = datetime(2026, 10, 14, 22, 1, tzinfo=timezone.utc)
        for state in ({}, {"auto_trading": {"state": "ON"}}, {"auto_trading": None}):
            with self.subTest(state=state):
                result = module.public_status(self.config, state, now=now)
                self.assertFalse(result.get("auto_trading_off_verified", False))
                displayed = result.get("auto_trading")
                if isinstance(displayed, dict):
                    self.assertNotEqual(displayed.get("state"), "OFF")
                else:
                    self.assertNotEqual(displayed, "OFF")

    def test_off_requires_fresh_heartbeat_and_every_guard_explicitly_disabled(self):
        now = datetime(2026, 10, 14, 22, 1, tzinfo=timezone.utc)
        guards = ("requested_entries_enabled", "entries_enabled", "worker_active",
                  "auto_restart_enabled", "capital_transfers_permitted")
        state = {"serving": True, "heartbeat_at": "2026-10-14T22:00:59Z",
                 "auto_trading": {"state": "OFF", "checked_at": "2026-10-14T22:00:59Z",
                                  **{key: False for key in guards}}}
        fresh = module.public_status(self.config, state, now=now)
        self.assertEqual(fresh["auto_trading"]["state"], "OFF")
        variants = []
        for field in guards:
            for replacement in (True, None, 0, "false"):
                variant = deepcopy(state)
                variant["auto_trading"][field] = replacement
                variants.append(variant)
            variant = deepcopy(state)
            del variant["auto_trading"][field]
            variants.append(variant)
        for heartbeat in ("2026-10-14T21:58:59Z", "2026-10-14T22:01:01Z", None, "not-a-clock"):
            variants.append({**state, "heartbeat_at": heartbeat})
        for checked_at in ("2026-10-14T21:58:59Z", "2026-10-14T22:01:01Z", None, "not-a-clock"):
            variant = deepcopy(state)
            variant["auto_trading"]["checked_at"] = checked_at
            variants.append(variant)
        variant = deepcopy(state)
        del variant["auto_trading"]["checked_at"]
        variants.append(variant)
        for variant in variants:
            with self.subTest(variant=variant):
                result = module.public_status(self.config, variant, now=now)
                self.assertNotEqual(result["auto_trading"]["state"], "OFF")


class StationObservationRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = config_fixture(Path(self.temp.name).resolve())
        self.now = datetime(2026, 10, 14, 22, 1, tzinfo=timezone.utc)
        self.enterContext(patch.object(module, "utc_now", return_value=self.now))
        self.view = {"latest_captured_at": "2026-10-14T22:00:59Z",
                     "summary": {"recorded_prediction_count": 2, "observed_outcome_count": 1,
                                 "conclusion": "PENDING"}}
        self.read_view = self.enterContext(patch.object(module, "_pinned_view", return_value=self.view))
        self.off = {"state": "OFF", "requested_entries_enabled": False, "entries_enabled": False,
                    "worker_active": False, "auto_restart_enabled": False, "capital_transfers_permitted": False}
        self.runtime = self.enterContext(patch("blackpod_build_week.auto_trading_runtime.runtime_status", return_value=self.off))
        self.state = {"heartbeat_at": "2026-10-14T22:01:00Z", "serving": True,
                      "experiment": {"recorded_prediction_count": 0, "observed_outcome_count": 0},
                      "auto_trading": {**self.off, "checked_at": "2026-10-14T21:58:00Z"},
                      "collector": {"reason": "VERIFIED"}}

    def test_post_collection_refresh_updates_counts_and_actual_off_sample_time(self):
        module.refresh_observations(self.config, self.state)
        self.assertEqual(self.state["experiment"]["recorded_prediction_count"], 2)
        self.assertEqual(self.state["experiment"]["observed_outcome_count"], 1)
        self.assertEqual(self.state["experiment"]["latest_captured_at"], "2026-10-14T22:00:59Z")
        self.assertEqual(self.state["auto_trading"]["state"], "OFF")
        self.assertEqual(self.state["auto_trading"]["checked_at"], "2026-10-14T22:01:00Z")
        self.runtime.assert_called_once_with(Path(self.config["runtime_root"]))

    def test_on_post_collection_cannot_inherit_preflight_off_verification(self):
        self.runtime.return_value = {**self.off, "state": "ON", "entries_enabled": True}
        module.refresh_observations(self.config, self.state)
        self.assertNotEqual(self.state["auto_trading"].get("state"), "OFF")
        result = module.public_status(self.config, self.state, now=self.now)
        self.assertNotEqual(result["auto_trading"]["state"], "OFF")
        self.assertEqual(self.state["experiment"]["recorded_prediction_count"], 2)

    def test_failed_post_collection_sample_clears_previous_off_claim(self):
        self.runtime.side_effect = ValueError("private-secret /private/source")
        module.refresh_observations(self.config, self.state)
        self.assertNotEqual(self.state["auto_trading"].get("state"), "OFF")
        result = module.public_status(self.config, self.state, now=self.now)
        self.assertNotEqual(result["auto_trading"]["state"], "OFF")
        self.assertNotIn("private-secret", json.dumps(result))

    def test_failed_pin_validation_clears_old_experiment_and_blocks_collection(self):
        self.read_view.side_effect = ValueError("private-secret /private/source")
        module.refresh_observations(self.config, self.state)
        self.assertEqual(self.state["experiment"], {})
        self.assertEqual(self.state["collector"]["reason"], "DATA_OR_OFF_GATE_BLOCKED")
        # Independent actual runtime evidence may still establish OFF.
        self.runtime.assert_called_once_with(Path(self.config["runtime_root"]))
        self.assertNotIn("private-secret", json.dumps(self.state))


class _LocalHTTPMixin:
    def start(self, server):
        self.server = server
        # Exercise the actual request handler without listening on any port.
        server.server_port = 5183
        server.server_name = "localhost"
        self.addCleanup(server.server_close)

    def request(self, path, method="GET", headers=None):
        class Connection:
            def __init__(self, request):
                self.source = BytesIO(request)
                self.output = bytearray()
            def makefile(self, *args, **kwargs):
                return self.source
            def sendall(self, data):
                self.output.extend(data)
        fields = {"Host": f"127.0.0.1:{self.server.server_port}", "Connection": "close", **(headers or {})}
        request = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{name}: {value}\r\n" for name, value in fields.items()) + "\r\n"
        connection = Connection(request.encode("ascii"))
        self.server.RequestHandlerClass(connection, ("127.0.0.1", 55000), self.server)
        head, _, body = bytes(connection.output).partition(b"\r\n\r\n")
        status_line, _, raw_headers = head.partition(b"\r\n")
        return int(status_line.split()[1]), dict(BytesHeaderParser().parsebytes(raw_headers)), body


class StationHTTPTests(_LocalHTTPMixin, unittest.TestCase):
    def setUp(self):
        self.start(module.LocalStatusServer(("127.0.0.1", 0), lambda: {
            "schema_version": "synthetic.station.status.v1", "service": "RUNNING",
            "status": "RUNNING", "auto_trading": {"state": "OFF"},
            "experiment": {"latest_captured_at": None, "recorded_prediction_count": 0,
                           "observed_outcome_count": 0},
            "collector": {"enabled": True, "schedule": "18:30 America/Los_Angeles",
                          "next_attempt_at": None, "last_success_at": None, "reason": "WAITING"}}, bind_and_activate=False))

    def test_fixed_readonly_pages_and_status_json(self):
        for path in ("/", "/status.html"):
            with self.subTest(path=path):
                status, headers, raw = self.request(path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers.get("Content-Type", ""))
                self.assertNotIn(b"<form", raw.lower())
        status, headers, raw = self.request("/status.json")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(json.loads(raw)["auto_trading"]["state"], "OFF")

    def test_control_methods_and_arbitrary_paths_are_unavailable(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"):
            with self.subTest(method=method):
                self.assertEqual(self.request("/status.json", method)[0], 405)
        for path in ("/collect", "/start", "/status.json?collect=true", "/../state.json", "/credentials"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_cross_origin_or_hostile_host_is_rejected(self):
        for headers in ({"Origin": "https://example.invalid"},
                        {"Host": "example.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/status.json", headers=headers)[0], 403)

    def test_head_reports_headers_without_a_response_body(self):
        status, headers, raw = self.request("/status.json", "HEAD")
        self.assertEqual(status, 200)
        self.assertGreater(int(headers["Content-Length"]), 0)
        self.assertEqual(raw, b"")


class StationHistoricalHTTPTests(_LocalHTTPMixin, unittest.TestCase):
    def setUp(self):
        from blackpod_build_week.shadow_historical_dashboard import export_dashboard
        from test_shadow_historical_dashboard import historical_bundle
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        # All evidence is generated from the repository's synthetic fixtures.
        with patch("socket.socket.connect", side_effect=AssertionError("provider forbidden")):
            arguments = historical_bundle(self.root)
            self.history = self.root / "dashboard"
            export_dashboard(arguments.output_root, self.history)
        self.start(module.SnapshotServer(("127.0.0.1", 0), self.history, bind_and_activate=False))

    def test_verified_dashboard_and_original_report_are_served_unchanged(self):
        for path in ("dashboard.html", "report.html", "report.json", "rows.csv", "cohorts.json", "bundle-manifest.json"):
            with self.subTest(path=path):
                status, _, raw = self.request("/" + path)
                self.assertEqual(status, 200)
                self.assertEqual(raw, (self.history / path).read_bytes())

    def test_unlisted_files_traversal_and_mutations_are_denied(self):
        (self.history / "secret.env").write_text("private-secret")
        for path in ("/secret.env", "/../secret.env", "/%2e%2e/secret.env", "/sources/secret.env", "/report.json?root=/private"):
            with self.subTest(path=path):
                status, _, raw = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"private-secret", raw)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"):
            with self.subTest(method=method):
                self.assertEqual(self.request("/dashboard.html", method)[0], 405)

    def test_changed_or_symlinked_snapshot_cannot_be_published_as_original(self):
        original = self.history / "report.html"
        original.write_text("changed evidence")
        self.assertNotEqual(self.request("/report.html")[0], 200)
        original.unlink()
        target = self.root / "outside.html"
        target.write_text("private-secret")
        original.symlink_to(target)
        status, _, raw = self.request("/report.html")
        self.assertNotEqual(status, 200)
        self.assertNotIn(b"private-secret", raw)

    def test_cross_origin_or_hostile_host_is_rejected(self):
        for headers in ({"Origin": "https://example.invalid"},
                        {"Host": "example.invalid"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/dashboard.html", headers=headers)[0], 403)


if __name__ == "__main__":
    unittest.main()
