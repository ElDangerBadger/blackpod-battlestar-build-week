"""Controlled end-to-end shadow studies use no provider or execution runtime."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.decision_journal_store import JournalStore, JournalUnsafePathError
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.trading_shadow_example import (
    EVALUATED_AT, example_material, fixture_material, main as example_main, prepare_example, zigzag_source_material,
)
from blackpod_build_week.trading_shadow_journal import (
    STUDY_TYPE, EVALUATION_TYPE, assess_registered_shadow, build_shadow_evaluation_event, build_study_event,
)


def invoke(command, arguments):
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        status = command(arguments)
    return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()


class TradingShadowExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            cls.material = example_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temporary).resolve() / "example"

    def test_zigzag_source_has_authored_positive_and_negative_close_returns(self):
        material = zigzag_source_material()
        bars_ref = material["request"].sources["bars_evidence"]
        self.assertTrue(bars_ref["path"].endswith(".raw"))
        bars = json.loads(material["blobs"][bars_ref["sha256"]])["bars"]
        for rows in bars.values():
            changes = [right["c"] - left["c"] for left, right in zip(rows, rows[1:])]
            self.assertTrue(any(change > 0 for change in changes))
            self.assertTrue(any(change < 0 for change in changes))

    def test_authored_capture_receipts_bind_changed_bar_bytes(self):
        material = zigzag_source_material()
        for kind in ("bars", "calendar"):
            body = material["request"].sources[kind + "_evidence"]
            receipt_ref = material["request"].sources[kind + "_receipt_evidence"]
            receipt = json.loads(material["blobs"][receipt_ref["sha256"]])
            self.assertEqual(receipt["body_sha256"], body["sha256"])
            self.assertEqual(receipt["size_bytes"], len(material["blobs"][body["sha256"]]))

    def test_both_hypotheses_produce_shadow_intents_and_closed_fixture_trades(self):
        self.assertEqual(len(self.material["dataset"].sessions), 40)
        self.assertEqual(len(self.material["studies"]), 2)
        for row in self.material["studies"]:
            production = row["evaluation_event"].payload["production"]
            self.assertEqual(production["status"], "PRODUCED_SHADOW_RESEARCH_ONLY")
            self.assertGreater(len(production["episodes"]), 0)
            self.assertGreater(len(production["intents"]["decisions"]), 0)
            self.assertEqual(row["result"]["status"], "SHADOW_SIMULATED")
            self.assertGreater(len(row["result"]["cost_stress_runs"][0]["candidate"]["folds"][0]["fills"]), 0)

    def test_original_quality_plans_and_hypotheses_keep_their_semantics(self):
        for row in self.material["studies"]:
            self.assertEqual(row["plan"].evaluation_purpose, "DATA_QUALITY_ONLY")
            self.assertEqual(row["plan"].strategy["implementation_status"], "EXTERNAL_INTENTS_ONLY")
            self.assertEqual(row["hypothesis"].implementation_status, "SPECIFICATION_ONLY_NO_INTENTS")
            self.assertEqual(row["intents"].decisions, [])
            original = row["plan_event"]
            self.assertEqual(original.payload["plan"], row["plan"].to_dict())
            self.assertEqual(row["plan"].domain, "TRADING")
        for event in self.material["events"]:
            if event.event_type == "TRADING_RESEARCH_EVALUATION_RECORDED":
                self.assertEqual(event.payload["result"]["evaluation_purpose"], "DATA_QUALITY_ONLY")
                self.assertIsNone(event.payload["result"]["aggregate"])

    def test_all_declared_cost_stresses_and_benchmarks_are_exercised(self):
        for row in self.material["studies"]:
            runs = row["result"]["cost_stress_runs"]
            self.assertEqual([run["multiplier"] for run in runs], ["1", "2", "4"])
            for run in runs:
                self.assertEqual(run["status"], "SIMULATED")
                self.assertEqual(run["folds"][0]["cash_benchmark"]["simulated_net_pnl"], "0")
                self.assertGreater(len(run["folds"][0]["control"]["cohorts"]), 0)
                self.assertIn(run["folds"][0]["comparison"]["status"],
                              {"COMPLETE_DESCRIPTIVE_COMPARISON", "INCONCLUSIVE"})

    def test_results_cannot_be_realized_trade_pnl_or_execution_authority(self):
        for row in self.material["studies"]:
            result = row["result"]
            self.assertEqual(result["evidence_scope"], "SYNTHETIC_FIXTURE_ONLY")
            self.assertIsNone(result["realized_trade_pnl"])
            self.assertIsNone(result["aggregate"])
            self.assertFalse(result["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in result["authority"].values()))
            for consistency in result["cost_stress_consistency"]:
                self.assertFalse(consistency["winner_selected"])
                self.assertFalse(consistency["promotion_enabled"])
                self.assertEqual(consistency["statistical_significance"], "NOT_ASSESSED")

    def test_holdout_remains_withheld_and_has_no_generated_decisions(self):
        sessions = self.material["dataset"].sessions
        index = {session["session_id"]: count for count, session in enumerate(sessions)}
        for row in self.material["studies"]:
            self.assertEqual(row["result"]["final_holdout"]["scoring_status"], "WITHHELD")
            start = row["plan"].protocol["final_holdout"]["start_index"]
            for decision in row["evaluation_event"].payload["production"]["intents"]["decisions"]:
                self.assertLess(index[decision["source_session_id"]], start)

    def test_original_ancestry_and_fixed_parameters_are_retained(self):
        for row in self.material["studies"]:
            hypothesis = row["hypothesis"]
            self.assertEqual(hypothesis.ancestry, "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")
            self.assertEqual(hypothesis.signal["parameter_selection"], "PREDECLARED_PROPOSED_NOT_TUNED")
            self.assertEqual(hypothesis.preregistration_claim, "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION")

    def test_material_bytes_and_event_ids_are_reproducible(self):
        other = example_material()
        self.assertEqual(self.material["evidence"], other["evidence"])
        self.assertEqual(self.material["blobs"], other["blobs"])
        self.assertEqual([event.to_bytes() for event in self.material["events"]],
                         [event.to_bytes() for event in other["events"]])

    def test_gate_origins_are_explicit_authored_test_evidence(self):
        material = fixture_material()
        for source in (material["price_source"], material["cost_source"]):
            self.assertEqual(source.basis, "SYNTHETIC_FIXTURE")
            for reference in source.origin_evidence:
                raw = material["blobs"][reference["sha256"]]
                self.assertEqual(sha256_bytes(raw), reference["sha256"])
                self.assertIn(b"authored", raw)

    def test_prepare_records_ten_events_with_retained_sources_and_no_orphans(self):
        result = prepare_example(self.root)
        self.assertEqual(result["events_written"], 10)
        self.assertEqual(result["journal_verification"]["event_count"], 10)
        self.assertEqual(result["journal_verification"]["orphan_evidence_count"], 0)
        self.assertGreater(result["journal_verification"]["evidence_count"], 20)
        self.assertFalse(result["real_market_performance_evaluated"])
        self.assertFalse(result["recorded_paper_budgets_used"])
        self.assertFalse(result["auto_trading_enabled"])

    def test_prepare_idempotent_retry_preserves_all_original_bytes(self):
        prepare_example(self.root)
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = prepare_example(self.root)
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(result["events_written"], 0)
        self.assertEqual(before, after)

    def test_journal_replays_after_external_example_inputs_are_removed(self):
        prepare_example(self.root)
        shutil.rmtree(self.root / "input")
        shutil.rmtree(self.root / "evidence")
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        for event in events:
            if event.event_type == STUDY_TYPE:
                replay = build_study_event(event.payload["study"], events, blobs)
                self.assertEqual(event.to_bytes(), replay.to_bytes())
            if event.event_type == EVALUATION_TYPE:
                replay = build_shadow_evaluation_event(event.payload["study"], events, blobs,
                    evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
                self.assertEqual(event.to_bytes(), replay.to_bytes())
        self.assertEqual(store.verify().event_count, 10)

    def test_read_only_assessment_does_not_change_journal_bytes(self):
        prepare_example(self.root)
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        before = {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}
        for row in self.material["studies"]:
            assessment = assess_registered_shadow(row["study"], events, blobs)
            self.assertEqual(assessment["result"], row["result"])
        after = {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}
        self.assertEqual(before, after)

    def test_main_emits_an_explicitly_synthetic_manifest(self):
        status, result, errors = invoke(example_main, ["--output-root", str(self.root)])
        self.assertEqual(status, 0, errors)
        self.assertEqual(result["data_status"], "SYNTHETIC_FIXTURE_ONLY")
        self.assertIn("NOT_ACTUAL_PROVIDER_RESPONSES", result["observations"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertFalse(result["final_holdout_scored"])

    def test_prepare_rejects_mission_storage_before_writes(self):
        protected = Path(self.temporary).resolve() / "missions" / "new-example"
        with self.assertRaises(JournalUnsafePathError):
            prepare_example(protected)
        self.assertFalse(protected.exists())

    def test_prepare_rejects_symlink_output_before_writes(self):
        external = Path(self.temporary).resolve() / "external"
        external.mkdir()
        self.root.symlink_to(external, target_is_directory=True)
        with self.assertRaises((JournalUnsafePathError, ValueError, OSError)):
            prepare_example(self.root)
        self.assertEqual(list(external.iterdir()), [])

    def test_immutable_conflicting_study_input_is_not_overwritten(self):
        target = self.root / "input/study-1.json"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"conflicting original study")
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            prepare_example(self.root)
        self.assertEqual(target.read_bytes(), b"conflicting original study")
        self.assertFalse((self.root / "journal").exists())


if __name__ == "__main__":
    unittest.main()
