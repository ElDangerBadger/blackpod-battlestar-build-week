"""V16 governed evidence, risk-review links and append-only simulation replay."""
import copy
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_shadow_review import ReviewedShadowStudy
from blackpod_build_week.contracts.trading_shadow_risk_review import TradingShadowRiskReview
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_review_example import fixture_material, EVALUATED_AT, INTAKE_RECORDED_AT
from blackpod_build_week.trading_shadow_review_journal import (
    build_evidence_intake_event, evidence_for_intake, build_risk_review_event, evidence_for_risk_review,
    build_reviewed_study_event, build_reviewed_evaluation_event, evidence_for_reviewed_study,
    assess_registered_reviewed_study, implementation_evidence,
    CONTINUITY_TYPE, COST_TYPE, RISK_TYPE,
)
from blackpod_build_week.trading_shadow_review import reviewed_study_material, ref


class ReviewedShadowJournalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.store = JournalStore(self.root / "journal")
        self.material = fixture_material(); self.row = self.material["studies"][0]; self.study = self.row["study"]
        for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
            self.store.append(event, evidence)
        self.intake_events = []
        for kind, adapter in (("CONTINUITY", self.material["continuity"]), ("COST", self.material["costs"])):
            event = build_evidence_intake_event(kind, adapter["export"], self.material["blobs"], recorded_at=INTAKE_RECORDED_AT)
            self.store.append(event, evidence_for_intake(kind, adapter["export"], self.material["blobs"]))
            self.intake_events.append(event)
        self.risk_events = []
        for row in self.material["studies"]:
            self.risk_events.append(self.record_risk(row["risk_review"]))

    def context(self):
        events, blobs = self.store.verified_contents(); blobs.update(self.material["blobs"])
        return events, blobs

    def record_risk(self, review):
        events, blobs = self.context(); event = build_risk_review_event(review, events, blobs)
        self.store.append(event, evidence_for_risk_review(review, events, blobs))
        return event

    def register(self, study=None):
        study = study or self.study; events, blobs = self.context()
        event = build_reviewed_study_event(study, events, blobs)
        return self.store.append(event, evidence_for_reviewed_study(study, events, blobs)), event

    def evaluate(self, study=None, evaluation_id="reviewed-test-evaluation", recorded_at=EVALUATED_AT):
        study = study or self.study; events, blobs = self.context()
        event = build_reviewed_evaluation_event(study, events, blobs, evaluation_id=evaluation_id, recorded_at=recorded_at)
        return self.store.append(event, evidence_for_reviewed_study(study, events, blobs)), event

    def changed_risk_study(self, mutate):
        value = self.row["risk_review"].to_dict(); value["risk_review_id"] = "changed-test-risk-review"; mutate(value)
        review = TradingShadowRiskReview.from_mapping(value)
        reference = ref("test-reviewed/risk-review.v1.json", review.to_bytes())
        self.material["blobs"][reference["sha256"]] = review.to_bytes()
        self.record_risk(review)
        study = self.study.to_dict(); study["risk_review_evidence"] = reference
        return ReviewedShadowStudy.from_mapping(study)

    def forged_event_rejects(self, mutate, *, evaluation=False):
        if evaluation: self.register()
        events, blobs = self.context()
        event = build_reviewed_evaluation_event(self.study, events, blobs, evaluation_id="forged", recorded_at=EVALUATED_AT) if evaluation else build_reviewed_study_event(self.study, events, blobs)
        value = event.to_dict(); mutate(value)
        with self.assertRaises((ValueError, JournalStoreError)):
            self.store.append(JournalEvent.from_mapping(value), evidence_for_reviewed_study(self.study, events, blobs))

    def test_full_v16_registration_and_evaluation_linked_replay(self):
        _, registration = self.register(); appended, event = self.evaluate()
        self.assertEqual(appended.sequence, 12)
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v16")
        self.assertEqual(event.payload["study_event_id"], registration.event_id)
        self.assertEqual(event.payload["risk_review_event_id"], self.risk_events[0].event_id)
        self.assertEqual(event.payload["continuity_event_id"], self.intake_events[0].event_id)
        self.assertEqual(event.payload["cost_event_id"], self.intake_events[1].event_id)
        self.assertEqual(event.payload["base_plan_event_id"], self.row["plan_event"].event_id)
        self.assertEqual(event.payload["result"]["status"], "SHADOW_SIMULATED")
        self.assertEqual(len(event.payload["result"]["calculation_result"]["cost_stress_runs"]), 3)
        self.assertIsNone(event.payload["result"]["realized_trade_pnl"])
        self.assertFalse(any(event.payload["result"]["authority"].values()))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_intake_exact_retry_is_idempotent(self):
        adapter = self.material["continuity"]
        event = build_evidence_intake_event("CONTINUITY", adapter["export"], self.material["blobs"], recorded_at=INTAKE_RECORDED_AT)
        self.assertFalse(self.store.append(event, evidence_for_intake("CONTINUITY", adapter["export"], self.material["blobs"])).written)
        self.assertEqual(self.store.verify().event_count, 10)

    def test_risk_review_exact_retry_is_idempotent(self):
        self.assertEqual(self.record_risk(self.row["risk_review"]).to_bytes(), self.risk_events[0].to_bytes())
        self.assertEqual(self.store.verify().event_count, 10)

    def test_study_exact_retry_is_idempotent(self):
        first, event = self.register(); second, again = self.register()
        self.assertTrue(first.written); self.assertFalse(second.written)
        self.assertEqual(event.to_bytes(), again.to_bytes())

    def test_evaluation_exact_retry_is_idempotent(self):
        self.register(); first, event = self.evaluate(); second, again = self.evaluate()
        self.assertTrue(first.written); self.assertFalse(second.written)
        self.assertEqual(event.to_bytes(), again.to_bytes())

    def test_later_trial_preserves_original_evaluation_retry(self):
        self.register(); _, original = self.evaluate()
        value = self.study.to_dict(); value.update(study_id="later-reviewed-study", registered_at="2025-04-01T16:00:00Z")
        value["trial_registry"] = {"trial_id": "later-reviewed-trial", "prior_trial_ids": [self.study.trial_registry["trial_id"]]}
        self.register(ReviewedShadowStudy.from_mapping(value)); _, again = self.evaluate()
        self.assertEqual(original.to_bytes(), again.to_bytes())

    def test_evaluation_without_registration_rejects(self):
        with self.assertRaisesRegex(ValueError, "original immutable"):
            self.evaluate()

    def test_missing_base_plan_registration_rejects(self):
        events, blobs = self.context()
        previous = tuple(event for event in events if event.event_id != self.row["plan_event"].event_id)
        with self.assertRaises(ValueError): build_reviewed_study_event(self.study, previous, blobs)

    def test_missing_preceding_risk_review_record_rejects(self):
        events, blobs = self.context()
        with self.assertRaisesRegex(ValueError, "unique preceding"):
            build_reviewed_study_event(self.study, tuple(event for event in events if event.event_type != RISK_TYPE), blobs)

    def test_missing_preceding_continuity_record_rejects(self):
        events, blobs = self.context()
        with self.assertRaisesRegex(ValueError, "unique preceding"):
            build_reviewed_study_event(self.study, tuple(event for event in events if event.event_type != CONTINUITY_TYPE), blobs)

    def test_missing_preceding_cost_record_rejects(self):
        events, blobs = self.context()
        with self.assertRaisesRegex(ValueError, "unique preceding"):
            build_reviewed_study_event(self.study, tuple(event for event in events if event.event_type != COST_TYPE), blobs)

    def test_duplicate_preceding_hash_records_reject_at_context_boundary(self):
        events, blobs = self.context()
        with self.assertRaisesRegex(ValueError, "unique preceding"):
            build_reviewed_study_event(self.study, events + (self.risk_events[0],), blobs)

    def test_study_clock_cannot_predate_risk_review(self):
        value = self.study.to_dict(); value["registered_at"] = "2025-04-01T12:30:00Z"
        with self.assertRaises(ValueError): self.register(ReviewedShadowStudy.from_mapping(value))

    def test_source_journal_clock_cannot_follow_study_freeze(self):
        events, blobs = self.context(); value = self.intake_events[0].to_dict()
        value["recorded_at"] = "2025-04-01T16:00:00Z"
        future = JournalEvent.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "source journal"):
            build_reviewed_study_event(self.study, tuple(future if event.event_id == future.event_id else event for event in events), blobs)

    def test_evaluation_clock_cannot_predate_registration(self):
        self.register()
        with self.assertRaises(ValueError): self.evaluate(recorded_at="2025-04-01T13:59:00Z")

    def test_adapter_record_cannot_predate_intake_declaration(self):
        adapter = self.material["continuity"]
        with self.assertRaises(ValueError): build_evidence_intake_event("CONTINUITY", adapter["export"], self.material["blobs"], recorded_at="2025-04-01T11:59:00Z")

    def test_scope_and_sizing_must_equal_explicit_risk_review(self):
        for changes in ({"evidence_scope": "RETAINED_HISTORY_RESEARCH"}, {"sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "61"}}):
            value = self.study.to_dict(); value.update(changes)
            with self.assertRaisesRegex(ValueError, "sizing/scope"): self.register(ReviewedShadowStudy.from_mapping(value))

    def test_valid_adapter_for_different_dataset_cannot_replace_original_context(self):
        from blackpod_build_week.trading_historical_intake import build_historical_intake
        from blackpod_build_week.trading_continuity_intake import build_continuity_intake
        historical = self.material["request"].to_dict(); historical["run_id"] = "different-valid-history"
        alternate = build_historical_intake(historical, self.material["blobs"])
        combined = {**self.material["blobs"], **alternate["blobs"]}
        request = self.material["continuity"]["request"].to_dict()
        request.update(run_id="different-valid-continuity", dataset_evidence=ref("test-reviewed/different-dataset.v2.json", alternate["dataset"].to_bytes()),
                       coverage_basis="EX_DATE_COVERAGE_UNVERIFIED", coverage_review_evidence=None)
        adapter = build_continuity_intake(request, combined)
        export_ref = ref("test-reviewed/different-continuity-export.v1.json", adapter["export"].to_bytes())
        events, blobs = self.context(); blobs.update(adapter["blobs"]); blobs[export_ref["sha256"]] = adapter["export"].to_bytes()
        study = self.study.to_dict(); study["continuity_intake_evidence"] = export_ref
        with self.assertRaisesRegex(ValueError, "adapter dataset"):
            build_reviewed_study_event(study, events, blobs)

    def test_changed_registered_study_conflicts_without_rewriting_original(self):
        self.register(); before = self.store.verify().to_dict()
        value = self.study.to_dict(); value["continuity_intake_evidence"] = None
        with self.assertRaisesRegex(ValueError, "immutable"): self.register(ReviewedShadowStudy.from_mapping(value))
        self.assertEqual(before, self.store.verify().to_dict())

    def test_incomplete_trial_registry_rejects(self):
        self.register(); value = self.study.to_dict(); value["study_id"] = "new-review-study"
        value["trial_registry"] = {"trial_id": "new-review-trial", "prior_trial_ids": []}
        with self.assertRaisesRegex(ValueError, "every preceding"): self.register(ReviewedShadowStudy.from_mapping(value))

    def test_evidence_changes_require_separate_experiment(self):
        self.register(); value = self.study.to_dict(); value["study_id"] = "changed-evidence-study"
        value["continuity_intake_evidence"] = None
        value["trial_registry"] = {"trial_id": "changed-evidence-trial", "prior_trial_ids": [self.study.trial_registry["trial_id"]]}
        with self.assertRaisesRegex(ValueError, "distinct reviewed experiment"): self.register(ReviewedShadowStudy.from_mapping(value))

    def test_missing_optional_intakes_record_deferred_zero_exposure(self):
        value = self.study.to_dict(); value["continuity_intake_evidence"] = value["cost_intake_evidence"] = None
        study = ReviewedShadowStudy.from_mapping(value)
        self.register(study); _, event = self.evaluate(study)
        self.assertEqual(event.payload["result"]["status"], "DEFER_EVIDENCE_GATES")
        self.assertEqual(event.payload["production"]["intents"]["decisions"], [])
        self.assertEqual(event.payload["result"]["calculation_result"]["cost_stress_runs"], [])
        self.assertIsNone(event.payload["continuity_event_id"])
        self.assertIsNone(event.payload["cost_event_id"])

    def test_proposed_review_defers_without_projecting_or_authorizing(self):
        study = self.changed_risk_study(lambda value: value.update(status="PROPOSED"))
        self.register(study); _, event = self.evaluate(study)
        self.assertFalse(event.payload["gate_assessment"]["eligible"])
        self.assertIn("RISK_REVIEW_NOT_APPROVED_FOR_SHADOW", event.payload["gate_assessment"]["reason_codes"])
        self.assertFalse(event.payload["result"]["internal_risk_projection_prepared"])
        self.assertEqual(event.payload["production"]["intents"]["decisions"], [])
        self.assertFalse(any(event.payload["result"]["authority"].values()))

    def test_approved_review_projects_only_risk_and_preserves_original_bytes(self):
        study = self.changed_risk_study(lambda value: value["simulation_risk"].update(initial_cash="1200"))
        events, blobs = self.context(); original = self.row["plan"].to_bytes()
        material = reviewed_study_material(study, events, blobs)
        before, after = material["base_plan"].to_dict(), material["projected_plan"].to_dict()
        self.assertNotEqual(before["risk"], after["risk"])
        before.pop("risk"); after.pop("risk"); self.assertEqual(before, after)
        self.assertEqual(original, self.row["plan"].to_bytes())
        self.register(study); _, event = self.evaluate(study)
        self.assertEqual(event.payload["result"]["original_simulation_risk"], self.row["plan"].risk)
        self.assertEqual(event.payload["result"]["reviewed_simulation_risk"]["initial_cash"], "1200")
        self.assertFalse(event.payload["risk_assessment"]["provenance"]["desk_budget_activated"])

    def test_assessment_is_read_only_and_uses_immutable_registration(self):
        self.register(); before = self.store.verify().to_dict()
        events, blobs = self.context(); result = assess_registered_reviewed_study(self.study, events, blobs)
        self.assertEqual(result["result"]["status"], "SHADOW_SIMULATED")
        self.assertEqual(before, self.store.verify().to_dict())
        self.assertEqual(result["result"]["final_holdout"]["scoring_status"], "WITHHELD")

    def test_source_dataset_hypothesis_raw_capture_and_code_retained(self):
        _, event = self.register(); hashes = {reference["sha256"] for reference in event.evidence}
        self.assertIn(self.row["plan"].dataset_evidence["sha256"], hashes)
        self.assertIn(self.row["plan"].frozen_hypothesis_evidence["sha256"], hashes)
        self.assertIn(self.material["request"].sources["bars_evidence"]["sha256"], hashes)
        self.assertIn(self.material["continuity"]["request"].pages[0]["response_evidence"]["sha256"], hashes)
        self.assertTrue(any("implementation/trading_shadow_intents.py" in reference["path"] for reference in event.evidence))
        self.assertTrue(any("implementation/trading_cost_intake.py" in reference["path"] for reference in event.evidence))

    def test_rehashed_link_forgery_rejects(self):
        self.forged_event_rejects(lambda value: value["payload"].update(risk_review_event_id=self.risk_events[1].event_id))

    def test_rehashed_gate_forgery_rejects(self):
        self.forged_event_rejects(lambda value: value["payload"]["gate_assessment"].update(reason_codes=["invented"]))

    def test_rehashed_risk_assessment_forgery_rejects(self):
        self.forged_event_rejects(lambda value: value["payload"]["risk_assessment"].update(eligible=False))

    def test_rehashed_calculation_forgery_rejects(self):
        self.forged_event_rejects(lambda value: value["payload"]["result"]["calculation_result"].update(status="PROFITABLE"), evaluation=True)

    def test_rehashed_production_forgery_rejects(self):
        self.forged_event_rejects(lambda value: value["payload"]["production"].update(opportunities=[]), evaluation=True)

    def test_rehashed_intake_export_forgery_rejects(self):
        adapter = self.material["continuity"]
        event = build_evidence_intake_event("CONTINUITY", adapter["export"], self.material["blobs"], recorded_at=INTAKE_RECORDED_AT)
        value = event.to_dict(); value["payload"]["export"]["coverage_review_supported"] = False
        with self.assertRaises((ValueError, JournalStoreError)):
            self.store.append(JournalEvent.from_mapping(value), evidence_for_intake("CONTINUITY", adapter["export"], self.material["blobs"]))

    def test_result_cannot_claim_realized_trade_pnl_or_execution_authority(self):
        for mutate in (lambda value: value["payload"]["result"].update(realized_trade_pnl="1"),
                       lambda value: value["payload"]["result"]["authority"].update(execution_enabled=True)):
            # Each subcase starts with the same registered immutable study.
            self.forged_event_rejects(mutate, evaluation=True)

    def test_corrupted_native_bytes_reject_before_registration(self):
        events, blobs = self.context(); reference = self.material["continuity"]["request"].pages[0]["response_evidence"]
        blobs[reference["sha256"]] += b"corruption"
        with self.assertRaises(ValueError): build_reviewed_study_event(self.study, events, blobs)

    def test_changed_installed_adapter_code_fails_existing_replay(self):
        self.register(); code = implementation_evidence(); path = next(path for path in code if path.endswith("trading_continuity_intake.py"))
        code[path] += b"\n# test alternate installed adapter\n"
        with patch("blackpod_build_week.trading_shadow_review_journal.implementation_evidence", return_value=code):
            with self.assertRaises(JournalStoreError): self.store.verify()

    def test_changed_installed_adapter_code_blocks_evaluation(self):
        self.register(); code = implementation_evidence(); path = next(iter(code)); code[path] += b"\n# changed calculation\n"
        events, blobs = self.context()
        with patch("blackpod_build_week.trading_shadow_review_journal.implementation_evidence", return_value=code):
            with self.assertRaisesRegex(ValueError, "installed calculations"):
                build_reviewed_evaluation_event(self.study, events, blobs, evaluation_id="changed-code", recorded_at=EVALUATED_AT)

    def test_verification_works_after_external_material_disappears(self):
        self.register(); self.evaluate(); self.material["blobs"].clear(); self.material["evidence"].clear()
        self.assertEqual(self.store.verify().event_count, 12)

    def test_missing_bound_bytes_cannot_publish_partial_study(self):
        events, blobs = self.context(); event = build_reviewed_study_event(self.study, events, blobs)
        with self.assertRaises(JournalStoreError): self.store.append(event, {})
        self.assertEqual(self.store.verify().event_count, 10)

    def test_interrupted_publication_recovers_by_exact_retry(self):
        from blackpod_build_week import decision_journal_store as module
        events, blobs = self.context(); event = build_reviewed_study_event(self.study, events, blobs)
        evidence = evidence_for_reviewed_study(self.study, events, blobs); original = module._publish_immutable
        def interrupted(*args, **kwargs):
            if args[2].endswith(".json"): raise OSError("simulated interrupted entry publication")
            return original(*args, **kwargs)
        with patch.object(module, "_publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalStoreError): self.store.append(event, evidence)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().event_count, 11)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_previous_v15_records_remain_byte_identical_in_mixed_journal(self):
        from blackpod_build_week.trading_shadow_example import fixture_material as old_fixture
        from blackpod_build_week.trading_shadow_journal import build_study_event, build_shadow_evaluation_event, evidence_for_shadow
        old = old_fixture(); study = old["studies"][0]["study"]
        events, blobs = self.context(); blobs.update(old["blobs"])
        registration = build_study_event(study, events, blobs)
        self.store.append(registration, evidence_for_shadow(study, events, blobs))
        events, blobs = self.context(); blobs.update(old["blobs"])
        evaluation = build_shadow_evaluation_event(study, events, blobs, evaluation_id="old-v15-evaluation", recorded_at="2025-04-01T13:00:00Z")
        self.store.append(evaluation, evidence_for_shadow(study, events, blobs))
        originals = {path.name: path.read_bytes() for path in (self.store.root / "entries").glob("*.json")}
        self.register(); self.evaluate()
        for name, raw in originals.items(): self.assertEqual(raw, (self.store.root / "entries" / name).read_bytes())
        self.assertEqual(self.store.verify().event_count, 14)


if __name__ == "__main__": unittest.main()
