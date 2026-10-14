"""Real-interface passive history integration, conflicts and interrupted writes."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.evidence_reconciliation import EvidenceReconciliationRequest, REVIEW_TYPE, validate_result
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week import decision_journal_store as storage
from blackpod_build_week.evidence_reconciliation import build_source_context
from blackpod_build_week.evidence_reconciliation_journal import review_material
from blackpod_build_week.evidence_reconciliation_example import example_material
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


@lru_cache(maxsize=1)
def fixture():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("offline only")):
        material = example_material()
        count = next(index for index, event in enumerate(material["events"]) if event.event_type == REVIEW_TYPE)
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve() / "journal"
        store = JournalStore(root)
        append_journal_batch(store, [{"event": event, "evidence": evidence} for event, evidence in
            zip(material["events"][:count], material["event_evidence"][:count])])
        return material, count, root, temporary


def entries(root):
    return {path.name: path.read_bytes() for path in sorted((root / "entries").glob("*.json"))}


class EvidenceReconciliationJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture, cls.source_count, cls.base, cls.retained_temporary = fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "journal"
        shutil.copytree(self.base, self.root)
        self.store = JournalStore(self.root)
        self.events = self.fixture["events"][:self.source_count]
        self.blobs = dict(self.fixture["blobs"])
        self.request = self.fixture["cases"][0]["request"]

    def material(self, request=None, events=None, blobs=None):
        return review_material(request or self.request, self.events if events is None else events,
            self.blobs if blobs is None else blobs)

    def changed_request(self, **changes):
        return EvidenceReconciliationRequest.from_mapping({**self.request.to_dict(), **changes})

    def test_source_context_preserves_market_and_delivery_clocks(self):
        context = build_source_context(self.request.anchor_review_event_id, self.events, self.blobs,
            recorded_at=self.request.data_cutoff_at, declared_evaluation_mode=self.request.declared_evaluation_mode)["context"]
        self.assertEqual(context.feed, "iex")
        self.assertEqual(context.collection_mode, "MARKET_DATA_GET_ONLY")
        self.assertIsNone(context.account_evidence)
        self.assertGreaterEqual(context.delivery_interval["start_at"], context.market_event_interval["start_at"])
        self.assertEqual(len(context.quote_receipt_evidence), 12)

    def test_original_native_result_and_authority_are_preserved(self):
        result = self.material()["result"]
        anchor = next(event for event in self.events if event.event_id == self.request.anchor_review_event_id)
        native = anchor.payload["result"]["anchor_qualification"]["result"]
        self.assertEqual(result["native_qualification_snapshot"], native)
        self.assertEqual(result["native_reason_codes"], native["reason_codes"])
        self.assertFalse(result["native_qualification_recomputed"])
        self.assertEqual(result["native_coverage_proposal"]["status"], "UNRESOLVED")
        self.assertIsNone(result["cost_assumptions_proposal"])
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertFalse(any(result["authority"].values()))

    def test_later_review_cutoff_reuses_frozen_packet_without_rewriting_it(self):
        before = self.material()["result"]
        request = self.changed_request(review_id="later-frozen-packet-review", recorded_at="2025-04-12T12:00:00Z",
            data_cutoff_at="2025-04-11T12:00:00Z")
        after = self.material(request)["result"]
        self.assertEqual(after["source_context"], before["source_context"])
        self.assertEqual(after["historical_feed_cost_applicability"], before["historical_feed_cost_applicability"])

    def test_strict_request_rejects_authority_and_unknown_fields(self):
        for changes in ({"auto_trading_enabled": True}, {"scope": "EXECUTE"}, {"domain": "INVESTMENT"},
                {"extra": 1}, {"authority": {**self.request.authority, "execution_enabled": True}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.changed_request(**changes)

    def test_request_does_not_accept_missing_source_or_account_alias(self):
        for field in ("effective_date_request_evidence", "applicability_packet_evidence"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.changed_request(**{field: None})
        with self.assertRaises(ValueError):
            self.changed_request(account_profile_evidence=self.request.applicability_packet_evidence)

    def test_nested_result_cannot_gain_authority_or_rewrite_native_reasons(self):
        result = self.material()["result"]
        for field, value in (("native_gate_override", True), ("source_applicability_verified", True),
                ("realized_trade_pnl", "1"), ("native_reason_codes", ["INVENTED"])):
            changed = deepcopy(result); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_result(changed)
        changed = deepcopy(result); changed["native_coverage_proposal"]["status"] = "SUPPORTED"
        with self.assertRaises(ValueError): validate_result(changed)

    def test_result_rejects_context_rebinding(self):
        result = self.material()["result"]
        result["source_context"]["context_id"] = "different-context"
        with self.assertRaises(ValueError): validate_result(result)

    def test_missing_or_altered_retained_sources_fail_closed(self):
        for reference in (self.request.effective_date_request_evidence, self.request.applicability_packet_evidence):
            for replacement in (None, b"tampered"):
                blobs = dict(self.blobs)
                if replacement is None: blobs.pop(reference["sha256"])
                else: blobs[reference["sha256"]] = replacement
                with self.subTest(path=reference["path"], replacement=replacement), self.assertRaises(ValueError):
                    self.material(blobs=blobs)

    def test_source_cutoff_cannot_exclude_the_original_anchor(self):
        with self.assertRaises(ValueError):
            self.material(self.changed_request(data_cutoff_at="2025-01-01T00:00:00Z"))

    def test_duplicate_history_ids_reject(self):
        with self.assertRaises(ValueError): self.material(events=(*self.events, self.events[-1]))

    def test_missing_selected_anchor_rejects_without_latest_fallback(self):
        with self.assertRaises(ValueError):
            self.material(events=tuple(event for event in self.events if event.event_id != self.request.anchor_review_event_id))

    def test_missing_selected_receipt_rejects(self):
        context = self.material()["result"]["source_context"]
        blobs = dict(self.blobs); blobs.pop(context["quote_receipt_evidence"][0]["sha256"])
        with self.assertRaises(ValueError): self.material(blobs=blobs)

    def test_native_result_leaf_cannot_be_reconstructed_when_missing(self):
        anchor = next(event for event in self.events if event.event_id == self.request.anchor_review_event_id)
        reference = next(ref for ref in anchor.evidence if ref["path"] == "native-closure/result.v1.json")
        blobs = dict(self.blobs); blobs.pop(reference["sha256"])
        with self.assertRaises(ValueError): self.material(blobs=blobs)

    def test_mixed_history_append_verify_preserves_all_old_bytes(self):
        before = entries(self.root)
        material = self.material()
        appended = self.store.append(material["event"], material["evidence"])
        self.assertTrue(appended.written)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, self.source_count + 1)
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(summary.staging_orphan_count, 0)
        self.assertTrue(all(entries(self.root)[name] == raw for name, raw in before.items()))

    def test_exact_retry_writes_nothing(self):
        material = self.material()
        self.store.append(material["event"], material["evidence"])
        before = entries(self.root)
        retry = self.store.append(material["event"], {})
        self.assertFalse(retry.written)
        self.assertEqual(entries(self.root), before)

    def test_exact_material_retry_uses_original_prefix_after_later_reviews(self):
        material = self.material()
        replay = self.material(events=self.fixture["events"])
        self.assertEqual(replay["event"].to_bytes(), material["event"].to_bytes())

    def test_identity_conflict_cannot_replace_the_record(self):
        material = self.material(); self.store.append(material["event"], material["evidence"])
        before = entries(self.root)
        changed = self.material(self.changed_request(recorded_at="2025-04-12T12:00:00Z"))
        with self.assertRaises(JournalStoreError): self.store.append(changed["event"], changed["evidence"])
        self.assertEqual(entries(self.root), before)

    def test_supersession_is_linked_and_cannot_be_consumed_twice(self):
        first = self.material()
        events = (*self.events, first["event"])
        blobs = {**self.blobs, **{sha256_bytes(raw): raw for raw in first["evidence"].values()}}
        request = self.changed_request(review_id="followup-review", recorded_at="2025-04-12T12:00:00Z",
            data_cutoff_at="2025-04-11T12:00:00Z", supersedes_event_id=first["event"].event_id)
        second = self.material(request, events=events, blobs=blobs)
        self.assertEqual(second["event"].payload["prior_review_event_ids"], [first["event"].event_id])
        other = self.changed_request(review_id="conflicting-followup", recorded_at="2025-04-13T12:00:00Z",
            data_cutoff_at="2025-04-11T12:00:00Z", supersedes_event_id=first["event"].event_id)
        with self.assertRaises(ValueError): self.material(other, events=(*events, second["event"]), blobs=blobs)

    def test_unrelated_supersession_and_backdated_cutoff_reject(self):
        with self.assertRaises(ValueError): self.material(self.changed_request(supersedes_event_id=self.events[0].event_id))
        first = self.material(); events = (*self.events, first["event"])
        with self.assertRaises(ValueError):
            self.material(self.changed_request(review_id="backdated-followup", recorded_at="2025-01-01T00:00:00Z",
                data_cutoff_at="2025-01-01T00:00:00Z", supersedes_event_id=first["event"].event_id), events=events)

    def test_interruption_before_entry_publication_recovers_without_rewriting_prefix(self):
        before = entries(self.root); material = self.material()
        original = storage._publish_immutable
        def interrupted(staging, destination, name, raw):
            if name.endswith(".json"): raise OSError("authored publication interruption")
            return original(staging, destination, name, raw)
        with patch.object(storage, "_publish_immutable", side_effect=interrupted), self.assertRaises(JournalStoreError):
            self.store.append(material["event"], material["evidence"])
        self.assertEqual(entries(self.root), before)
        recovered = self.store.append(material["event"], material["evidence"])
        self.assertTrue(recovered.written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(all(entries(self.root)[name] == raw for name, raw in before.items()))

    def test_rehashed_envelope_tampering_still_fails_semantic_replay(self):
        material = self.material(); self.store.append(material["event"], material["evidence"])
        path = sorted((self.root / "entries").glob("*.json"))[-1]
        envelope = json.loads(path.read_bytes())
        envelope["event"]["payload"]["prior_review_event_ids"] = [self.events[0].event_id]
        event = JournalEvent.from_mapping(envelope["event"])
        envelope["event_sha256"] = sha256_bytes(event.to_bytes())
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(envelope))
        with self.assertRaises(JournalStoreError): self.store.verify()


if __name__ == "__main__": unittest.main()
