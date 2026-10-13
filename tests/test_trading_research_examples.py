"""Runnable independent synthetic research, portable replay and passive effects."""
from __future__ import annotations

import ast
import contextlib
from decimal import Decimal
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_research_example import (
    EVALUATED_AT, EVALUATION_ID, SYMBOLS, example_material, main, prepare_example,
)
from blackpod_build_week.trading_research_evaluation import evaluate_research


class TradingResearchExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "example"

    def call(self, function, argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = function(argv)
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def tree(self, root=None):
        root = root or self.root
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def test_material_is_deterministic_and_entirely_synthetic(self):
        first, second = example_material(), example_material()
        for key in ("plan", "dataset", "intents", "plan_event", "evaluation_event"):
            self.assertEqual(first[key].to_bytes(), second[key].to_bytes())
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertEqual(first["result"], second["result"])
        self.assertEqual(first["dataset"].universe, SYMBOLS)
        self.assertEqual(first["dataset"].provenance["source_kind"], "SYNTHETIC_FIXTURE")
        self.assertEqual(first["dataset"].provenance["timestamp_policy"], "SYNTHETIC_DECLARED")
        self.assertFalse(first["dataset"].provenance["historical_point_in_time_verified"])
        source = json.loads(first["evidence"]["market/synthetic-source.json"])
        self.assertEqual(source["sessions"], first["dataset"].sessions)
        self.assertEqual(source["data_status"], "SYNTHETIC_FIXTURE")

    def test_source_dataset_and_intents_retain_exact_declared_bytes(self):
        material = example_material()
        for reference in (material["plan"].dataset_evidence, material["plan"].intents_evidence,
                          material["dataset"].provenance["source_evidence"][0]):
            raw = material["evidence"][reference["path"]]
            self.assertEqual(sha256_bytes(raw), reference["sha256"])
            self.assertEqual(len(raw), reference["size_bytes"])
            self.assertEqual(material["blobs"][reference["sha256"]], raw)
        self.assertEqual(material["evidence"]["research/dataset.json"], material["dataset"].to_bytes())
        self.assertEqual(material["evidence"]["research/intents.json"], material["intents"].to_bytes())

    def test_external_decisions_and_sizes_are_authored_not_a_strategy(self):
        material = example_material()
        self.assertEqual(material["intents"].origin, "EXTERNALLY_AUTHORED_RESEARCH_ONLY")
        self.assertEqual(material["plan"].strategy["implementation_status"], "EXTERNAL_INTENTS_ONLY")
        self.assertEqual(material["plan"].strategy["ancestry"], "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")
        self.assertIn("No economic edge claimed", material["plan"].strategy["expected_edge"])
        self.assertEqual(material["plan"].risk["initial_cash"], "1000")
        self.assertEqual(len(material["intents"].decisions), 5)
        self.assertEqual([row["qty"] for row in material["intents"].decisions], ["2", "10000", "0", "1", "1"])

    def test_example_imports_no_legacy_strategy_provider_or_executor(self):
        source = Path(__file__).resolve().parents[1] / "src/blackpod_build_week/trading_research_example.py"
        names = set()
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                names.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
        forbidden = {"galactica_trading_adapter", "auto_trading_worker", "modeldock_client", "shadow_native_analysis",
                     "shadow_galactica_analysis", "shadow_brigade_analysis", "shadow_quantitative_producer", "pickle", "joblib"}
        self.assertTrue(names.isdisjoint(forbidden), names & forbidden)
        for forbidden_text in ("from test_", "import test_", "buried_treasure", "api_keys.yaml", "AutoTradingController"):
            self.assertNotIn(forbidden_text, source.read_text())

    def test_simulation_has_partial_fifo_exits_hold_and_oversize_rejection(self):
        material = example_material()
        fold = material["result"]["folds"][0]
        self.assertEqual(fold["status"], "SIMULATED")
        self.assertEqual(len(fold["fills"]), 3)
        self.assertEqual([fill["side"] for fill in fold["fills"]], ["BUY", "SELL", "SELL"])
        self.assertEqual(len(fold["matched_lots"]), 2)
        self.assertEqual([row["qty"] for row in fold["matched_lots"]], ["1", "1"])
        self.assertTrue(any(row["decision_id"] == "synthetic-oversize-reject" for row in fold["rejections"]))
        self.assertFalse(any(fill["decision_id"] in ("synthetic-oversize-reject", "synthetic-hold") for fill in fold["fills"]))

    def test_authority_realized_returns_and_holdout_remain_separate(self):
        material = example_material()
        for document in (material["plan"], material["dataset"], material["intents"]):
            self.assertFalse(any(document.authority.values()))
        result = material["result"]
        self.assertFalse(any(result["authority"].values()))
        self.assertFalse(result["auto_trading_enabled"])
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertIsNone(result["aggregate"])
        self.assertEqual(material["plan"].protocol["final_holdout"], {"start_index": 11, "end_index": 11})
        self.assertFalse(any(fill["execution_session_id"] == "synthetic-session-11" for fill in result["folds"][0]["fills"]))

    def test_expected_costs_and_partial_fee_accounting_conserve_simulated_cash(self):
        fold = example_material()["result"]["folds"][0]
        self.assertEqual([fill["price"] for fill in fold["fills"]], ["100.1", "101.898", "102.897"])
        self.assertEqual([row["allocated_entry_fee"] for row in fold["matched_lots"]], ["0.05", "0.05"])
        metrics = fold["metrics"]
        self.assertEqual(metrics["simulated_total_pnl"], "4.295")
        self.assertEqual(metrics["ending_equity"], "1004.295")
        self.assertEqual(metrics["fees"], "0.3")
        self.assertEqual(metrics["adverse_price_cost"], "0.405")
        self.assertEqual(metrics["modeled_total_cost"], "0.705")
        self.assertEqual(Decimal(metrics["ending_equity"]) - Decimal(metrics["initial_cash"]), Decimal(metrics["simulated_total_pnl"]))
        self.assertEqual(sum(Decimal(row["simulated_net_pnl"]) for row in fold["matched_lots"]), Decimal("4.295"))
        self.assertEqual(fold["open_lots"], [])

    def test_day_variant_defers_without_swing_substitution(self):
        material = example_material()
        value = material["plan"].to_dict()
        value["horizon"]["kind"] = "DAY"
        result = evaluate_research(TradingResearchPlan.from_mapping(value), material["dataset"], material["intents"])
        self.assertEqual(result["folds"][0]["status"], "DEFER_UNSUPPORTED_DAY_HORIZON")
        self.assertEqual(result["folds"][0]["fills"], [])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_prepare_is_immutable_idempotent_and_registers_only_plan(self):
        first = prepare_example(self.root)
        retained = self.tree()
        second = prepare_example(self.root)
        self.assertTrue(first["seed_written"])
        self.assertFalse(second["seed_written"])
        self.assertEqual(self.tree(), retained)
        self.assertEqual(first["data_status"], "SYNTHETIC_FIXTURE")
        self.assertEqual(first["orders_submitted"], 0)
        self.assertEqual(first["provider_calls"], 0)
        self.assertEqual(first["model_inference_calls"], 0)
        self.assertFalse(first["recorded_paper_budgets_used"])
        self.assertFalse(first["auto_trading_changed"])
        store = JournalStore(self.root / "journal")
        self.assertEqual(store.verify().event_count, 1)
        self.assertEqual(store.verify().orphan_evidence_count, 0)
        self.assertEqual(store.events()[0].event_id, first["expected_ids"]["plan_event_id"])

    def test_preparation_and_material_never_call_network_process_inference_or_activation(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")), \
                patch.object(subprocess, "run", side_effect=AssertionError("process forbidden")), \
                patch("pickle.loads", side_effect=AssertionError("model restore forbidden")), \
                patch("blackpod_build_week.auto_trading_runtime.enable_trading", side_effect=AssertionError("activation forbidden")), \
                patch("blackpod_build_week.modeldock_client.ModelDockClient.generate_text", side_effect=AssertionError("inference forbidden")):
            result = self.call(main, ["--output-root", str(self.root)])
        self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(any(result["authority"].values()))

    def test_retained_journal_can_reproduce_evaluation_without_original_input_directory(self):
        from blackpod_build_week.trading_research_journal import build_evaluation_event, evidence_for_research
        prepare_example(self.root)
        copied = self.root.parent / "portable"
        shutil.copytree(self.root / "journal", copied)
        shutil.rmtree(self.root)
        store = JournalStore(copied)
        events, blobs = store.verified_contents()
        plan = TradingResearchPlan.from_mapping(events[0].payload["plan"])
        event = build_evaluation_event(plan, events, blobs, evaluation_id=EVALUATION_ID, recorded_at=EVALUATED_AT)
        self.assertTrue(store.append(event, evidence_for_research(plan, blobs)).written)
        self.assertEqual(store.verify().event_count, 2)
        self.assertEqual(store.verify().orphan_evidence_count, 0)

    def test_existing_changed_input_cannot_be_overwritten(self):
        prepare_example(self.root)
        changed = b"existing unrelated research plan\n"
        (self.root / "input/plan.json").write_bytes(changed)
        with self.assertRaises((ValueError, OSError, JournalStoreError)):
            prepare_example(self.root)
        self.assertEqual((self.root / "input/plan.json").read_bytes(), changed)

    def test_source_tree_and_symlink_output_reject_without_changes(self):
        target = Path(__file__).resolve().parents[1] / "fixtures/synthetic-trading-research-write-test"
        with self.assertRaises((ValueError, OSError, JournalStoreError)):
            prepare_example(target)
        self.assertFalse(target.exists())
        real = self.root.parent / "real"
        real.mkdir()
        self.root.symlink_to(real, target_is_directory=True)
        with self.assertRaises((ValueError, OSError, JournalStoreError)):
            prepare_example(self.root)
        self.assertEqual(list(real.iterdir()), [])

    def test_cli_register_evaluate_record_show_and_retry_are_passive(self):
        from blackpod_build_week.trading_research_cli import main as research_cli
        prepared = prepare_example(self.root)
        args = ["--plan", str(self.root / "input/plan.json"), "--evidence-root", str(self.root / "evidence"),
                "--journal-root", str(self.root / "journal")]
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")), \
                patch("blackpod_build_week.auto_trading_runtime.enable_trading", side_effect=AssertionError("activation forbidden")):
            registered = self.call(research_cli, ["register", *args])
            self.assertFalse(registered["written"])
            before = self.tree()
            evaluated = self.call(research_cli, ["evaluate", *args])
            self.assertEqual(self.tree(), before)
            self.assertEqual(evaluated["result"], example_material()["result"])
            command = ["record", *args, "--evaluation-id", EVALUATION_ID, "--recorded-at", EVALUATED_AT]
            recorded = self.call(research_cli, command)
            self.assertTrue(recorded["written"])
            self.assertEqual(recorded["event_id"], prepared["expected_ids"]["evaluation_event_id"])
            self.assertFalse(self.call(research_cli, command)["written"])
            shown = self.call(research_cli, ["show", "--journal-root", str(self.root / "journal"), "--event-id", recorded["event_id"]])
            self.assertEqual(shown["event_id"], recorded["event_id"])
        result = JournalStore(self.root / "journal").verify()
        self.assertEqual(result.event_count, 2)
        self.assertEqual(result.orphan_evidence_count, 0)

    def test_changed_evidence_rejects_before_evaluation_or_record(self):
        from blackpod_build_week.trading_research_cli import main as research_cli
        prepare_example(self.root)
        source = self.root / "evidence/research/dataset.json"
        source.write_bytes(source.read_bytes() + b"\n")
        args = ["--plan", str(self.root / "input/plan.json"), "--evidence-root", str(self.root / "evidence"),
                "--journal-root", str(self.root / "journal")]
        # A retained journal can satisfy the same hash binding without reading
        # a changed redundant copy. Use a separate unregistered journal to
        # exercise explicit input integrity rather than forcing disk reload.
        args[-1] = str(self.root.parent / "unregistered-journal")
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = research_cli(["register", *args])
        self.assertEqual(status, 2)
        self.assertEqual(JournalStore(self.root / "journal").verify().event_count, 1)
        self.assertEqual(source.read_bytes()[-1:], b"\n")


if __name__ == "__main__":
    unittest.main()
