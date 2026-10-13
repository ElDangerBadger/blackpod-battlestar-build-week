from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.contracts.decision_journal import EvaluationInput, JournalEvent
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.decision_journal_cli import build_evaluation_event
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.decision_journal_store import (
    JournalConflictError, JournalPersistenceError, JournalStore, JournalUnsafePathError,
    JournalVerificationError, _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore


def identity(prefix, value):
    return prefix + '-' + sha256_bytes(canonical_json_bytes(value))


class InvestmentHypothesisStoreTests(unittest.TestCase):
    """Offline v1/v2 storage integration; source missions never change."""

    maxDiff = None

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / 'journal'
        self.store = JournalStore(self.root)
        request = MissionRequest.from_mapping({
            'schema_version': 'blackpod.mission_request.v1',
            'mission_id': 'mission-shadow-hypothesis', 'request_id': 'request-shadow-hypothesis',
            'run_mode': 'REPLAY', 'symbol': 'MSFT', 'requested_at': '2026-10-11T00:00:00Z',
            'operator_id': 'test-operator',
        })
        self.mission = MissionStore(self.base / 'source').initialize(
            request, mission_id=request.mission_id, started_at=request.requested_at,
            observed_at=request.requested_at,
        )
        self.history = load_verified_history(self.mission.paths.mission_root)
        self.parent = project_history(self.history)[0]
        self.store.append(self.parent, dict(self.history.source_files))

    def test_verified_contents_single_scan_defensive_mapping_and_read_only(self):
        before = {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob('*') if path.is_file()}
        with mock.patch.object(self.store, '_scan', wraps=self.store._scan) as scan, \
             mock.patch('blackpod_build_week.decision_journal_store.os.mkdir',
                        side_effect=AssertionError('read created directory')), \
             mock.patch('blackpod_build_week.decision_journal_store.fcntl.flock',
                        side_effect=AssertionError('read created lock')):
            events, blobs = self.store.verified_contents()
            self.assertEqual(scan.call_count, 1)
        self.assertIsInstance(events, tuple)
        self.assertEqual(events[0].to_bytes(), self.parent.to_bytes())
        self.assertEqual(set(blobs), {reference['sha256'] for reference in self.parent.evidence})
        blobs.clear()
        self.assertTrue(self.store.verified_contents()[1])
        self.assertEqual(before, {str(path.relative_to(self.root)): (path.read_bytes(), path.stat().st_mtime_ns)
                                  for path in self.root.rglob('*') if path.is_file()})

    def test_verified_contents_missing_root_creates_nothing(self):
        missing = self.base / 'missing-journal'
        with self.assertRaises(JournalVerificationError):
            JournalStore(missing).verified_contents()
        self.assertFalse(missing.exists())

    def test_verified_contents_rejects_tamper_before_returning_evidence(self):
        blob = next((self.root / 'evidence').iterdir())
        blob.chmod(0o600)
        blob.write_bytes(b'tampered')
        with self.assertRaisesRegex(JournalVerificationError, 'hash mismatch'):
            self.store.verified_contents()

    def hypothesis(self, **changes):
        request_reference = next(reference for reference in self.parent.evidence
                                 if reference['path'] == 'request/mission_request.json')
        mapping = {
            'schema_version': 'blackpod.investment_hypothesis.v1',
            'hypothesis_id': 'hypothesis-store-fixture', 'recorded_at': '2026-10-12T00:00:00Z',
            'author_id': 'test-researcher', 'domain': 'INVESTMENT', 'mode': 'SHADOW',
            'status': 'SHADOW_DRAFT', 'research_mode': 'PROSPECTIVE',
            'evidence_cutoff_at': '2026-10-12T00:00:00Z',
            'scope': {'kind': 'SYMBOL', 'identifiers': ['MSFT']},
            'observations': [{
                'observation_id': 'observation-symbol', 'source_event_id': self.parent.event_id,
                'artifact_path': request_reference['path'], 'artifact_sha256': request_reference['sha256'],
                'value_pointer': '/symbol', 'value': 'MSFT', 'unit': 'symbol',
                'as_of_pointer': '/requested_at', 'as_of': '2026-10-11T00:00:00Z',
                'time_role': 'REQUESTED_AT',
            }],
            'hypothesis': {'statement': 'Fixture proposition for source binding tests.',
                           'causal_mechanism': 'Fixture mechanism; no verified economic claim.',
                           'assumptions': ['Fixture data remains available.'],
                           'observation_ids': ['observation-symbol']},
            'horizon': {'start_at': '2026-10-12T00:00:00Z', 'review_at': '2026-11-12T00:00:00Z',
                        'end_at': '2027-01-12T00:00:00Z'},
            'expected_outcomes': [{'outcome_id': 'outcome-symbol', 'description': 'Fixture observation.',
                                   'metric': 'observed-symbol', 'unit': 'symbol', 'operator': 'EQ',
                                   'threshold': 'MSFT', 'due_at': '2027-01-12T00:00:00Z'}],
            'alternatives': [{'alternative_id': 'alternative-fixture', 'statement': 'Fixture alternative.',
                              'distinguishing_observation': 'The fixture uses a different symbol.',
                              'observation_ids': ['observation-symbol']}],
            'invalidation_conditions': [{'condition_id': 'condition-fixture', 'description': 'Fixture invalidation.',
                                         'metric': 'observed-symbol', 'unit': 'symbol', 'operator': 'NE',
                                         'threshold': 'MSFT', 'check_by': '2027-01-12T00:00:00Z'}],
            'evaluation_plan': {'plan_id': 'plan-store-fixture', 'method': 'MANUAL_SOURCE_BOUND_REVIEW',
                                'evaluate_at': '2027-01-12T00:00:00Z', 'outcome_ids': ['outcome-symbol'],
                                'condition_ids': ['condition-fixture'],
                                'success_rule': 'ALL_EXPECTED_OUTCOMES_AND_NO_INVALIDATION',
                                'missing_data_policy': 'INCONCLUSIVE', 'evaluator_role': 'research-reviewer'},
            'authority': {'authorization_enabled': False, 'capital_activation_enabled': False,
                          'execution_enabled': False, 'policy_changes_enabled': False},
        }
        mapping.update(changes)
        return InvestmentHypothesis.from_mapping(mapping)

    def built_hypothesis(self, hypothesis=None):
        from blackpod_build_week.investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
        hypothesis = self.hypothesis() if hypothesis is None else hypothesis
        events, blobs = self.store.verified_contents()
        return (build_hypothesis_event(hypothesis, events, blobs),
                evidence_for_hypothesis(hypothesis, events, blobs))

    def test_mixed_v1_v2_exact_identities_and_source_hash(self):
        event, evidence = self.built_hypothesis()
        self.assertEqual(event.schema_version, 'blackpod.decision_journal_event.v2')
        self.assertEqual(event.decision_id, identity('journal-decision', {
            'kind': 'INVESTMENT_HYPOTHESIS', 'hypothesis_id': self.hypothesis().hypothesis_id,
        }))
        self.assertEqual(event.event_id, identity('journal-event', {
            'decision_id': event.decision_id, 'event_type': 'INVESTMENT_HYPOTHESIS_RECORDED',
        }))
        self.assertEqual(event.source['source_sha256'], sha256_bytes(self.hypothesis().to_bytes()))
        before = (self.root / 'entries/00000001.json').read_bytes()
        source_before = dict(self.history.source_files)
        self.assertEqual(self.store.append(event, evidence).sequence, 2)
        self.assertFalse(self.store.append(event, {}).written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual((self.root / 'entries/00000001.json').read_bytes(), before)
        events, blobs = self.store.verified_contents()
        self.assertEqual(events[0].domain, 'UNCLASSIFIED')
        self.assertEqual(events[0].to_bytes(), self.parent.to_bytes())
        self.assertEqual(events[1].domain, 'INVESTMENT')
        self.assertEqual(blobs[event.source['source_sha256']], self.hypothesis().to_bytes())
        self.assertEqual(dict(load_verified_history(self.mission.paths.mission_root).source_files), source_before)
        self.mission.paths.mission_root.rename(self.base / 'mission-removed')
        self.assertEqual(self.store.verify().event_count, 2)

    def test_fixed_plan_same_hypothesis_identity_conflicts_and_original_stays(self):
        event, evidence = self.built_hypothesis()
        self.store.append(event, evidence)
        original = (self.root / 'entries/00000002.json').read_bytes()
        changed = self.hypothesis().to_dict()
        changed['expected_outcomes'][0]['threshold'] = 'SPY'
        conflict, retained = self.built_hypothesis(InvestmentHypothesis.from_mapping(changed))
        self.assertEqual(conflict.event_id, event.event_id)
        with self.assertRaisesRegex(JournalConflictError, 'different content'):
            self.store.append(conflict, retained)
        self.assertEqual((self.root / 'entries/00000002.json').read_bytes(), original)
        self.assertFalse(self.store.append(event, {}).written)

    def test_mutated_event_identity_rejected_under_writer_lock(self):
        event, evidence = self.built_hypothesis()
        for field in ('decision_id', 'event_id'):
            changed = event.to_dict()
            changed[field] = identity('journal-' + field.replace('_id', ''), {'wrong': field})
            with self.subTest(field=field), self.assertRaises(JournalVerificationError):
                self.store.append(JournalEvent.from_mapping(changed), evidence)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_missing_hypothesis_draft_retention_rejected(self):
        event, _ = self.built_hypothesis()
        with self.assertRaisesRegex(JournalVerificationError, 'evidence'):
            self.store.append(event, {})
        self.assertEqual(self.store.verify().event_count, 1)

    def test_canonical_hypothesis_draft_source_mismatch_rejected(self):
        event, evidence = self.built_hypothesis()
        changed = event.to_dict()
        request_reference = next(reference for reference in self.parent.evidence
                                 if reference['path'] == 'request/mission_request.json')
        changed['source']['source_sha256'] = request_reference['sha256']
        # The wrong bytes are legitimately retained evidence; source binding
        # must still distinguish a hypothesis from a historical request.
        changed['evidence'].append(request_reference)
        with self.assertRaisesRegex(ContractValidationError, 'hash does not match payload'):
            self.store.append(JournalEvent.from_mapping(changed), evidence)

    def test_orphan_or_mismatched_observation_link_rejected_at_append(self):
        event, evidence = self.built_hypothesis()
        draft_path = f'hypotheses/{self.hypothesis().hypothesis_id}/hypothesis.json'
        for key, value in (
            ('source_event_id', identity('journal-event', {'missing': 'parent'})),
            ('artifact_sha256', sha256_bytes(b'wrong source bytes')),
            ('artifact_path', 'artifacts/unknown.json'),
            ('value', 'SPY'),
        ):
            changed = event.to_dict()
            changed['payload']['observations'][0][key] = value
            draft = canonical_json_bytes(changed['payload'])
            changed['source']['source_sha256'] = sha256_bytes(draft)
            for reference in changed['evidence']:
                if reference['path'] == draft_path:
                    reference['sha256'] = sha256_bytes(draft)
                    reference['size_bytes'] = len(draft)
            retained = {**evidence, draft_path: draft}
            candidate = JournalEvent.from_mapping(changed)
            with self.subTest(key=key), self.assertRaisesRegex(JournalVerificationError, 'investment hypothesis'):
                self.store.append(candidate, retained)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_corrupt_hypothesis_retained_evidence_rejects_even_retry(self):
        event, evidence = self.built_hypothesis()
        self.store.append(event, evidence)
        draft = self.root / 'evidence' / event.source['source_sha256']
        draft.chmod(0o600)
        draft.write_bytes(b'corrupt hypothesis draft')
        for action in (self.store.verify, lambda: self.store.append(event, evidence)):
            with self.subTest(action=action), self.assertRaisesRegex(JournalVerificationError, 'hash mismatch'):
                action()
        self.assertEqual(len(list((self.root / 'entries').iterdir())), 2)

    def test_interrupted_hypothesis_precommit_recovers_orphan_draft(self):
        event, evidence = self.built_hypothesis()
        def fail_before_event(staging, target, name, payload):
            if name == '00000002.json':
                raise JournalPersistenceError('injected before hypothesis event')
            return _publish_immutable(staging, target, name, payload)
        with mock.patch('blackpod_build_week.decision_journal_store._publish_immutable',
                        side_effect=fail_before_event):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, 1)
        self.assertGreaterEqual(summary.orphan_evidence_count, 1)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_interrupted_hypothesis_postcommit_retry_is_noop(self):
        event, evidence = self.built_hypothesis()
        def fail_after_event(staging, target, name, payload):
            _publish_immutable(staging, target, name, payload)
            if name == '00000002.json':
                raise JournalPersistenceError('injected after hypothesis event')
        with mock.patch('blackpod_build_week.decision_journal_store._publish_immutable',
                        side_effect=fail_after_event):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 2)
        original = (self.root / 'entries/00000002.json').read_bytes()
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual((self.root / 'entries/00000002.json').read_bytes(), original)

    def test_rehashed_hypothesis_semantic_tamper_detected_on_verify(self):
        event, evidence = self.built_hypothesis()
        self.store.append(event, evidence)
        entry_path = self.root / 'entries/00000002.json'
        entry = json.loads(entry_path.read_bytes())
        entry['event']['event_id'] = identity('journal-event', {'wrong': 'identity'})
        entry['event_sha256'] = sha256_bytes(canonical_json_bytes(entry['event']))
        entry_path.chmod(0o600)
        entry_path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaises(JournalVerificationError):
            self.store.verify()

    def test_deeply_nested_retained_entry_verify_and_retry_fail_cleanly(self):
        event, evidence = self.built_hypothesis()
        self.store.append(event, evidence)
        path = self.root / 'entries/00000002.json'
        path.chmod(0o600)
        path.write_bytes(b'{"event":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}')
        for action in (self.store.verify, lambda: self.store.append(event, {})):
            with self.subTest(action=action), self.assertRaisesRegex(JournalVerificationError, 'invalid journal event'):
                action()
        self.assertEqual(len(list((self.root / 'entries').iterdir())), 2)

    def test_existing_evaluation_cannot_target_hypothesis_or_add_authority(self):
        event, evidence = self.built_hypothesis()
        self.store.append(event, evidence)
        evaluation = {
            'schema_version': 'blackpod.decision_journal_evaluation.v1',
            'evaluation_id': 'evaluation-hypothesis-attempt', 'decision_id': event.decision_id,
            'recorded_at': '2027-01-13T00:00:00Z', 'evaluator': 'test-reviewer',
            'evaluation_type': 'PROCESS', 'conclusion': 'Fixture review only.',
            'outcome_status': 'OBSERVED', 'realized_trade_pnl': None,
        }
        with self.assertRaisesRegex(ContractValidationError, 'recorded mission'):
            build_evaluation_event(EvaluationInput.from_mapping(evaluation), event)
        evaluation['authorization_enabled'] = True
        with self.assertRaisesRegex(ContractValidationError, 'unknown'):
            EvaluationInput.from_mapping(evaluation)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_original_nonexecuted_mission_evaluation_cannot_claim_trade_pnl(self):
        evaluation = EvaluationInput.from_mapping({
            'schema_version': 'blackpod.decision_journal_evaluation.v1',
            'evaluation_id': 'evaluation-pnl-attempt', 'decision_id': self.parent.decision_id,
            'recorded_at': '2027-01-13T00:00:00Z', 'evaluator': 'test-reviewer',
            'evaluation_type': 'TRADE', 'conclusion': 'Attempted unsupported PNL.',
            'outcome_status': 'OBSERVED', 'realized_trade_pnl': 42,
        })
        with self.assertRaisesRegex(ContractValidationError, 'P&L'):
            build_evaluation_event(evaluation, self.parent)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_source_mission_root_safety_remains(self):
        for root in (self.mission.paths.mission_root,
                     self.mission.paths.mission_root / 'journal', self.base / 'source'):
            with self.subTest(root=root), self.assertRaises(JournalUnsafePathError):
                JournalStore(root)


if __name__ == '__main__':
    unittest.main()
