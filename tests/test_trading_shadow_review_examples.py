"""Offline, reproducible review examples never claim actual market performance."""
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
from blackpod_build_week.trading_shadow_review_example import (
    EVALUATED_AT, fixture_material, example_material, prepare_example, main as example_main,
)
from blackpod_build_week.trading_shadow_review_journal import (
    CONTINUITY_TYPE, COST_TYPE, RISK_TYPE, STUDY_TYPE, EVALUATION_TYPE,
    assess_registered_reviewed_study, validate_reviewed_event,
)


def invoke(command, arguments):
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        status = command(arguments)
    return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()


class GovernedShadowExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("process forbidden")):
            cls.material = example_material()
            cls.shared_temp = tempfile.TemporaryDirectory()
            cls.shared_root = Path(cls.shared_temp.name).resolve() / "source-example"
            cls.prepared = prepare_example(cls.shared_root)

    @classmethod
    def tearDownClass(cls):
        cls.shared_temp.cleanup()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temporary).resolve() / "example"

    def copy_example(self):
        shutil.copytree(self.shared_root, self.root)
        return self.root

    def test_forty_sessions_eighty_native_quotes_and_independent_coverage(self):
        m = self.material
        self.assertEqual(len(m["dataset"].sessions), 40)
        self.assertEqual(m["costs"]["assessment"]["native_quote_count"], 80)
        self.assertEqual(m["costs"]["assessment"]["eligible_opening_quote_count"], 80)
        self.assertEqual(m["costs"]["assessment"]["missing_symbol_sessions"], [])
        self.assertEqual(m["continuity"]["export"].derived_event_count, 0)
        self.assertTrue(m["continuity"]["export"].coverage_review_supported)
        self.assertEqual(m["coverage_review"].status, "SUPPORTED")

    def test_measured_spread_and_declared_fee_assumptions_have_distinct_origins(self):
        m = self.material
        model = m["costs"]["review"].cost_model
        self.assertEqual(model["slippage_bps"], "5")
        self.assertEqual(model["fee_bps"], "0")
        self.assertEqual(model["fee_per_fill"], "0.10")
        self.assertEqual(model["spread_bps"], "9.995002498750624688")
        refs = m["costs"]["source"].origin_evidence
        paths = {ref["path"] for ref in refs}
        self.assertIn("synthetic-reviewed/quotes.raw", paths)
        self.assertIn("synthetic-reviewed/cost-assumptions-origin.raw", paths)
        raw = m["evidence"]["synthetic-reviewed/cost-assumptions-origin.raw"]
        self.assertIn(b"not quotes, observed executions", raw)

    def test_approved_reviews_only_declare_toy_sizing_and_simulation_caps(self):
        for row in self.material["studies"]:
            review = row["risk_review"]
            self.assertEqual(review.status, "APPROVED_FOR_SHADOW")
            self.assertEqual(review.sizing["per_symbol_notional"], "60")
            self.assertEqual(review.simulation_risk["initial_cash"], "1000")
            self.assertEqual(review.simulation_risk["max_order_notional"], "100")
            self.assertEqual(review.simulation_risk["max_position_fraction"], "0.1")
            self.assertEqual(review.simulation_risk["max_gross_exposure_fraction"], "0.2")
            self.assertFalse(row["result"]["risk_assessment"]["provenance"]["desk_budget_activated"])
            self.assertFalse(row["result"]["risk_assessment"]["provenance"]["human_execution_approval_verified"])

    def test_both_hypotheses_generate_episodes_and_simulated_closed_trades(self):
        for row in self.material["studies"]:
            self.assertEqual(row["result"]["status"], "SHADOW_SIMULATED")
            production = row["evaluation_event"].payload["production"]
            self.assertEqual(production["status"], "PRODUCED_SHADOW_RESEARCH_ONLY")
            self.assertGreater(len(production["episodes"]), 0)
            self.assertGreater(len(production["intents"]["decisions"]), 0)
            calculation = row["result"]["calculation_result"]
            self.assertGreater(len(calculation["cost_stress_runs"][0]["candidate"]["folds"][0]["fills"]), 0)

    def test_all_stress_multipliers_and_matched_controls_are_exercised(self):
        for row in self.material["studies"]:
            runs = row["result"]["calculation_result"]["cost_stress_runs"]
            self.assertEqual([run["multiplier"] for run in runs], ["1", "2", "4"])
            for run in runs:
                self.assertEqual(run["status"], "SIMULATED")
                self.assertGreater(len(run["folds"][0]["control"]["cohorts"]), 0)
                self.assertEqual(run["folds"][0]["cash_benchmark"]["simulated_net_pnl"], "0")

    def test_original_quality_plans_are_immutable_and_unscored(self):
        for row in self.material["studies"]:
            self.assertEqual(row["plan"].evaluation_purpose, "DATA_QUALITY_ONLY")
            self.assertEqual(row["plan"].strategy["implementation_status"], "EXTERNAL_INTENTS_ONLY")
            self.assertEqual(row["plan_event"].payload["plan"], row["plan"].to_dict())
            self.assertEqual(row["intents"].decisions, [])
            self.assertEqual(row["result"]["original_simulation_risk"], row["plan"].risk)
            self.assertEqual(row["result"]["reviewed_simulation_risk"], row["risk_review"].simulation_risk)
            original_ref = row["study"].base_plan_evidence
            self.assertEqual(sha256_bytes(row["plan"].to_bytes()), original_ref["sha256"])
            self.assertEqual(self.material["blobs"][original_ref["sha256"]], row["plan"].to_bytes())
            self.assertEqual(row["evaluation_event"].payload["result"]["internal_risk_projection_semantics"],
                             "EPHEMERAL_SIMULATION_ONLY_ORIGINAL_PLAN_UNMODIFIED")

    def test_hypotheses_remain_independent_fixed_unproven_specifications(self):
        for row in self.material["studies"]:
            hypothesis = row["hypothesis"]
            self.assertEqual(hypothesis.ancestry, "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")
            self.assertEqual(hypothesis.signal["parameter_selection"], "PREDECLARED_PROPOSED_NOT_TUNED")
            self.assertEqual(hypothesis.preregistration_claim, "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION")

    def test_holdout_is_withheld_without_generated_decisions(self):
        sessions = self.material["dataset"].sessions
        positions = {session["session_id"]: index for index, session in enumerate(sessions)}
        for row in self.material["studies"]:
            self.assertEqual(row["result"]["final_holdout"]["scoring_status"], "WITHHELD")
            cutoff = row["plan"].protocol["final_holdout"]["start_index"]
            for decision in row["evaluation_event"].payload["production"]["intents"]["decisions"]:
                self.assertLess(positions[decision["source_session_id"]], cutoff)

    def test_fourteen_events_preserve_six_original_foundation_events(self):
        events = self.material["events"]
        self.assertEqual(len(events), 14)
        self.assertEqual([event.event_type for event in events[6:10]], [CONTINUITY_TYPE, COST_TYPE, RISK_TYPE, RISK_TYPE])
        self.assertEqual([event.event_type for event in events[10:]], [STUDY_TYPE, EVALUATION_TYPE, STUDY_TYPE, EVALUATION_TYPE])
        self.assertNotIn("TRADING_SHADOW_STUDY_REGISTERED", [event.event_type for event in events])
        self.assertTrue(all(event.schema_version == "blackpod.decision_journal_event.v16" for event in events[6:]))

    def test_review_study_events_link_exact_preceding_evidence_and_risk(self):
        expected_intakes = self.material["intake_events"]
        for row in self.material["studies"]:
            event = row["study_event"]
            self.assertEqual(event.payload["risk_review_event_id"], row["risk_event"].event_id)
            self.assertEqual(event.payload["continuity_event_id"], expected_intakes[0].event_id)
            self.assertEqual(event.payload["cost_event_id"], expected_intakes[1].event_id)
            self.assertEqual(row["evaluation_event"].payload["study_event_id"], event.event_id)
            self.assertEqual(row["evaluation_event"].recorded_at, EVALUATED_AT)

    def test_all_authority_is_off_and_realized_trade_pnl_is_absent(self):
        for row in self.material["studies"]:
            result = row["result"]
            self.assertIsNone(result["realized_trade_pnl"])
            self.assertFalse(result["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in result["authority"].values()))
            self.assertFalse(result["gate_assessment"]["provenance"]["provider_authenticity_verified"])
            self.assertFalse(result["gate_assessment"]["provenance"]["human_execution_approval_verified"])
            self.assertFalse(result["trial_registry"]["global_trial_completeness_verified"])
            self.assertFalse(result["trial_registry"]["prospective_preregistration_verified"])

    def test_every_origin_remains_authored_and_hash_bound(self):
        material = fixture_material()
        for doc in (material["coverage_review"], material["assumptions"], *(row["risk_review"] for row in material["studies"])):
            refs = doc.source_evidence if hasattr(doc, "source_evidence") else doc.origin_evidence
            for ref in refs:
                raw = material["blobs"][ref["sha256"]]
                self.assertEqual(sha256_bytes(raw), ref["sha256"])
                self.assertIn(b"authored", raw.lower())

    def test_material_event_bytes_and_identity_are_reproducible(self):
        other = example_material()
        self.assertEqual(other["evidence"], self.material["evidence"])
        self.assertEqual([event.to_bytes() for event in other["events"]],
                         [event.to_bytes() for event in self.material["events"]])

    def test_prepared_journal_has_fourteen_events_and_zero_orphans(self):
        result = self.prepared
        self.assertEqual(result["events_written"], 14)
        self.assertEqual(result["journal_verification"]["event_count"], 14)
        self.assertEqual(result["journal_verification"]["orphan_evidence_count"], 0)
        self.assertEqual(result["journal_verification"]["evidence_count"], 53)
        self.assertFalse(result["real_market_performance_evaluated"])
        self.assertFalse(result["recorded_paper_budgets_used"])
        self.assertFalse(result["desk_budget_activated"])

    def test_idempotent_cli_retry_preserves_every_original_byte(self):
        self.copy_example()
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        status, result, errors = invoke(example_main, ["--output-root", str(self.root)])
        self.assertEqual(status, 0, errors)
        self.assertEqual(result["events_written"], 0)
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertFalse(result["final_holdout_scored"])

    def test_journal_replays_with_external_inputs_removed(self):
        self.copy_example()
        shutil.rmtree(self.root / "input"); shutil.rmtree(self.root / "evidence")
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        for index, event in enumerate(events):
            if event.schema_version == "blackpod.decision_journal_event.v16":
                validate_reviewed_event(event, events[:index], blobs)
        self.assertEqual(store.verify().event_count, 14)

    def test_read_only_assessment_preserves_original_journal_entries(self):
        self.copy_example(); store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        before = {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}
        for row in self.material["studies"]:
            result = assess_registered_reviewed_study(row["study"], events, blobs)
            self.assertEqual(result["result"], row["result"])
        after = {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}
        self.assertEqual(before, after)

    def test_unsafe_mission_storage_rejected_before_files_are_written(self):
        target = Path(self.temporary).resolve() / "missions" / "new-example"
        with self.assertRaises(JournalUnsafePathError): prepare_example(target)
        self.assertFalse(target.exists())

    def test_symlink_output_rejected_before_files_are_written(self):
        external = Path(self.temporary).resolve() / "external"; external.mkdir()
        self.root.symlink_to(external, target_is_directory=True)
        with self.assertRaises((JournalUnsafePathError, ValueError, OSError)): prepare_example(self.root)
        self.assertEqual(list(external.iterdir()), [])

    def test_conflicting_original_study_file_never_overwritten(self):
        target = self.root / "input/study-1.json"; target.parent.mkdir(parents=True)
        target.write_bytes(b"conflicting original study")
        with self.assertRaises((ValueError, OSError, RuntimeError)): prepare_example(self.root)
        self.assertEqual(target.read_bytes(), b"conflicting original study")
        self.assertFalse((self.root / "journal").exists())


if __name__ == "__main__":
    unittest.main()
