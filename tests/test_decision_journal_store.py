from __future__ import annotations

import multiprocessing
import os
import stat
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import ComponentProvenance, MissionRequest, MissionSnapshot
from blackpod_build_week.contracts.decision_journal import (
    EvaluationInput, JournalEvent,
)
from blackpod_build_week.decision_journal_projection import VerifiedHistory, load_verified_history, project_history
from blackpod_build_week.decision_journal_store import (
    JournalConflictError, JournalPersistenceError, JournalStore, JournalUnsafePathError,
    JournalVerificationError, _publish_immutable, check_separate_root,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore


def _identity(prefix, value):
    return prefix + '-' + sha256_bytes(canonical_json_bytes(value))


def _concurrent_append(root, event_dict, evidence, gate, results):
    try:
        gate.wait(timeout=10)
        result = JournalStore(Path(root)).append(JournalEvent.from_mapping(event_dict), evidence)
        results.put((result.written, result.sequence))
    except Exception as exc:
        import traceback
        results.put(('error', traceback.format_exc()))


class DecisionJournalStoreTests(unittest.TestCase):
    maxDiff = None
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'journal'
        self.store = JournalStore(self.root)
        self.mission_store = MissionStore(self.base / 'source')
        request = MissionRequest.from_mapping({
            'schema_version': 'blackpod.mission_request.v1',
            'mission_id': 'mission-journal-store', 'request_id': 'request-journal-store',
            'run_mode': 'REPLAY', 'symbol': 'MSFT', 'requested_at': '2026-10-11T00:00:00Z',
            'operator_id': 'test-operator',
        })
        self.initial = self.mission_store.initialize(
            request, mission_id=request.mission_id, started_at=request.requested_at,
            observed_at=request.requested_at,
        )
        self.history = load_verified_history(self.initial.paths.mission_root)
        self.first = project_history(self.history)[0]
        self.evidence = dict(self.history.source_files)

    def append_first(self):
        return self.store.append(self.first, self.evidence)

    def second_revision(self):
        updated = replace(self.initial.snapshot, revision=2,
                          snapshot_id='mission-journal-store-r0002',
                          previous_snapshot_sha256=self.initial.snapshot_sha256,
                          observed_at='2026-10-11T00:01:00Z')
        self.mission_store.commit_snapshot(self.initial.paths, updated)
        history = load_verified_history(self.initial.paths.mission_root)
        return project_history(history)[1], dict(history.source_files)

    def evaluation(self, **changes):
        value = EvaluationInput.from_mapping({
            'schema_version': 'blackpod.decision_journal_evaluation.v1',
            'evaluation_id': 'evaluation-process-store', 'decision_id': self.first.decision_id,
            'recorded_at': '2026-10-12T00:00:00Z', 'evaluator': 'test-reviewer',
            'evaluation_type': 'PROCESS', 'conclusion': 'No execution was authorized.',
            'outcome_status': 'OBSERVED', 'realized_trade_pnl': None,
        })
        execution = changes.pop('execution_status', 'NOT_EXECUTED')
        raw = value.to_bytes()
        mapping = {
            'schema_version': 'blackpod.decision_journal_event.v1',
            'event_id': _identity('journal-event', {
                'decision_id': self.first.decision_id, 'event_type': 'EVALUATION_RECORDED',
                'evaluation_id': value.evaluation_id,
            }),
            'decision_id': self.first.decision_id, 'domain': self.first.domain,
            'event_type': 'EVALUATION_RECORDED', 'recorded_at': value.recorded_at,
            'source': {'kind': 'EVALUATION', 'evaluation_id': value.evaluation_id,
                       'source_sha256': sha256_bytes(raw)},
            'evidence': [{'path': 'evaluations/evaluation.json', 'sha256': sha256_bytes(raw),
                          'size_bytes': len(raw)}],
            'payload': {**value.to_dict(), 'execution_status': execution},
            **changes,
        }
        return JournalEvent.from_mapping(mapping), {sha256_bytes(raw): raw}

    def test_append_layout_hashes_retry_and_source_independence(self):
        first = self.append_first()
        self.assertEqual((first.written, first.sequence), (True, 1))
        summary = self.store.verify()
        self.assertEqual(summary.event_count, 1)
        self.assertEqual(summary.evidence_count, 2)
        self.assertEqual(summary.orphan_evidence_count, 0)
        before = (self.root / 'entries/00000001.json').read_bytes()
        self.assertEqual(self.store.append(self.first, {}).written, False)
        self.assertEqual((self.root / 'entries/00000001.json').read_bytes(), before)
        self.initial.paths.mission_root.rename(self.base / 'source-removed')
        self.assertEqual(self.store.events()[0].to_bytes(), self.first.to_bytes())
        self.assertEqual(self.store.verify().event_count, 1)

    def test_conflict_same_identity_different_content(self):
        self.append_first()
        mapping = self.first.to_dict()
        mapping['payload']['classification']['reason'] = 'Conflicting import explanation.'
        with self.assertRaises(JournalConflictError):
            self.store.append(JournalEvent.from_mapping(mapping), self.evidence)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_domain_cannot_change_in_later_revision(self):
        self.append_first()
        second, evidence = self.second_revision()
        history = load_verified_history(self.initial.paths.mission_root)
        classified = project_history(history, 'TRADING', 'Explicit desk import.')[1]
        with self.assertRaisesRegex(JournalConflictError, 'domain'):
            self.store.append(classified, evidence)

    def test_contiguous_revisions_and_previous_hash(self):
        second, evidence = self.second_revision()
        with self.assertRaisesRegex(JournalConflictError, 'revision'):
            self.store.append(second, evidence)
        self.append_first()
        self.assertEqual(self.store.append(second, evidence).sequence, 2)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_source_semantics_cannot_be_fabricated(self):
        mapping = self.first.to_dict()
        mapping['payload']['symbol'] = 'SPY'
        with self.assertRaisesRegex(JournalVerificationError, 'projection'):
            self.store.append(JournalEvent.from_mapping(mapping), self.evidence)
        self.assertEqual(self.store.verify().event_count, 0)

    def test_source_snapshot_hash_correlation_and_reference(self):
        mapping = self.first.to_dict()
        mapping['source']['source_sha256'] = sha256_bytes(self.history._request_bytes)
        with self.assertRaisesRegex(JournalVerificationError, 'snapshot'):
            self.store.append(JournalEvent.from_mapping(mapping), self.evidence)

    def test_linked_evaluation_preserves_original_and_retries(self):
        self.append_first()
        before = (self.root / 'entries/00000001.json').read_bytes()
        event, evidence = self.evaluation()
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, {}).written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual((self.root / 'entries/00000001.json').read_bytes(), before)

    def test_orphan_evaluation_domain_and_execution_mismatch_rejected(self):
        event, evidence = self.evaluation()
        with self.assertRaisesRegex(JournalConflictError, 'existing'):
            self.store.append(event, evidence)
        self.append_first()
        for changes in ({'domain': 'TRADING'}, {'execution_status': 'SHADOW_ONLY'}):
            with self.subTest(changes=changes):
                event, evidence = self.evaluation(**changes)
                with self.assertRaises(JournalConflictError):
                    self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_missing_evidence_and_wrong_supplied_hash_fail_before_event(self):
        with self.assertRaisesRegex(JournalVerificationError, 'evidence'):
            self.store.append(self.first, {})
        with self.assertRaisesRegex(JournalVerificationError, 'hash'):
            self.store.append(self.first, {'0' * 64: b'bad'})
        self.assertEqual(self.store.verify().event_count, 0)

    def test_evidence_tamper_blocks_append_and_noop(self):
        self.append_first()
        blob = next((self.root / 'evidence').iterdir())
        blob.chmod(0o600)
        blob.write_bytes(b'tampered')
        for action in (self.store.verify, lambda: self.store.append(self.first, {})):
            with self.assertRaisesRegex(JournalVerificationError, 'hash mismatch'):
                action()
        self.assertEqual(len(list((self.root / 'entries').iterdir())), 1)

    def test_missing_retained_evidence_blocks_verification(self):
        self.append_first()
        next((self.root / 'evidence').iterdir()).unlink()
        with self.assertRaisesRegex(JournalVerificationError, 'missing'):
            self.store.verify()

    def test_entry_tamper_missing_reorder_and_predecessor_detected(self):
        self.append_first()
        second, evidence = self.second_revision()
        self.store.append(second, evidence)
        entry = self.root / 'entries/00000001.json'
        entry.rename(self.root / 'entries/00000003.json')
        with self.assertRaisesRegex(JournalVerificationError, 'sequence'):
            self.store.verify()
        (self.root / 'entries/00000003.json').rename(entry)
        import json
        second_path = self.root / 'entries/00000002.json'
        mapping = json.loads(second_path.read_bytes())
        mapping['previous_entry_sha256'] = '0' * 64
        second_path.chmod(0o600)
        second_path.write_bytes(canonical_json_bytes(mapping))
        with self.assertRaisesRegex(JournalVerificationError, 'predecessor'):
            self.store.verify()

    def test_rehashed_entry_semantic_tamper_detected(self):
        self.append_first()
        import json
        path = self.root / 'entries/00000001.json'
        entry = json.loads(path.read_bytes())
        entry['event']['payload']['symbol'] = 'SPY'
        entry['event_sha256'] = sha256_bytes(canonical_json_bytes(entry['event']))
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaisesRegex(JournalVerificationError, 'projection'):
            self.store.verify()

    def test_verify_missing_root_and_existing_root_are_read_only(self):
        with self.assertRaises(JournalVerificationError):
            self.store.verify()
        self.assertFalse(self.root.exists())
        self.append_first()
        before = {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.root.rglob('*') if p.is_file()}
        with mock.patch('blackpod_build_week.decision_journal_store.os.mkdir', side_effect=AssertionError('mkdir forbidden')), \
             mock.patch('blackpod_build_week.decision_journal_store.fcntl.flock', side_effect=AssertionError('lock forbidden')):
            self.store.verify()
            self.store.events()
        self.assertEqual(before, {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in self.root.rglob('*') if p.is_file()})

    def test_precommit_interruption_reuses_orphan_evidence(self):
        def fail_before_event(staging, target, name, payload):
            if name.endswith('.json'):
                raise JournalPersistenceError('injected before event publication')
            return _publish_immutable(staging, target, name, payload)
        with mock.patch('blackpod_build_week.decision_journal_store._publish_immutable', side_effect=fail_before_event):
            with self.assertRaises(JournalPersistenceError):
                self.append_first()
        summary = self.store.verify()
        self.assertEqual((summary.event_count, summary.orphan_evidence_count), (0, 2))
        self.assertTrue(self.append_first().written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_postcommit_interruption_retry_is_noop(self):
        def fail_after_event(staging, target, name, payload):
            _publish_immutable(staging, target, name, payload)
            if name.endswith('.json'):
                raise JournalPersistenceError('injected after event publication')
        with mock.patch('blackpod_build_week.decision_journal_store._publish_immutable', side_effect=fail_after_event):
            with self.assertRaises(JournalPersistenceError):
                self.append_first()
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertFalse(self.append_first().written)

    def test_file_fsync_failure_does_not_publish_partial_event(self):
        real_fsync = os.fsync
        def fail_regular(descriptor):
            if stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError('injected fsync failure')
            real_fsync(descriptor)
        with mock.patch('blackpod_build_week.decision_journal_store.os.fsync', side_effect=fail_regular):
            with self.assertRaises(JournalPersistenceError):
                self.append_first()
        self.assertEqual(self.store.verify().event_count, 0)
        self.assertTrue(self.append_first().written)

    def test_directory_fsync_failure_after_publication_retries(self):
        self.append_first()
        second, evidence = self.second_revision()
        real_fsync = os.fsync
        entries_inode = (self.root / 'entries').stat().st_ino
        def fail_entries(descriptor):
            if os.fstat(descriptor).st_ino == entries_inode:
                raise OSError('injected entry directory fsync failure')
            real_fsync(descriptor)
        with mock.patch('blackpod_build_week.decision_journal_store.os.fsync', side_effect=fail_entries):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(second, evidence)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertFalse(self.store.append(second, evidence).written)

    def test_staging_recovery_is_reported_read_only_then_cleaned_on_append(self):
        self.append_first()
        orphan = self.root / ('staging/.publish-' + 'a' * 32 + '.tmp')
        orphan.write_bytes(b'partial staging bytes')
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertTrue(orphan.exists())
        self.assertFalse(self.append_first().written)
        self.assertFalse(orphan.exists())

    def test_internal_staging_link_after_kill_is_recoverable(self):
        self.append_first()
        orphan = self.root / ('staging/.publish-' + 'a' * 32 + '.tmp')
        os.link(self.root / 'entries/00000001.json', orphan)
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertFalse(self.append_first().written)
        self.assertEqual((self.root / 'entries/00000001.json').stat().st_nlink, 1)

    def test_unknown_staging_files_fail_without_cleanup(self):
        self.append_first()
        unknown = self.root / 'staging/unrecognized.tmp'
        unknown.write_bytes(b'preserve')
        with self.assertRaisesRegex(JournalVerificationError, 'staging'):
            self.append_first()
        self.assertEqual(unknown.read_bytes(), b'preserve')

    def test_unsafe_root_ancestor_and_source_overlap_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        linked = self.base / 'linked'
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(JournalUnsafePathError):
            JournalStore(linked / 'journal')
        for destination in (self.initial.paths.mission_root,
                            self.initial.paths.mission_root / 'journal', self.base / 'source'):
            with self.subTest(destination=destination):
                with self.assertRaises(JournalUnsafePathError):
                    check_separate_root(destination, self.initial.paths.mission_root)
        with self.assertRaises(JournalUnsafePathError):
            JournalStore(self.base / 'safe/../escape')

    def test_symlink_children_external_hardlink_and_nonregular_rejected(self):
        self.append_first()
        blob = next((self.root / 'evidence').iterdir())
        external_link = self.base / 'external-link'
        os.link(blob, external_link)
        with self.assertRaises(JournalUnsafePathError):
            self.store.verify()
        external_link.unlink()
        original = blob.read_bytes()
        external = self.base / 'external-blob'
        external.write_bytes(original)
        blob.unlink()
        blob.symlink_to(external)
        with self.assertRaises(JournalUnsafePathError):
            self.store.verify()
        blob.unlink()
        os.mkfifo(blob)
        with self.assertRaises(JournalUnsafePathError):
            self.store.verify()

    def test_symlink_lock_and_child_directory_rejected(self):
        self.append_first()
        lock = self.root / '.journal.lock'
        lock.unlink()
        external = self.base / 'external-lock'
        external.write_bytes(b'')
        lock.symlink_to(external)
        with self.assertRaises((JournalUnsafePathError, JournalPersistenceError)):
            self.append_first()
        lock.unlink()
        lock.write_bytes(b'')
        (self.root / 'staging').rmdir()
        external_dir = self.base / 'external-stage'
        external_dir.mkdir()
        (self.root / 'staging').symlink_to(external_dir, target_is_directory=True)
        with self.assertRaises(JournalUnsafePathError):
            self.store.verify()

    def test_unrelated_existing_directory_and_temp_collision_are_preserved(self):
        self.root.mkdir()
        unrelated = self.root / 'unrelated.txt'
        unrelated.write_bytes(b'preserve this file')
        with self.assertRaisesRegex(JournalVerificationError, 'unexpected'):
            self.append_first()
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'unrelated.txt'})
        unrelated.unlink()
        self.append_first()
        orphan = self.root / ('staging/.publish-' + 'a' * 32 + '.tmp')
        orphan.write_bytes(b'preexisting temporary bytes')
        stage = os.open(self.root / 'staging', os.O_RDONLY | os.O_DIRECTORY)
        target = os.open(self.root / 'evidence', os.O_RDONLY | os.O_DIRECTORY)
        try:
            with mock.patch('blackpod_build_week.decision_journal_store.uuid.uuid4',
                            return_value=mock.Mock(hex='a' * 32)):
                with self.assertRaises(JournalConflictError):
                    _publish_immutable(stage, target, '0' * 64, b'new')
        finally:
            os.close(stage)
            os.close(target)
        self.assertEqual(orphan.read_bytes(), b'preexisting temporary bytes')

    def test_all_appends_refuse_canonical_storage_before_any_mutation(self):
        source = self.base / 'source'
        before = {str(p.relative_to(source)): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in source.rglob('*') if p.is_file()}
        for root in (self.initial.paths.mission_root, source,
                     source / 'journal', source / 'missions' / 'journal-sibling'):
            with self.subTest(root=root):
                with self.assertRaises(JournalUnsafePathError):
                    JournalStore(root).append(self.first, self.evidence)
        self.assertEqual(before, {str(p.relative_to(source)): (p.read_bytes(), p.stat().st_mtime_ns)
                                  for p in source.rglob('*') if p.is_file()})
        self.assertFalse((source / 'journal').exists())
        self.assertFalse((source / 'missions/journal-sibling').exists())
        self.assertFalse((source / '.journal.lock').exists())
        self.assertFalse((self.initial.paths.mission_root / '.journal.lock').exists())

    def test_reject_oversized_retained_file_before_reading(self):
        self.append_first()
        with mock.patch('blackpod_build_week.decision_journal_store._MAX_FILE_BYTES', 1):
            with self.assertRaisesRegex(JournalVerificationError, 'limit'):
                self.store.verify()

    def test_oversized_event_evidence_and_entry_rejected_before_publication(self):
        with mock.patch('blackpod_build_week.decision_journal_store._MAX_FILE_BYTES', 1):
            with self.assertRaisesRegex(JournalVerificationError, 'event.*limit'):
                self.append_first()
        self.assertFalse(self.root.exists())
        limit = len(self.first.to_bytes()) + 1
        oversized = b'x' * (limit + 1)
        with mock.patch('blackpod_build_week.decision_journal_store._MAX_FILE_BYTES', limit):
            with self.assertRaisesRegex(JournalVerificationError, 'evidence.*limit'):
                self.store.append(self.first, {sha256_bytes(oversized): oversized, **self.evidence})
            with self.assertRaisesRegex(JournalVerificationError, 'entry.*limit'):
                self.append_first()
        self.assertEqual(list((self.root / 'entries').iterdir()), [])
        self.assertEqual(list((self.root / 'evidence').iterdir()), [])
        self.assertTrue(self.append_first().written)

    def test_reject_file_changed_while_reading(self):
        self.append_first()
        real_read = os.read
        changed = False
        def modify_during_read(descriptor, size):
            nonlocal changed
            piece = real_read(descriptor, size)
            if piece and not changed:
                changed = True
                os.fchmod(descriptor, 0o600)
            return piece
        with mock.patch('blackpod_build_week.decision_journal_store.os.read', side_effect=modify_during_read):
            with self.assertRaisesRegex(JournalVerificationError, 'changed during read'):
                self.store.verify()

    def test_changed_started_at_rejected_even_with_valid_source_hash(self):
        self.append_first()
        second, evidence = self.second_revision()
        history = load_verified_history(self.initial.paths.mission_root)
        snapshot = replace(history.snapshot_history[-1], started_at='2026-10-10T00:00:00Z')
        raw = canonical_json_bytes(snapshot.to_dict())
        files = dict(history.source_files)
        files['snapshots/mission_snapshot-r0002.json'] = raw
        fabricated = VerifiedHistory(Path('/'), history._request_bytes, (raw,), files)
        event = project_history(fabricated)[0]
        with self.assertRaisesRegex(JournalVerificationError, 'started_at'):
            self.store.append(event, files)

    def test_artifact_and_component_regression_rejected_in_retained_lineage(self):
        self.append_first()
        artifact = self.mission_store.write_immutable_artifact(
            self.initial.snapshot.mission_id, relative_path='audit/extra.json', payload=b'{}\n',
            name='audit_extra', producer='harbormaster', schema_version='blackpod.audit_extra.v1',
            observed_at=self.initial.snapshot.observed_at,
        )
        component = ComponentProvenance.from_mapping({
            'git_revision': 'a' * 40, 'git_branch': 'fixture', 'dirty_worktree': False,
            'oracle_entry_point': 'blackpod.oracle.fixture', 'run_mode': 'REPLAY',
            'transport': 'REPLAY_FIXTURE', 'replay_fixture_id': 'fixture-store-history',
            'replay_fixture_sha256': 'b' * 64,
        })
        second = replace(self.initial.snapshot, revision=2,
                         snapshot_id='mission-journal-store-r0002',
                         previous_snapshot_sha256=self.initial.snapshot_sha256,
                         artifacts=(*self.initial.snapshot.artifacts, artifact),
                         components={'battlestar': component})
        digest = self.mission_store.commit_snapshot(self.initial.paths, second)
        history = load_verified_history(self.initial.paths.mission_root)
        self.store.append(project_history(history)[1], dict(history.source_files))
        for changes, expected in (({'artifacts': self.initial.snapshot.artifacts}, 'artifacts'),
                                  ({'components': {}}, 'component provenance')):
            with self.subTest(changes=changes):
                third = replace(second, revision=3, snapshot_id='mission-journal-store-r0003',
                                previous_snapshot_sha256=digest, **changes)
                raw = canonical_json_bytes(third.to_dict())
                files = dict(history.source_files)
                files['snapshots/mission_snapshot-r0003.json'] = raw
                event = project_history(VerifiedHistory(Path('/'), history._request_bytes, (raw,), files))[0]
                with self.assertRaisesRegex(JournalVerificationError, expected):
                    self.store.append(event, files)

    def test_evaluation_cannot_predate_latest_evidence(self):
        self.append_first()
        event, evidence = self.evaluation()
        mapping = event.to_dict()
        mapping['recorded_at'] = mapping['payload']['recorded_at'] = '2026-10-10T00:00:00Z'
        original = {key: value for key, value in mapping['payload'].items() if key != 'execution_status'}
        raw = canonical_json_bytes(original)
        mapping['source']['source_sha256'] = sha256_bytes(raw)
        mapping['evidence'][0].update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        with self.assertRaisesRegex(JournalConflictError, 'predate'):
            self.store.append(JournalEvent.from_mapping(mapping), {sha256_bytes(raw): raw})

    def test_concurrent_writers_append_exactly_once(self):
        context = multiprocessing.get_context('fork')
        gate, results = context.Barrier(3), context.Queue()
        processes = [context.Process(target=_concurrent_append,
                     args=(str(self.root), self.first.to_dict(), self.evidence, gate, results))
                     for _ in range(2)]
        for process in processes:
            process.start()
        gate.wait(timeout=10)
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                self.fail('concurrent writer did not finish')
            self.assertEqual(process.exitcode, 0)
        outcomes = [results.get(timeout=2) for _ in processes]
        self.assertCountEqual(outcomes, [(True, 1), (False, 1)])
        self.assertEqual(self.store.verify().event_count, 1)


if __name__ == '__main__':
    unittest.main()
