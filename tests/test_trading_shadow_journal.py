"""Frozen study history, evidence gates and matched research replay integrity."""
import copy
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_shadow_research import TradingShadowStudy
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError, JournalConflictError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_example import fixture_material, EVALUATED_AT
from blackpod_build_week.trading_shadow_journal import (
    build_study_event, build_shadow_evaluation_event, evidence_for_shadow, assess_registered_shadow,
    implementation_evidence,
)


class ShadowJournalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.store = JournalStore(self.root / "journal")
        self.material = fixture_material(); self.study = self.material["studies"][0]["study"]
        for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
            self.store.append(event, evidence)

    def context(self):
        events, blobs = self.store.verified_contents()
        blobs.update(self.material["blobs"])
        return events, blobs

    def register(self, study=None):
        study = study or self.study
        events, blobs = self.context()
        event = build_study_event(study, events, blobs)
        return self.store.append(event, evidence_for_shadow(study, events, blobs)), event

    def evaluate(self, study=None, evaluation_id="root-shadow-evaluation", recorded_at=EVALUATED_AT):
        study = study or self.study
        events, blobs = self.context()
        event = build_shadow_evaluation_event(study, events, blobs, evaluation_id=evaluation_id, recorded_at=recorded_at)
        return self.store.append(event, evidence_for_shadow(study, events, blobs)), event

    def test_full_registration_and_linked_replay(self):
        _, registration = self.register(); appended, event = self.evaluate()
        self.assertEqual(appended.sequence, 8)
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v15")
        self.assertEqual(event.payload["study_event_id"], registration.event_id)
        self.assertEqual(event.payload["base_plan_event_id"], self.material["studies"][0]["plan_event"].event_id)
        self.assertEqual(len(event.payload["result"]["cost_stress_runs"]), 3)
        self.assertIsNone(event.payload["result"]["realized_trade_pnl"])
        self.assertFalse(any(event.payload["result"]["authority"].values()))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_registration_exact_retry_is_idempotent(self):
        first, event = self.register(); second, again = self.register()
        self.assertTrue(first.written); self.assertFalse(second.written)
        self.assertEqual(event.to_bytes(), again.to_bytes())
        self.assertEqual(self.store.verify().event_count, 7)

    def test_evaluation_exact_retry_is_idempotent(self):
        self.register(); first, event = self.evaluate(); second, again = self.evaluate()
        self.assertTrue(first.written); self.assertFalse(second.written)
        self.assertEqual(event.to_bytes(), again.to_bytes())

    def test_later_trial_does_not_change_original_evaluation_retry(self):
        self.register(); _, original = self.evaluate()
        value = self.study.to_dict(); value.update(study_id="later-shadow-study", registered_at="2025-04-01T14:00:00Z")
        value["trial_registry"] = {"trial_id": "later-shadow-trial", "prior_trial_ids": [self.study.trial_registry["trial_id"]]}
        later = TradingShadowStudy.from_mapping(value)
        self.register(later)
        _, again = self.evaluate()
        self.assertEqual(original.to_bytes(), again.to_bytes())

    def test_evaluation_without_registration_is_rejected(self):
        events, blobs = self.context()
        with self.assertRaisesRegex(ValueError, "preceding"):
            build_shadow_evaluation_event(self.study, events, blobs, evaluation_id="unregistered", recorded_at=EVALUATED_AT)

    def test_missing_base_registration_is_rejected(self):
        events, blobs = self.context()
        with self.assertRaises(ValueError): build_study_event(self.study, events[:2], blobs)

    def test_original_dataset_and_hypothesis_sources_are_retained(self):
        _, event = self.register()
        base = self.material["studies"][0]["plan"]
        hashes = {ref["sha256"] for ref in event.evidence}
        self.assertIn(base.dataset_evidence["sha256"], hashes)
        self.assertIn(base.frozen_hypothesis_evidence["sha256"], hashes)
        self.assertIn(self.material["request"].sources["bars_evidence"]["sha256"], hashes)
        self.assertTrue(any("implementation/trading_shadow_intents.py" in ref["path"] for ref in event.evidence))

    def test_registration_clock_before_base_is_rejected(self):
        value = self.study.to_dict(); value["registered_at"] = "2025-04-01T10:00:00Z"
        events, blobs = self.context()
        with self.assertRaises(ValueError): build_study_event(value, events, blobs)

    def test_evaluation_clock_before_registration_is_rejected(self):
        self.register()
        with self.assertRaises(ValueError): self.evaluate(recorded_at="2025-04-01T11:59:00Z")

    def test_changed_registered_sizing_conflicts(self):
        self.register(); value = self.study.to_dict(); value["sizing"]["per_symbol_notional"] = "60"
        with self.assertRaisesRegex(ValueError, "immutable"): self.register(TradingShadowStudy.from_mapping(value))

    def test_incomplete_trial_registry_is_rejected(self):
        self.register(); value = self.study.to_dict(); value["study_id"] = "new-trial-study"
        value["trial_registry"] = {"trial_id": "new-shadow-trial", "prior_trial_ids": []}
        with self.assertRaisesRegex(ValueError, "every preceding"): self.register(TradingShadowStudy.from_mapping(value))

    def test_gate_policy_changes_require_separate_experiment(self):
        self.register(); value = self.study.to_dict(); value["study_id"] = "changed-gate-study"
        value["price_continuity_evidence"] = None
        value["trial_registry"] = {"trial_id": "changed-gate-trial", "prior_trial_ids": [self.study.trial_registry["trial_id"]]}
        with self.assertRaisesRegex(ValueError, "distinct experiment"): self.register(TradingShadowStudy.from_mapping(value))

    def test_missing_gate_study_is_recorded_as_deferred_without_exposure(self):
        value = self.study.to_dict(); value["cost_evidence"] = value["price_continuity_evidence"] = None
        value["evidence_scope"] = "RETAINED_HISTORY_RESEARCH"
        study = TradingShadowStudy.from_mapping(value)
        self.register(study); _, event = self.evaluate(study)
        result, production = event.payload["result"], event.payload["production"]
        self.assertEqual(result["status"], "DEFER_EVIDENCE_GATES")
        self.assertEqual(result["cost_stress_runs"], [])
        self.assertEqual(production["intents"]["decisions"], [])

    def test_assessment_is_read_only(self):
        self.register(); before = self.store.verify().to_dict()
        events, blobs = self.context()
        result = assess_registered_shadow(self.study, events, blobs)
        self.assertEqual(result["result"]["status"], "SHADOW_SIMULATED")
        self.assertEqual(before, self.store.verify().to_dict())

    def test_rehashed_result_tampering_is_rejected(self):
        self.register(); events, blobs = self.context()
        event = build_shadow_evaluation_event(self.study, events, blobs, evaluation_id="tampered", recorded_at=EVALUATED_AT)
        value = event.to_dict(); value["payload"]["result"]["aggregate"] = {"return": "10"}
        with self.assertRaises(JournalStoreError):
            self.store.append(JournalEvent.from_mapping(value), evidence_for_shadow(self.study, events, blobs))

    def test_rehashed_production_tampering_is_rejected(self):
        self.register(); events, blobs = self.context()
        event = build_shadow_evaluation_event(self.study, events, blobs, evaluation_id="tampered", recorded_at=EVALUATED_AT)
        value = event.to_dict(); value["payload"]["production"]["opportunities"] = []
        with self.assertRaises(JournalStoreError):
            self.store.append(JournalEvent.from_mapping(value), evidence_for_shadow(self.study, events, blobs))

    def test_original_authority_cannot_be_changed(self):
        self.register(); events, blobs = self.context()
        value = build_shadow_evaluation_event(self.study, events, blobs, evaluation_id="tampered", recorded_at=EVALUATED_AT).to_dict()
        value["payload"]["result"]["authority"]["execution_enabled"] = True
        with self.assertRaises(ValueError): JournalEvent.from_mapping(value)

    def test_hash_corrupted_origin_material_is_rejected(self):
        events, blobs = self.context()
        ref = self.material["price_source"].origin_evidence[0]
        blobs[ref["sha256"]] += b"tampered"
        with self.assertRaises(ValueError): build_study_event(self.study, events, blobs)

    def test_changed_installed_calculation_code_fails_replay(self):
        self.register(); code = implementation_evidence()
        path = next(iter(code)); code[path] += b"\n# simulated changed version\n"
        with patch("blackpod_build_week.trading_shadow_journal.implementation_evidence", return_value=code):
            with self.assertRaises(JournalStoreError): self.store.verify()

    def test_verification_replays_after_external_sources_disappear(self):
        self.register(); self.evaluate(); self.material["blobs"].clear(); self.material["evidence"].clear()
        self.assertEqual(self.store.verify().event_count, 8)

    def test_missing_bound_bytes_reject_publication(self):
        events, blobs = self.context(); event = build_study_event(self.study, events, blobs)
        with self.assertRaises(JournalStoreError): self.store.append(event, {})
        self.assertEqual(self.store.verify().event_count, 6)

    def test_interrupted_append_recovers_by_exact_retry(self):
        from blackpod_build_week import decision_journal_store as module
        events, blobs = self.context(); event = build_study_event(self.study, events, blobs)
        evidence = evidence_for_shadow(self.study, events, blobs)
        original = module._publish_immutable
        def interrupted(*args, **kwargs):
            if args[2].endswith(".json"):
                raise OSError("simulated interrupted publication")
            return original(*args, **kwargs)
        with patch.object(module, "_publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalStoreError): self.store.append(event, evidence)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().event_count, 7)


if __name__ == "__main__": unittest.main()
