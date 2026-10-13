"""Offline commands retain shadow proposals and never start trading or inference."""
from copy import deepcopy
import io
import json
from decimal import Context, Inexact, ROUND_UP, Rounded, localcontext
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from blackpod_build_week import desk_candidate_review_cli as cli
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_desk_candidate_review_engine import DeskReviewFixture


class DeskReviewCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("stage or inference forbidden")))
        self.enterContext(patch("blackpod_build_week.auto_trading_runtime.enable_trading", side_effect=AssertionError("activation forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.inputs = self.base / "inputs"
        self.inputs.mkdir()
        self.root = self.base / "journal"
        self.f = DeskReviewFixture()
        self.addCleanup(self.f.close)
        self.review = self.base / "review.json"
        self.write_inputs()

    def write_inputs(self):
        from blackpod_build_week import desk_candidate_review as engine
        self.review.write_bytes(self.f.document.to_bytes())
        for path, raw in engine.evidence_for_desk_review(self.f.document, self.f.events, self.f.blobs).items():
            target = self.inputs / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def seed(self):
        store = JournalStore(self.root)
        for event in self.f.events: store.append(event, self.f.blobs)
        return store

    def invoke(self, *args):
        with patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO) as err:
            try: code = cli.main(list(args))
            except SystemExit as exc: code = exc.code
        return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    def args(self, command, source=True):
        value = [command, "--journal-root", str(self.root), "--review", str(self.review)]
        if source: value += ["--evidence-root", str(self.inputs)]
        return value

    def retained(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def record(self):
        code, value, error = self.invoke(*self.args("record"))
        self.assertEqual((code, error), (0, ""))
        return value

    def test_assess_is_passive_and_preserves_verified_journal(self):
        self.seed()
        before = self.retained()
        code, value, error = self.invoke(*self.args("assess"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(value["orders_submitted"], 0)
        self.assertFalse(value["auto_trading_changed"])
        self.assertFalse(value["result"]["auto_trading_enabled"])
        self.assertFalse(value["result"]["readiness"])
        self.assertIsNone(value["result"]["realized_trade_pnl"])
        self.assertEqual(self.retained(), before)

    def test_record_and_retained_only_retry_after_evidence_removed(self):
        store = self.seed()
        first = self.record()
        self.assertTrue(first["written"])
        before = self.retained()
        shutil.rmtree(self.inputs)
        code, second, error = self.invoke(*self.args("record", False))
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(self.retained(), before)
        self.assertEqual(store.verify().orphan_evidence_count, 0)

    def test_retained_assess_works_without_input_evidence_root(self):
        self.seed()
        first = self.record()
        shutil.rmtree(self.inputs)
        code, value, error = self.invoke(*self.args("assess", False))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(value["event_id"], first["event_id"])

    def test_missing_source_does_not_publish_partial_event(self):
        store = self.seed()
        before = self.retained()
        code, value, error = self.invoke(*self.args("record", False))
        self.assertEqual(code, 2)
        self.assertIsNone(value)
        self.assertIn("evidence", error)
        self.assertEqual(store.verify().event_count, len(self.f.events))
        self.assertEqual(self.retained(), before)

    def test_changed_evidence_file_cannot_substitute_bound_source(self):
        self.seed()
        before = self.retained()
        path = self.inputs / self.f.document.sources["market_evidence"]["path"]
        path.write_bytes(b'{"schema_version":"invented"}')
        code, _, error = self.invoke(*self.args("record"))
        self.assertEqual(code, 2)
        self.assertIn("hash or size", error)
        self.assertEqual(self.retained(), before)

    def test_changed_native_source_does_not_trigger_import_or_stage(self):
        self.seed()
        before = self.retained()
        path = self.inputs / ("native_analysis_code/" + next(iter(self.f.sources)))
        path.write_bytes(b"raise AssertionError('must not execute')\n")
        code, _, _ = self.invoke(*self.args("record"))
        self.assertEqual(code, 2)
        self.assertEqual(self.retained(), before)

    def test_composite_spyglass_record_uses_retained_code_and_keeps_automation_off(self):
        self.f.with_galactica()
        self.write_inputs()
        self.seed()
        value = self.record()
        self.assertFalse(value["result"]["auto_trading_enabled"])
        self.assertIn("BRIGADE_CURRENT_FORECASTS_UNAVAILABLE_INFERENCE_NOT_RUN", value["result"]["reason_codes"])
        shutil.rmtree(self.inputs)
        code, retry, error = self.invoke(*self.args("record", False))
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(retry["written"])

    def test_show_requires_verified_matching_review_event(self):
        self.seed()
        value = self.record()
        before = self.retained()
        code, shown, error = self.invoke("show", "--journal-root", str(self.root), "--event-id", value["event_id"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(shown["source"]["kind"], "SHADOW_DESK_REVIEW")
        self.assertEqual(shown["payload"]["review"], self.f.document.to_dict())
        self.assertEqual(self.retained(), before)
        code, _, _ = self.invoke("show", "--journal-root", str(self.root), "--event-id", self.f.events[0].event_id)
        self.assertEqual(code, 2)

    def test_unknown_event_cannot_be_shown_or_rendered(self):
        self.seed()
        for command in ("show", "render"):
            args = [command, "--journal-root", str(self.root), "--event-id", "journal-event-" + "0" * 64]
            if command == "render": args += ["--output", str(self.base / "report.html")]
            code, _, _ = self.invoke(*args)
            self.assertEqual(code, 2)
        self.assertFalse((self.base / "report.html").exists())

    def test_source_tree_cannot_be_the_journal(self):
        code, _, error = self.invoke("record", "--journal-root", str(self.inputs), "--review", str(self.review), "--evidence-root", str(self.inputs))
        self.assertEqual(code, 2)
        self.assertTrue(error)
        self.assertFalse((self.inputs / "events").exists())

    def test_symlinked_evidence_root_or_file_fails_closed(self):
        self.seed()
        link = self.base / "linked-inputs"
        link.symlink_to(self.inputs, target_is_directory=True)
        code, _, _ = self.invoke("record", "--journal-root", str(self.root), "--review", str(self.review), "--evidence-root", str(link))
        self.assertEqual(code, 2)
        source = self.inputs / self.f.document.sources["market_evidence"]["path"]
        destination = self.base / "market-original.json"
        source.rename(destination)
        source.symlink_to(destination)
        code, _, _ = self.invoke(*self.args("record"))
        self.assertEqual(code, 2)

    def test_contract_cannot_enable_trading_in_a_shadow_review(self):
        self.seed()
        value = self.f.document.to_dict()
        value["authority"]["execution_enabled"] = True
        self.review.write_bytes(canonical_json_bytes(value))
        code, _, _ = self.invoke(*self.args("record"))
        self.assertEqual(code, 2)

    def test_conflicting_retry_policy_does_not_change_original_event(self):
        self.seed()
        self.record()
        before = self.retained()
        value = self.f.document.to_dict()
        value["policy"]["max_entry_fraction"] = "0.20"
        self.review.write_bytes(canonical_json_bytes(value))
        code, _, error = self.invoke(*self.args("record", False))
        self.assertEqual(code, 2)
        self.assertIn("conflicts", error)
        self.assertEqual(self.retained(), before)

    def test_malformed_or_duplicate_json_input_fails_without_writing(self):
        self.seed()
        for raw in (b"[]", b'{"review_id":"a","review_id":"b"}'):
            self.review.write_bytes(raw)
            code, _, _ = self.invoke(*self.args("record"))
            self.assertEqual(code, 2)

    def test_missing_source_journal_cannot_invent_equity_budget(self):
        code, _, _ = self.invoke(*self.args("assess"))
        self.assertEqual(code, 2)
        self.assertFalse(self.root.exists())

    def test_help_exposes_only_offline_commands(self):
        parser = cli.build_parser()
        for command in ("prepare-analysis", "assess", "record", "show", "render"):
            with self.assertRaises(SystemExit) as result:
                with patch("sys.stdout", new_callable=io.StringIO): parser.parse_args([command, "--help"])
            self.assertEqual(result.exception.code, 0)
        with patch("sys.stderr", new_callable=io.StringIO):
            with self.assertRaises(SystemExit): parser.parse_args(["enable"])

    def test_evidence_reference_depth_limit_fails_closed(self):
        value = {"nested": {}}
        for _ in range(25): value = {"nested": value}
        with self.assertRaises(ValueError): list(cli._references(value))

    def test_render_is_immutable_and_does_not_change_journal(self):
        self.seed()
        value = self.record()
        before = self.retained()
        target = self.base / "rendered" / "review.html"
        args = ["render", "--journal-root", str(self.root), "--event-id", value["event_id"], "--output", str(target)]
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        html = target.read_text()
        self.assertIn("OFF", html)
        self.assertIn("XLK", html)
        self.assertEqual(result["sha256"], sha256_bytes(target.read_bytes()))
        self.assertEqual(self.retained(), before)
        raw = target.read_bytes()
        self.assertEqual(self.invoke(*args)[0], 0)
        self.assertEqual(target.read_bytes(), raw)
        target.write_bytes(b"unrelated report")
        self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(target.read_bytes(), b"unrelated report")

    def test_render_cannot_write_inside_journal_or_source_storage(self):
        self.seed()
        value = self.record()
        before = self.retained()
        code, _, _ = self.invoke("render", "--journal-root", str(self.root), "--event-id", value["event_id"],
                                "--output", str(self.root / "report.html"))
        self.assertEqual(code, 2)
        self.assertEqual(self.retained(), before)

    def prepare_roots(self):
        native, galactica = self.base / "native", self.base / "galactica"
        for path, raw in self.f.sources.items():
            target = native / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        fixtures = Path(__file__).resolve().parents[1] / "fixtures/shadow_galactica_analysis"
        for source, relative in (("spyglass.py", "spyglass.py"), ("brigade_debrief.py", "scripts/brigade_debrief.py"),
                                 ("blackwell_brigade.py", "agents/blackwell_brigade.py")):
            target = galactica / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((fixtures / source).read_bytes())
        return native, galactica

    def prepare_args(self, native, galactica):
        return ["prepare-analysis", "--market", str(self.inputs / self.f.document.sources["market_evidence"]["path"]),
            "--evidence-root", str(self.inputs), "--native-root", str(native), "--galactica-root", str(galactica),
            "--generated-at", self.f.recorded_at]

    def input_files(self):
        return {str(path.relative_to(self.inputs)): path.read_bytes() for path in self.inputs.rglob("*") if path.is_file()}

    def test_prepare_analysis_uses_pinned_native_and_spyglass_without_inference(self):
        native, galactica = self.prepare_roots()
        before = self.input_files()
        args = self.prepare_args(native, galactica)
        code, result, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        packet = json.loads(Path(result["path"]).read_bytes())
        self.assertEqual(packet["schema_version"], "blackpod.shadow_analysis_bundle.v1")
        self.assertFalse(result["current_brigade_inference_run"])
        self.assertEqual(result["brigade_status"], "MISSING_CURRENT_FORECASTS_AND_INFERENCE")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertFalse(result["auto_trading_changed"])
        self.assertEqual(packet["native"], self.f.analysis)
        self.assertTrue(all(self.input_files()[path] == raw for path, raw in before.items()))
        capture = self.input_files()
        second_code, repeated, error = self.invoke(*args)
        self.assertEqual((second_code, error), (0, ""))
        self.assertEqual(result["sha256"], repeated["sha256"])
        self.assertEqual(self.input_files(), capture)
        self.assertFalse(self.root.exists())

    def test_prepare_tampered_native_or_spyglass_pin_fails_before_writes(self):
        native, galactica = self.prepare_roots()
        for target in (native / next(iter(self.f.sources)), galactica / "spyglass.py"):
            original = target.read_bytes()
            target.write_bytes(original + b"\nraise AssertionError('unreviewed code')\n")
            before = self.input_files()
            code, _, error = self.invoke(*self.prepare_args(native, galactica))
            self.assertEqual(code, 2)
            self.assertTrue("pin" in error.lower() or "fingerprint" in error.lower())
            self.assertEqual(self.input_files(), before)
            target.write_bytes(original)

    def test_prepare_rejects_changed_raw_market_before_publishing_analysis(self):
        native, galactica = self.prepare_roots()
        path = self.inputs / self.f.market["source_evidence"][1]["path"]
        path.write_bytes(b'{"bars":{},"next_page_token":null}')
        before = self.input_files()
        code, _, _ = self.invoke(*self.prepare_args(native, galactica))
        self.assertEqual(code, 2)
        self.assertEqual(self.input_files(), before)

    def test_prepare_historical_brigade_date_and_transcript_are_all_or_none(self):
        from test_shadow_galactica_analysis import TRANSCRIPT
        native, galactica = self.prepare_roots()
        transcript = self.base / "brigade.txt"
        transcript.write_bytes(TRANSCRIPT)
        for extra in (["--brigade-transcript", str(transcript)], ["--brigade-as-of", "2026-04-24T20:00:00Z"]):
            before = self.input_files()
            code, _, error = self.invoke(*self.prepare_args(native, galactica), *extra)
            self.assertEqual(code, 2)
            self.assertIn("together", error)
            self.assertEqual(self.input_files(), before)

    def test_prepare_historical_brigade_retains_dissent_without_current_vote(self):
        from test_shadow_galactica_analysis import TRANSCRIPT
        native, galactica = self.prepare_roots()
        transcript = self.base / "brigade.txt"
        transcript.write_bytes(TRANSCRIPT)
        code, result, error = self.invoke(*self.prepare_args(native, galactica), "--brigade-transcript", str(transcript),
                                        "--brigade-as-of", "2026-04-24T20:00:00Z")
        self.assertEqual((code, error), (0, ""))
        packet = json.loads(Path(result["path"]).read_bytes())
        self.assertEqual(packet["galactica"]["brigade"]["status"], "HISTORICAL_INPUT_ONLY")
        self.assertFalse(packet["galactica"]["brigade"]["current_opinions_available"])
        self.assertFalse(result["current_brigade_inference_run"])
        self.assertEqual((self.inputs / "galactica/brigade-transcript.txt").read_bytes(), TRANSCRIPT)
        self.assertIn("dissent", json.dumps(packet["galactica"]["brigade"]["parsed_report"]).lower())

    def test_prepare_cannot_publish_back_into_native_source_tree(self):
        native, galactica = self.prepare_roots()
        args = self.prepare_args(native, galactica)
        args[args.index("--evidence-root") + 1] = str(native)
        code, _, _ = self.invoke(*args)
        self.assertEqual(code, 2)
        self.assertFalse((native / "native_analysis_code").exists())


class DeskReviewPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from blackpod_build_week.desk_candidate_review import build_desk_review_event
        cls.f = DeskReviewFixture()
        cls.event = build_desk_review_event(cls.f.document, cls.f.events, cls.f.blobs)
    @classmethod
    def tearDownClass(cls): cls.f.close()

    def render(self, event=None, blobs=None):
        from blackpod_build_week.desk_candidate_review_presentation import render_desk_review
        return render_desk_review(event or self.event, blobs if blobs is not None else self.f.blobs)

    def test_visible_authority_boundaries_and_unknown_return_never_approve_trade(self):
        html = self.render()
        for phrase in ("AUTO-TRADING AUTHORITY OFF", "NO ORDER AUTHORIZATION", "Expected return is unknown", "Research only",
                       "SHADOW handoff is not trading approval", "no perpetual 50/50 rebalancing"):
            self.assertIn(phrase, html)
        self.assertIn("Recorded review authority only; current runtime status is checked separately", html)
        self.assertNotIn("<button", html)

    def test_every_retained_evidence_hash_is_visible(self):
        html = self.render()
        self.assertIn(self.event.event_id, html)
        for reference in self.event.evidence:
            self.assertIn(reference["sha256"], html)
            self.assertIn(reference["path"], html)

    def test_missing_or_tampered_source_cannot_render(self):
        for change in ("missing", "tamper"):
            blobs = dict(self.f.blobs)
            digest = self.f.document.sources["issuer_evidence"]["sha256"]
            if change == "missing": blobs.pop(digest)
            else: blobs[digest] += b" "
            with self.assertRaises(ValueError): self.render(blobs=blobs)

    def test_conditional_pilot_and_deferred_plan_have_different_visible_status(self):
        from blackpod_build_week.desk_candidate_review import build_desk_review_event
        f = DeskReviewFixture()
        self.addCleanup(f.close)
        first = self.render()
        self.assertIn("XLK · 3 shares", first)
        for snapshot in f.market["snapshots"].values(): snapshot["latestQuote"]["bp"] = 0
        f.refresh_market()
        event = build_desk_review_event(f.document, f.events, f.blobs)
        second = self.render(event, f.blobs)
        self.assertIn("No entry proposed", second)
        self.assertIn("Current proposed quantity: 0", second)
        self.assertIn("Missing positive two-sided quote", second)

    def test_source_text_and_urls_are_html_escaped_without_execution(self):
        from blackpod_build_week.desk_candidate_review import build_desk_review_event
        f = DeskReviewFixture()
        self.addCleanup(f.close)
        injected = '<img src=x onerror="alert(1)">'
        f.issuer["facts"][0]["mandate"] = injected
        f.issuer["facts"][0]["issuer"] = injected
        f.document = f.document_for()
        event = build_desk_review_event(f.document, f.events, f.blobs)
        html = self.render(event, f.blobs)
        self.assertNotIn(injected, html)
        self.assertIn("&lt;img", html)
        self.assertIn("&quot;alert(1)&quot;", html)

    def test_rendering_retained_content_never_fetches_sources(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("source fetch forbidden")):
            self.render()

    def test_changed_valid_policy_and_benchmark_are_rendered_from_event(self):
        from blackpod_build_week.contracts.desk_candidate_review import DeskReviewInput
        from blackpod_build_week.desk_candidate_review import build_desk_review_event
        f = DeskReviewFixture()
        self.addCleanup(f.close)
        value = f.document.to_dict()
        value["policy"].update(max_entry_fraction="0.05", scenario_risk_fraction="0.001", atr_multiple="3",
            price_buffer_fraction="0.02", investment_candidate_fraction="0.10", investment_horizon_days=30,
            benchmark_symbol="USMV")
        f.document = DeskReviewInput.from_mapping(value)
        event = build_desk_review_event(f.document, f.events, f.blobs)
        html = self.render(event, f.blobs)
        self.assertIn("2.00% price buffer", html)
        self.assertIn("10.00%-of-desk cap", html)
        self.assertIn("3.00 ATR distance", html)
        self.assertIn("0.10% of the trading budget", html)
        self.assertIn("30-day proposed research horizon", html)
        self.assertIn("USMV is the benchmark control", html)
        self.assertNotIn("SPY is the benchmark control", html)

    def test_hostile_ambient_decimal_context_cannot_change_rendered_report(self):
        expected = self.render()
        context = Context(prec=3, rounding=ROUND_UP)
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        with localcontext(context):
            self.assertEqual(self.render(), expected)

    def test_no_specific_split_date_or_external_etn_claim_is_invented(self):
        html = self.render()
        self.assertNotIn("November 5", html)
        self.assertNotIn("form424b2.htm", html)
        self.assertNotIn("Barclays pricing supplement", html)
        self.assertIn("Known corporate actions inside the proposed horizon", html)


class PassiveArtifactWriterTests(unittest.TestCase):
    """Exercise real parent locking and interrupted no-replace publication."""
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()

    def test_second_parent_writer_cannot_recover_first_active_staging_file(self):
        from blackpod_build_week import auto_trading_runtime as runtime
        first, second = self.base / "reports/first.html", self.base / "reports/second.html"
        staged, release, second_started, second_lock_attempted = (threading.Event() for _ in range(4))
        original_link = runtime.os.link
        original_flock = runtime.fcntl.flock
        calls, calls_lock = [], threading.Lock()

        def observe_parent_lock(descriptor, operation):
            with calls_lock:
                calls.append((descriptor, operation))
                if len(calls) == 2: second_lock_attempted.set()
            return original_flock(descriptor, operation)

        def pause_first_publication(source, destination, *args, **kwargs):
            if destination == first.name:
                staged.set()
                if not release.wait(5): raise AssertionError("first publication was not released")
            return original_link(source, destination, *args, **kwargs)

        def write_second():
            second_started.set()
            cli._write(second, b"second retained report", ())

        with patch.object(runtime.os, "link", side_effect=pause_first_publication), patch.object(runtime.fcntl, "flock", side_effect=observe_parent_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(cli._write, first, b"first retained report", ())
                try:
                    self.assertTrue(staged.wait(2))
                    stage_paths = list(first.parent.glob(".runtime-*.tmp"))
                    self.assertEqual(len(stage_paths), 1)
                    original_stage = stage_paths[0].read_bytes()
                    b = pool.submit(write_second)
                    self.assertTrue(second_started.wait(2))
                    self.assertTrue(second_lock_attempted.wait(2))
                    self.assertFalse(b.done())
                    self.assertFalse(first.exists())
                    self.assertFalse(second.exists())
                    self.assertEqual(stage_paths[0].read_bytes(), original_stage)
                finally:
                    release.set()
                a.result(timeout=3)
                b.result(timeout=3)
        self.assertEqual(first.read_bytes(), b"first retained report")
        self.assertEqual(second.read_bytes(), b"second retained report")
        self.assertEqual(list(first.parent.glob(".runtime-*.tmp")), [])

    def test_unpublished_orphan_is_recovered_before_new_passive_write(self):
        parent = self.base / "reports"
        parent.mkdir()
        orphan = parent / (".runtime-" + "a" * 32 + ".tmp")
        orphan.write_bytes(b"interrupted unpublished report")
        target = parent / "review.html"
        cli._write(target, b"complete retained report", ())
        self.assertFalse(orphan.exists())
        self.assertEqual(target.read_bytes(), b"complete retained report")

    def test_exact_internal_publication_hardlink_recovers_on_identical_retry(self):
        target = self.base / "reports/review.html"
        cli._write(target, b"immutable report", ())
        staged = target.parent / (".runtime-" + "b" * 32 + ".tmp")
        os.link(target, staged)
        self.assertEqual(target.stat().st_nlink, 2)
        cli._write(target, b"immutable report", ())
        self.assertEqual(target.read_bytes(), b"immutable report")
        self.assertFalse(staged.exists())
        self.assertEqual(target.stat().st_nlink, 1)

    def test_external_hardlinks_cannot_be_repaired_or_overwritten(self):
        target = self.base / "reports/review.html"
        cli._write(target, b"immutable report", ())
        external = self.base / "external-report-link"
        os.link(target, external)
        with self.assertRaises((ValueError, OSError)):
            cli._write(target, b"changed report", ())
        self.assertEqual(target.read_bytes(), b"immutable report")
        self.assertEqual(external.read_bytes(), b"immutable report")

    def test_unsafe_orphan_symlink_is_rejected_without_removing_target(self):
        parent = self.base / "reports"
        parent.mkdir()
        external = self.base / "outside.txt"
        external.write_bytes(b"untouched outside bytes")
        staged = parent / (".runtime-" + "c" * 32 + ".tmp")
        staged.symlink_to(external)
        with self.assertRaises(ValueError): cli._write(parent / "new.html", b"new report", ())
        self.assertTrue(staged.is_symlink())
        self.assertEqual(external.read_bytes(), b"untouched outside bytes")
        self.assertFalse((parent / "new.html").exists())

    def test_nested_git_source_tree_is_rejected_before_creating_report_parent(self):
        for marker_is_file in (False, True):
            root = self.base / ("worktree" if marker_is_file else "battlestar")
            root.mkdir()
            if marker_is_file: (root / ".git").write_text("gitdir: /synthetic/git-metadata\n")
            else: (root / ".git").mkdir()
            target = root / "nested/reports/review.html"
            with self.assertRaisesRegex(ValueError, "repository source trees"):
                cli._write(target, b"report", ())
            self.assertFalse((root / "nested").exists())

    def test_nested_installed_trading_storage_is_rejected_by_either_lock_marker(self):
        for marker in ("ledger.lock", "worker.lock"):
            root = self.base / marker.replace(".", "-")
            root.mkdir()
            (root / marker).write_bytes(b"")
            target = root / "nested/review.html"
            with self.assertRaisesRegex(ValueError, "installed trading runtime storage"):
                cli._write(target, b"report", ())
            self.assertFalse((root / "nested").exists())

    def test_git_metadata_and_explicit_source_overlap_are_rejected(self):
        root = self.base / "native"
        root.mkdir()
        (root / ".git").mkdir()
        with self.assertRaises(ValueError): cli._write(root / ".git/objects/review.html", b"report", ())
        source = self.base / "source"
        source.mkdir()
        with self.assertRaises((ValueError, JournalStoreError)): cli._write(source / "reports/review.html", b"report", (source,))
        self.assertFalse((source / "reports").exists())

    def test_package_ignored_output_is_the_explicit_repository_exception(self):
        package_root = Path(__file__).resolve().parents[1]
        output = package_root / "output"
        output.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="shadow-writer-test-", dir=output)
        self.addCleanup(directory.cleanup)
        target = Path(directory.name) / "review.html"
        cli._write(target, b"passive ignored report", ())
        self.assertEqual(target.read_bytes(), b"passive ignored report")

    def test_staged_external_hardlink_is_never_treated_as_safe_internal_recovery(self):
        parent = self.base / "reports"
        parent.mkdir()
        external = self.base / "outside.txt"
        external.write_bytes(b"retained external evidence")
        staged = parent / (".runtime-" + "d" * 32 + ".tmp")
        os.link(external, staged)
        with self.assertRaises(ValueError): cli._write(parent / "review.html", b"report", ())
        self.assertTrue(staged.exists())
        self.assertEqual(external.read_bytes(), b"retained external evidence")
        self.assertFalse((parent / "review.html").exists())


if __name__ == "__main__": unittest.main()
