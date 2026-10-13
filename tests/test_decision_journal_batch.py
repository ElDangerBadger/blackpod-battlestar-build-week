"""Safe prefix commits, whole-suffix validation, conflicts and batch recovery."""
import multiprocessing
import socket
import unittest
from unittest.mock import patch

import test_decision_journal_store as fixtures
import test_train_market_evidence_cli as cli_fixtures
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week import decision_journal_store as original


def _concurrent_batch(root, materials, gate, results):
    try:
        gate.wait(timeout=10)
        result = append_journal_batch(original.JournalStore(root), materials)
        results.put([(row.written, row.sequence) for row in result])
    except Exception as exc:
        results.put({"error": repr(exc)})


class JournalBatchTests(unittest.TestCase):
    def setUp(self):
        fixtures.DecisionJournalStoreTests.setUp(self)
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        second, evidence = fixtures.DecisionJournalStoreTests.second_revision(self)
        self.records = [{"event": self.first, "evidence": self.evidence}, {"event": second, "evidence": evidence}]

    def test_batch_entries_are_byte_identical_to_individual_appends(self):
        other = original.JournalStore(self.base / "individual")
        for row in self.records:
            other.append(row["event"], row["evidence"])
        result = append_journal_batch(self.store, self.records)
        self.assertEqual([(row.written, row.sequence) for row in result], [(True, 1), (True, 2)])
        self.assertEqual(self.store.verify().to_dict(), other.verify().to_dict())
        for name in ("00000001.json", "00000002.json"):
            self.assertEqual((self.root / "entries" / name).read_bytes(), (other.root / "entries" / name).read_bytes())

    def test_exact_retry_is_noop_after_later_records(self):
        append_journal_batch(self.store, self.records)
        event, evidence = fixtures.DecisionJournalStoreTests.evaluation(self)
        self.store.append(event, evidence)
        before = self.store.verify().to_dict()
        retry = append_journal_batch(self.store, self.records)
        self.assertTrue(all(not row.written for row in retry))
        self.assertEqual(self.store.verify().to_dict(), before)

    def test_existing_exact_prefix_only_appends_remaining_suffix(self):
        self.store.append(self.first, self.evidence)
        result = append_journal_batch(self.store, self.records)
        self.assertEqual([(row.written, row.sequence) for row in result], [(False, 1), (True, 2)])

    def test_later_invalid_record_publishes_no_new_entry_or_evidence(self):
        changed = self.records[1]["event"].to_dict()
        changed["payload"]["symbol"] = "QQQ"
        records = [self.records[0], {**self.records[1], "event": JournalEvent.from_mapping(changed)}]
        with self.assertRaises(original.JournalVerificationError):
            append_journal_batch(self.store, records)
        self.assertEqual(list((self.root / "entries").iterdir()), [])
        self.assertEqual(list((self.root / "evidence").iterdir()), [])

    def test_forward_link_cannot_use_future_batch_source(self):
        event, evidence = fixtures.DecisionJournalStoreTests.evaluation(self)
        with self.assertRaises(original.JournalConflictError):
            append_journal_batch(self.store, [{"event": event, "evidence": evidence}, self.records[0]])
        self.assertEqual(self.store.verify().event_count, 0)

    def test_missing_later_source_bytes_do_not_publish_first_record(self):
        evidence = dict(self.records[1]["evidence"])
        evidence.pop("snapshots/mission_snapshot-r0002.json")
        with self.assertRaises(original.JournalVerificationError):
            append_journal_batch(self.store, [self.records[0], {**self.records[1], "evidence": evidence}])
        self.assertEqual(self.store.verify().event_count, 0)

    def test_concurrent_identical_batches_publish_each_event_once(self):
        context = multiprocessing.get_context("fork")
        gate, results = context.Event(), context.Queue()
        materials = [{"event": row["event"].to_dict(), "evidence": row["evidence"]} for row in self.records]
        workers = [context.Process(target=_concurrent_batch, args=(self.root, materials, gate, results)) for _ in range(2)]
        for worker in workers:
            worker.start()
        try:
            gate.set()
            replies = [results.get(timeout=20) for _ in workers]
            self.assertEqual(sorted(replies), [[(False, 1), (False, 2)], [(True, 1), (True, 2)]])
            self.assertEqual(self.store.verify().event_count, 2)
        finally:
            for worker in workers:
                worker.join(timeout=10)
                if worker.is_alive():
                    worker.terminate()
                    worker.join()

    def test_duplicate_identity_rejected_before_creating_storage(self):
        with self.assertRaises(original.JournalConflictError):
            append_journal_batch(self.store, [self.records[0], self.records[0]])
        self.assertFalse(self.root.exists())

    def test_changed_existing_identity_conflicts_without_appending_suffix(self):
        self.store.append(self.first, self.evidence)
        changed = self.first.to_dict()
        changed["payload"]["classification"]["reason"] = "Changed immutable reason."
        before = self.store.verify().to_dict()
        with self.assertRaises(original.JournalConflictError):
            append_journal_batch(self.store, [{**self.records[0], "event": JournalEvent.from_mapping(changed)}, self.records[1]])
        self.assertEqual(self.store.verify().to_dict(), before)

    def test_interrupted_suffix_recovers_by_exact_retry(self):
        publish = original._publish_immutable
        def interrupted(staging, destination, name, raw):
            if name == "00000002.json":
                raise OSError("simulated publication interruption")
            return publish(staging, destination, name, raw)
        with patch.object(original, "_publish_immutable", side_effect=interrupted), self.assertRaises(original.JournalPersistenceError):
            append_journal_batch(self.store, self.records)
        self.assertEqual(self.store.verify().event_count, 1)
        result = append_journal_batch(self.store, self.records)
        self.assertEqual([(row.written, row.sequence) for row in result], [(False, 1), (True, 2)])
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertEqual(self.store.verify().staging_orphan_count, 0)

    def test_existing_journal_is_fully_scanned_once_under_batch_lock(self):
        with patch.object(self.store, "_scan", wraps=self.store._scan) as scan:
            append_journal_batch(self.store, self.records)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_malformed_supplied_bytes_hash_or_path_reject(self):
        for evidence in ({"../escape": b"bad"}, {"a" * 64: b"wrong-hash"}, {"source.raw": "not bytes"}):
            with self.subTest(evidence=evidence), self.assertRaises(original.JournalVerificationError):
                append_journal_batch(self.store, [{"event": self.first, "evidence": evidence}])
        self.assertFalse(self.root.exists())

    def test_unsafe_root_or_lock_rejected(self):
        target = self.base / "target"
        target.mkdir()
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises((original.JournalStoreError, OSError)):
            append_journal_batch(self.store, self.records)

    def test_batch_bounds_cannot_be_unbounded_or_boolean(self):
        for rows in ([], None, {}, [self.records[0]] * 4097):
            with self.subTest(kind=type(rows).__name__), self.assertRaises(original.JournalVerificationError):
                append_journal_batch(self.store, rows)
        with patch("blackpod_build_week.decision_journal_batch.MAX_BATCH_SUPPLIED_BYTES", 1), self.assertRaises(original.JournalVerificationError):
            append_journal_batch(self.store, self.records)
        self.assertFalse(self.root.exists())

    def test_distinct_byte_cap_stops_before_hashing_remaining_materials(self):
        from blackpod_build_week import decision_journal_batch as batch
        with patch.object(batch, "MAX_BATCH_SUPPLIED_BYTES", 1), \
                patch.object(batch, "sha256_bytes", wraps=batch.sha256_bytes) as hashed, \
                self.assertRaises(original.JournalVerificationError):
            append_journal_batch(self.store, self.records)
        self.assertEqual(hashed.call_count, 1)
        self.assertFalse(self.root.exists())


class BatchedTrainExportCliTests(cli_fixtures.TrainEvidenceCliTests):
    """Original export safety and retry tests also run on opt-in batch mode."""
    def export_args(self):
        arguments = super().export_args()
        return [*arguments[:-2], "--batched-journal-append", *arguments[-2:]]

    def test_invalid_aggregate_does_not_publish_valid_segments(self):
        self.captured()
        before = original.JournalStore(self.journal).verify().to_dict()
        arguments = [*self.export_args(), "--continuity-event-id", "journal-event-" + "b" * 64]
        code, result = self.call(arguments)
        self.assertEqual(code, 2)
        self.assertEqual(original.JournalStore(self.journal).verify().to_dict(), before)
