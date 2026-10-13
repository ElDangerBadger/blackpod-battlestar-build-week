"""Synthetic end-to-end passive intake/hypothesis/data-quality examples."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.contracts.historical_intake import HistoricalIntakeRequest
from blackpod_build_week.decision_journal_store import JournalStore, JournalUnsafePathError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_historical_example import (
    EVALUATED_AT, example_material, main as example_main, prepare_example, synthetic_source_material,
)
from blackpod_build_week.trading_historical_intake import build_historical_intake, verify_historical_intake
from blackpod_build_week.trading_research_cli import main as research_main
from blackpod_build_week.trading_research_intake_cli import main as intake_main
from blackpod_build_week.trading_research_intake_cli import make_plan
from blackpod_build_week.trading_research_journal import assess_registered_research, build_evaluation_event, build_plan_event, evidence_for_research
from blackpod_build_week.trading_research_intake_journal import build_catalog_event, build_intake_event, catalog_evidence, intake_evidence
from blackpod_build_week.trading_hypotheses import catalog_documents


def invoke(command, arguments):
    output, errors = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        status = command(arguments)
    return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()


def json_calendar_material():
    material = synthetic_source_material()
    mapping = material["request"].to_dict()
    reference = mapping["sources"]["calendar_evidence"]
    original = reference["path"]
    reference["path"] = "synthetic-historical/calendar.json"
    material["evidence"][reference["path"]] = material["evidence"].pop(original)
    material["request"] = HistoricalIntakeRequest.from_mapping(mapping)
    return material


class TradingHistoricalExampleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temporary).resolve() / "example"

    def test_synthetic_material_has_two_specifications_and_no_strategy_votes(self):
        material = example_material()
        self.assertEqual(len(material["dataset"].sessions), 40)
        self.assertEqual(len(material["studies"]), 2)
        self.assertEqual([study["hypothesis"].signal["family"] for study in material["studies"]],
                         ["FIVE_SESSION_CONTINUATION", "PREVIOUS_SESSION_REVERSAL"])
        for study in material["studies"]:
            self.assertEqual(study["intents"].decisions, [])
            self.assertEqual(study["plan"].evaluation_purpose, "DATA_QUALITY_ONLY")
            self.assertEqual(study["hypothesis"].ancestry, "INDEPENDENT_NEW_RESEARCH_SPECIFICATION")

    def test_synthetic_bytes_and_events_are_reproducible(self):
        one, two = example_material(), example_material()
        self.assertEqual(one["evidence"], two["evidence"])
        self.assertEqual(one["blobs"], two["blobs"])
        self.assertEqual([event.to_bytes() for event in one["events"]], [event.to_bytes() for event in two["events"]])
        self.assertEqual(one["request"].to_bytes(), two["request"].to_bytes())

    def test_synthetic_calendar_remains_explicit_raw_array(self):
        material = synthetic_source_material()
        calendar_ref = material["request"].sources["calendar_evidence"]
        self.assertTrue(calendar_ref["path"].endswith(".raw"))
        calendar = json.loads(material["blobs"][calendar_ref["sha256"]])
        self.assertEqual(len(calendar), 40)
        self.assertEqual(calendar[0]["session_close"], "2000")
        self.assertEqual(calendar[0]["close"], "16:00")
        self.assertEqual(calendar[0]["date"], "2025-01-02")

    def test_fixture_receipts_bind_raw_numeric_bytes_without_external_calls(self):
        material = synthetic_source_material()
        refs = material["request"].sources
        for kind in ("bars", "calendar"):
            body_ref, receipt_ref = refs[kind + "_evidence"], refs[kind + "_receipt_evidence"]
            raw = material["blobs"][body_ref["sha256"]]
            receipt = json.loads(material["blobs"][receipt_ref["sha256"]])
            self.assertEqual(receipt["body_sha256"], sha256_bytes(raw))
            self.assertEqual(receipt["size_bytes"], len(raw))
            self.assertEqual(receipt["method"], "GET")
        bars = json.loads(material["blobs"][refs["bars_evidence"]["sha256"]])
        self.assertIs(type(bars["bars"]["SYNTHA"][0]["o"]), int)

    def test_example_uses_auxiliary_end_plus_delay_as_an_assumption(self):
        material = example_material()
        self.assertEqual(material["dataset"].sessions[0]["close_at"], "2025-01-02T21:00:00Z")
        self.assertEqual(material["dataset"].sessions[0]["available_at"], "2025-01-03T01:01:00Z")
        provenance = material["dataset"].provenance
        self.assertFalse(provenance["historical_point_in_time_verified"])
        self.assertFalse(provenance["availability_assumption"]["assumption_verified"])

    def test_both_studies_have_only_data_quality_results(self):
        for study in example_material()["studies"]:
            result = study["result"]
            self.assertEqual(result["schema_version"], "blackpod.trading_research_evaluation.v2")
            self.assertEqual(result["folds"][0]["status"], "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER")
            self.assertIsNone(result["folds"][0]["metrics"])
            self.assertIsNone(result["folds"][0]["benchmark"])
            self.assertEqual(result["folds"][0]["fills"], [])
            self.assertIsNone(result["aggregate"])
            self.assertIsNone(result["realized_trade_pnl"])
            self.assertFalse(result["auto_trading_enabled"])
            self.assertTrue(all(value is False for value in result["authority"].values()))

    def test_frozen_specs_bind_distinct_hold_horizons(self):
        studies = example_material()["studies"]
        self.assertEqual([study["plan"].horizon["label_horizon_sessions"] for study in studies], [3, 1])
        for study in studies:
            self.assertEqual(study["plan"].strategy["strategy_id"], study["hypothesis"].hypothesis_id)
            self.assertEqual(study["plan"].horizon["max_holding_sessions"], study["hypothesis"].horizon["holding_sessions"])

    def test_prepare_records_six_events_with_all_evidence_and_no_orphans(self):
        result = prepare_example(self.root)
        self.assertEqual(result["events_written"], 6)
        verification = result["journal_verification"]
        self.assertEqual(verification["event_count"], 6)
        self.assertEqual(verification["evidence_count"], 14)
        self.assertEqual(verification["orphan_evidence_count"], 0)
        self.assertEqual(verification["staging_orphan_count"], 0)
        self.assertFalse(result["recorded_paper_budgets_used"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["model_inference_calls"], 0)

    def test_prepare_retry_is_idempotent_and_preserves_all_files(self):
        first = prepare_example(self.root)
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        second = prepare_example(self.root)
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(second["events_written"], 0)
        self.assertEqual(first["journal_verification"], second["journal_verification"])
        self.assertEqual(before, after)

    def test_retained_journal_replays_after_original_input_removal(self):
        prepare_example(self.root)
        shutil.rmtree(self.root / "input")
        shutil.rmtree(self.root / "evidence")
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        for event in events:
            if event.event_type == "TRADING_RESEARCH_EVALUATION_RECORDED":
                plan = TradingResearchPlan.from_mapping(event.payload["plan"])
                replay = build_evaluation_event(plan, events, blobs, evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
                self.assertEqual(replay.to_bytes(), event.to_bytes())
        self.assertEqual(store.verify().event_count, 6)

    def test_read_only_assessment_preserves_original_journal_bytes(self):
        prepare_example(self.root)
        store = JournalStore(self.root / "journal")
        events, blobs = store.verified_contents()
        before = {path.name: path.read_bytes() for path in (self.root / "journal" / "entries").iterdir()}
        for event in events:
            if event.event_type == "TRADING_RESEARCH_PLAN_REGISTERED":
                result = assess_registered_research(event.payload["plan"], events, blobs)
                self.assertEqual(result["evaluation_purpose"], "DATA_QUALITY_ONLY")
        after = {path.name: path.read_bytes() for path in (self.root / "journal" / "entries").iterdir()}
        self.assertEqual(before, after)

    def test_example_main_emits_explicit_synthetic_manifest(self):
        status, result, errors = invoke(example_main, ["--output-root", str(self.root)])
        self.assertEqual(status, 0, errors)
        self.assertEqual(result["data_status"], "SYNTHETIC_FIXTURE")
        self.assertIn("NOT_ACTUAL_PROVIDER_RESPONSES", result["observations"])
        self.assertFalse(result["price_return_continuity_verified"])
        self.assertFalse(result["hypothesis_performance_evaluated"])

    def test_export_verification_cli_uses_the_retained_example_only(self):
        prepare_example(self.root)
        status, result, errors = invoke(intake_main, ["verify-export", "--export", str(self.root / "input/intake.json"),
            "--evidence-root", str(self.root / "evidence")])
        self.assertEqual(status, 0, errors)
        self.assertTrue(result["verified"])
        self.assertEqual(result["coverage"]["included_session_count"], 40)

    def test_both_plan_evaluate_and_record_cli_commands_replay_offline(self):
        material = prepare_example(self.root)
        for study in material["studies"]:
            arguments = ["--plan", str(self.root / study["plan_path"]), "--journal-root", str(self.root / "journal")]
            status, result, errors = invoke(research_main, ["evaluate", *arguments])
            self.assertEqual(status, 0, errors)
            self.assertEqual(result["result"]["evaluation_purpose"], "DATA_QUALITY_ONLY")
            status, result, errors = invoke(research_main, ["record", *arguments,
                "--evaluation-id", study["evaluation_id"], "--recorded-at", EVALUATED_AT])
            self.assertEqual(status, 0, errors)
            self.assertFalse(result["written"])
        self.assertEqual(JournalStore(self.root / "journal").verify().event_count, 6)

    def test_rendered_example_labels_data_quality_and_disabled_authority(self):
        material = prepare_example(self.root)
        report = Path(self.temporary).resolve() / "report/review.html"
        status, result, errors = invoke(research_main, ["render", "--journal-root", str(self.root / "journal"),
            "--event-id", material["studies"][0]["evaluation_event_id"], "--output", str(report)])
        self.assertEqual(status, 0, errors)
        html = report.read_text()
        self.assertIn("DATA QUALITY ONLY", html)
        self.assertIn("AUTOMATION AUTHORITY OFF", html)
        self.assertIn("RETROSPECTIVE_ASSUMPTION_NO_PIT_PROOF", html)
        self.assertIn("NO_STRATEGY_PRODUCER", html)

    def test_prepare_rejects_mission_storage_before_writes(self):
        protected = Path(self.temporary).resolve() / "missions" / "new-example"
        with self.assertRaises(JournalUnsafePathError):
            prepare_example(protected)
        self.assertFalse(protected.exists())

    def test_prepare_rejects_symlink_output_before_writes(self):
        target = Path(self.temporary).resolve() / "external"
        target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises((JournalUnsafePathError, ValueError, OSError)):
            prepare_example(self.root)
        self.assertEqual(list(target.iterdir()), [])

    def test_conflicting_immutable_input_is_not_overwritten(self):
        request = self.root / "input/request.json"
        request.parent.mkdir(parents=True)
        request.write_bytes(b"conflicting external input")
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            prepare_example(self.root)
        self.assertEqual(request.read_bytes(), b"conflicting external input")
        self.assertFalse((self.root / "journal").exists())

    def test_corrupted_source_blob_rejects_without_repair(self):
        material = synthetic_source_material()
        ref = material["request"].sources["bars_evidence"]
        material["blobs"][ref["sha256"]] += b"\n"
        with self.assertRaises(ValueError):
            build_historical_intake(material["request"], material["blobs"])

    def test_json_calendar_array_exports_and_verifies_through_offline_cli(self):
        material = json_calendar_material()
        evidence_root = self.root / "source"
        request_path = self.root / "input/request.json"
        request_path.parent.mkdir(parents=True)
        request_path.write_bytes(material["request"].to_bytes())
        for path, raw in material["evidence"].items():
            target = evidence_root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        destination = self.root / "export"
        status, result, errors = invoke(intake_main, ["export", "--request", str(request_path),
            "--evidence-root", str(evidence_root), "--output-directory", str(destination)])
        self.assertEqual(status, 0, errors)
        self.assertEqual(result["coverage"]["included_session_count"], 40)
        status, result, errors = invoke(intake_main, ["verify-export", "--export", str(destination / "historical-intake/export.v1.json"),
            "--evidence-root", str(destination)])
        self.assertEqual(status, 0, errors)
        self.assertTrue(result["verified"])
        self.assertEqual((destination / "synthetic-historical/calendar.json").read_bytes(),
                         material["evidence"]["synthetic-historical/calendar.json"])

    def test_json_calendar_full_journal_replays_with_only_retained_sources(self):
        sources = json_calendar_material()
        intake = build_historical_intake(sources["request"], sources["blobs"])
        catalog = example_material()["catalog"]
        blobs = dict(intake["blobs"])
        retained_catalog = catalog_evidence(catalog)
        blobs.update({sha256_bytes(raw): raw for raw in retained_catalog.values()})
        store = JournalStore(self.root / "journal")
        store.append(build_catalog_event(catalog), retained_catalog)
        store.append(build_intake_event(intake["export"], blobs, recorded_at="2025-04-01T10:05:00Z"),
                     intake_evidence(intake["export"], blobs))
        for index, hypothesis in enumerate(catalog_documents(catalog), 1):
            material = make_plan(hypothesis, intake["dataset"], blobs, registered_at="2025-04-01T10:20:00Z",
                                 experiment_id="json-calendar-experiment-%d" % index, plan_id="json-calendar-plan-%d" % index)
            blobs.update(material["blobs"])
            events, _ = store.verified_contents()
            plan_event = build_plan_event(material["plan"], events, blobs)
            store.append(plan_event, evidence_for_research(material["plan"], blobs))
            events, _ = store.verified_contents()
            event = build_evaluation_event(material["plan"], events, blobs,
                                          evaluation_id="json-calendar-evaluation-%d" % index, recorded_at=EVALUATED_AT)
            store.append(event, evidence_for_research(material["plan"], blobs))
        # There were no source directories or provider requests. Every replay
        # must use only immutable evidence copied into the journal.
        events, retained = store.verified_contents()
        self.assertEqual(store.verify().event_count, 6)
        self.assertEqual(store.verify().orphan_evidence_count, 0)
        for event in events:
            if event.event_type == "TRADING_RESEARCH_EVALUATION_RECORDED":
                replay = build_evaluation_event(event.payload["plan"], events, retained,
                    evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
                self.assertEqual(replay.to_bytes(), event.to_bytes())


if __name__ == "__main__":
    unittest.main()
