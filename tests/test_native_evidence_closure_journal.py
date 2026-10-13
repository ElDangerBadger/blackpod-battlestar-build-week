"""Immutable closure records, retained-only replay, retry and recovery."""
from functools import lru_cache
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from test_segmented_evidence_qualification import fixture_material
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.native_evidence_closure import (
    REQUEST_VERSION, NativeEvidenceClosureReviewRequest,
)
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalStoreError, JournalPersistenceError,
)
from blackpod_build_week import decision_journal_store as storage
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.native_evidence_closure_journal import review_material
from blackpod_build_week.segmented_evidence_qualification_journal import qualification_material


@lru_cache(maxsize=1)
def retained_closure_fixture():
    """Build one real-interface synthetic prefix, with all providers prohibited."""
    with patch.object(socket.socket, "connect", side_effect=AssertionError("offline only")):
        material = fixture_material(include_binding=True, policy_case="inactive-proposed-design")
        events, blobs = list(material["events"]), dict(material["blobs"])
        qualification = qualification_material(material["request"], events, blobs)
        events.append(qualification["event"])
        evidence = [*material["event_evidence"], qualification["evidence"]]
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "journal"
        store = JournalStore(root)
        append_journal_batch(store, [{"event": event, "evidence": item}
            for event, item in zip(events, evidence)])
        request = NativeEvidenceClosureReviewRequest.from_mapping({
            "schema_version": REQUEST_VERSION, "review_id": "journal-native-review-001",
            "recorded_at": "2025-04-06T12:00:00Z", "data_cutoff_at": "2025-04-06T11:00:00Z",
            "domain": "TRADING", "mode": "SHADOW_RESEARCH",
            "scope": "NATIVE_EVIDENCE_CLOSURE_REVIEW_ONLY",
            "anchor_qualification_event_id": qualification["event"].event_id,
            "candidate_qualification_event_id": None, "supplemental_review_evidence": None,
            "supersedes_event_id": None, "auto_trading_enabled": False,
            "authority": material["policy"].authority})
        return material, request, qualification, root, temporary


def entry_state(root):
    return {path.name: path.read_bytes() for path in sorted((root / "entries").glob("*.json"))}


class NativeClosureJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.request, cls.qualification, cls.base, cls.retained_temp = retained_closure_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        shutil.copytree(self.base, self.root / "journal")
        self.store = JournalStore(self.root / "journal")

    def material(self, request=None):
        events, blobs = self.store.verified_contents()
        return review_material(request or self.request, events, blobs)

    def append(self, request=None):
        material = self.material(request)
        return self.store.append(material["event"], material["evidence"]), material

    def test_mixed_version_review_preserves_original_entry_bytes_and_zero_orphans(self):
        original = entry_state(self.store.root)
        appended, material = self.append()
        self.assertTrue(appended.written)
        self.assertEqual(material["event"].schema_version, "blackpod.decision_journal_event.v21")
        self.assertEqual(material["event"].decision_id, self.qualification["event"].decision_id)
        after = entry_state(self.store.root)
        self.assertEqual({name: after[name] for name in original}, original)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, len(original) + 1)
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(summary.staging_orphan_count, 0)

    def test_exact_retry_after_linked_later_review_preserves_original_bytes(self):
        _, first = self.append()
        changed = self.request.to_dict()
        changed.update(review_id="journal-native-review-002", recorded_at="2025-04-07T12:00:00Z",
            data_cutoff_at="2025-04-07T11:00:00Z", supersedes_event_id=first["event"].event_id)
        self.append(changed)
        original = entry_state(self.store.root)
        retry, material = self.append()
        self.assertFalse(retry.written)
        self.assertEqual(material["event"].to_bytes(), first["event"].to_bytes())
        self.assertEqual(entry_state(self.store.root), original)

    def test_changed_source_under_same_review_id_conflicts(self):
        self.append()
        request = self.request.to_dict()
        request["data_cutoff_at"] = "2025-04-06T10:59:00Z"
        with self.assertRaises(ValueError):
            self.material(request)

    def test_wrong_decision_identity_rejects(self):
        material = self.material()
        value = material["event"].to_dict()
        value["decision_id"] = "journal-decision-" + "a" * 64
        with self.assertRaises(JournalStoreError):
            self.store.append(JournalEvent.from_mapping(value), material["evidence"])

    def test_rehashed_semantic_report_tamper_rejects_append(self):
        material = self.material()
        value = material["event"].to_dict()
        value["payload"]["result"]["limitations"] = ["Changed purported review after source verification."]
        with self.assertRaises((ValueError, JournalStoreError)):
            self.store.append(JournalEvent.from_mapping(value), material["evidence"])

    def test_rehashed_stored_result_tamper_rejects_verification(self):
        appended, _ = self.append()
        path = self.store.root / "entries" / ("%08d.json" % appended.sequence)
        value = json.loads(path.read_bytes())
        value["event"]["payload"]["result"]["limitations"] = ["Unvalidated replacement reasoning."]
        value["event_sha256"] = sha256_bytes(canonical_json_bytes(value["event"]))
        # Simulate a privileged actor bypassing the deliberate read-only mode.
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(JournalStoreError):
            self.store.verify()

    def test_missing_preceding_raw_quote_blob_rejects_retained_only_replay(self):
        self.append()
        source = self.source["segment_events"][0].payload["request"]["pages"][0]["body_evidence"]
        (self.store.root / "evidence" / source["sha256"]).unlink()
        with self.assertRaises(JournalStoreError):
            self.store.verify()

    def test_new_method_pin_change_rejects_history(self):
        self.append()
        from blackpod_build_week import native_evidence_closure as engine
        with patch.object(engine, "implementation_evidence", return_value={"changed.py": b"changed"}):
            with self.assertRaises(JournalStoreError):
                self.store.verify()

    def test_compact_review_does_not_duplicate_raw_capture_pages(self):
        material = self.material()
        source_hashes = {ref["sha256"] for event in self.source["segment_events"]
            for page in event.payload["request"]["pages"] for ref in page.values()}
        retained = {ref["sha256"] for ref in material["event"].evidence}
        self.assertFalse(source_hashes & retained)

    def test_precommit_interruption_recovers_original_prefix_and_exact_retry(self):
        original = entry_state(self.store.root)
        material = self.material()
        name = "%08d.json" % (len(original) + 1)
        publish = storage._publish_immutable
        def interrupted(staging, destination, filename, raw):
            if filename == name:
                raise OSError("simulated interrupted review publication")
            return publish(staging, destination, filename, raw)
        with patch.object(storage, "_publish_immutable", side_effect=interrupted), self.assertRaises(JournalPersistenceError):
            self.store.append(material["event"], material["evidence"])
        self.assertEqual(entry_state(self.store.root), original)
        self.assertTrue(self.store.append(material["event"], material["evidence"]).written)
        self.assertFalse(self.store.append(material["event"], material["evidence"]).written)
        summary = self.store.verify()
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(summary.staging_orphan_count, 0)

    def test_postcommit_failure_retries_without_another_event(self):
        material = self.material()
        count = len(entry_state(self.store.root))
        name = "%08d.json" % (count + 1)
        publish = storage._publish_immutable
        def committed_failure(staging, destination, filename, raw):
            result = publish(staging, destination, filename, raw)
            if filename == name:
                raise OSError("simulated directory durability failure after publication")
            return result
        with patch.object(storage, "_publish_immutable", side_effect=committed_failure), self.assertRaises(JournalPersistenceError):
            self.store.append(material["event"], material["evidence"])
        self.assertFalse(self.store.append(material["event"], material["evidence"]).written)
        self.assertEqual(self.store.verify().event_count, count + 1)

    def test_original_prefix_replay_needs_no_external_source_folders(self):
        self.append()
        events, blobs = self.store.verified_contents()
        replay = review_material(self.request, events, blobs)
        self.assertFalse(self.store.append(replay["event"], replay["evidence"]).written)

    def test_noncanonical_supplemental_source_bytes_survive_retained_only_replay(self):
        from blackpod_build_week.contracts.native_evidence_closure import CATEGORIES, SUPPLEMENTAL_VERSION
        events, blobs = self.store.verified_contents()
        value = {
            "schema_version": SUPPLEMENTAL_VERSION, "supplemental_review_id": "noncanonical-source-review",
            "recorded_at": "2025-04-06T10:00:00Z",
            "anchor_qualification_event_id": self.request.anchor_qualification_event_id,
            "candidate_qualification_event_id": None, "reviewer_id": "fictional-source-reviewer",
            "review_notes": "Unresolved software fixture, never native gate approval.",
            "categories": [{"category": category, "status": "UNRESOLVED",
                "source_event_ids": [], "source_documents": [], "notes": "No closure claimed."}
                for category in CATEGORIES],
            "auto_trading_enabled": False, "authority": self.request.authority}
        raw = json.dumps(value, indent=5, sort_keys=False).encode("utf-8")
        digest = sha256_bytes(raw)
        request = self.request.to_dict()
        request["supplemental_review_evidence"] = {
            "path": "external/original-supplemental.json", "sha256": digest, "size_bytes": len(raw)}
        material = review_material(request, events, {**blobs, digest: raw})
        self.store.append(material["event"], material["evidence"])
        self.assertEqual((self.store.root / "evidence" / digest).read_bytes(), raw)
        retained_events, retained_blobs = self.store.verified_contents()
        repeated = review_material(request, retained_events, retained_blobs)
        self.assertEqual(repeated["event"].to_bytes(), material["event"].to_bytes())
        self.assertFalse(self.store.append(repeated["event"], repeated["evidence"]).written)


if __name__ == "__main__":
    unittest.main()
