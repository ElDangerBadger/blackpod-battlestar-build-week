"""Coverage reports distinguish fixture software tests from market evidence."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.research_acceptance_examples import representative_material
from blackpod_build_week.research_acceptance_journal import assessment_material
from blackpod_build_week.research_baseline import build_baseline_report, baseline_from_journal
from blackpod_build_week.research_baseline_cli import main


AS_OF = "2027-04-12T00:00:00Z"


class ResearchBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")):
            cls.material = representative_material()
            events, blobs = list(cls.material["events"]), dict(cls.material["blobs"])
            cls.assessment_evidence = []
            for case in cls.material["cases"]:
                blobs.update({sha256_bytes(raw): raw for raw in case.get("extra_evidence", {}).values()})
                result = assessment_material(case["request"], events, blobs)
                events.append(result["event"])
                blobs.update({sha256_bytes(raw): raw for raw in result["evidence"].values()})
                cls.assessment_evidence.append(result["evidence"])
            cls.events, cls.blobs = tuple(events), blobs

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def report(self, events=None, cohort="SYNTHETIC_FIXTURE_ONLY", as_of=AS_OF):
        return build_baseline_report(self.events if events is None else events,
                                     self.blobs, cohort=cohort, as_of=as_of)

    def test_same_retained_inputs_produce_identical_report_bytes_and_identity(self):
        self.assertEqual(canonical_json_bytes(self.report()), canonical_json_bytes(self.report()))
        report = self.report()
        identity = report.pop("report_id")
        self.assertEqual(identity, "research-baseline-" + sha256_bytes(canonical_json_bytes(report)))

    def test_report_binds_exact_calculation_sources_and_changes_identity_with_them(self):
        report = self.report(events=())
        prefix = "research-baseline/implementation/"
        package = Path(__file__).resolve().parents[1] / "src/blackpod_build_week"
        self.assertEqual(len(report["implementation_evidence"]), 4)
        for reference in report["implementation_evidence"]:
            raw = (package / reference["path"][len(prefix):]).read_bytes()
            self.assertEqual(reference["sha256"], sha256_bytes(raw))
            self.assertEqual(reference["size_bytes"], len(raw))
        changed = deepcopy(report["implementation_evidence"])
        changed[0]["sha256"] = "0" * 64
        with patch("blackpod_build_week.research_baseline._implementation_references", return_value=changed):
            self.assertNotEqual(self.report(events=())["report_id"], report["report_id"])

    def test_desks_horizons_and_methods_remain_distinct(self):
        report = self.report()
        trading, investment = report["domains"]
        self.assertEqual(trading["domain"], "TRADING")
        self.assertEqual(investment["domain"], "INVESTMENT")
        self.assertEqual(trading["hypothesis_revision_count"], 2)
        self.assertEqual(investment["hypothesis_revision_count"], 1)
        self.assertEqual(len(trading["horizon_counts"]), 2)
        self.assertEqual(len(investment["horizon_counts"]), 1)
        self.assertNotEqual(trading["methodology_counts"], investment["methodology_counts"])

    def test_assessment_scopes_not_counted_as_independent_evaluations(self):
        report = self.report()
        trading, investment = report["domains"]
        self.assertEqual(trading["active_assessment_count"], 5)
        self.assertEqual(investment["active_assessment_count"], 2)
        self.assertEqual(trading["distinct_assessed_evaluation_count"], 3)
        self.assertEqual(investment["distinct_assessed_evaluation_count"], 1)
        self.assertEqual(investment["assessed_hypothesis_revision_count"], 1)

    def test_eligibility_and_outcome_stored_separately(self):
        report = self.report()
        unperformed = next(row for row in report["assessments"] if row["state"]["original_classification"] == "EVALUABLE")
        self.assertEqual(unperformed["state"]["eligibility"], "EVALUABLE")
        self.assertIsNone(unperformed["state"]["outcome"])
        self.assertFalse(unperformed["state"]["evaluation_performed"])
        supported = next(row for row in report["assessments"] if row["state"]["original_classification"] == "SUPPORTED")
        self.assertEqual(supported["state"]["outcome"], "SUPPORTED")

    def test_synthetic_support_never_becomes_predictive_effectiveness(self):
        report = self.report()
        self.assertFalse(report["cohort"]["authenticated"])
        self.assertFalse(report["cohort"]["historical_point_in_time_verified"])
        for metric in report["metrics"].values():
            self.assertIsNone(metric["value"])
            self.assertEqual(metric["status"], "UNAVAILABLE")
            self.assertTrue(metric["reason_code"])
        self.assertIn("SYNTHETIC_COUNTS_AND_VALUES_ESTABLISH_SOFTWARE_BEHAVIOR_ONLY", report["limitations"])

    def test_no_improper_cross_domain_or_fold_performance_aggregation(self):
        report = self.report()
        self.assertNotIn("combined_return", report)
        evaluations = [row for row in report["native_evaluations"] if row["domain"] == "TRADING"]
        comparisons = [measurement for row in evaluations for measurement in row["measurements"]
                       if measurement["kind"] == "NATIVE_DESCRIPTIVE_COMPARISON"]
        self.assertTrue(comparisons)
        self.assertEqual({row["cost_multiplier"] for row in comparisons}, {"1", "2", "4"})
        self.assertTrue(all("fold_id" in row for row in comparisons))
        self.assertTrue(all(row["realized_trade_pnl"] is None for row in evaluations))

    def test_pure_report_does_not_claim_whole_journal_verification(self):
        self.assertEqual(self.report()["verification"]["scope"], "TYPED_EVENTS_AND_SELECTED_ASSESSMENT_REPLAY_ONLY")

    def test_future_records_cannot_be_backdated_into_earlier_baseline(self):
        with self.assertRaisesRegex(ValueError, "clock"):
            self.report(as_of="2026-10-13T00:00:00Z")

    def test_explicit_fixture_rejected_in_every_real_cohort(self):
        for cohort in ("RECORDED_HISTORICAL_HYPOTHESES", "RECONSTRUCTED_HISTORICAL_RESEARCH", "PROSPECTIVE_SHADOW_RESEARCH"):
            with self.subTest(cohort=cohort), self.assertRaisesRegex(ValueError, "synthetic"):
                self.report(cohort=cohort)

    def test_cohort_has_no_default_or_unknown_value(self):
        for value in (None, "", "REAL", [], True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.report(cohort=value)

    def test_duplicate_source_event_is_deduplicated_without_extra_sample(self):
        original = self.report()
        duplicated = self.report(events=(*self.events, self.events[-1]))
        self.assertEqual(duplicated["verification"]["duplicate_input_event_count"], 1)
        self.assertEqual(duplicated["domains"], original["domains"])
        self.assertEqual(duplicated["verification"]["ordered_event_set_sha256"], original["verification"]["ordered_event_set_sha256"])

    def test_same_event_identity_changed_bytes_rejected(self):
        value = self.events[-1].to_dict()
        value["payload"]["assessment"]["claim_scope"] += " Changed bytes."
        changed = JournalEvent.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "conflicting"):
            self.report(events=(*self.events, changed))

    def test_source_records_and_blobs_are_unchanged(self):
        before = [event.to_bytes() for event in self.events], dict(self.blobs)
        self.report()
        self.assertEqual(before, ([event.to_bytes() for event in self.events], self.blobs))

    def test_superseded_assessment_stays_visible_but_not_active(self):
        old = self.events[-1]
        request = deepcopy(old.payload["request"])
        request.update(assessment_id="baseline-linked-correction", supersedes_event_id=old.event_id,
                       recorded_at="2027-04-11T00:02:00Z")
        result = assessment_material(request, self.events, self.blobs)
        blobs = {**self.blobs, **{sha256_bytes(raw): raw for raw in result["evidence"].values()}}
        report = build_baseline_report((*self.events, result["event"]), blobs,
                                      cohort="SYNTHETIC_FIXTURE_ONLY", as_of=AS_OF)
        self.assertEqual(len(report["assessments"]), 8)
        self.assertTrue(next(row for row in report["assessments"] if row["event_id"] == old.event_id)["superseded"])
        self.assertEqual(report["domains"][1]["active_assessment_count"], 2)

    def test_forecasts_expose_horizons_and_missing_outcomes_without_scoring(self):
        from test_forecast_intake_engine import ForecastIntakeFixture
        from blackpod_build_week.forecast_journal import build_forecast_intake_event
        fixture = ForecastIntakeFixture()
        event = build_forecast_intake_event(fixture.document, (), fixture.blobs)
        report = build_baseline_report((event,), fixture.blobs,
            cohort="SYNTHETIC_FIXTURE_ONLY", as_of="2026-10-14T00:00:00Z")
        coverage = report["forecast_coverage"]
        self.assertEqual(coverage["row_count"], 3)
        self.assertEqual(coverage["elapsed_target_count"], 1)
        self.assertEqual(coverage["outcome_count"], 0)
        self.assertEqual(coverage["evaluation_count"], 0)
        self.assertEqual(len(coverage["horizon_counts"]), 3)
        self.assertTrue(all(row["outcome_available"] is False for row in report["forecast_rows"]))
        self.assertIsNone(report["metrics"]["forecast_error"]["value"])

    def test_retrospective_mode_cannot_be_claimed_historical_or_prospective(self):
        from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
        from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
        material = self.material["investment"]
        source = material["hypothesis_event"]
        prefix = material["events"][:material["events"].index(source)]
        value = material["hypothesis"].to_dict()
        value["research_mode"] = "RETROSPECTIVE"
        hypothesis = InvestmentHypothesis.from_mapping(value)
        event = build_hypothesis_event(hypothesis, prefix, material["blobs"])
        retained = evidence_for_hypothesis(hypothesis, prefix, material["blobs"])
        blobs = {**material["blobs"], **{sha256_bytes(raw): raw for raw in retained.values()}}
        for cohort in ("RECORDED_HISTORICAL_HYPOTHESES", "PROSPECTIVE_SHADOW_RESEARCH"):
            with self.subTest(cohort=cohort), self.assertRaisesRegex(ValueError, "retrospective"):
                build_baseline_report((*prefix, event), blobs,
                                      cohort=cohort, as_of=AS_OF)

    def test_shared_forecast_evidence_retains_each_desk_and_intake_review(self):
        from test_forecast_intake_engine import ForecastIntakeFixture
        from blackpod_build_week.contracts.forecast_intake import ForecastIntake
        from blackpod_build_week.forecast_journal import build_forecast_intake_event
        fixture = ForecastIntakeFixture()
        events = []
        for domain, identity in (("TRADING", "first"), ("INVESTMENT", "second"), ("TRADING", "third")):
            value = fixture.document.to_dict()
            value.update(domain=domain, intake_id=identity)
            events.append(build_forecast_intake_event(ForecastIntake.from_mapping(value), (), fixture.blobs))
        report = build_baseline_report(events, fixture.blobs, cohort="SYNTHETIC_FIXTURE_ONLY", as_of=AS_OF)
        self.assertEqual(report["forecast_coverage"]["row_count"], 9)
        self.assertEqual(report["forecast_coverage"]["unique_raw_source_row_count"], 3)
        self.assertEqual(report["forecast_coverage"]["unique_domain_source_row_count"], 6)
        self.assertEqual({row["domain"] for row in report["forecast_rows"]}, {"TRADING", "INVESTMENT"})
        self.assertEqual({row["intake_id"] for row in report["forecast_rows"]}, {"first", "second", "third"})

    def test_native_evaluator_v1_metrics_and_cash_benchmark_are_retained(self):
        from blackpod_build_week.trading_research_example import example_material
        from blackpod_build_week.trading_research_journal import build_plan_event, build_evaluation_event
        material = example_material()
        plan = build_plan_event(material["plan"], (), material["blobs"])
        evaluation = build_evaluation_event(material["plan"], (plan,), material["blobs"],
            evaluation_id="baseline-native-v1", recorded_at="2026-07-02T00:00:00Z")
        report = build_baseline_report((plan, evaluation), material["blobs"], cohort="SYNTHETIC_FIXTURE_ONLY", as_of=AS_OF)
        self.assertEqual(report["domains"][0]["native_measured_evaluation_count"], 1)
        row = report["native_evaluations"][0]
        self.assertTrue(row["measurement_performed"])
        self.assertTrue(row["native_fold_statuses"])
        self.assertTrue(row["measurements"])
        self.assertIn("benchmark", row["measurements"][0])
        self.assertIsNone(report["metrics"]["predictive_effectiveness"]["value"])

    def test_known_historical_trading_plan_cannot_be_relabeled_prospective(self):
        from blackpod_build_week.trading_historical_example import example_material
        material = example_material()
        with self.assertRaisesRegex(ValueError, "reconstructed historical trading"):
            build_baseline_report(material["events"], material["blobs"],
                                  cohort="PROSPECTIVE_SHADOW_RESEARCH", as_of=AS_OF)

    def test_frozen_specification_without_historical_study_is_collectable(self):
        catalog = next(event for event in self.material["events"]
                       if event.event_type == "TRADING_HYPOTHESIS_CATALOG_RECORDED")
        report = build_baseline_report((catalog,), self.blobs,
            cohort="PROSPECTIVE_SHADOW_RESEARCH", as_of=AS_OF)
        self.assertEqual(report["domains"][0]["hypothesis_revision_count"], 2)
        self.assertFalse(report["cohort"]["authenticated"])
        self.assertEqual(report["domains"][0]["native_measured_evaluation_count"], 0)

    def test_missing_assessment_evidence_rejects_report(self):
        blobs = dict(self.blobs)
        del blobs[self.events[-1].payload["request"]["hypothesis"]["evidence"]["sha256"]]
        with self.assertRaises(ValueError):
            build_baseline_report(self.events, blobs, cohort="SYNTHETIC_FIXTURE_ONLY", as_of=AS_OF)

    def test_empty_history_reports_zero_not_zero_accuracy(self):
        report = self.report(events=())
        self.assertEqual(report["verification"]["event_count"], 0)
        self.assertTrue(all(row["hypothesis_revision_count"] == 0 for row in report["domains"]))
        self.assertIsNone(report["metrics"]["directional_accuracy"]["value"])

    def test_every_authority_and_execution_field_remains_disabled(self):
        report = self.report()
        self.assertFalse(report["auto_trading_enabled"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual(report["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(report["realized_trade_pnl"])

    def test_cli_full_replay_retry_and_source_preservation(self):
        from blackpod_build_week.decision_journal_store import JournalStore
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            journal, target = root / "journal", root / "reports/baseline.json"
            store = JournalStore(journal)
            # Smaller actual mixed-version investment fixture, not a mocked verifier.
            investment = self.material["investment"]
            for event, evidence in zip(investment["events"], investment["event_evidence"]):
                store.append(event, evidence)
            before = {str(path.relative_to(journal)): path.read_bytes() for path in journal.rglob("*") if path.is_file()}
            args = ["--journal-root", str(journal), "--cohort", "SYNTHETIC_FIXTURE_ONLY", "--as-of", AS_OF, "--output", str(target)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                first, mtime = target.read_bytes(), target.stat().st_mtime_ns
                self.assertEqual(main(args), 0)
            self.assertEqual(first, target.read_bytes())
            self.assertEqual(mtime, target.stat().st_mtime_ns)
            self.assertEqual(json.loads(first)["verification"]["scope"], "FULL_JOURNAL_SEMANTIC_REPLAY")
            self.assertEqual(before, {str(path.relative_to(journal)): path.read_bytes() for path in journal.rglob("*") if path.is_file()})

    def test_cli_missing_journal_fails_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--journal-root", str(root / "missing"), "--cohort", "SYNTHETIC_FIXTURE_ONLY", "--as-of", AS_OF, "--output", str(target)]), 2)
            self.assertFalse(target.exists())

    def test_cli_rejects_source_journal_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--journal-root", str(root / "journal"), "--cohort", "SYNTHETIC_FIXTURE_ONLY", "--as-of", AS_OF, "--output", str(root / "journal/report.json")]), 2)


if __name__ == "__main__":
    unittest.main()
