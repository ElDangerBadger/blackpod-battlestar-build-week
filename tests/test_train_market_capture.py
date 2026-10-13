"""Offline fixed-GET transport, durable capture and interrupted recovery tests."""
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from blackpod_build_week import train_market_capture as runner
from blackpod_build_week.contracts.train_market_evidence import TrainMarketCapturePlan, TrainMarketCaptureSnapshot, DEFAULT_LIMITS
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.trading_cost_intake import _nanos
from blackpod_build_week.trading_shadow_review_example import example_material


CREDS = PaperCredentials("fixture-capture-key", "fixture-capture-secret")
CAPTURED = "2025-04-02T00:00:00Z"
EXPORTED = "2025-04-03T00:00:00Z"


def capture_fixture():
    material = example_material()
    blobs = dict(material["blobs"])
    for evidence in material["event_evidence"]:
        blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    plan = prepare_capture_plan(material["events"], blobs, capture_id="synthetic-train-capture",
        created_at="2025-04-01T16:00:00Z", base_plan_event_id=material["studies"][0]["plan_event"].event_id)
    quotes = json.loads(material["evidence"]["synthetic-reviewed/quotes.raw"])["quotes"]
    return plan, blobs, quotes


class AuthoredTransport:
    def __init__(self, quotes, *, empty=False):
        self.quotes, self.empty, self.calls = quotes, empty, []

    def __call__(self, query, credentials, *, timeout, max_response_bytes):
        self.calls.append(copy.deepcopy(query))
        lower, upper = _nanos(query["start"], "fixture start"), _nanos(query["end"], "fixture end")
        body = {"quotes": {symbol: ([] if self.empty else [row for row in rows if lower <= _nanos(row["t"], "fixture quote") <= upper])
                           for symbol, rows in self.quotes.items()}, "next_page_token": None}
        return runner.MarketResponse(200, canonical_json_bytes(body))


class CaptureRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")):
            cls.fixture = capture_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "capture"
        self.plan, self.blobs, self.quotes = self.fixture
        self.transport = AuthoredTransport(self.quotes)
        self.sleeps = []

    def run_capture(self, *, plan=None, budget=None, source=True, transport=None, clock=None):
        return runner.capture_train_quotes(plan or self.plan, self.root, CREDS,
            source_blobs=self.blobs if source else None, request_budget=budget,
            transport=transport or self.transport, clock=clock or (lambda: CAPTURED), sleeper=self.sleeps.append)

    def snapshot(self):
        return runner.read_capture(self.plan, self.root, exported_at=EXPORTED)

    def test_complete_capture_retains_exact_native_bodies_and_receipts(self):
        result = self.run_capture()
        self.assertEqual(result["requests_this_invocation"], 12)
        self.assertEqual(result["complete_segment_count"], 12)
        self.assertTrue(result["pagination_complete"])
        self.assertFalse(result["coverage_verified"])
        material = self.snapshot()
        snapshot = TrainMarketCaptureSnapshot.from_mapping(material["snapshot"])
        self.assertEqual(snapshot.attempt_count, 12)
        self.assertTrue(all(row["status"] == "COMPLETE" for row in snapshot.segments))
        self.assertEqual(snapshot.retained_bytes, sum(map(len, material["evidence"].values())))
        for segment, query in zip(snapshot.segments, self.transport.calls):
            page = segment["pages"][0]
            body = material["evidence"][page["body_evidence"]["path"]]
            receipt = json.loads(material["evidence"][page["receipt_evidence"]["path"]])
            self.assertEqual(receipt["query"], query)
            self.assertEqual(receipt["body_sha256"], sha256_bytes(body))
            self.assertEqual(receipt["url"], runner.QUOTES_URL)
        self.assertEqual(self.sleeps, [1.0] * 11)

    def test_completed_exact_retry_makes_zero_provider_calls_and_keeps_bytes(self):
        self.run_capture()
        before = self.snapshot()
        result = self.run_capture(source=False, transport=lambda *args, **kwargs: self.fail("unexpected provider call"))
        self.assertEqual(result["requests_this_invocation"], 0)
        self.assertEqual(before, self.snapshot())

    def test_partial_invocation_budget_resumes_remaining_segments_only(self):
        first = self.run_capture(budget=2)
        snapshot = self.snapshot()["snapshot"]
        self.assertEqual(first["stop_reason"], "INVOCATION_REQUEST_BUDGET")
        self.assertEqual(first["complete_segment_count"], 2)
        self.assertEqual(snapshot["segments"][2]["status"], "NOT_STARTED")
        self.transport.calls.clear()
        second = self.run_capture(budget=2, source=False)
        self.assertEqual(second["attempt_count"], 4)
        self.assertEqual(self.transport.calls[0], self.plan.segments[2]["query"])

    def test_zero_budget_initializes_offline_without_provider_request(self):
        result = self.run_capture(budget=0)
        self.assertEqual(result["requests_this_invocation"], 0)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["status"], "NOT_STARTED")

    def test_missing_source_proof_rejects_before_provider_call(self):
        with self.assertRaisesRegex(ValueError, "verified frozen"):
            self.run_capture(source=False)
        self.assertEqual(self.transport.calls, [])

    def test_synthetic_default_transport_never_contacts_a_provider(self):
        with self.assertRaisesRegex(ValueError, "synthetic capture"):
            runner.capture_train_quotes(self.plan, self.root, CREDS, source_blobs=self.blobs)

    def test_forged_test_window_plan_rejects_before_provider_call(self):
        value = self.plan.to_dict()
        value["segments"][0]["query"]["start"] = self.plan.segments[-1]["query"]["start"]
        value["segments"][0]["query"]["end"] = self.plan.segments[-1]["query"]["end"]
        with self.assertRaisesRegex(ValueError, "every exact original TRAIN"):
            self.run_capture(plan=TrainMarketCapturePlan.from_mapping(value))
        self.assertEqual(self.transport.calls, [])

    def test_same_capture_directory_cannot_accept_changed_plan(self):
        self.run_capture(budget=1)
        value = self.plan.to_dict(); value["capture_id"] = "different-capture"
        with self.assertRaisesRegex(ValueError, "frozen plan"):
            self.run_capture(plan=TrainMarketCapturePlan.from_mapping(value))

    def test_forward_pagination_retains_every_page_and_exact_token(self):
        calls = []
        def pages(query, credentials, **kwargs):
            calls.append(copy.deepcopy(query))
            native = json.loads(self.transport(query, credentials, **kwargs).body)
            if "page_token" not in query:
                return runner.MarketResponse(200, canonical_json_bytes({"quotes": {"SYNTHA": native["quotes"]["SYNTHA"]}, "next_page_token": "page-two"}))
            self.assertEqual(query["page_token"], "page-two")
            return runner.MarketResponse(200, canonical_json_bytes({"quotes": {"SYNTHB": native["quotes"]["SYNTHB"]}, "next_page_token": None}))
        self.run_capture(budget=2, transport=pages)
        material = self.snapshot()
        self.assertEqual(len(material["snapshot"]["segments"][0]["pages"]), 2)
        self.assertEqual(calls[1]["page_token"], "page-two")

    def test_repeated_token_is_failure_and_never_false_complete(self):
        def loop(query, credentials, **kwargs):
            return runner.MarketResponse(200, canonical_json_bytes({"quotes": {}, "next_page_token": "loop"}))
        result = self.run_capture(budget=3, transport=loop)
        self.assertEqual(result["requests_this_invocation"], 2)
        self.assertEqual(result["stop_reason"], "INVALID_RESPONSE")
        row = self.snapshot()["snapshot"]["segments"][0]
        self.assertEqual(row["status"], "UNAVAILABLE")
        self.assertEqual(len(row["pages"]), 1)

    def test_http_failure_retains_only_safe_status_without_body_or_keys(self):
        def failure(*args, **kwargs):
            return runner.MarketResponse(403, b"fixture-capture-secret provider error")
        result = self.run_capture(transport=failure)
        self.assertEqual(result["requests_this_invocation"], 1)
        material = self.snapshot()
        row = material["snapshot"]["segments"][0]
        self.assertEqual(row["failure"], {"code": "HTTP_ERROR", "http_status": 403})
        self.assertEqual(row["pages"], [])
        self.assertFalse(any(path.startswith("source/") for path in material["evidence"]))
        self.assertFalse(any(b"fixture-capture-secret" in raw for raw in material["evidence"].values()))

    def test_http_failure_requires_explicit_resume_no_automatic_retry(self):
        self.run_capture(transport=lambda *args, **kwargs: (_ for _ in ()).throw(runner.CaptureTransportError("HTTP_ERROR", 429)))
        result = self.run_capture(budget=1, source=False)
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["status"], "COMPLETE")
        self.assertEqual(len(self.sleeps), 1)

    def test_unexpected_transport_message_is_not_printed_or_retained(self):
        def failure(*args, **kwargs):
            raise OSError("fixture-capture-secret unsafe original exception")
        result = self.run_capture(transport=failure)
        self.assertEqual(result["stop_reason"], "TRANSPORT_ERROR")
        self.assertFalse(any(b"fixture-capture-secret" in raw for raw in self.snapshot()["evidence"].values()))

    def test_literal_and_escaped_credential_echo_are_never_retained(self):
        for body in (b'{"quotes":{},"next_page_token":"fixture-capture-secret"}',
                     b'{"quotes":{},"next_page_token":"fixture-capture-secr\\u0065t"}'):
            with self.subTest(body=body):
                temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
                self.root = Path(temporary.name).resolve() / "capture"
                result = self.run_capture(transport=lambda *args, **kwargs: runner.MarketResponse(200, body))
                self.assertEqual(result["stop_reason"], "SENSITIVE_RESPONSE_REFUSED")
                self.assertFalse(any(path.startswith("source/") for path in self.snapshot()["evidence"]))

    def test_malformed_native_source_never_appears_as_successful_page(self):
        result = self.run_capture(transport=lambda *args, **kwargs: runner.MarketResponse(200, b'{"quotes":{},"quotes":{}}'))
        self.assertEqual(result["stop_reason"], "INVALID_RESPONSE")
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["pages"], [])

    def test_terminal_empty_200_is_complete_pagination_without_coverage_claim(self):
        result = self.run_capture(budget=1, transport=AuthoredTransport(self.quotes, empty=True))
        self.assertEqual(result["complete_segment_count"], 1)
        self.assertFalse(result["coverage_verified"])
        row = self.snapshot()["snapshot"]["segments"][0]
        self.assertEqual(row["status"], "COMPLETE")
        self.assertEqual(json.loads(self.snapshot()["evidence"][row["pages"][0]["body_evidence"]["path"]])["quotes"]["SYNTHA"], [])

    def test_interruption_after_started_charges_attempt_and_resumes_same_cursor(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_capture(transport=lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
        recovered = self.snapshot()
        self.assertEqual(recovered["snapshot"]["attempt_count"], 1)
        self.assertEqual(recovered["snapshot"]["segments"][0]["failure"]["code"], "INTERRUPTED")
        result = self.run_capture(budget=1, source=False, clock=lambda: "2025-04-04T00:00:00Z")
        self.assertEqual(result["attempt_count"], 2)
        self.assertEqual(self.transport.calls[0], self.plan.segments[0]["query"])

    def test_fully_persisted_pair_without_completion_recovers_without_get(self):
        with patch.object(runner, "_finish", side_effect=KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.run_capture(budget=1)
        calls = len(self.transport.calls)
        recovered = self.snapshot()
        self.assertEqual(len(self.transport.calls), calls)
        self.assertEqual(recovered["snapshot"]["segments"][0]["status"], "COMPLETE")
        self.assertEqual(recovered["snapshot"]["attempt_count"], 1)
        self.assertEqual(recovered, self.snapshot())

    def test_lone_body_is_not_imported_or_exported_as_verified_evidence(self):
        original = runner._immutable
        def interrupted(path, raw):
            if str(path).endswith("receipt.v1.json"): raise KeyboardInterrupt()
            return original(path, raw)
        with patch.object(runner, "_immutable", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            self.run_capture(budget=1)
        body_path = self.root / "source/attempt-000001.body.raw"
        self.assertTrue(body_path.exists())
        recovered = self.snapshot()
        self.assertEqual(recovered["snapshot"]["segments"][0]["status"], "UNAVAILABLE")
        self.assertNotIn("source/attempt-000001.body.raw", recovered["evidence"])
        self.assertEqual(recovered["snapshot"]["retained_bytes"], sum(map(len, recovered["evidence"].values())))

    def test_two_link_publication_stage_is_recovered_before_regular_checks(self):
        self.run_capture(budget=1)
        target = self.root / "source/attempt-000001.body.raw"
        stage = target.parent / (".capture-stage-" + "a" * 32 + "-" + target.name)
        os.link(target, stage)
        self.assertEqual(target.stat().st_nlink, 2)
        self.snapshot()
        self.assertFalse(stage.exists()); self.assertEqual(target.stat().st_nlink, 1)

    def test_changed_raw_receipt_or_checkpoint_rejects_replay(self):
        self.run_capture(budget=1)
        path = self.root / "source/attempt-000001.body.raw"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "hash or size"):
            self.snapshot()

    def test_boolean_checkpoint_sequence_cannot_impersonate_integer(self):
        self.run_capture(budget=1)
        path = self.root / "attempts/attempt-000001.started.v1.json"
        value = json.loads(path.read_bytes()); value["sequence"] = True
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(ValueError, "checkpoint chain"):
            self.snapshot()

    def test_symlink_and_external_hardlink_sources_reject(self):
        self.run_capture(budget=1)
        target = self.root / "source/attempt-000001.body.raw"
        external = self.root.parent / "external.raw"; os.link(target, external)
        with self.assertRaisesRegex(ValueError, "unsafe source"):
            self.snapshot()
        external.unlink()
        raw = target.read_bytes(); target.unlink(); external.write_bytes(raw); target.symlink_to(external)
        with self.assertRaises(ValueError): self.snapshot()

    def test_busy_capture_lock_fails_without_provider(self):
        self.run_capture(budget=0)
        with runner._lock(self.root, create=False), self.assertRaisesRegex(ValueError, "lock is busy"):
            self.run_capture(budget=1, source=False)
        self.assertEqual(self.transport.calls, [])

    def test_repository_runtime_journal_and_credential_like_sources_are_guarded(self):
        for name in ("src", "tests", ".git"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError): runner.capture_train_quotes(self.plan, self.root.parent / name / "capture", CREDS, source_blobs=self.blobs, transport=self.transport)
        protected = self.root.parent / "protected"; protected.mkdir(); (protected / "ledger.lock").write_bytes(b"")
        with self.assertRaises(ValueError): runner.capture_train_quotes(self.plan, protected / "capture", CREDS, source_blobs=self.blobs, transport=self.transport)
        self.assertEqual(self.transport.calls, [])

    def test_budget_and_lifetime_request_caps_never_auto_expand(self):
        limits = dict(DEFAULT_LIMITS); limits.update(max_total_requests=1, max_requests_per_invocation=1)
        value = self.plan.to_dict(); value["limits"] = limits
        self.plan = TrainMarketCapturePlan.from_mapping(value)
        result = self.run_capture(budget=1)
        self.assertEqual(result["stop_reason"], "TOTAL_REQUEST_LIMIT")
        second = self.run_capture(budget=1, source=False)
        self.assertEqual(second["requests_this_invocation"], 0)
        with self.assertRaisesRegex(ValueError, "invocation bound"): self.run_capture(budget=2, source=False)

    def test_page_row_and_byte_caps_preserve_explicit_incompleteness(self):
        limits = dict(DEFAULT_LIMITS); limits["max_pages_per_segment"] = 1
        value = self.plan.to_dict(); value["limits"] = limits; self.plan = TrainMarketCapturePlan.from_mapping(value)
        result = self.run_capture(transport=lambda *args, **kwargs: runner.MarketResponse(200, b'{"quotes":{},"next_page_token":"pending"}'))
        self.assertEqual(result["stop_reason"], "SEGMENT_PAGE_LIMIT")
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["status"], "INCOMPLETE")
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["failure"]["code"], "SEGMENT_PAGE_LIMIT")

    def test_response_over_frozen_byte_limit_is_never_truncated_or_kept(self):
        result = self.run_capture(transport=lambda query, credentials, **kwargs: runner.MarketResponse(200, b"x" * (kwargs["max_response_bytes"] + 1)))
        self.assertEqual(result["stop_reason"], "RESPONSE_TOO_LARGE")
        self.assertEqual(self.snapshot()["snapshot"]["segments"][0]["pages"], [])

    def test_capture_and_export_clocks_cannot_move_backwards(self):
        with self.assertRaisesRegex(ValueError, "predate"): self.run_capture(clock=lambda: "2025-03-01T00:00:00Z")
        self.run_capture(budget=1)
        with self.assertRaisesRegex(ValueError, "predate"): runner.read_capture(self.plan, self.root, exported_at="2025-04-01T16:00:00Z")

    def test_refreshed_clock_regression_stops_before_start_or_provider_request(self):
        clocks = iter([CAPTURED, "2025-04-01T17:00:00Z"])
        with self.assertRaisesRegex(ValueError, "before request"):
            self.run_capture(budget=1, clock=lambda: next(clocks))
        self.assertEqual(self.transport.calls, [])
        self.assertFalse((self.root / "attempts").exists())

    def test_next_attempt_clock_regression_preserves_first_completed_page(self):
        clocks = iter([CAPTURED, CAPTURED, CAPTURED, "2025-04-01T17:00:00Z"])
        with self.assertRaisesRegex(ValueError, "before request"):
            self.run_capture(budget=2, clock=lambda: next(clocks))
        self.assertEqual(len(self.transport.calls), 1)
        self.assertFalse((self.root / "attempts/attempt-000002.started.v1.json").exists())
        self.assertEqual(self.snapshot()["snapshot"]["attempt_count"], 1)

    def audit_material(self, *, budget=1, transport=None):
        self.run_capture(budget=budget, transport=transport)
        material = self.snapshot()
        return material["snapshot"], {sha256_bytes(raw): raw for raw in material["evidence"].values()}

    def test_snapshot_semantic_validation_is_pure_and_reconstructs_exact_state(self):
        snapshot, blobs = self.audit_material()
        with patch.object(os, "open", side_effect=AssertionError("filesystem forbidden")):
            result = runner.validate_capture_snapshot(self.plan, snapshot, blobs)
        self.assertEqual(result["snapshot"], snapshot)
        self.assertEqual(snapshot["retained_bytes"], sum(map(len, result["evidence"].values())))

    def test_fake_attempt_count_or_missing_checkpoints_cannot_pass_hash_only_audit(self):
        snapshot, blobs = self.audit_material()
        for mutate in (lambda value: value.update(attempt_count=99),
                       lambda value: value.update(checkpoint_evidence=[]),
                       lambda value: value.update(retained_bytes=1),
                       lambda value: value["segments"][0].update(status="NOT_STARTED", pages=[])):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(snapshot); mutate(changed)
                with self.assertRaises(ValueError): runner.validate_capture_snapshot(self.plan, changed, blobs)

    def test_false_failure_or_false_completion_cannot_replace_checkpoint_disposition(self):
        snapshot, blobs = self.audit_material()
        changed = copy.deepcopy(snapshot)
        changed["segments"][0]["failure"] = {"code": "HTTP_ERROR", "http_status": 403}
        with self.assertRaisesRegex(ValueError, "checkpoint replay"):
            runner.validate_capture_snapshot(self.plan, changed, blobs)
        changed = copy.deepcopy(snapshot); changed["segments"][1]["status"] = "COMPLETE"
        with self.assertRaisesRegex(ValueError, "checkpoint replay"):
            runner.validate_capture_snapshot(self.plan, changed, blobs)

    def changed_checkpoint(self, snapshot, blobs, path, mutate):
        snapshot, blobs = copy.deepcopy(snapshot), dict(blobs)
        ref = next(ref for ref in snapshot["checkpoint_evidence"] if ref["path"] == path)
        value = json.loads(blobs[ref["sha256"]]); mutate(value)
        raw = canonical_json_bytes(value)
        ref.update(sha256=sha256_bytes(raw), size_bytes=len(raw)); blobs[ref["sha256"]] = raw
        return snapshot, blobs

    def test_rehashed_completion_count_hash_time_or_cursor_forgery_is_invalid(self):
        snapshot, blobs = self.audit_material()
        for mutate in (lambda value: value.update(native_row_count=999),
                       lambda value: value.update(native_row_count=True),
                       lambda value: value.update(started_sha256="a" * 64),
                       lambda value: value.update(completed_at="2025-04-04T00:00:00Z"),
                       lambda value: value.update(next_page_token="invented-token"),
                       lambda value: value.update(outcome="FAILED", failure={"code": "HTTP_ERROR", "http_status": 401})):
            with self.subTest(mutate=mutate):
                changed, changed_blobs = self.changed_checkpoint(snapshot, blobs, "attempts/attempt-000001.completed.v1.json", mutate)
                with self.assertRaises(ValueError): runner.validate_capture_snapshot(self.plan, changed, changed_blobs)

    def test_rehashed_started_plan_query_sequence_or_predecessor_is_invalid(self):
        snapshot, blobs = self.audit_material()
        for mutate in (lambda value: value.update(capture_plan_sha256="a" * 64),
                       lambda value: value.update(sequence=True),
                       lambda value: value.update(previous_completed_sha256="a" * 64),
                       lambda value: value["query"].update(feed="sip"),
                       lambda value: value.update(started_at="2025-04-04T00:00:00Z")):
            with self.subTest(mutate=mutate):
                changed, changed_blobs = self.changed_checkpoint(snapshot, blobs, "attempts/attempt-000001.started.v1.json", mutate)
                with self.assertRaises(ValueError): runner.validate_capture_snapshot(self.plan, changed, changed_blobs)

    def test_pure_snapshot_audit_accepts_recovered_failure_and_resource_stop(self):
        snapshot, blobs = self.audit_material(transport=lambda *args, **kwargs: runner.MarketResponse(403, b"not retained"))
        self.assertEqual(runner.validate_capture_snapshot(self.plan, snapshot, blobs)["snapshot"], snapshot)

    def test_pure_audit_rejects_missing_or_changed_original_source_snapshot(self):
        snapshot, blobs = self.audit_material()
        changed = copy.deepcopy(snapshot)
        removed = next(ref for ref in changed["checkpoint_evidence"] if ref["path"].startswith("source_evidence/") and ref["path"] != "source_evidence/index.v1.json")
        changed["checkpoint_evidence"].remove(removed)
        with self.assertRaisesRegex(ValueError, "missing or changed leaf"):
            runner.validate_capture_snapshot(self.plan, changed, blobs)


class FakeHTTPResponse(BytesIO):
    def __init__(self, body, url, status=200):
        super().__init__(body); self.url, self.status = url, status
    def geturl(self): return self.url
    def read1(self, limit): return self.read(limit)


class MarketTransportTests(unittest.TestCase):
    def setUp(self):
        self.query = {"symbols": "QQQ,SPY", "start": "2024-01-02T14:30:00Z", "end": "2024-01-02T14:31:00Z",
                      "limit": 10000, "feed": "iex", "currency": "USD", "sort": "asc", "asof": "-"}

    def test_fixed_get_and_secure_handlers_no_proxy_redirect_or_arbitrary_headers(self):
        captured = {}
        class Opener:
            def open(self, request, timeout):
                captured["request"], captured["timeout"] = request, timeout
                return FakeHTTPResponse(b'{"quotes":{},"next_page_token":null}', request.full_url)
        def build(*handlers):
            captured["handlers"] = handlers; return Opener()
        with patch.object(runner, "build_opener", side_effect=build):
            result = runner.market_get(self.query, CREDS)
        self.assertEqual(result.status, 200)
        self.assertEqual(captured["request"].method, "GET")
        self.assertTrue(captured["request"].full_url.startswith(runner.QUOTES_URL + "?"))
        proxy, redirect, https = captured["handlers"]
        self.assertEqual(proxy.proxies, {})
        self.assertIsInstance(redirect, runner._RefuseRedirects)
        self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(https._context.check_hostname)
        self.assertEqual(captured["timeout"], 20)

    def test_redirect_handler_closes_body_without_following(self):
        body = BytesIO(b"sensitive")
        with self.assertRaises(runner.CaptureTransportError) as raised:
            runner._RefuseRedirects().redirect_request(None, body, 302, "secret", {}, "https://evil.invalid")
        self.assertEqual(raised.exception.code, "REDIRECT_REFUSED")
        self.assertTrue(body.closed)

    def test_http_error_body_is_never_read_or_exposed(self):
        error = HTTPError("https://evil.invalid/secret", 401, "fixture-capture-secret", {}, BytesIO(b"secretbody"))
        error.read = lambda *args: self.fail("HTTP error body must not be read")
        class Opener:
            def open(self, *args, **kwargs): raise error
        with patch.object(runner, "build_opener", return_value=Opener()), self.assertRaises(runner.CaptureTransportError) as raised:
            runner.market_get(self.query, CREDS)
        self.assertEqual(str(raised.exception), "HTTP_ERROR")
        self.assertEqual(raised.exception.http_status, 401)

    def test_transport_timeout_url_and_unknown_io_errors_are_sanitized(self):
        for error, expected in ((TimeoutError("secret"), "TIMEOUT"), (URLError("secret"), "URL_ERROR"), (OSError("secret"), "TRANSPORT_ERROR")):
            with self.subTest(error=error):
                class Opener:
                    def open(self, *args, **kwargs): raise error
                with patch.object(runner, "build_opener", return_value=Opener()), self.assertRaises(runner.CaptureTransportError) as raised:
                    runner.market_get(self.query, CREDS)
                self.assertEqual(str(raised.exception), expected)

    def test_response_deadline_size_and_final_url_mismatch_are_refused(self):
        for kind in ("large", "redirect", "deadline"):
            with self.subTest(kind=kind):
                class Opener:
                    def open(self, request, **kwargs):
                        return FakeHTTPResponse(b"123456", request.full_url if kind != "redirect" else "https://evil.invalid")
                with patch.object(runner, "build_opener", return_value=Opener()):
                    if kind == "deadline":
                        with patch.object(runner.time, "monotonic", side_effect=[0, 30]), self.assertRaises(runner.CaptureTransportError) as raised:
                            runner.market_get(self.query, CREDS, max_response_bytes=5)
                    else:
                        with self.assertRaises(runner.CaptureTransportError) as raised:
                            runner.market_get(self.query, CREDS, max_response_bytes=5)
                self.assertEqual(raised.exception.code, {"large": "RESPONSE_TOO_LARGE", "redirect": "REDIRECT_REFUSED", "deadline": "TIMEOUT"}[kind])

    def test_feed_mapping_invalid_timeout_and_endpoint_like_query_are_refused(self):
        for change in ({"feed": "sip"}, {"asof": "today"}, {"endpoint": "/v2/orders"}, {"symbols": "SPY,QQQ"}):
            with self.subTest(change=change), self.assertRaises(runner.CaptureTransportError):
                runner.market_get({**self.query, **change}, CREDS)
        with self.assertRaises(runner.CaptureTransportError): runner.market_get(self.query, CREDS, timeout=100)
        self.assertNotIn("fixture-capture-secret", repr(CREDS))


if __name__ == "__main__":
    unittest.main()
