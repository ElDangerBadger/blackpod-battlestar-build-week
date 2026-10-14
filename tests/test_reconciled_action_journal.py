"""Original-history lineage, frozen source identities and journal recovery."""
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
from blackpod_build_week.contracts.reconciled_action_intake import ReconciledActionIntakePolicy, ReconciledActionIntakeRequest
from blackpod_build_week.contracts.reconciled_action_journal import POLICY_TYPE, INTAKE_TYPE
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week import decision_journal_store as storage
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_action_journal import (
    source_context, prepare_policy, policy_material, intake_material,
)


@lru_cache(maxsize=1)
def fixture():
    from blackpod_build_week.reconciled_action_intake_example import example_material
    with patch.object(socket.socket, "connect", side_effect=AssertionError("offline only")), patch("subprocess.Popen", side_effect=AssertionError("no workers")):
        material = example_material()
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "journal"
        n = material["source_count"]
        append_journal_batch(JournalStore(root), [{"event": event, "evidence": evidence} for event, evidence in
            zip(material["events"][:n], material["event_evidence"][:n])])
        return material, root, temporary


def entries(root):
    return {path.name: path.read_bytes() for path in sorted((root / "entries").glob("*.json"))}


def later(value):
    return (parse_rfc3339(value, "fixture clock") + timedelta(days=1)).isoformat().replace("+00:00", "Z")


class ReconciledActionJournalTests(unittest.TestCase):
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
        self.n = self.material["source_count"]
        self.events = self.material["events"][:self.n]
        self.blobs = dict(self.material["blobs"])
        self.policy = self.material["policy"]
        self.request = self.material["request"]

    def policy_change(self, **changes):
        return ReconciledActionIntakePolicy.from_mapping({**self.policy.to_dict(), **changes})

    def request_change(self, **changes):
        return ReconciledActionIntakeRequest.from_mapping({**self.request.to_dict(), **changes})

    def policy_record(self):
        return policy_material(self.policy, self.events, self.blobs)

    def intake_record(self, request=None, policy=None):
        p = self.policy_record() if policy is None else policy
        return intake_material(request or self.request, (*self.events, p["event"]), self.blobs)

    def batch(self):
        return [self.policy_record(), self.intake_record()]

    def test_source_intake_has_independent_identity_but_exact_native_binding(self):
        context = source_context(self.policy.anchor_review_event_id, self.events, self.blobs)
        self.assertNotEqual(context["continuity"].decision_id, context["anchor"].decision_id)
        self.assertEqual(context["native_continuity_export_evidence"], self.policy.native_continuity_export_evidence)
        self.assertEqual(context["masks_raw"], self.blobs[self.policy.original_native_masks_evidence["sha256"]])

    def test_prepare_policy_derives_exact_old_masks_without_rewriting_sources(self):
        before = dict(self.blobs)
        prepared = prepare_policy(self.policy.anchor_review_event_id, self.policy.policy_id, self.policy.recorded_at,
            self.policy.independent_inventories, self.events, self.blobs)
        self.assertEqual(prepared["policy"].to_bytes(), self.policy.to_bytes())
        self.assertEqual(self.blobs, before)
        self.assertFalse(any(prepared["policy"].authority.values()))

    def test_original_research_identity_and_all_native_reasons_are_retained(self):
        p, i = self.batch()
        anchor = next(event for event in self.events if event.event_id == self.policy.anchor_review_event_id)
        for material in (p, i):
            self.assertEqual(material["event"].decision_id, anchor.decision_id)
            self.assertEqual(material["event"].payload["anchor_snapshot"]["native_qualification_snapshot"], anchor.payload["result"]["native_qualification_snapshot"])
        result = i["result"]
        self.assertFalse(result["legacy_source_compatible"])
        self.assertFalse(result["old_masks_modified"])
        self.assertFalse(result["coverage_supported"])
        self.assertIsNone(result["realized_trade_pnl"])

    def test_policy_cannot_drop_original_independent_inventory(self):
        context = source_context(self.policy.anchor_review_event_id, self.events, self.blobs)
        refs = [ref for ref in self.policy.independent_inventories if ref not in context["independent_inventories"]]
        self.assertTrue(refs)
        with self.assertRaises(ValueError):
            policy_material(self.policy_change(independent_inventories=refs), self.events, self.blobs)

    def test_policy_cannot_rebind_original_dataset_or_export(self):
        for field in ("dataset_evidence", "native_continuity_export_evidence"):
            changed = {**getattr(self.policy, field), "path": "rebound/" + field + ".json"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                policy_material(self.policy_change(**{field: changed}), self.events, self.blobs)

    def test_policy_cannot_rewrite_original_mask_snapshot(self):
        raw = canonical_json_bytes({"invented": True})
        ref = {"path": self.policy.original_native_masks_evidence["path"], "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        with self.assertRaises(ValueError):
            policy_material(self.policy_change(original_native_masks_evidence=ref), self.events, {**self.blobs, sha256_bytes(raw): raw})

    def test_missing_selected_anchor_never_uses_latest_fallback(self):
        with self.assertRaises(ValueError):
            policy_material(self.policy, tuple(event for event in self.events if event.event_id != self.policy.anchor_review_event_id), self.blobs)

    def test_duplicate_history_ids_reject(self):
        with self.assertRaises(ValueError):
            policy_material(self.policy, (*self.events, self.events[-1]), self.blobs)

    def test_changed_anchor_payload_cannot_replace_retained_original(self):
        anchor = next(event for event in self.events if event.event_id == self.policy.anchor_review_event_id)
        changed = anchor.to_dict()
        changed["payload"]["result"]["review_id"] = "different-review"
        with self.assertRaises(ValueError):
            fake = JournalEvent.from_mapping(changed)
            policy_material(self.policy, tuple(fake if event == anchor else event for event in self.events), self.blobs)

    def test_missing_masks_and_manifest_sources_fail_closed(self):
        for ref in (self.policy.original_native_masks_evidence, self.policy.independent_inventories[-1]):
            blobs = dict(self.blobs); blobs.pop(ref["sha256"])
            with self.subTest(path=ref["path"]), self.assertRaises(ValueError):
                policy_material(self.policy, self.events, blobs)

    def test_policy_status_and_authority_are_closed(self):
        for changes in ({"status": "PROPOSED"}, {"auto_trading_enabled": True},
                {"authority": {**self.policy.authority, "execution_enabled": True}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.policy_change(**changes)

    def test_intake_requires_recorded_policy_before_itself(self):
        with self.assertRaises(ValueError): intake_material(self.request, self.events, self.blobs)

    def test_intake_cannot_select_unrelated_policy_leaf_alias(self):
        request = self.request_change(policy_evidence={**self.request.policy_evidence, "path": "unrelated-policy.json"})
        with self.assertRaises(ValueError): self.intake_record(request)

    def test_later_intake_reuses_frozen_sources_and_exact_old_masks(self):
        before = self.intake_record()["result"]
        request = self.request_change(intake_id="later-same-frozen-policy", recorded_at=later(self.request.recorded_at), data_cutoff_at=later(self.request.data_cutoff_at))
        after = self.intake_record(request)["result"]
        self.assertEqual(before["original_native_masks"], after["original_native_masks"])
        self.assertEqual(before["candidate_overlay"], after["candidate_overlay"])

    def test_mixed_history_publication_and_full_verification_preserve_prefix(self):
        before = entries(self.root)
        result = append_journal_batch(self.store, self.batch())
        self.assertEqual([item.written for item in result], [True, True])
        summary = self.store.verify()
        self.assertEqual(summary.event_count, self.n + 2)
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(summary.staging_orphan_count, 0)
        self.assertTrue(all(entries(self.root)[name] == raw for name, raw in before.items()))

    def test_exact_policy_and_intake_retry_writes_nothing(self):
        batch = self.batch(); append_journal_batch(self.store, batch)
        before = entries(self.root)
        retried = append_journal_batch(self.store, [{"event": item["event"], "evidence": {}} for item in batch])
        self.assertEqual([item.written for item in retried], [False, False])
        self.assertEqual(entries(self.root), before)

    def test_projection_retry_after_later_records_keeps_original_prefix(self):
        p, i = self.batch()
        later_events = (*self.events, p["event"], i["event"])
        self.assertEqual(policy_material(self.policy, later_events, self.blobs)["event"].to_bytes(), p["event"].to_bytes())
        self.assertEqual(intake_material(self.request, later_events, self.blobs)["event"].to_bytes(), i["event"].to_bytes())

    def test_changed_content_under_existing_policy_identity_conflicts(self):
        append_journal_batch(self.store, self.batch())
        changed = self.policy_change(recorded_at=later(self.policy.recorded_at))
        with self.assertRaises((ValueError, JournalStoreError)):
            policy_material(changed, self.material["events"], self.blobs)

    def test_rehashed_semantic_tampering_rejected(self):
        append_journal_batch(self.store, self.batch())
        path = self.root / "entries" / ("%08d.json" % (self.n + 2))
        entry = json.loads(path.read_bytes())
        entry["event"]["payload"]["result"]["reason_codes"].append("FORGED_EVIDENCE_SUPPORT")
        entry["event_sha256"] = sha256_bytes(canonical_json_bytes(entry["event"]))
        path.chmod(0o600)  # Deliberately simulate an attacker able to rewrite a retained file.
        path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaises(JournalStoreError): self.store.verify()

    def test_supersession_appends_and_cannot_fork(self):
        p, i = self.batch()
        request = self.request_change(intake_id="linked-research-review", recorded_at=later(self.request.recorded_at),
            data_cutoff_at=later(self.request.data_cutoff_at), supersedes_event_id=i["event"].event_id)
        previous = (*self.events, p["event"], i["event"])
        linked = intake_material(request, previous, self.blobs)
        self.assertEqual(linked["event"].payload["prior_intake_event_ids"], [i["event"].event_id])
        fork = self.request_change(intake_id="forked-review", recorded_at=request.recorded_at, data_cutoff_at=request.data_cutoff_at, supersedes_event_id=i["event"].event_id)
        with self.assertRaises(ValueError): intake_material(fork, (*previous, linked["event"]), self.blobs)

    def test_interrupted_suffix_recovers_without_rewriting_original_policy(self):
        batch = self.batch(); original = storage._publish_immutable
        def fail(staging, target, name, raw):
            if name == "%08d.json" % (self.n + 2): raise OSError("authored precommit interruption")
            return original(staging, target, name, raw)
        with patch.object(storage, "_publish_immutable", side_effect=fail), self.assertRaises(JournalStoreError):
            append_journal_batch(self.store, batch)
        self.assertEqual(len(entries(self.root)), self.n + 1)
        retried = append_journal_batch(self.store, batch)
        self.assertEqual([item.written for item in retried], [False, True])
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_postpublication_interruption_recovers_as_zero_write_retry(self):
        batch = self.batch(); original = storage._publish_immutable
        def fail(staging, target, name, raw):
            result = original(staging, target, name, raw)
            if name == "%08d.json" % (self.n + 2): raise OSError("authored postcommit interruption")
            return result
        with patch.object(storage, "_publish_immutable", side_effect=fail), self.assertRaises(JournalStoreError):
            append_journal_batch(self.store, batch)
        self.assertEqual(len(entries(self.root)), self.n + 2)
        retried = append_journal_batch(self.store, batch)
        self.assertEqual([item.written for item in retried], [False, False])
        self.assertEqual(self.store.verify().staging_orphan_count, 0)
