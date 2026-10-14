"""Offline presentation boundary tests; synthetic views, no market acquisition."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from blackpod_build_week import shadow_experiment_reader as module
from blackpod_build_week.cabin_reader import CabinHTTPServer, CabinReader


class ShadowExperimentReaderTests(unittest.TestCase):
    def test_unconfigured_never_reads_or_creates_directories(self):
        with patch.object(module, "_read_experiment_view") as read, patch.object(Path, "mkdir", side_effect=AssertionError("write")):
            result = module.ShadowExperimentReader().current()
        read.assert_not_called()
        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertIsNone(result["experiment"])

    def test_reads_one_explicit_root_and_does_not_rewrite_projection(self):
        root = Path("/explicit/research-root")
        view = {"schema_version": "synthetic.test.v1", "preserved": ["missing outcome", 0, None]}
        with patch.object(module, "_read_experiment_view", return_value=view) as read:
            result = module.ShadowExperimentReader(root).current()
        read.assert_called_once_with(root)
        self.assertEqual(result["status"], "READY")
        self.assertIs(result["experiment"], view)
        self.assertNotIn(str(root), json.dumps(result))

    def test_validation_failures_are_generic_and_do_not_expose_paths(self):
        for error in (OSError("/private/key"), ValueError("/private/key"), RuntimeError("/private/key"), RecursionError("/private/key")):
            with self.subTest(error=type(error).__name__), patch.object(module, "_read_experiment_view", side_effect=error):
                result = module.ShadowExperimentReader(Path("/private/source")).current()
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertIsNone(result["experiment"])
            self.assertNotIn("/private", json.dumps(result))

    def test_oversized_or_unsafe_projection_fails_closed(self):
        for value in ({"items": [0] * 10001}, {"value": float("nan")}, {"text": "x" * (module.MAX_FEED_BYTES + 1)}):
            with self.subTest(value=str(value)[:40]), patch.object(module, "_read_experiment_view", return_value=value):
                self.assertEqual(module.ShadowExperimentReader(Path("/source")).current()["status"], "UNAVAILABLE")

    def test_non_normalized_root_rejected(self):
        for root in (Path("../other"), Path("/source/../other"), Path("/source\nother")):
            with self.subTest(root=root), self.assertRaises(ValueError):
                module.ShadowExperimentReader(root)

    def test_actual_core_fixture_is_verified_without_source_mutations_or_provider_calls(self):
        from test_shadow_experiment import fixture
        from blackpod_build_week.shadow_experiment import freeze_experiment
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / "journal"
            protocol, evidence = fixture()
            freeze_experiment(root, protocol, evidence)
            def state():
                return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in root.rglob("*") if path.is_file()}
            before = state()
            with patch.object(Path, "mkdir", side_effect=AssertionError("write")), patch("socket.socket.connect", side_effect=AssertionError("network")):
                result = module.ShadowExperimentReader(root).current()
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["experiment"]["summary"]["recorded_prediction_count"], 0)
            self.assertIsNone(result["experiment"]["summary"]["net_return"])
            self.assertEqual(before, state())
            alias = Path(temp) / "alias"
            alias.symlink_to(root, target_is_directory=True)
            self.assertEqual(module.ShadowExperimentReader(alias).current()["status"], "UNAVAILABLE")


class ShadowExperimentHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "index.html").write_text("<h1>Cabin</h1>", encoding="utf-8")
        self.server = CabinHTTPServer(CabinReader(), self.root, 0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response, response.read()

    def test_fixed_feed_and_standalone_route_need_no_mission(self):
        response, raw = self.request("/live/shadow-experiment/current.json")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(json.loads(raw)["status"], "NOT_CONFIGURED")
        response, raw = self.request("/?view=research")
        self.assertEqual(response.status, 200)
        self.assertIn(b"Cabin", raw)

    def test_mutations_source_selection_queries_and_arbitrary_paths_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(self.request("/live/shadow-experiment/current.json", method)[0].status, 405)
        for path in ("/live/shadow-experiment/current.json?root=/private", "/live/shadow-experiment/anything", "/?view=research&root=/private"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0].status, 404)

    def test_cross_origin_request_rejected(self):
        response, _ = self.request("/live/shadow-experiment/current.json", headers={"Origin": "https://example.invalid"})
        self.assertEqual(response.status, 403)
