"""v20 source binding, immutable replay, linked updates and durable recovery."""
from functools import lru_cache
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from test_segmented_evidence_qualification import fixture_material
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.segmented_evidence_qualification import (
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest,
)
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError, JournalPersistenceError
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week import decision_journal_store as storage
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.segmented_evidence_qualification_journal import binding_material, qualification_material


@lru_cache(maxsize=1)
def retained_fixture():
    """One verified prefix shared by CLI/journal tests in the same process."""
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
        material = fixture_material()
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "journal"
        store = JournalStore(root)
        append_journal_batch(store, [{"event": event, "evidence": evidence}
            for event, evidence in zip(material["events"], material["event_evidence"])])
        return material, root, temporary


class SegmentedJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material, cls.base, cls.retained_temp = retained_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        shutil.copytree(self.base, self.root / "journal")
        self.store = JournalStore(self.root / "journal")

    def freeze(self, document=None):
        events, blobs = self.store.verified_contents()
        material = binding_material(document or self.material["binding"], events, blobs)
        result = self.store.append(material["event"], material["evidence"])
        return result, material

    def evaluate(self, document=None):
        events, blobs = self.store.verified_contents()
        material = qualification_material(document or self.material["request"], events, blobs)
        result = self.store.append(material["event"], material["evidence"])
        return result, material

    def test_binding_and_assessment_append_without_changing_source_history(self):
        before = [event.to_bytes() for event in self.store.events()]
        self.freeze()
        written, material = self.evaluate()
        self.assertTrue(written.written)
        self.assertEqual(material["event"].schema_version, "blackpod.decision_journal_event.v20")
        self.assertEqual(material["result"]["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertEqual([event.to_bytes() for event in self.store.events()[:len(before)]], before)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_exact_retry_after_later_link_preserves_original_record(self):
        self.freeze()
        _, first = self.evaluate()
        request = self.material["request"].to_dict()
        request.update(qualification_id="root-linked-segmented-review", recorded_at="2025-04-06T12:00:00Z",
            data_cutoff_at="2025-04-06T11:00:00Z", supersedes_event_id=first["event"].event_id)
        self.evaluate(request)
        retry, repeated = self.evaluate()
        self.assertFalse(retry.written)
        self.assertEqual(first["event"].to_bytes(), repeated["event"].to_bytes())
        self.assertFalse(self.freeze()[0].written)

    def test_changed_binding_identity_conflicts(self):
        self.freeze()
        document = self.material["binding"].to_dict()
        document["recorded_at"] = "2025-04-05T10:01:00Z"
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.freeze(document)

    def test_changed_assessment_identity_conflicts(self):
        self.freeze()
        self.evaluate()
        document = self.material["request"].to_dict()
        document["data_cutoff_at"] = "2025-04-05T11:30:00Z"
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.evaluate(document)

    def test_unsupported_positive_pnl_or_execution_cannot_be_recorded(self):
        self.freeze()
        events, blobs = self.store.verified_contents()
        material = qualification_material(self.material["request"], events, blobs)
        for field, value in (("realized_trade_pnl", "1"), ("execution_status", "EXECUTED"),
                ("economic_hypothesis_supported", True), ("uncertainty_computed", True),
                ("existing_gate_override", True), ("auto_trading_enabled", True)):
            changed = material["event"].to_dict()
            changed["payload"]["result"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                JournalEvent.from_mapping(changed)

    def test_rehashed_semantic_result_tamper_rejects_append(self):
        self.freeze()
        events, blobs = self.store.verified_contents()
        material = qualification_material(self.material["request"], events, blobs)
        changed = material["event"].to_dict()
        changed["payload"]["result"]["limitations"] = ["Invented result after valid source hashes."]
        with self.assertRaises(JournalStoreError):
            self.store.append(JournalEvent.from_mapping(changed), material["evidence"])

    def test_methodology_pin_change_rejects_read(self):
        self.freeze()
        from blackpod_build_week import segmented_evidence_qualification as engine
        with patch.object(engine, "implementation_evidence", return_value={"changed.py": b"different"}):
            with self.assertRaises(JournalStoreError):
                self.store.verify()

    def test_missing_raw_source_blob_is_rejected_even_when_consumer_uses_compact_evidence(self):
        self.freeze()
        self.evaluate()
        event = self.material["segment_events"][0]
        reference = event.payload["request"]["pages"][0]["body_evidence"]
        (self.store.root / "evidence" / reference["sha256"]).unlink()
        with self.assertRaises(JournalStoreError):
            self.store.verify()

    def test_interrupted_qualification_publication_recovers_exactly(self):
        self.freeze()
        events, blobs = self.store.verified_contents()
        material = qualification_material(self.material["request"], events, blobs)
        next_entry = "%08d.json" % (len(events) + 1)
        publish = storage._publish_immutable
        def interrupted(staging, destination, name, raw):
            if name == next_entry:
                raise OSError("simulated interrupted qualification publication")
            return publish(staging, destination, name, raw)
        with patch.object(storage, "_publish_immutable", side_effect=interrupted), self.assertRaises(JournalPersistenceError):
            self.store.append(material["event"], material["evidence"])
        written = self.store.append(material["event"], material["evidence"])
        self.assertTrue(written.written)
        self.assertFalse(self.store.append(material["event"], material["evidence"]).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertEqual(self.store.verify().staging_orphan_count, 0)

    def test_source_clocks_and_future_cutoff_reject(self):
        self.freeze()
        request = self.material["request"].to_dict()
        request["data_cutoff_at"] = "2025-04-05T09:00:00Z"
        with self.assertRaisesRegex(ValueError, "cutoff"):
            self.evaluate(request)
        request["data_cutoff_at"] = "2025-04-07T00:00:00Z"
        with self.assertRaises(ValueError):
            SegmentedEvidenceQualificationRequest.from_mapping(request)

    def test_wrong_decision_domain_or_identity_cannot_append(self):
        events, blobs = self.store.verified_contents()
        material = binding_material(self.material["binding"], events, blobs)
        changed = material["event"].to_dict()
        changed["decision_id"] = "journal-decision-" + "a" * 64
        with self.assertRaises(JournalStoreError):
            self.store.append(JournalEvent.from_mapping(changed), material["evidence"])

    def test_compact_binding_does_not_duplicate_capture_raw_corpus(self):
        _, material = self.freeze()
        raw_hashes = {reference["sha256"] for event in self.material["segment_events"]
            for page in event.payload["request"]["pages"] for reference in page.values()}
        self.assertFalse(raw_hashes & {reference["sha256"] for reference in material["event"].evidence})
