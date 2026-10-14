"""Exact v23 lineage, immutable v24 research records and interrupted retries."""
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import parse_rfc3339
from blackpod_build_week.contracts.reconciled_shadow_qualification import ReconciledShadowQualificationRequest
from blackpod_build_week.contracts.reconciled_shadow_qualification_journal import TYPE
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week import decision_journal_store as storage
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_shadow_qualification_journal import source_context, qualification_material


def later(value, days=1):
    return (parse_rfc3339(value, "fixture clock") + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def entries(root):
    return {path.name: path.read_bytes() for path in sorted((root / "entries").glob("*.json"))}


@lru_cache(maxsize=1)
def fixture():
    from blackpod_build_week.reconciled_shadow_qualification_example import example_material
    with patch.object(socket.socket, "connect", side_effect=AssertionError("offline only")), patch("subprocess.Popen", side_effect=AssertionError("no workers")):
        material = example_material()
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "journal"
        count = material["source_count"]
        append_journal_batch(JournalStore(root), [{"event": event, "evidence": evidence} for event, evidence in
            zip(material["events"][:count], material["event_evidence"][:count])])
        return material, root, temporary


class ReconciledShadowQualificationJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material, cls.base, cls.keep = fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "journal"
        shutil.copytree(self.base, self.root)
        self.store = JournalStore(self.root)
        self.count = self.material["source_count"]
        self.events = self.material["events"][:self.count]
        self.blobs = dict(self.material["blobs"])
        self.request = self.material["request"]

    def request_change(self, **changes):
        return ReconciledShadowQualificationRequest.from_mapping({**self.request.to_dict(), **changes})

    def record(self, request=None, events=None, blobs=None):
        return qualification_material(request or self.request, self.events if events is None else events,
            self.blobs if blobs is None else blobs)

    def extend(self, material, events=None, blobs=None):
        retained = dict(self.blobs if blobs is None else blobs)
        retained.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
        return (*(self.events if events is None else events), material["event"]), retained

    def test_exact_intake_derives_original_policy_native_and_distinct_continuity_identity(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        self.assertEqual(context["intake_result_ref"], self.request.intake_result_evidence)
        self.assertEqual(context["native_snapshot"], context["native"].payload["result"])
        self.assertNotEqual(context["continuity"].decision_id, context["native"].decision_id)
        self.assertEqual(context["intake"].decision_id, context["native"].decision_id)

    def test_result_retains_all_native_gates_masks_and_source_witnesses(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        result = self.record()["result"]
        self.assertEqual(result["native_qualification_snapshot"], context["native_snapshot"])
        self.assertTrue(set(context["native_snapshot"]["reason_codes"]) <= set(result["reason_codes"]))
        self.assertEqual(result["boundary_catalog"], context["intake_result"]["candidate_overlay"])
        self.assertEqual(result["coverage_matrix"], context["intake_result"]["coverage_matrix"])
        self.assertFalse(result["eligible_for_study_design"])
        self.assertFalse(result["old_masks_modified"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_mixed_publication_full_verification_preserves_every_original_entry(self):
        before = entries(self.root)
        result = self.store.append(**{key: self.record()[key] for key in ("event", "evidence")})
        self.assertTrue(result.written)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, self.count + 1)
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(summary.staging_orphan_count, 0)
        self.assertTrue(all(entries(self.root)[name] == raw for name, raw in before.items()))

    def test_exact_retry_writes_nothing(self):
        material = self.record()
        self.store.append(material["event"], material["evidence"])
        before = entries(self.root)
        retry = self.store.append(material["event"], {})
        self.assertFalse(retry.written)
        self.assertEqual(entries(self.root), before)

    def test_projection_retry_after_later_record_uses_original_prefix(self):
        material = self.record()
        events, blobs = self.extend(material)
        request = self.request_change(qualification_id="later-independent-review", recorded_at=later(self.request.recorded_at), data_cutoff_at=later(self.request.data_cutoff_at))
        second = self.record(request, events, blobs)
        events, blobs = self.extend(second, events, blobs)
        retried = self.record(events=events, blobs=blobs)
        self.assertEqual(retried["event"].to_bytes(), material["event"].to_bytes())

    def test_changed_request_under_existing_identity_is_a_conflict(self):
        material = self.record()
        events, blobs = self.extend(material)
        changed = self.request_change(recorded_at=later(self.request.recorded_at))
        with self.assertRaises(ValueError): self.record(changed, events, blobs)

    def test_missing_selected_intake_never_falls_back(self):
        events = tuple(event for event in self.events if event.event_id != self.request.intake_event_id)
        with self.assertRaises(ValueError): self.record(events=events)

    def test_duplicate_history_id_rejects(self):
        with self.assertRaises(ValueError): self.record(events=(*self.events, self.events[-1]))

    def test_intake_result_alias_cannot_replace_original_leaf(self):
        changed = self.request_change(intake_result_evidence={**self.request.intake_result_evidence, "path": "unrelated/intake.json"})
        with self.assertRaises(ValueError): self.record(changed)

    def test_missing_intake_result_bytes_fail_closed(self):
        blobs = dict(self.blobs); blobs.pop(self.request.intake_result_evidence["sha256"])
        with self.assertRaises(ValueError): self.record(blobs=blobs)

    def test_missing_selected_intake_implementation_cannot_be_reconstructed_from_installed_code(self):
        intake = next(event for event in self.events if event.event_id == self.request.intake_event_id)
        reference = next(ref for ref in intake.evidence if ref["path"] == "reconciled-actions/implementation/reconciled_action_intake.py")
        blobs = dict(self.blobs); blobs.pop(reference["sha256"])
        with self.assertRaises(ValueError): self.record(blobs=blobs)

    def test_tampered_selected_policy_implementation_is_rejected(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        reference = next(ref for ref in context["policy_event"].evidence if ref["path"] == "reconciled-actions/implementation/reconciled_action_journal.py")
        blobs = {**self.blobs, reference["sha256"]: b"changed implementation evidence"}
        with self.assertRaises(ValueError): self.record(blobs=blobs)

    def test_tampered_intake_result_payload_is_rejected(self):
        intake = next(event for event in self.events if event.event_id == self.request.intake_event_id)
        changed = intake.to_dict()
        changed["payload"]["result"]["reason_codes"].append("FORGED_SOURCE_SUPPORT")
        with self.assertRaises(ValueError):
            tampered = JournalEvent.from_mapping(changed)
            self.record(events=tuple(tampered if event == intake else event for event in self.events))

    def test_original_policy_event_cannot_be_replaced_by_a_valid_looking_summary(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        policy = context["policy_event"]
        changed = policy.to_dict(); changed["payload"]["implementation_evidence"] = []
        with self.assertRaises(ValueError):
            tampered = JournalEvent.from_mapping(changed)
            self.record(events=tuple(tampered if event == policy else event for event in self.events))

    def test_original_native_leaf_is_required(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        blobs = dict(self.blobs); blobs.pop(context["native_result_ref"]["sha256"])
        with self.assertRaises(ValueError): self.record(blobs=blobs)

    def test_cutoff_must_include_intake_event_even_when_its_policy_is_older(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        changed = self.request_change(data_cutoff_at=context["policy_event"].recorded_at)
        with self.assertRaises(ValueError): self.record(changed)

    def test_equal_source_clock_and_cutoff_are_valid(self):
        context = source_context(self.request.intake_event_id, self.events, self.blobs)
        changed = self.request_change(data_cutoff_at=context["intake"].recorded_at)
        self.assertFalse(self.record(changed)["result"]["eligible_for_study_design"])

    def test_future_cutoff_and_authority_changes_are_rejected(self):
        for changes in ({"data_cutoff_at": later(self.request.recorded_at)}, {"auto_trading_enabled": True},
                {"domain": "INVESTMENT"}, {"mode": "PAPER"}, {"scope": "EXECUTION"},
                {"authority": {**self.request.authority, "execution_enabled": True}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.request_change(**changes)

    def test_journal_source_hash_and_selected_link_are_strict(self):
        event = self.record()["event"].to_dict()
        variants = []
        changed = deepcopy(event); changed["source"]["source_sha256"] = "0" * 64; variants.append(changed)
        changed = deepcopy(event); changed["payload"]["links"]["intake_event_id"] = self.events[0].event_id; variants.append(changed)
        changed = deepcopy(event); changed["payload"]["result"]["recorded_at"] = later(self.request.recorded_at); variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed["source"]), self.assertRaises(ValueError): JournalEvent.from_mapping(changed)

    def test_rebound_source_snapshot_cannot_be_published(self):
        material = self.record()
        changed = material["event"].to_dict(); changed["payload"]["source_snapshot"]["intake_event_sha256"] = "0" * 64
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(changed), material["evidence"])
        self.assertEqual(len(entries(self.root)), self.count)

    def test_foreign_research_decision_cannot_own_qualification(self):
        material = self.record(); changed = material["event"].to_dict()
        changed["decision_id"] = "journal-decision-" + "0" * 64
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(changed), material["evidence"])

    def test_rehashed_semantic_tampering_does_not_survive_verification(self):
        material = self.record(); self.store.append(material["event"], material["evidence"])
        path = self.root / "entries" / ("%08d.json" % (self.count + 1))
        entry = json.loads(path.read_bytes())
        entry["event"]["payload"]["source_snapshot"]["native_qualification_event_sha256"] = "0" * 64
        entry["event_sha256"] = sha256_bytes(canonical_json_bytes(entry["event"]))
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaises(JournalStoreError): self.store.verify()

    def test_linked_supersession_appends_and_cannot_fork(self):
        base = self.record(); events, blobs = self.extend(base)
        changed = self.request_change(qualification_id="linked-overlay-review", recorded_at=later(self.request.recorded_at),
            data_cutoff_at=later(self.request.data_cutoff_at), supersedes_event_id=base["event"].event_id)
        linked = self.record(changed, events, blobs)
        self.assertEqual(linked["event"].payload["prior_qualification_event_ids"], [base["event"].event_id])
        events, blobs = self.extend(linked, events, blobs)
        fork = self.request_change(qualification_id="fork-overlay-review", recorded_at=changed.recorded_at,
            data_cutoff_at=changed.data_cutoff_at, supersedes_event_id=base["event"].event_id)
        with self.assertRaises(ValueError): self.record(fork, events, blobs)

    def test_supersession_cannot_retreat_cutoff(self):
        base = self.record(); events, blobs = self.extend(base)
        changed = self.request_change(qualification_id="later-cutoff-review", recorded_at=later(self.request.recorded_at),
            data_cutoff_at=later(self.request.data_cutoff_at), supersedes_event_id=base["event"].event_id)
        linked = self.record(changed, events, blobs); events, blobs = self.extend(linked, events, blobs)
        retreat = self.request_change(qualification_id="retreat-cutoff-review", recorded_at=later(changed.recorded_at),
            data_cutoff_at=self.request.data_cutoff_at, supersedes_event_id=linked["event"].event_id)
        with self.assertRaises(ValueError): self.record(retreat, events, blobs)

    def test_backdating_same_anchor_history_rejects(self):
        base = self.record(); events, blobs = self.extend(base)
        changed = self.request_change(qualification_id="backdated-review", recorded_at=self.events[-1].recorded_at,
            data_cutoff_at=self.events[-1].recorded_at)
        with self.assertRaises(ValueError): self.record(changed, events, blobs)

    def test_superseding_an_unrelated_event_rejects(self):
        with self.assertRaises(ValueError): self.record(self.request_change(supersedes_event_id=self.request.intake_event_id))

    def test_stale_fork_projection_rejects_under_writer_lock(self):
        base = self.record(); self.store.append(base["event"], base["evidence"])
        events, blobs = self.extend(base)
        common = {"recorded_at": later(self.request.recorded_at), "data_cutoff_at": later(self.request.data_cutoff_at),
            "supersedes_event_id": base["event"].event_id}
        first = self.record(self.request_change(qualification_id="first-claim", **common), events, blobs)
        stale = self.record(self.request_change(qualification_id="stale-second-claim", **common), events, blobs)
        self.store.append(first["event"], first["evidence"])
        with self.assertRaises(JournalStoreError): self.store.append(stale["event"], stale["evidence"])

    def test_prepublication_interruption_recovers_exactly(self):
        material = self.record(); before = entries(self.root); original = storage._publish_immutable
        def fail(staging, target, name, raw):
            if name == "%08d.json" % (self.count + 1): raise OSError("authored precommit interruption")
            return original(staging, target, name, raw)
        with patch.object(storage, "_publish_immutable", side_effect=fail), self.assertRaises(JournalStoreError):
            self.store.append(material["event"], material["evidence"])
        self.assertEqual(entries(self.root), before)
        self.assertTrue(self.store.append(material["event"], material["evidence"]).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_postpublication_interruption_retries_without_duplicate(self):
        material = self.record(); original = storage._publish_immutable
        def fail(staging, target, name, raw):
            result = original(staging, target, name, raw)
            if name == "%08d.json" % (self.count + 1): raise OSError("authored postcommit interruption")
            return result
        with patch.object(storage, "_publish_immutable", side_effect=fail), self.assertRaises(JournalStoreError):
            self.store.append(material["event"], material["evidence"])
        before = entries(self.root)
        self.assertFalse(self.store.append(material["event"], {}).written)
        self.assertEqual(entries(self.root), before)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)


if __name__ == "__main__": unittest.main()
