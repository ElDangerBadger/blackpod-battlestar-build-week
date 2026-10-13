"""Offline explicit shadow commands, immutable artifacts and opaque origins."""
import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_shadow_research import TradingShadowStudy
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_cli import main, load_shadow_evidence, render_shadow_review
from blackpod_build_week.trading_shadow_example import fixture_material, EVALUATED_AT, STUDY_REGISTERED_AT


class TradingShadowCLITests(unittest.TestCase):
    def test_long_study_identifier_is_rejected_before_artifact_writes(self):
        target = self.base / "oversized-study"
        status, output, errors = self.prepare(output=target, study_id="a" * 111)
        self.assertEqual(status, 2)
        self.assertIsNone(output)
        self.assertIn("maximum 110", errors)
        self.assertFalse(target.exists())

    @classmethod
    def setUpClass(cls):
        cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("legacy execution forbidden")))
        self.enterContext(patch("blackpod_build_week.shadow_brigade_analysis.build_shadow_brigade_analysis", side_effect=AssertionError("Brigade producer forbidden")))
        self.enterContext(patch("blackpod_build_week.shadow_galactica_analysis.build_shadow_galactica_analysis", side_effect=AssertionError("legacy analysis forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.journal, self.evidence, self.input = self.base / "journal", self.base / "evidence", self.base / "input"
        self.input.mkdir()
        for path, raw in self.material["evidence"].items():
            target = self.evidence / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        self.study = self.input / "study.json"
        self.study.write_bytes(self.material["studies"][0]["study"].to_bytes())
        store = JournalStore(self.journal)
        for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
            store.append(event, evidence)

    def call(self, command, *extras, study=None, journal=None, evidence=None):
        args = [command, "--journal-root", str(journal or self.journal)]
        if command in {"register", "evaluate", "record"}:
            args += ["--study", str(study or self.study), "--evidence-root", str(evidence or self.evidence)]
        args += list(extras)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = main(args)
        return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()

    def register(self):
        status, result, errors = self.call("register")
        self.assertEqual(status, 0, errors)
        return result

    def record(self):
        self.register()
        status, result, errors = self.call("record", "--evaluation-id", "cli-shadow-evaluation", "--recorded-at", EVALUATED_AT)
        self.assertEqual(status, 0, errors)
        return result

    def prepare(self, *extras, output=None, study_id="prepared-shadow-study", experiment_id="prepared-shadow-experiment", gates=True):
        args = ["--base-plan-event-id", self.material["studies"][0]["plan_event"].event_id,
                "--study-id", study_id, "--experiment-id", experiment_id,
                "--registered-at", STUDY_REGISTERED_AT, "--per-symbol-notional", "80",
                "--evidence-scope", "SYNTHETIC_FIXTURE_ONLY", "--output-directory", str(output or self.base / "prepared")]
        if gates:
            args += ["--price-continuity", str(self.evidence / "synthetic-shadow/continuity-review.v1.json"),
                     "--cost-evidence", str(self.evidence / "synthetic-shadow/cost-review.v1.json"),
                     "--evidence-root", str(self.evidence)]
        return self.call("prepare", *args, *extras)

    def test_prepare_publishes_validated_artifacts_without_registering(self):
        before = JournalStore(self.journal).verify().event_count
        status, result, errors = self.prepare()
        self.assertEqual(status, 0, errors)
        self.assertFalse(result["registered"])
        self.assertTrue(result["gate_assessment"]["eligible"])
        self.assertEqual(JournalStore(self.journal).verify().event_count, before)
        prepared = TradingShadowStudy.from_bytes(Path(result["study_path"]).read_bytes())
        self.assertFalse(prepared.auto_trading_enabled)
        self.assertTrue(all(value is False for value in prepared.authority.values()))
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["provider_calls"], 0)

    def test_prepare_retry_preserves_identical_file_bytes(self):
        status, first, errors = self.prepare()
        self.assertEqual(status, 0, errors)
        before = Path(first["study_path"]).read_bytes()
        status, second, errors = self.prepare()
        self.assertEqual(status, 0, errors)
        self.assertEqual(first, second)
        self.assertEqual(before, Path(second["study_path"]).read_bytes())

    def test_prepare_conflict_never_rewrites_original_declaration(self):
        status, first, errors = self.prepare()
        self.assertEqual(status, 0, errors)
        source = Path(first["study_path"])
        before = source.read_bytes()
        status, _, errors = self.prepare("--per-symbol-notional", "81")
        self.assertEqual(status, 2)
        self.assertTrue(errors)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 6)

    def test_prepare_derives_prior_trials_and_preserves_retry_prefix(self):
        status, first, errors = self.prepare(study_id="prepared-trial-one", experiment_id="same-shadow-experiment",
                                            output=self.base / "prepared-one")
        self.assertEqual(status, 0, errors)
        status, _, errors = self.call("register", study=Path(first["study_path"]), evidence=self.base / "prepared-one")
        self.assertEqual(status, 0, errors)
        status, second, errors = self.prepare(study_id="prepared-trial-two", experiment_id="same-shadow-experiment",
                                             output=self.base / "prepared-two")
        self.assertEqual(status, 0, errors)
        second_study = TradingShadowStudy.from_bytes(Path(second["study_path"]).read_bytes())
        self.assertEqual(second_study.trial_registry["prior_trial_ids"], ["prepared-trial-one-trial-1"])
        status, _, errors = self.call("register", study=Path(second["study_path"]), evidence=self.base / "prepared-two")
        self.assertEqual(status, 0, errors)
        status, retried, errors = self.prepare(study_id="prepared-trial-one", experiment_id="same-shadow-experiment",
                                              output=self.base / "prepared-one")
        self.assertEqual(status, 0, errors)
        self.assertEqual(first, retried)

    def test_prepare_missing_gates_is_explicitly_deferred(self):
        status, result, errors = self.prepare(gates=False)
        self.assertEqual(status, 0, errors)
        self.assertFalse(result["gate_assessment"]["eligible"])
        self.assertEqual(result["gate_assessment"]["reason_codes"], ["COST_EVIDENCE_MISSING", "PRICE_CONTINUITY_EVIDENCE_MISSING"])

    def test_full_prepared_pipeline_register_evaluate_record_verify(self):
        status, result, errors = self.prepare()
        self.assertEqual(status, 0, errors)
        study, evidence = Path(result["study_path"]), self.base / "prepared"
        status, registered, errors = self.call("register", study=study, evidence=evidence)
        self.assertEqual(status, 0, errors)
        self.assertTrue(registered["written"])
        status, assessment, errors = self.call("evaluate", study=study, evidence=evidence)
        self.assertEqual(status, 0, errors)
        self.assertEqual(assessment["result"]["status"], "SHADOW_SIMULATED")
        self.assertTrue(assessment["production"]["intents"]["decisions"])
        self.assertIsNone(assessment["result"]["realized_trade_pnl"])
        status, recorded, errors = self.call("record", "--evaluation-id", "prepared-evaluation", "--recorded-at", EVALUATED_AT,
                                             study=study, evidence=evidence)
        self.assertEqual(status, 0, errors)
        self.assertTrue(recorded["written"])
        status, verified, errors = self.call("verify")
        self.assertEqual(status, 0, errors)
        self.assertEqual(verified["event_count"], 8)
        self.assertEqual(verified["orphan_evidence_count"], 0)

    def test_register_retry_is_idempotent(self):
        first, second = self.register(), self.register()
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(JournalStore(self.journal).verify().event_count, 7)

    def test_evaluation_requires_prior_registration(self):
        status, result, errors = self.call("evaluate")
        self.assertEqual(status, 2)
        self.assertIsNone(result)
        self.assertIn("registration", errors)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 6)

    def test_register_cannot_invent_missing_foundation(self):
        status, _, errors = self.call("register", journal=self.base / "empty-journal")
        self.assertEqual(status, 2)
        self.assertIn("preceding", errors)
        self.assertFalse((self.base / "empty-journal").exists())

    def test_evaluate_is_pure_and_preserves_original_event_count(self):
        self.register()
        status, result, errors = self.call("evaluate")
        self.assertEqual(status, 0, errors)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 7)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["auto_trading_changed"])
        self.assertFalse(result["result"]["auto_trading_enabled"])

    def test_record_retry_show_and_verify_replay(self):
        first, second = self.record(), self.record()
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        status, shown, errors = self.call("show", "--event-id", first["event_id"])
        self.assertEqual(status, 0, errors)
        self.assertEqual(shown["schema_version"], "blackpod.decision_journal_event.v15")
        self.assertEqual(shown["payload"]["result"]["status"], "SHADOW_SIMULATED")
        self.assertIsNone(shown["payload"]["result"]["realized_trade_pnl"])
        self.assertFalse(shown["payload"]["production"]["auto_trading_enabled"])
        status, verified, errors = self.call("verify")
        self.assertEqual(status, 0, errors)
        self.assertEqual(verified["event_count"], 8)
        self.assertEqual(verified["orphan_evidence_count"], 0)

    def test_missing_gate_record_retains_defer_without_scores(self):
        status, prepared, errors = self.prepare(gates=False)
        self.assertEqual(status, 0, errors)
        study, evidence = Path(prepared["study_path"]), self.base / "prepared"
        status, _, errors = self.call("register", study=study, evidence=evidence)
        self.assertEqual(status, 0, errors)
        status, recorded, errors = self.call("record", "--evaluation-id", "deferred-evaluation", "--recorded-at", EVALUATED_AT,
                                             study=study, evidence=evidence)
        self.assertEqual(status, 0, errors)
        status, shown, errors = self.call("show", "--event-id", recorded["event_id"])
        self.assertEqual(status, 0, errors)
        result = shown["payload"]["result"]
        self.assertEqual(result["status"], "DEFER_EVIDENCE_GATES")
        self.assertFalse(result["cost_stress_runs"])
        self.assertFalse(shown["payload"]["production"]["intents"]["decisions"])

    def test_render_is_safe_and_explains_exposure_and_authority_limits(self):
        recorded = self.record()
        output = self.base / "reports/review.html"
        status, rendered, errors = self.call("render", "--event-id", recorded["event_id"], "--output", str(output))
        self.assertEqual(status, 0, errors)
        html = output.read_text()
        for phrase in ("SHADOW SIMULATION ONLY", "ALL EXECUTION AUTHORITY OFF", "FINAL HOLDOUT UNSCORED",
                       "not realized trade P&amp;L", "INCONCLUSIVE", "does not match daily exposure or beta",
                       "Fractional control quantities", "source", "UNASSESSED", "passive journal v15"):
            self.assertIn(phrase, html)
        self.assertEqual(rendered["sha256"], sha256_bytes(output.read_bytes()))

    def test_render_retry_is_byte_identical(self):
        recorded = self.record()
        output = self.base / "reports/review.html"
        first = self.call("render", "--event-id", recorded["event_id"], "--output", str(output))
        second = self.call("render", "--event-id", recorded["event_id"], "--output", str(output))
        self.assertEqual(first, second)
        self.assertEqual(first[0], 0, first[2])

    def test_report_outputs_cannot_touch_journal_or_its_parent(self):
        recorded = self.record()
        for output in (self.journal / "review.html", self.base / "review.html"):
            with self.subTest(output=output):
                status, _, errors = self.call("render", "--event-id", recorded["event_id"], "--output", str(output))
                self.assertEqual(status, 2)
                self.assertTrue(errors)

    def test_registration_cannot_be_rendered_as_scored_evaluation(self):
        registered = self.register()
        status, _, errors = self.call("render", "--event-id", registered["event_id"], "--output", str(self.base / "reports/registration.html"))
        self.assertEqual(status, 2)
        self.assertIn("evaluation", errors)

    def test_other_architectural_event_cannot_be_shown_as_shadow(self):
        event_id = self.material["events"][0].event_id
        status, _, errors = self.call("show", "--event-id", event_id)
        self.assertEqual(status, 2)
        self.assertIn("unknown verified", errors)

    def test_no_authority_override_can_be_smuggled_into_study(self):
        value = json.loads(self.study.read_bytes())
        value["auto_trading_enabled"] = True
        self.study.write_bytes(canonical_json_bytes(value))
        status, _, errors = self.call("register")
        self.assertEqual(status, 2)
        self.assertIn("auto_trading_enabled", errors)

    def test_study_source_cannot_be_inside_journal(self):
        source = self.journal / "unsafe-study.json"
        source.write_bytes(self.study.read_bytes())
        status, _, errors = self.call("register", study=source)
        self.assertEqual(status, 2)
        self.assertTrue(errors)

    def test_symlink_study_rejects_before_registration(self):
        linked = self.input / "linked.json"
        linked.symlink_to(self.study)
        status, _, errors = self.call("register", study=linked)
        self.assertEqual(status, 2)
        self.assertIn("safely", errors)

    def test_changed_source_bytes_fail_before_registration(self):
        source = self.evidence / "synthetic-shadow/cost-origin.raw"
        source.write_bytes(b"Changed source.")
        status, _, errors = self.call("register")
        self.assertEqual(status, 2)
        self.assertIn("hash", errors)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 6)

    def test_registered_source_bytes_survive_changed_external_copy(self):
        self.register()
        (self.evidence / "synthetic-shadow/cost-origin.raw").write_bytes(b"External edit.")
        status, result, errors = self.call("evaluate")
        self.assertEqual(status, 0, errors)
        self.assertEqual(result["result"]["status"], "SHADOW_SIMULATED")

    def test_loader_keeps_origin_json_arrays_opaque(self):
        material = copy.deepcopy(self.material)
        source = material["cost_source"].to_dict()
        raw_origin = b'[{"path":"not-followed.json","sha256":"' + b"0" * 64 + b'","size_bytes":3}]'
        origin_ref = {"path": "synthetic-shadow/list-origin.json", "sha256": sha256_bytes(raw_origin), "size_bytes": len(raw_origin)}
        source["origin_evidence"] = [origin_ref]
        from blackpod_build_week.contracts.trading_shadow_research import TradingCostSource, TradingCostEvidence
        source_body = TradingCostSource.from_mapping(source).to_bytes()
        source_ref = {"path": "synthetic-shadow/new-cost-source.json", "sha256": sha256_bytes(source_body), "size_bytes": len(source_body)}
        review = material["cost_review"].to_dict()
        review["source_evidence"] = [source_ref]
        review_body = TradingCostEvidence.from_mapping(review).to_bytes()
        review_ref = {"path": "synthetic-shadow/new-cost-review.json", "sha256": sha256_bytes(review_body), "size_bytes": len(review_body)}
        study = material["studies"][0]["study"].to_dict()
        study["cost_evidence"] = review_ref
        for ref, raw in ((origin_ref, raw_origin), (source_ref, source_body), (review_ref, review_body)):
            path = self.evidence / ref["path"]
            path.write_bytes(raw)
        loaded = load_shadow_evidence(self.evidence, study, self.material["blobs"])
        self.assertEqual(loaded[origin_ref["sha256"]], raw_origin)
        self.assertNotIn("0" * 64, loaded)

    def test_loader_origin_symlink_rejects(self):
        source = self.evidence / "synthetic-shadow/cost-origin.raw"
        genuine = self.base / "genuine-cost.raw"
        source.rename(genuine)
        source.symlink_to(genuine)
        status, _, errors = self.call("register")
        self.assertEqual(status, 2)
        self.assertIn("safely", errors)

    def test_prepare_cannot_write_to_journal_or_its_parent(self):
        for output in (self.journal, self.base):
            with self.subTest(output=output):
                status, _, errors = self.prepare(output=output)
                self.assertEqual(status, 2)
                self.assertTrue(errors)

    def test_prepare_invalid_base_event_rejects_without_creating_output(self):
        status, _, errors = self.prepare("--base-plan-event-id", "journal-event-" + "0" * 64)
        self.assertEqual(status, 2)
        self.assertIn("verified preceding", errors)
        self.assertFalse((self.base / "prepared").exists())

    def test_prepare_synthetic_reviews_cannot_gate_retained_history_scope(self):
        status, result, errors = self.prepare("--evidence-scope", "RETAINED_HISTORY_RESEARCH")
        self.assertEqual(status, 0, errors)
        self.assertFalse(result["gate_assessment"]["eligible"])
        self.assertIn("PRICE_CONTINUITY_EVIDENCE_SCOPE_MISMATCH", result["gate_assessment"]["reason_codes"])

    def test_html_escapes_all_external_gate_notes(self):
        recorded = self.record()
        event = next(event for event in JournalStore(self.journal).events() if event.event_id == recorded["event_id"])
        value = event.to_dict()
        unsafe = '<script>alert("unsafe")</script>'
        value["payload"]["result"]["limitations"].append(unsafe)
        # Contract permits descriptive result fields; only verified journal replay
        # may authorize rendering through main. Direct rendering still escapes.
        altered = JournalEvent.from_mapping(value)
        html = render_shadow_review(altered)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
