"""V17 append-only assessments reuse authoritative retained-input replay."""
import copy
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.research_assessment import ResearchAssessmentRequest
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError, JournalPersistenceError
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.research_acceptance import assess_research, prepare_request
from blackpod_build_week.research_acceptance_journal import assessment_material, validate_assessment_event
from test_research_acceptance_trading import material_with_blobs, acceptance_request


class ResearchAcceptanceJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = material_with_blobs()
        cls.base = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.base.cleanup)
        cls.base_root = Path(cls.base.name).resolve() / "journal"
        store = JournalStore(cls.base_root)
        for event, evidence in zip(cls.original["events"], cls.original["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        shutil.copytree(self.base_root, self.root / "journal")
        self.store = JournalStore(self.root / "journal")
        self.request = acceptance_request(self.original)

    def material(self, request=None):
        events, blobs = self.store.verified_contents()
        return assessment_material(request or self.request, events, blobs)

    def append(self, request=None):
        material = self.material(request)
        return self.store.append(material["event"], material["evidence"]), material

    def later(self, first, **changes):
        return {**copy.deepcopy(self.request), "assessment_id": "later-acceptance", "recorded_at": "2025-04-03T00:00:00Z", "data_cutoff_at": "2025-04-02T00:00:00Z", "supersedes_event_id": first.event_id, **changes}

    def test_full_v17_replay_original_parent_and_source_bytes(self):
        before = tuple(event.to_bytes() for event in self.store.events())
        appended, material = self.append(); event = material["event"]
        self.assertTrue(appended.written)
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v17")
        source = next(event for event in self.original["events"] if event.event_id == self.request["hypothesis"]["source_event_id"])
        self.assertEqual(event.decision_id, source.decision_id)
        self.assertEqual(tuple(event.to_bytes() for event in self.store.events()[:len(before)]), before)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_exact_retry_and_retry_after_later_history(self):
        first, material = self.append(); old = material["event"].to_bytes()
        retry, repeated = self.append(); self.assertFalse(retry.written)
        self.assertEqual(old, repeated["event"].to_bytes())
        _, later = self.append(self.later(material["event"]))
        retry, repeated = self.append(); self.assertFalse(retry.written)
        self.assertEqual(old, repeated["event"].to_bytes())
        self.assertEqual(later["event"].payload["prior_assessment_event_ids"], [material["event"].event_id])

    def test_later_link_preserves_original_assessment(self):
        _, original = self.append()
        _, later = self.append(self.later(original["event"]))
        self.assertEqual(later["event"].payload["request"]["supersedes_event_id"], original["event"].event_id)
        self.assertEqual(self.store.events()[-2].to_bytes(), original["event"].to_bytes())

    def test_changed_request_same_identity_rejects(self):
        self.append()
        for field, value in (("recorded_at", "2025-04-03T00:00:00Z"), ("assessment_scope", "ECONOMIC_VALIDATION")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "immutable"):
                self.material({**self.request, field: value})

    def test_supersession_cannot_cross_hypothesis_revision_or_scope(self):
        _, original = self.append()
        for changes in ({"assessment_scope": "ECONOMIC_VALIDATION"}, {"hypothesis": {**self.request["hypothesis"], "evidence": {**self.request["hypothesis"]["evidence"], "sha256": "a" * 64}}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.material(self.later(original["event"], **changes))

    def test_supersession_requires_existing_same_history_and_no_branch(self):
        _, original = self.append()
        with self.assertRaises(ValueError): self.material(self.later(original["event"], supersedes_event_id="journal-event-" + "a" * 64))
        self.append(self.later(original["event"]))
        with self.assertRaisesRegex(ValueError, "branch"): self.material(self.later(original["event"], assessment_id="branched-acceptance"))

    def test_supersession_cutoff_cannot_move_backwards(self):
        _, original = self.append()
        with self.assertRaisesRegex(ValueError, "backwards"):
            self.material(self.later(original["event"], data_cutoff_at="2025-04-01T22:00:00Z"))

    def test_same_scope_record_clock_cannot_backdate_previous_assessment(self):
        self.append()
        with self.assertRaisesRegex(ValueError, "prior same-scope"):
            self.material({**self.request, "assessment_id": "backdated", "recorded_at": "2025-04-01T23:00:00Z"})

    def test_source_after_cutoff_rejects(self):
        with self.assertRaises(ValueError): self.material({**self.request, "data_cutoff_at": "2025-04-01T13:00:00Z"})

    def test_tampered_assessment_and_prior_links_reject(self):
        material = self.material()
        value = material["event"].to_dict(); value["payload"]["prior_assessment_event_ids"] = ["journal-event-" + "a" * 64]
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(value), material["evidence"])
        value = material["event"].to_dict(); value["payload"]["assessment"]["claim_scope"] = "Unverified replacement"
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(value), material["evidence"])

    def test_wrong_decision_parent_rejects(self):
        material = self.material(); value = material["event"].to_dict(); value["decision_id"] = "journal-decision-" + "a" * 64
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(value), material["evidence"])

    def test_retained_implementation_change_rejects(self):
        _, material = self.append()
        events, blobs = self.store.verified_contents()
        from blackpod_build_week import research_acceptance
        with patch.object(research_acceptance, "implementation_evidence", return_value={"research-acceptance/implementation/research_acceptance.py": b"changed"}):
            with self.assertRaises(ValueError): validate_assessment_event(material["event"], events[:-1], blobs)

    def test_existing_evidence_corruption_rejects_before_new_write(self):
        material = self.material(); digest = self.request["hypothesis"]["evidence"]["sha256"]
        path = self.store.root / "evidence" / digest; os.chmod(path, 0o644); path.write_bytes(b"corrupt")
        with self.assertRaises(JournalStoreError): self.store.append(material["event"], material["evidence"])

    def test_interrupted_entry_publication_recovers_with_orphan_evidence(self):
        from blackpod_build_week import decision_journal_store as module
        material = self.material(); original = module._publish_immutable
        def interrupted(staging, directory, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("simulated entry interruption")
            return original(staging, directory, name, raw)
        with patch.object(module, "_publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalPersistenceError): self.store.append(material["event"], material["evidence"])
        self.assertEqual(self.store.verify().event_count, len(self.original["events"]))
        self.assertGreater(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(material["event"], material["evidence"]).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_duplicate_context_events_reject(self):
        events, blobs = self.store.verified_contents()
        with self.assertRaisesRegex(ValueError, "unique"):
            assess_research(self.request, events + (events[0],), blobs)

    def test_preparation_keeps_original_catalog_after_later_catalog_append(self):
        from blackpod_build_week.trading_research_intake_journal import build_catalog_event, catalog_evidence
        from blackpod_build_week.contracts.trading_hypothesis import TradingHypothesisCatalog
        events, blobs = self.store.verified_contents()
        original = next(event for event in events if event.event_type == "TRADING_HYPOTHESIS_CATALOG_RECORDED")
        document = {**original.payload["catalog"], "catalog_id": "later-distinct-catalog"}
        catalog = TradingHypothesisCatalog.from_mapping(document); self.store.append(build_catalog_event(catalog), catalog_evidence(catalog))
        events, blobs = self.store.verified_contents()
        prepared = prepare_request(events, research_event_id=self.request["research_event_id"], assessment_id="prepared-later", recorded_at="2025-04-03T00:00:00Z", data_cutoff_at="2025-04-02T00:00:00Z", blobs=blobs)
        self.assertEqual(prepared.hypothesis, self.request["hypothesis"])

    def test_findings_cannot_misstate_exact_source_observation(self):
        from blackpod_build_week import research_acceptance_trading
        events, blobs = self.store.verified_contents()
        material = research_acceptance_trading.assess_trading_acceptance(self.request, events, blobs)
        material["assessment_fields"]["findings"][0]["observed"] = "forged"
        with patch.object(research_acceptance_trading, "assess_trading_acceptance", return_value=material):
            with self.assertRaisesRegex(ValueError, "source scalar"): assess_research(self.request, events, blobs)
