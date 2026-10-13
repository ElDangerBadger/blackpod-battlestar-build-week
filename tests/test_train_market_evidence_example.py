"""Authored TRAIN capture examples establish availability, never effectiveness."""
import ast
import contextlib
from datetime import timedelta
import inspect
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import train_market_evidence_example as example
from blackpod_build_week.contracts.mission_request import parse_rfc3339, format_rfc3339
from blackpod_build_week.contracts.train_market_evidence import (
    TrainMarketCapturePlan, TrainMarketCaptureSnapshot, TrainMarketExportRequest,
)
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class TrainMarketExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name).resolve() / "train-example"
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("provider forbidden")), \
             patch("blackpod_build_week.paper_account_probe.parse_credentials", side_effect=AssertionError("credential file loading forbidden")):
            cls.sources = example.fixture_sources()
            cls.summary = example.prepare_example(cls.root)
            cls.contents = {row["case_id"]: JournalStore(cls.root / row["journal_root"]).verified_contents()
                            for row in cls.summary["cases"]}

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def case(self, identity="full"):
        return next(row for row in self.summary["cases"] if row["case_id"] == identity)

    def result(self, identity="full"):
        return json.loads((self.root / self.case(identity)["result_path"]).read_bytes())

    def plan(self, identity="full"):
        return TrainMarketCapturePlan.from_bytes((self.root / self.case(identity)["plan_path"]).read_bytes())

    def snapshot(self, identity="full"):
        return TrainMarketCaptureSnapshot.from_bytes((self.root / self.case(identity)["snapshot_path"]).read_bytes())

    def test_three_cases_distinguish_pagination_coverage_and_partial_work(self):
        self.assertEqual([row["status"] for row in self.summary["cases"]],
                         ["CAPTURE_COMPLETE", "CAPTURE_INCOMPLETE", "CAPTURE_COMPLETE"])
        self.assertEqual([row["coverage_complete"] for row in self.summary["cases"]], [True, False, False])
        self.assertEqual(self.summary["data_status"], "SYNTHETIC_FIXTURE_ONLY")

    def test_complete_fixture_has_twelve_segments_and_twenty_four_covered_pairs(self):
        counts = self.case()["counts"]
        self.assertEqual(counts["planned_segments"], 12)
        self.assertEqual(counts["provided_segments"], 12)
        self.assertEqual(counts["planned_symbol_sessions"], 24)
        self.assertEqual(counts["covered_symbol_sessions"], 24)
        self.assertEqual(counts["missing_symbol_sessions"], 0)
        self.assertEqual(counts["raw_quote_count"], 24)
        self.assertEqual(counts["eligible_quote_count"], 24)

    def test_partial_capture_preserves_twenty_missing_pairs_and_ten_unprocessed_sessions(self):
        counts = self.case("partial")["counts"]
        self.assertEqual(counts["provided_segments"], 2)
        self.assertEqual(counts["missing_segments"], 10)
        self.assertEqual(counts["covered_symbol_sessions"], 4)
        self.assertEqual(counts["missing_symbol_sessions"], 20)
        self.assertEqual(len(self.result("partial")["segments"]), 12)
        self.assertEqual(len(self.result("partial")["missing_symbol_sessions"]), 20)

    def test_terminal_empty_success_completes_retrieval_without_coverage(self):
        row = self.case("terminal-empty")
        self.assertTrue(row["capture_complete"])
        self.assertFalse(row["coverage_complete"])
        self.assertEqual(row["counts"]["capture_complete_segments"], 12)
        self.assertEqual(row["counts"]["coverage_complete_segments"], 11)
        self.assertEqual(row["counts"]["raw_quote_count"], 22)
        self.assertEqual(row["counts"]["missing_symbol_sessions"], 2)
        self.assertIsNone(self.result("terminal-empty")["folds"][0]["training_spread_profile"])

    def test_every_journal_preserves_fourteen_original_source_events(self):
        original = [event.to_bytes() for event in self.sources["events"]]
        for case_id, (events, _) in self.contents.items():
            self.assertEqual([event.to_bytes() for event in events[:14]], original)
            self.assertTrue(all(event.schema_version == "blackpod.decision_journal_event.v19" for event in events[14:]))
        self.assertEqual([row["journal_verification"]["event_count"] for row in self.summary["cases"]], [28, 18, 28])

    def test_capture_queries_match_original_returned_train_opening_windows(self):
        sessions = self.sources["dataset"].sessions
        plan = self.plan()
        self.assertEqual([segment["session_index"] for segment in plan.segments], list(range(12)))
        for segment in plan.segments:
            expected = sessions[segment["session_index"]]
            self.assertEqual(segment["session_id"], expected["session_id"])
            self.assertEqual(segment["query"]["start"], expected["open_at"])
            self.assertEqual(segment["query"]["end"], format_rfc3339(
                parse_rfc3339(expected["open_at"], "source open") + timedelta(seconds=60)))
            self.assertEqual(segment["query"]["feed"], "iex")
            self.assertEqual(segment["query"]["limit"], 10000)
            self.assertEqual(segment["query"]["asof"], "-")

    def test_all_native_rows_are_original_authored_quotes_inside_train(self):
        old_ref = self.sources["costs"]["request"].quote_pages[0]["body_evidence"]
        old = json.loads(self.sources["blobs"][old_ref["sha256"]])
        events, blobs = self.contents["full"]
        count = 0
        for event in events:
            if event.event_type != "TRAIN_MARKET_CAPTURE_SEGMENT_RECORDED":
                continue
            for page in event.payload["request"]["pages"]:
                body = json.loads(blobs[page["body_evidence"]["sha256"]])
                for symbol, rows in body["quotes"].items():
                    for row in rows:
                        self.assertIn(row, old["quotes"][symbol])
                    count += len(rows)
        self.assertEqual(count, 24)
        self.assertTrue(self.summary["raw_bodies_are_authored_quote_subsets_not_real_provider_captures"])

    def test_capture_plan_precedes_every_retained_receipt(self):
        events, blobs = self.contents["full"]
        plan_event = next(event for event in events if event.event_type == "TRAIN_MARKET_CAPTURE_PLAN_RECORDED")
        positions = {event.event_id: index for index, event in enumerate(events)}
        for event in events:
            if event.event_type != "TRAIN_MARKET_CAPTURE_SEGMENT_RECORDED":
                continue
            self.assertLess(positions[plan_event.event_id], positions[event.event_id])
            self.assertEqual(event.payload["request"]["capture_plan_event_id"], plan_event.event_id)
            for page in event.payload["request"]["pages"]:
                receipt = json.loads(blobs[page["receipt_evidence"]["sha256"]])
                self.assertGreater(parse_rfc3339(receipt["captured_at"], "receipt"),
                                   parse_rfc3339(plan_event.recorded_at, "freeze"))
                self.assertEqual(receipt["body_sha256"], page["body_evidence"]["sha256"])
                self.assertEqual(receipt["method"], "GET")
                self.assertEqual(receipt["url"], "https://data.alpaca.markets/v2/stocks/quotes")

    def test_aggregate_group_discloses_every_recorded_segment(self):
        for identity, (events, _) in self.contents.items():
            aggregate = next(event for event in events if event.event_id == self.case(identity)["export_event_id"])
            request = aggregate.payload["request"]
            selected = sorted(event.event_id for event in events
                              if event.event_type == "TRAIN_MARKET_CAPTURE_SEGMENT_RECORDED"
                              and event.source["export_id"] == request["export_id"])
            self.assertEqual(request["segment_event_ids"], selected)

    def test_partial_snapshot_retains_every_planned_segment_and_exact_attempt_budget(self):
        snapshot = self.snapshot("partial")
        self.assertEqual(snapshot.attempt_count, 2)
        self.assertEqual(len(snapshot.segments), 12)
        self.assertEqual(sum(segment["status"] == "COMPLETE" for segment in snapshot.segments), 2)
        self.assertEqual(sum(segment["status"] == "NOT_STARTED" for segment in snapshot.segments), 10)
        attempts = [ref for ref in snapshot.checkpoint_evidence
                    if ref["path"].endswith(("started.v1.json", "completed.v1.json"))]
        self.assertEqual(len(attempts), 4)
        self.assertGreater(len(snapshot.checkpoint_evidence), len(attempts))

    def test_snapshot_and_attempt_audits_are_retained_independently_of_capture_storage(self):
        for identity, (events, blobs) in self.contents.items():
            event = next(event for event in events if event.event_id == self.case(identity)["export_event_id"])
            request = event.payload["request"]
            reference = request["capture_snapshot_evidence"]
            self.assertEqual(sha256_bytes(blobs[reference["sha256"]]), reference["sha256"])
            snapshot = TrainMarketCaptureSnapshot.from_bytes(blobs[reference["sha256"]])
            self.assertEqual(snapshot.checkpoint_evidence, request["capture_checkpoint_evidence"])
            self.assertEqual(event.payload["result"]["capture_audit"]["attempt_count"], snapshot.attempt_count)
            for ref in request["capture_checkpoint_evidence"]:
                self.assertIn(ref, event.evidence)
                self.assertEqual(sha256_bytes(blobs[ref["sha256"]]), ref["sha256"])

    def test_complete_quotes_do_not_manufacture_independent_action_coverage(self):
        for row in self.summary["cases"]:
            coverage = row["continuity_coverage"]
            self.assertEqual(coverage["status"], "UNRESOLVED")
            self.assertFalse(coverage["independent_effective_date_coverage_supplied"])
            self.assertIsNone(coverage["review_evidence"])
            self.assertFalse(coverage["source_authentication_verified"])

    def test_segmented_profile_claims_no_v18_compatibility_or_cost_estimates(self):
        result = self.result()
        self.assertEqual(result["consumer_v18"], "INCOMPATIBLE_SEGMENTED_INPUT")
        self.assertFalse(result["slippage_estimated"])
        self.assertFalse(result["fees_estimated"])
        self.assertFalse(result["opening_execution_capacity_verified"])
        self.assertFalse(result["cost_assumptions_supplied"])
        self.assertTrue(result["folds"][0]["training_spread_profile"])

    def test_uncovered_or_partial_folds_have_no_imputed_training_profile(self):
        self.assertIsNone(self.result("partial")["folds"][0]["training_spread_profile"])
        self.assertIsNone(self.result("terminal-empty")["folds"][0]["training_spread_profile"])
        self.assertGreater(self.result("partial")["counts"]["missing_symbol_sessions"], 0)

    def test_fixture_keys_and_secret_values_are_absent_from_retained_evidence(self):
        for _, blobs in self.contents.values():
            self.assertFalse(any(b"FIXTURE_NOT_A_REAL_KEY" in raw or b"FIXTURE_NOT_A_REAL_SECRET" in raw
                                 for raw in blobs.values()))
        self.assertEqual(self.summary["credential_files_read"], 0)

    def test_every_new_record_links_original_research_decision_and_off_authority(self):
        parent = self.sources["events"][0]
        for events, _ in self.contents.values():
            for event in events[14:]:
                self.assertEqual(event.decision_id, parent.decision_id)
                self.assertEqual(event.payload["links"]["hypothesis_event_id"], parent.event_id)
                document = event.payload.get("plan", event.payload.get("request"))
                self.assertFalse(document["auto_trading_enabled"])
                self.assertTrue(all(value is False for value in document["authority"].values()))

    def test_no_performance_statistics_budget_activation_or_holdout_scoring(self):
        self.assertFalse(self.summary["new_strategy_returns_computed"])
        self.assertFalse(self.summary["uncertainty_computed"])
        self.assertFalse(self.summary["economic_hypothesis_supported"])
        self.assertFalse(self.summary["desk_budget_activated"])
        self.assertFalse(self.summary["capital_transfers_enabled"])
        self.assertEqual(self.summary["provider_calls"], 0)
        self.assertEqual(self.summary["orders_submitted"], 0)
        for identity in ("full", "partial", "terminal-empty"):
            result = self.result(identity)
            self.assertFalse(result["economic_hypothesis_supported"])
            self.assertFalse(result["uncertainty_computed"])
            self.assertFalse(result["existing_gate_override"])
            self.assertEqual(result["execution_status"], "NOT_EXECUTED")
            self.assertIsNone(result["realized_trade_pnl"])
            self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")

    def test_three_journals_have_zero_orphans_and_no_inferred_capture(self):
        for row in self.summary["cases"]:
            self.assertEqual(row["journal_verification"]["orphan_evidence_count"], 0)
            self.assertEqual(row["journal_verification"]["staging_orphan_count"], 0)
        self.assertEqual(self.summary["events_written"], 74)

    def test_exact_example_retry_preserves_files_mtimes_and_partial_progress(self):
        before = state(self.root)
        with patch("blackpod_build_week.train_market_capture.capture_train_quotes", side_effect=AssertionError("implicit capture resumption forbidden")):
            result = example.prepare_example(self.root)
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(result["cases"], self.summary["cases"])
        self.assertEqual(state(self.root), before)
        self.assertEqual(result["cases"][1]["attempt_count"], 2)

    def test_retained_only_verification_works_after_capture_and_input_folders_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "copy"
            shutil.copytree(self.root, root)
            for row in self.summary["cases"]:
                shutil.rmtree(root / row["capture_root"])
                shutil.rmtree(root / row["case_id"] / "input")
                self.assertEqual(JournalStore(root / row["journal_root"]).verify().to_dict(), row["journal_verification"])

    def test_exported_plan_snapshot_and_request_contracts_are_strict(self):
        for row in self.summary["cases"]:
            plan = TrainMarketCapturePlan.from_bytes((self.root / row["plan_path"]).read_bytes())
            snapshot = TrainMarketCaptureSnapshot.from_bytes((self.root / row["snapshot_path"]).read_bytes())
            request = TrainMarketExportRequest.from_bytes((self.root / row["export_request_path"]).read_bytes())
            self.assertEqual(plan.capture_id, row["capture_id"])
            self.assertEqual(snapshot.capture_id, plan.capture_id)
            self.assertEqual(request.capture_plan_event_id, row["capture_plan_event_id"])
            self.assertEqual(snapshot.exported_at, request.exported_at)

    def test_module_imports_no_legacy_strategy_inference_or_broker_adapter(self):
        tree = ast.parse(inspect.getsource(example))
        modules = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(any(name in module for name in ("galactica", "modeldock", "navigator_adapter", "execution.broker"))
                             for module in modules))

    def test_symlink_output_rejects_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = example.main(["--output-root", str(link)])
            self.assertEqual(status, 2)
            self.assertEqual(list(target.iterdir()), [])
            self.assertEqual(output.getvalue(), "")
            self.assertTrue(errors.getvalue())


if __name__ == "__main__":
    unittest.main()
