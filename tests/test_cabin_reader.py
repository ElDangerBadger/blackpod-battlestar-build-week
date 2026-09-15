from __future__ import annotations

import ast
import contextlib
import http.client
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from blackpod_build_week import cabin_reader
from blackpod_build_week.cabin_context import (
    CABIN_CONTEXT_PATH, CaptureTransport, capture_cabin_context,
)
from blackpod_build_week.cabin_reader import (
    CabinHTTPServer, CabinReader, CabinReaderError, MANIFEST_PATH,
    ReadOnlyMissionStore, capture_publication,
)
from blackpod_build_week.contracts import (
    ComponentProvenance, MissionRequest, MissionSnapshot,
    NAVIGATOR_ALLOWED_OPERATIONS, NAVIGATOR_PROHIBITED_OPERATIONS,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_presentation import (
    project_mission_presentation, render_mission_presentation,
)
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.mission_transitions import begin_oracle


OBSERVED_AT = "2026-07-18T20:00:00Z"
MISSION_ID = "mission-cabin-reader-001"


class CabinReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.artifacts = self.base / "artifacts"
        self.store = MissionStore(self.artifacts)
        self.request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-cabin-reader-001", "mission_id": MISSION_ID,
            "run_mode": "LIVE", "symbol": "AAPL", "requested_at": OBSERVED_AT,
            "operator_id": "reader-test", "metadata": {},
        })
        self.initialized = self.store.initialize(
            self.request, mission_id=MISSION_ID, started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        self.root = self.initialized.paths.mission_root
        self.reader = CabinReader(self.artifacts, MISSION_ID)

    def tearDown(self):
        self.temporary.cleanup()

    def file_state(self):
        return {
            path.relative_to(self.artifacts).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.artifacts.rglob("*") if path.is_file()
        }

    def manifest(self, reader=None):
        reader = reader or self.reader
        feed = reader.current()
        self.assertEqual(feed["status"], "READY")
        payload = reader.artifact(feed["publication_id"], MANIFEST_PATH)
        self.assertIsNotNone(payload)
        self.assertEqual(feed["publication_id"], sha256_bytes(payload))
        return feed, json.loads(payload)

    def commit_value(self, update):
        loaded = self.store.load_mission(MISSION_ID)
        value = loaded.snapshot.to_dict()
        revision = loaded.snapshot.revision + 1
        value.update(revision=revision, snapshot_id=f"{MISSION_ID}-r{revision:04d}", previous_snapshot_sha256=loaded.current_snapshot_sha256)
        update(value)
        snapshot = MissionSnapshot.from_mapping(value)
        self.store.commit_snapshot(loaded.paths, snapshot)
        return snapshot

    def commit_outcome(self, outcome):
        """Minimal synthetic contract fixtures; not claimed as executed missions."""
        def update(value):
            value["mission_outcome"] = outcome
            if outcome == "INCOMPLETE":
                value["stages"]["oracle"]["status"] = "RUNNING"
                return
            if outcome == "FAILED":
                value["stages"]["oracle"].update(status="FAILED", error={
                    "code": "ORACLE_UNAVAILABLE", "error_type": "TestFailure",
                    "message": "Unavailable", "resumable": True, "observed_at": OBSERVED_AT,
                })
                return
            for stage, native in (("oracle", "READY"), ("council", "MIXED"), ("governor", "HOLD")):
                value["stages"][stage].update(status="SUCCEEDED", native_state=native, error=None)
            if outcome == "HELD":
                value["current_phase"] = "OPERATOR"
                value["operator"]["route"] = "PENDING_REVIEW"
            elif outcome == "VETOED":
                value.update(current_phase="COMPLETE", terminal=True)
                value["stages"]["governor"]["native_state"] = "STAND_DOWN"
                value["operator"]["route"] = "CLOSED_NO_ACTION"
            else:
                value.update(current_phase="COMPLETE", terminal=True, approval_scope="NAVIGATOR_SHADOW_HANDOFF")
                value["stages"]["governor"]["native_state"] = "PROCEED"
                value["operator"].update(route="PENDING_APPROVAL", action_status="SUCCEEDED", action="APPROVE_HANDOFF", result="APPROVED_FOR_HANDOFF", action_id="operator-action-reader-001", operator_id="reader-test", acted_at=OBSERVED_AT)
                value["stages"]["navigator"].update(status="SUCCEEDED", native_state="CREATED")
                value["navigator"] = {
                    "mode": "SHADOW", "handoff_status": "STAGED", "intake_status": "ACCEPTED",
                    "plan_status": "CREATED", "handoff_id": "handoff-reader-001",
                    "intake_receipt_id": "intake-reader-001", "plan_id": "plan-reader-001",
                    "expires_at": "2026-07-18T21:00:00Z", "idempotency_key": "reader-plan-001",
                    "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
                    "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
                }
        return self.commit_value(update)

    def test_unconfigured_and_missing_source_never_create_directories(self):
        missing = self.base / "never-created"
        for reader, expected in (
            (CabinReader(), "NOT_CONFIGURED"),
            (CabinReader(missing), "NOT_CONFIGURED"),
            (CabinReader(mission_id=MISSION_ID), "NOT_CONFIGURED"),
            (CabinReader(missing, MISSION_ID), "UNAVAILABLE"),
        ):
            with mock.patch.object(Path, "mkdir", side_effect=AssertionError("reader attempted mkdir")):
                feed = reader.current()
            self.assertEqual(feed["status"], expected)
            self.assertNotIn(str(missing), json.dumps(feed))
        self.assertFalse(missing.exists())

    def test_partial_live_projection_is_pure_readonly_and_uses_original_clock(self):
        before = self.file_state()
        with mock.patch.object(Path, "mkdir", side_effect=AssertionError("reader attempted mkdir")):
            feed, manifest = self.manifest()
        self.assertEqual(before, self.file_state())
        self.assertFalse((self.root / "presentation").exists())
        self.assertEqual(feed["observed_at"], OBSERVED_AT)
        self.assertNotEqual(feed["checked_at"], OBSERVED_AT)
        self.assertEqual(manifest["schema_version"], "blackpod.presentation_manifest.v1")
        self.assertEqual(manifest["generated_at"], OBSERVED_AT)
        self.assertEqual(manifest["modeldock_mode"], "NOT_RECORDED")
        self.assertIsNone(manifest["build_week_revision"])
        self.assertIsNone(manifest["battlestar_revision"])
        self.assertNotIn("demo_scenario", manifest)
        self.assertEqual(manifest["final_outcome"], "INCOMPLETE")
        summary = json.loads(self.reader.artifact(feed["publication_id"], manifest["mission_summary"]["path"]))
        self.assertEqual(summary["stages"]["oracle"]["technical_status"], "NOT_STARTED")
        for field in ("captains_log", "mission_summary", "final_snapshot"):
            ref = manifest[field]
            self.assertEqual(ref["sha256"], sha256_bytes(self.reader.artifact(feed["publication_id"], ref["path"])))

    def test_all_canonical_outcomes_are_publishable_without_approval_gate(self):
        for outcome in ("INCOMPLETE", "FAILED", "HELD", "VETOED", "APPROVED"):
            with self.subTest(outcome=outcome):
                self.commit_outcome(outcome)
                _, manifest = self.manifest()
                self.assertEqual(manifest["final_outcome"], outcome)
                self.assertEqual(manifest["allowed_operations"], list(NAVIGATOR_ALLOWED_OPERATIONS))
                self.assertEqual(manifest["prohibited_operations"], list(NAVIGATOR_PROHIBITED_OPERATIONS))

    def test_real_running_transition_is_visible_without_rewriting_stored_summary(self):
        loaded = self.store.load_mission(MISSION_ID)
        render_mission_presentation(self.store, loaded)
        stale_summary = (self.root / "presentation/mission_summary.json").read_bytes()
        source = self.store.write_immutable_artifact(MISSION_ID, relative_path="oracle/inputs/quotes.json", payload=b"{}\n", name="quotes", producer="harbormaster", schema_version=None, observed_at=OBSERVED_AT)
        provenance = ComponentProvenance.from_mapping({
            "git_revision": "a" * 40, "git_branch": "main", "dirty_worktree": False,
            "oracle_entry_point": "blackpod.runtime.oracle_pipeline.run_oracle_pipeline",
            "run_mode": "LIVE", "transport": "LIVE_YFINANCE", "replay_fixture_id": None,
            "replay_fixture_sha256": None,
        })
        running = begin_oracle(loaded.snapshot, previous_snapshot_sha256=loaded.current_snapshot_sha256, observed_at=OBSERVED_AT, provenance=provenance, input_artifacts=(source,))
        self.store.commit_snapshot(loaded.paths, running)
        feed, manifest = self.manifest()
        self.assertEqual(manifest["battlestar_revision"], "a" * 40)
        self.assertEqual((self.root / "presentation/mission_summary.json").read_bytes(), stale_summary)
        summary = json.loads(self.reader.artifact(feed["publication_id"], "presentation/mission_summary.json"))
        self.assertEqual(summary["stages"]["oracle"]["technical_status"], "RUNNING")
        self.assertEqual(summary["snapshot_count"], 2)

    def test_shared_projection_matches_existing_writer_without_any_io(self):
        loaded = self.store.load_mission(MISSION_ID)
        published = render_mission_presentation(self.store, loaded)
        source_bytes = {
            **{artifact.path: (self.root / artifact.path).read_bytes() for artifact in loaded.snapshot.artifacts},
            **{f"snapshots/mission_snapshot-r{snapshot.revision:04d}.json": canonical_json_bytes(snapshot.to_dict()) for snapshot in loaded.snapshot_history},
        }
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("projection performed IO")), mock.patch.object(Path, "mkdir", side_effect=AssertionError("projection wrote files")):
            projection = project_mission_presentation(loaded, source_bytes)
        self.assertEqual(projection.captain_log, published.captain_log)
        self.assertEqual(projection.mission_summary, published.mission_summary)
        for path, payload in projection.files.items():
            self.assertEqual(payload, (self.root / path).read_bytes())

    def test_historical_optional_defaults_preserve_original_immutable_bytes(self):
        # Early v1 snapshots are valid without the later optional fields. Their
        # raw bytes and hashes remain authoritative, not normalized to_dict().
        value = self.initialized.snapshot.to_dict()
        for key in ("components", "operator", "navigator", "approval_scope"):
            value.pop(key)
        for stage in value["stages"].values():
            stage.pop("modeldock_calls")
        payload = canonical_json_bytes(value)
        self.initialized.paths.current_snapshot.write_bytes(payload)
        self.initialized.paths.revision_snapshot.write_bytes(payload)
        before = self.file_state()
        feed, manifest = self.manifest()
        self.assertEqual(manifest["final_snapshot"]["sha256"], sha256_bytes(payload))
        self.assertEqual(self.reader.artifact(feed["publication_id"], "mission_snapshot.json"), payload)
        for path in ("presentation/captains_log.json", "presentation/mission_summary.json"):
            presentation = json.loads(self.reader.artifact(feed["publication_id"], path))
            self.assertEqual(presentation["generated_from_snapshot"]["sha256"], sha256_bytes(payload))
        self.assertEqual(before, self.file_state())

    def test_bad_evidence_is_unavailable_without_leaking_exception_or_previous_ready(self):
        ready, _ = self.manifest()
        (self.root / "request/mission_request.json").write_bytes(b"secret=never-echo-this\n")
        feed = self.reader.current()
        self.assertEqual(feed["status"], "UNAVAILABLE")
        self.assertNotIn("publication_id", feed)
        self.assertNotIn("never-echo-this", json.dumps(feed))
        self.assertNotIn(str(self.base), json.dumps(feed))
        self.assertIsNotNone(self.reader.artifact(ready["publication_id"], MANIFEST_PATH))

    def test_replay_mission_is_never_promoted_to_live(self):
        request = replace(self.request, run_mode=cabin_reader.RunMode.REPLAY, mission_id="mission-reader-replay", request_id="request-reader-replay")
        self.store.initialize(request, mission_id=request.mission_id, started_at=OBSERVED_AT, observed_at=OBSERVED_AT)
        self.assertEqual(CabinReader(self.artifacts, request.mission_id).current()["status"], "UNAVAILABLE")

    def test_reader_never_serves_stale_demo_manifest_or_unreferenced_files(self):
        (self.root / "presentation").mkdir()
        (self.root / "presentation/demo_manifest.json").write_bytes(b"not valid JSON")
        (self.root / "private.txt").write_text("not mission evidence")
        feed, _ = self.manifest()
        self.assertIsNone(self.reader.artifact(feed["publication_id"], "presentation/demo_manifest.json"))
        self.assertIsNone(self.reader.artifact(feed["publication_id"], "private.txt"))

    def test_history_tampering_and_future_revision_are_not_publishable(self):
        revision = self.initialized.paths.revision_snapshot
        original = revision.read_bytes()
        revision.write_bytes(original + b" ")
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
        revision.write_bytes(original)
        (revision.parent / "mission_snapshot-r0002.json").write_bytes(original)
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_source_change_during_capture_is_rejected(self):
        original_read = cabin_reader._read_file
        calls = 0
        def changed_read(root, relative):
            nonlocal calls
            if relative == "request/mission_request.json":
                calls += 1
                if calls > 1:
                    return b"concurrent change"
            return original_read(root, relative)
        with mock.patch.object(cabin_reader, "_read_file", side_effect=changed_read):
            self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_symlinked_root_mission_parent_and_artifact_are_rejected(self):
        alias = self.base / "source-link"
        alias.symlink_to(self.artifacts, target_is_directory=True)
        self.assertEqual(CabinReader(alias, MISSION_ID).current()["status"], "UNAVAILABLE")
        for relative in ("request/mission_request.json", "request", "snapshots"):
            with self.subTest(relative=relative):
                path = self.root / relative
                saved = path.with_name(path.name + "-saved")
                path.rename(saved)
                path.symlink_to(saved, target_is_directory=saved.is_dir())
                self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
                path.unlink()
                saved.rename(path)
        mission_link = self.artifacts / "missions/mission-reader-link"
        mission_link.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(CabinReader(self.artifacts, mission_link.name).current()["status"], "UNAVAILABLE")

    def test_read_only_store_denies_all_writer_entrypoints(self):
        store = ReadOnlyMissionStore(self.artifacts)
        for name in ("initialize", "commit_snapshot", "reserve_directory", "write_immutable_artifact", "write_presentation_artifact"):
            with self.subTest(name=name), self.assertRaises(CabinReaderError):
                getattr(store, name)()

    def test_shared_validator_uses_only_bounded_no_follow_byte_reads(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded Path read")):
            self.manifest()

    def test_oversized_request_or_history_is_rejected_before_unbounded_read(self):
        for path in (self.initialized.paths.request_path, self.initialized.paths.revision_snapshot):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(b" " * 16385)
                with mock.patch.object(cabin_reader, "MAX_FILE_BYTES", 16384), mock.patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded Path read")):
                    self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")
                path.write_bytes(original)
        with mock.patch.object(cabin_reader, "MAX_PUBLICATION_BYTES", 1):
            self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_last_three_publications_retained_and_clocks_do_not_change_hash(self):
        first, _ = self.manifest()
        second, _ = self.manifest()
        self.assertEqual(first["publication_id"], second["publication_id"])
        self.assertNotEqual(first["checked_at"], second["checked_at"])
        identifiers = [first["publication_id"]]
        for _ in range(3):
            self.commit_value(lambda value: None)
            feed, _ = self.manifest()
            identifiers.append(feed["publication_id"])
        self.assertIsNone(self.reader.artifact(identifiers[0], MANIFEST_PATH))
        for identifier in identifiers[1:]:
            self.assertIsNotNone(self.reader.artifact(identifier, MANIFEST_PATH))

    def test_late_optional_context_changes_publication_without_rewriting_mission_time(self):
        first, manifest = self.manifest()
        self.assertNotIn("cabin_context", manifest)
        market = Path(__file__).resolve().parents[1] / "fixtures/cabin/aapl_navigator_market.live_capture.json"
        captured_at = "2026-07-19T20:00:00Z"
        capture_cabin_context(self.store, mission_id=MISSION_ID, captured_at=captured_at, market_bytes=market.read_bytes(), market_transport=CaptureTransport.LOCAL_JSON, market_source_identity="reader-market-fixture", navigator_git_revision="a" * 40)
        before = self.file_state()
        latest, manifest = self.manifest()
        self.assertNotEqual(first["publication_id"], latest["publication_id"])
        self.assertEqual(latest["observed_at"], OBSERVED_AT)
        self.assertEqual(manifest["cabin_context"]["observed_at"], captured_at)
        self.assertEqual(before, self.file_state())
        self.assertIsNone(self.reader.artifact(first["publication_id"], CABIN_CONTEXT_PATH))
        self.assertIsNotNone(self.reader.artifact(latest["publication_id"], CABIN_CONTEXT_PATH))
        (self.root / "presentation/navigator_market.json").write_bytes(b"{}\n")
        self.assertEqual(self.reader.current()["status"], "UNAVAILABLE")

    def test_invalid_mission_ids_and_path_probe_names_are_never_read(self):
        for mission in ("../outside", "/absolute", "mission\\escape", ".", ""):
            with self.subTest(mission=mission):
                self.assertNotEqual(CabinReader(self.artifacts, mission).current()["status"], "READY")
        for path in ("../secret", "a//b", "a/./b", "a/../b", "/secret", "a\\b", "a%2fb"):
            with self.subTest(path=path), self.assertRaises(cabin_reader.UnsafePathError):
                cabin_reader._read_file(self.root, path)

    def test_reader_imports_no_orchestration_or_external_service_clients(self):
        tree = ast.parse(Path(cabin_reader.__file__).read_text())
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        for value in imports:
            self.assertFalse(any(term in value for term in ("workflow", "adapter", "client", "operator_service", "broker", "demo_packager")), value)

    @contextlib.contextmanager
    def live_modeldock_fixture(self):
        # Reuse the existing pure-transition fixture, replacing its transport
        # provenance before any snapshots are created. No external call occurs.
        import test_mission_transitions as fixtures
        fixture = fixtures.OracleEnrichmentTransitionTests()
        request = replace(fixtures.request(), run_mode=cabin_reader.RunMode.LIVE)
        provenance = replace(fixtures.provenance(), run_mode=cabin_reader.RunMode.LIVE, transport=fixtures.OracleTransportKind.LIVE_YFINANCE, replay_fixture_id=None, replay_fixture_sha256=None)
        with mock.patch.object(fixtures, "request", return_value=request), mock.patch.object(fixtures, "provenance", return_value=provenance):
            fixture.setUp()
        provenance = replace(fixture.modeldock_provenance(), run_mode=cabin_reader.RunMode.LIVE, transport=cabin_reader.ModelDockTransportKind.LIVE_HTTP, replay_fixture_id=None, replay_fixture_sha256=None)
        call = replace(fixture.running_call(), run_mode=cabin_reader.RunMode.LIVE)
        fixture.modeldock_provenance = lambda: provenance
        fixture.running_call = lambda: call
        try:
            yield fixtures, fixture, CabinReader(fixture.store.artifacts_root, request.mission_id)
        finally:
            fixture.tearDown()

    def test_optional_modeldock_running_failed_and_successful_calls_are_honest(self):
        for expected in ("RUNNING", "FAILED", "LIVE"):
            with self.subTest(expected=expected), self.live_modeldock_fixture() as (fixtures, fixture, reader):
                if expected == "FAILED":
                    fixture.test_strict_failure_preserves_original_oracle_outputs()
                else:
                    running = fixture.begin_enrichment()
                    digest = fixture.store.commit_snapshot(fixture.initialized.paths, running)
                    if expected == "LIVE":
                        outputs = fixture.terminal_outputs()
                        complete = fixtures.complete_oracle_enrichment(running, previous_snapshot_sha256=digest, observed_at=fixtures.OBSERVED_AT, call=fixture.succeeded_call(outputs), output_artifacts=outputs)
                        fixture.store.commit_snapshot(fixture.initialized.paths, complete)
                _, manifest = self.manifest(reader)
                self.assertEqual(manifest["modeldock_mode"], expected)
                self.assertEqual(manifest["modeldock_provider"], "mlx" if expected == "LIVE" else None)
                if expected == "FAILED":
                    self.assertEqual(manifest["final_outcome"], "FAILED")

    def test_mocked_or_inconsistent_successful_live_calls_are_rejected(self):
        with self.live_modeldock_fixture() as (fixtures, fixture, reader):
            running = fixture.begin_enrichment()
            digest = fixture.store.commit_snapshot(fixture.initialized.paths, running)
            outputs = fixture.terminal_outputs()
            complete = fixtures.complete_oracle_enrichment(running, previous_snapshot_sha256=digest, observed_at=fixtures.OBSERVED_AT, call=fixture.succeeded_call(outputs), output_artifacts=outputs)
            fixture.store.commit_snapshot(fixture.initialized.paths, complete)
            self.manifest(reader)
            loaded = fixture.store.load_mission(complete.mission_id)
            latest = loaded.paths.snapshots_dir / f"mission_snapshot-r{complete.revision:04d}.json"
            for field, value in (("mocked", True), ("provider", "not-mlx"), ("run_mode", "REPLAY"), ("mission_id", "mission-wrong")):
                with self.subTest(field=field):
                    changed = complete.to_dict()
                    changed["stages"]["oracle"]["modeldock_calls"][0][field] = value
                    payload = canonical_json_bytes(changed)
                    latest.write_bytes(payload)
                    loaded.paths.current_snapshot.write_bytes(payload)
                    self.assertEqual(reader.current()["status"], "UNAVAILABLE")


class CabinReaderHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ui = self.root / "dist"
        (self.ui / "assets").mkdir(parents=True)
        (self.ui / "index.html").write_text("<html>Cabin</html>")
        (self.ui / "assets/app.js").write_text("console.log('read-only')")
        (self.ui / "demo").mkdir()
        (self.ui / "demo/secret.json").write_text("{}")
        (self.ui / "assets/unsafe.js").symlink_to(self.ui / "index.html")
        self.server = CabinHTTPServer(CabinReader(), self.ui, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path="/", method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_ui_and_unconfigured_feed_work_with_head_and_no_cors(self):
        for path in ("/", "/index.html", "/assets/app.js", "/?mode=live"):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, headers, payload = self.request("/live/current.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["status"], "NOT_CONFIGURED")
        status, headers, body = self.request("/live/current.json", "HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_http_serves_only_safe_whitelisted_resources(self):
        for path in ("/demo/secret.json", "/?mode=demo", "/?mode=replay", "/live/current.json?anything=1", "/assets/", "/assets/unsafe.js", "/../secret", "/%2e%2e/secret", "/%252e%252e/secret", "/assets%5capp.js", "/assets//app.js", "/assets/./app.js", "/unknown", "/live/revisions/not-a-digest/mission_snapshot.json"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_cross_origin_and_dns_rebinding_requests_are_denied(self):
        for headers in ({"Host": "attacker.example"}, {"Host": "localhost.evil.test"}, {"Host": f"0.0.0.0:{self.server.server_port}"}, {"Origin": "http://attacker.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/live/current.json", headers=headers)[0], 403)
        same = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("/live/current.json", headers={"Origin": same})[0], 200)

    def test_all_mutating_methods_are_denied(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"):
            with self.subTest(method=method):
                self.assertEqual(self.request("/live/current.json", method)[0], 405)

    def test_publication_bytes_are_immutable_and_hash_etag_verifiable(self):
        store = MissionStore(self.root / "artifacts")
        request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1", "request_id": "request-http-reader",
            "mission_id": "mission-http-reader", "run_mode": "LIVE", "symbol": "AAPL",
            "requested_at": OBSERVED_AT, "operator_id": "reader-test", "metadata": {},
        })
        store.initialize(request, mission_id=request.mission_id, started_at=OBSERVED_AT, observed_at=OBSERVED_AT)
        self.server.reader = CabinReader(store.artifacts_root, request.mission_id)
        _, _, body = self.request("/live/current.json")
        feed = json.loads(body)
        path = f"/live/{feed['base_url']}{MANIFEST_PATH}"
        status, headers, payload = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(sha256_bytes(payload), feed["publication_id"])
        self.assertIn("immutable", headers["Cache-Control"])
        self.assertEqual(headers["ETag"], f'"{sha256_bytes(payload)}"')
        status, _, body = self.request(path, headers={"If-None-Match": headers["ETag"]})
        self.assertEqual(status, 304)
        self.assertEqual(body, b"")
        self.assertEqual(self.request(path.replace(feed["publication_id"], "0" * 64))[0], 404)


if __name__ == "__main__":
    unittest.main()
