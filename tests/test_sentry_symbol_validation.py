"""Explicit symbol-contract validation over retained, authored headline evidence.

The real ModelDockClient uses only an in-memory HTTP response fixture. These
tests never contact an inference server, data provider, broker, or account.
"""
from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_synthesis_service as service
from blackpod_build_week import sentry_synthesis_transport as transport
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient
from blackpod_build_week.shadow_station import atomic_state
import test_sentry_synthesis_service as service_fixtures
import test_sentry_synthesis_transport as transport_fixtures


class SymbolFixtureTransport(transport_fixtures.FixtureTransport):
    """Return the requested original schema, with explicit parent-only defects."""
    def __init__(self):
        super().__init__()
        self.failure_mode = None
        self.interrupt_on_call = None

    def request(self, **kwargs):
        wire = json.loads(kwargs['body'])
        supplied = json.loads(wire['messages'][1]['content'])
        packet = supplied['evidence_packet']
        headline = next(item for item in packet['evidence'] if item['kind'] == 'HEADLINE')
        if self.interrupt_on_call == len(self.calls) + 1:
            self.calls.append(kwargs)
            raise KeyboardInterrupt()
        if 'original_oracle_draft' in supplied:
            self.content = transport_fixtures.challenge()
            self.content['draft_sha256'] = sha256_bytes(canonical_json_bytes(supplied['original_oracle_draft']))
            self.content['reviews'][0]['evidence_ids'] = [headline['evidence_id']]
        else:
            self.content = transport_fixtures.draft()
            self.content['overview']['evidence_ids'] = [headline['evidence_id']]
            theme = self.content['themes'][0]
            theme['evidence_ids'] = [headline['evidence_id']]
            theme['implications'][0]['symbol'] = headline['symbols'][0]
            if self.failure_mode == 'duplicate':
                theme['implications'].append(deepcopy(theme['implications'][0]))
            elif self.failure_mode == 'text':
                self.content['overview']['text'] = 'First line.\nSecond line.'
            schema = wire['response_format']['schema']['properties']['schema_version']['const']
            if schema == 'blackpod.sentry_oracle_draft.v3':
                self.content['schema_version'] = schema
                entries = theme.pop('implications')
                theme['implications_by_symbol'] = {
                    item['symbol']: {key: value for key, value in item.items() if key != 'symbol'}
                    for item in entries}
        return super().request(**kwargs)


class ExplicitSymbolValidationTests(unittest.TestCase):
    def setUp(self):
        self.helper = service_fixtures.SentrySynthesisServiceTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.config = self.helper.config
        self.config.update(experiment_id='frozen-fixture', protocol_sha256='a' * 64)
        self.helper.modeldock.update(timeout_seconds=900, delivery_grace_seconds=30)
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        atomic_state(service.catalyst_paths(self.config)[0] / 'control.json',
            {'schema_version': catalyst.VERSION, 'enabled': True, 'symbols': service_fixtures.WATCH})
        self.pins = self.enterContext(patch.object(service, '_pinned_view',
            return_value={'journal': {'last_entry_sha256': 'b' * 64}}))
        self.http = SymbolFixtureTransport()
        self.helper.http = self.http
        self.parent, self.parent_report = self.new_parent('duplicate', first=True)
        self.source_id = self.parent_report['report_id']
        self.originals = service.capsule_hashes(self.parent)
        self.helper.now += timedelta(seconds=1)

    def new_parent(self, mode=None, *, first=False, version=None):
        if not first:
            self.helper.now += timedelta(hours=1)
            index = len(service.ledger(self.helper.runs)) + 1
            self.helper.append_capture(self.helper.now, headline='Distinct retained headline ' + str(index),
                                       identity=1000 + index)
        self.http.failure_mode = mode
        self.http.interrupt_on_call = 1 if mode == 'uncertain' else None
        self.http.calls.clear()
        with patch.object(service, 'BACKGROUND_TRANSPORT_VERSION', version or service.TEXT_TRANSPORT_VERSION):
            if mode == 'uncertain':
                with self.assertRaises(KeyboardInterrupt):
                    self.helper.cycle()
                directory = self.helper.directory()
                report = service.recover_attempt(directory, self.config, self.helper.now)
            else:
                self.helper.cycle()
                directory = self.helper.directory()
                report = service.read_report(directory, self.config)
        self.http.failure_mode = None
        self.http.interrupt_on_call = None
        self.http.calls.clear()
        return directory, report

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        original_clock = self.helper.now
        self.helper.now = options['now']
        try:
            return service.validate_symbols(self.config, self.source_id, **options)
        finally:
            self.helper.now = original_clock

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, symbol_validation=True)

    def assert_no_child(self):
        self.assertFalse(self.child().exists())
        self.assertEqual(self.http.calls, [])

    def rewrite(self, path, value):
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))

    def test_exact_saved_packet_separate_child_and_original_keyed_draft_bound_challenge(self):
        observation = service.immutable_read(self.parent / 'oracle', 'local-contract-error.json')
        self.assertEqual(observation['schema_version'], 'blackpod.sentry_local_contract_observation.v2')
        self.assertEqual((observation['stage'], observation['reason']), ('HOST_RESPONSE_CONTRACT', 'DUPLICATE_SYMBOL'))
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation'], {
            'purpose': 'EXPLICIT_SYMBOL_VALIDATION', 'scope': 'MANUAL_RETAINED_EVIDENCE',
            'parent_report_id': self.source_id,
            'parent_report_sha256': sha256_bytes(canonical_json_bytes(self.parent_report)),
            'transport_schema_version': service.SYMBOL_TRANSPORT_VERSION})
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context'], self.parent_report['context'])
        self.assertEqual(result['draft']['schema_version'], 'blackpod.sentry_oracle_draft.v3')
        self.assertIn('implications_by_symbol', result['draft']['themes'][0])
        self.assertNotIn('implications', result['draft']['themes'][0])
        self.assertEqual(result['challenge']['draft_sha256'], sha256_bytes(canonical_json_bytes(result['draft'])))
        self.assertEqual(result['challenge']['reviews'][0]['status'], 'UNTESTED')
        self.assertTrue(all(value is False for value in result['authority'].values()))
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)
        self.assertEqual(len(self.http.calls), 2)
        requests = [json.loads(call['body']) for call in self.http.calls]
        self.assertEqual([wire['max_tokens'] for wire in requests], [4096, 4096])
        self.assertEqual([wire['timeout'] for wire in requests], [900, 900])
        self.assertEqual(requests[0]['response_format']['schema']['properties']['schema_version']['const'],
                         'blackpod.sentry_oracle_draft.v3')
        self.assertEqual(requests[1]['response_format']['schema']['properties']['schema_version']['const'],
                         'blackpod.sentry_challenge.v2')
        self.assertEqual(json.loads(requests[1]['messages'][1]['content'])['original_oracle_draft'], result['draft'])
        parent_id = self.parent_report['provenance']['oracle']['request_id']
        self.assertNotEqual(parent_id, result['provenance']['oracle']['request_id'])
        self.assertEqual(service.immutable_read(self.child(), 'run-intent.json')['schema_version'],
                         service.SYMBOL_VALIDATION_VERSION)
        self.assertEqual(service.read_report(self.child(), self.config), result)

    def test_same_explicit_child_retry_verification_and_status_are_provider_free(self):
        result = self.run_validation()
        original = service.capsule_hashes(self.child())
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no resend')):
            self.assertEqual(self.run_validation(), result)
            self.assertEqual(service.verify(self.config)['report_count'], 2)
            self.assertEqual(service.status(self.config, self.helper.now)['report'], result)
        self.assertEqual(service.capsule_hashes(self.child()), original)
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)
        self.assertEqual(len(self.http.calls), 2)

    def test_accepted_child_cannot_authorize_another_symbol_validation(self):
        result = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, result['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assertEqual(len(self.http.calls), 2)

    def test_text_format_parent_is_ineligible(self):
        _, report = self.new_parent('text')
        self.assertEqual(report['status'], 'REJECTED')
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, report['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assert_no_child()

    def test_accepted_parent_is_ineligible(self):
        _, report = self.new_parent()
        self.assertEqual(report['status'], 'CHALLENGED_INTERPRETATION')
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, report['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assert_no_child()

    def test_uncertain_parent_is_ineligible(self):
        _, report = self.new_parent('uncertain')
        self.assertEqual(report['status'], 'UNCERTAIN')
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, report['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assert_no_child()

    def test_v8_duplicate_parent_is_ineligible(self):
        directory, report = self.new_parent('duplicate', version=service.CONTRACT_TRANSPORT_VERSION)
        observation = service.immutable_read(directory / 'oracle', 'local-contract-error.json')
        self.assertEqual(observation['schema_version'], 'blackpod.sentry_local_contract_observation.v1')
        self.assertEqual(observation['reason'], 'DUPLICATE_SYMBOL')
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, report['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assert_no_child()

    def test_other_verified_local_rejection_reason_is_ineligible(self):
        path = self.parent / 'oracle/local-contract-error.json'
        value = json.loads(path.read_bytes())
        value['reason'] = 'DUPLICATE_CITATIONS'
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in value.items()
                                                                        if k != 'observation_sha256'}))
        self.rewrite(path, value)
        # The retained observation is internally bound and otherwise valid;
        # its different reason cannot admit the symbol-specific child.
        self.assertEqual(service.read_report(self.parent, self.config), self.parent_report)
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assert_no_child()

    def test_duplicate_parent_with_different_original_deadline_is_ineligible(self):
        self.helper.modeldock.update(timeout_seconds=60, delivery_grace_seconds=5)
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        _, report = self.new_parent('duplicate')
        self.assertEqual(report['status'], 'REJECTED')
        with self.assertRaises(ValueError):
            service.validate_symbols(self.config, report['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assert_no_child()

    def test_missing_or_unbound_parent_observation_cannot_authorize_child(self):
        path = self.parent / 'oracle/local-contract-error.json'
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assert_no_child()
        path.write_bytes(original)
        value = json.loads(original)
        value['request_id'] = 'unrelated-request'
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in value.items()
                                                                        if k != 'observation_sha256'}))
        self.rewrite(path, value)
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assert_no_child()

    def test_interrupted_oracle_recovers_uncertain_without_resend(self):
        self.http.interrupt_on_call = 1
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertTrue((self.child() / 'oracle/intent.json').exists())
        self.assertFalse((self.child() / 'oracle/receipt.json').exists())
        self.assertFalse((self.child() / 'challenge').exists())
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)

    def test_interrupted_challenge_preserves_original_keyed_oracle_and_never_resends(self):
        self.http.interrupt_on_call = 2
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        result = self.run_validation()
        self.assertEqual(result['status'], 'DRAFT_ONLY')
        self.assertEqual(result['draft']['schema_version'], 'blackpod.sentry_oracle_draft.v3')
        self.assertIsNone(result['challenge'])
        self.assertEqual(result['provenance']['challenge']['status'], 'UNCERTAIN')
        self.assertEqual(len(self.http.calls), 2)
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)

    def test_packet_only_child_stays_uncertain_without_inference_or_invented_reservation(self):
        service.write_json_once(self.child(), 'packet.json', self.parent_report['context'])
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertFalse((self.child() / 'run-intent.json').exists())
        self.assertEqual(self.http.calls, [])

    def assert_unexpected_challenge_fails_closed(self):
        self.assertEqual(self.parent_report['provenance']['oracle']['status'], 'REJECTED')
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no provider resend')):
            with self.assertRaises(ValueError):
                service.read_report(self.parent, self.config)
            with self.assertRaises(ValueError):
                service.verify(self.config)
            value = service.status(self.config, self.helper.now)
            self.assertEqual(value['status'], 'UNAVAILABLE')
            self.assertIsNone(value['report'])
            self.assertEqual(value['auto_trading'], 'UNVERIFIED')
            self.assertNotIn('role_diagnostics', value)
            with self.assertRaises(ValueError):
                self.run_validation()
        self.assert_no_child()

    def test_unexpected_empty_challenge_directory_cannot_be_labeled_not_run(self):
        path = self.parent / 'challenge'
        path.mkdir()
        try:
            self.assert_unexpected_challenge_fails_closed()
        finally:
            path.rmdir()
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)

    def test_dangling_challenge_symlink_cannot_be_labeled_not_run(self):
        path = self.parent / 'challenge'
        path.symlink_to(self.parent / 'absent-challenge-target', target_is_directory=True)
        self.assertFalse(path.exists())
        try:
            self.assert_unexpected_challenge_fails_closed()
        finally:
            path.unlink()
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)

    def test_newer_headlines_cannot_replace_the_saved_validation_packet(self):
        self.helper.append_capture(self.helper.now + timedelta(minutes=5),
                                   headline='A newer, unrelated observation', identity=999)
        with patch.object(service, 'current_packet', side_effect=AssertionError('saved packet required')):
            result = self.run_validation()
        self.assertEqual(result['context'], self.parent_report['context'])
        for call in self.http.calls:
            supplied = json.loads(json.loads(call['body'])['messages'][1]['content'])
            self.assertEqual(supplied['evidence_packet'], self.parent_report['context'])
        self.assertEqual(service.capsule_hashes(self.parent), self.originals)

    def test_pause_off_source_and_serialization_gates_remain_enforced(self):
        self.helper.control['enabled'] = False
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        self.assertEqual(self.run_validation()['status'], 'PAUSED')
        self.helper.control['enabled'] = True
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        for gate in (self.helper.off, self.pins):
            gate.side_effect = ValueError('fixture safety gate blocked')
            with self.assertRaises(ValueError):
                self.run_validation()
            gate.side_effect = None
        with service.service_lock(self.helper.root), self.assertRaises(ValueError):
            self.run_validation()
        self.assert_no_child()

    def test_reversed_clock_archive_bound_and_changed_watchlist_block_new_child(self):
        self.assertEqual(self.run_validation(now=self.helper.now - timedelta(minutes=1))['status'], 'CLOCK_BLOCKED')
        with patch.object(service, 'MAX_RUNS', 1):
            self.assertEqual(self.run_validation()['status'], 'ARCHIVE_REVIEW_REQUIRED')
        atomic_state(service.catalyst_paths(self.config)[0] / 'control.json',
            {'schema_version': catalyst.VERSION, 'enabled': True, 'symbols': ['SPY']})
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assert_no_child()

    def test_wrong_fixed_deadline_cannot_open_manual_child(self):
        for timeout, grace in ((899, 30), (900, 29)):
            with self.subTest(timeout=timeout, grace=grace):
                self.helper.modeldock.update(timeout_seconds=timeout, delivery_grace_seconds=grace)
                atomic_state(self.helper.root / 'control.json', self.helper.control)
                with self.assertRaises(ValueError):
                    self.run_validation()
        self.assert_no_child()

    def test_explicit_manual_child_runs_on_weekend_without_consuming_background_budget(self):
        saturday = service_fixtures.NOW + timedelta(days=2)
        result = self.run_validation(now=saturday)
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        value = service.status(self.config, saturday)
        self.assertEqual(value['operational']['background_attempt_count_today'], 0)
        self.assertEqual(value['operational']['manual_attempt_count_today'], 1)
        self.assertEqual(value['operational']['reason'], 'OUTSIDE_MONITORING_HOURS')
        self.assertEqual(len(self.http.calls), 2)

    def test_explicit_manual_child_bypasses_background_cap_and_spacing_only(self):
        for _ in range(3):
            self.new_parent('duplicate')
        entries = service.ledger(self.helper.runs)
        self.assertEqual(service.due(self.helper.now, entries, True)[1], 'DAILY_BUDGET_EXHAUSTED')
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(len(self.http.calls), 2)
        counts = service.status(self.config, self.helper.now)['operational']
        self.assertEqual(counts['background_attempt_count_today'], 4)
        self.assertEqual(counts['manual_attempt_count_today'], 1)
        self.assertEqual(service.due(self.helper.now, service.ledger(self.helper.runs), True)[1],
                         'DAILY_BUDGET_EXHAUSTED')

    def test_tampered_child_parent_hash_and_role_version_fail_provider_free_verification(self):
        self.run_validation()
        path = self.child() / 'run-intent.json'
        original = path.read_bytes()
        value = json.loads(original)
        value['validation']['parent_report_sha256'] = '0' * 64
        self.rewrite(path, value)
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            with self.assertRaises(ValueError):
                service.verify(self.config)
        self.rewrite(path, json.loads(original))
        role = self.child() / 'oracle/intent.json'
        value = json.loads(role.read_bytes())
        value['schema_version'] = service.TEXT_TRANSPORT_VERSION
        self.rewrite(role, value)
        with self.assertRaises(ValueError):
            service.verify(self.config)
        self.assertEqual(len(self.http.calls), 2)

    def test_symbol_cli_requires_named_source_and_exposes_no_force_or_budget_reset(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_symbols', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-symbols', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        for extra in ([], ['--source-report-id', self.source_id, '--force'],
                      ['--source-report-id', self.source_id, '--reset-budget']):
            with patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
                service.main(['validate-symbols', '--config', '/private/tmp/config.json', *extra])
        self.assertEqual(self.http.calls, [])


if __name__ == '__main__':
    unittest.main()
