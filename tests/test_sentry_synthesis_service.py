"""Offline governed-worker integration over real retained catalyst fixtures.

ModelDockClient is real; its HTTP transport is an authored response fixture.
No broker, news service, inference server, credentials, or live runtime is used.
"""
from datetime import timedelta
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_synthesis_service as service
from blackpod_build_week import sentry_synthesis_transport as transport
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient
from blackpod_build_week.shadow_station import atomic_state
from test_sentry_catalyst import NOW, WATCH, packet
from test_sentry_synthesis_transport import FixtureTransport, draft, challenge


class BoundFixtureTransport(FixtureTransport):
    """Author responses using the exact evidence IDs supplied on each wire."""
    def request(self, **kwargs):
        wire = json.loads(kwargs['body'])
        supplied = json.loads(wire['messages'][1]['content'])
        context = supplied['evidence_packet']
        headline = next(item for item in context['evidence'] if item['kind'] == 'HEADLINE')
        if 'original_oracle_draft' in supplied:
            self.content = challenge()
            self.content['draft_sha256'] = sha256_bytes(canonical_json_bytes(supplied['original_oracle_draft']))
            self.content['reviews'][0]['evidence_ids'] = [headline['evidence_id']]
        else:
            self.content = draft()
            self.content['overview']['evidence_ids'] = [headline['evidence_id']]
            self.content['themes'][0]['evidence_ids'] = [headline['evidence_id']]
            self.content['themes'][0]['implications'][0]['symbol'] = headline['symbols'][0]
        return super().request(**kwargs)


class SentrySynthesisServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.config = {key: str(root / key) for key in
                       ('station_root', 'runtime_root', 'experiment_root', 'historical_root', 'ui_root')}
        self.config['credentials_file'] = str(root / 'private/keys.yaml')
        self.root, self.runs = service.paths(self.config)
        self.store = catalyst.CatalystStore(service.catalyst_paths(self.config)[1])
        self.now = NOW
        self.modeldock = {'base_url': 'http://127.0.0.1:8000', 'timeout_seconds': 60,
                          'profile': 'default', 'provider': 'mlx', 'max_response_bytes': 1024 * 1024,
                          'delivery_grace_seconds': 5}
        self.control = {'schema_version': service.CONTROL_VERSION, 'enabled': True,
                        'modeldock': self.modeldock}
        atomic_state(self.root / 'control.json', self.control)
        self.off = self.enterContext(patch.object(service, '_off'))
        self.enterContext(patch.object(service, 'utc_now', side_effect=lambda: self.now))
        # Exercise the real role delivery with an explicit deterministic clock;
        # generate_role's production default callable is bound at definition.
        self.enterContext(patch.object(service, 'generate_role', side_effect=lambda *a, **kw:
            transport.generate_role(*a, **kw, now=lambda: self.now)))
        self.http = BoundFixtureTransport()
        self.factories = []
        self.append_capture(NOW)
        self.original_news = json.loads(packet()[1]['news'])

    def append_capture(self, at, *, headline='Company announces an agreement', identity=123, same_news=False):
        projection, blobs = packet(at=at, headline=headline, identity=identity)
        if same_news:
            blobs['news'] = canonical_json_bytes(self.original_news)
            receipt = json.loads(blobs['news_receipt'])
            receipt.update(body_sha256=sha256_bytes(blobs['news']), size_bytes=len(blobs['news']))
            blobs['news_receipt'] = canonical_json_bytes(receipt)
            projection = catalyst.project(blobs['news'], blobs['snapshots'], WATCH, catalyst.stamp(at))
        self.store.append(projection, blobs)

    def factory(self, config):
        # The run intent is durable before constructing any real client.
        entries = service.ledger(self.runs)
        self.assertTrue(entries)
        self.assertTrue((entries[-1][0] / 'run-intent.json').exists())
        self.factories.append(config)
        return ModelDockClient(config, transport=self.http, now=lambda: self.now)

    def cycle(self, at=None):
        if at is not None:
            self.now = at
        return service.cycle(self.config, now=self.now, client_factory=self.factory)

    def directory(self):
        return service.ledger(self.runs)[-1][0]

    def test_two_roles_real_client_fake_http_and_separate_immutable_dissent(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        self.assertEqual(len(self.http.calls), 2)
        self.assertEqual(len(self.factories), 2)
        requests = [json.loads(call['body']) for call in self.http.calls]
        first = requests[0]['metadata']['blackpod_correlation']['request_id']
        second = requests[1]['metadata']['blackpod_correlation']['request_id']
        self.assertNotEqual(first, second)
        self.assertEqual([call['url'] for call in self.http.calls],
                         ['http://127.0.0.1:8000/text/generate'] * 2)
        report = service.read_report(self.directory(), self.config)
        self.assertEqual(report['challenge']['reviews'][0]['status'], 'UNTESTED')
        self.assertEqual(report['challenge']['draft_sha256'], sha256_bytes(canonical_json_bytes(report['draft'])))
        self.assertEqual(report['context']['watchlist'], WATCH)
        self.assertEqual(report['portfolio']['status'], 'UNAVAILABLE_NO_VERIFIED_HOLDINGS')
        self.assertTrue(all(flag is False for flag in report['authority'].values()))
        self.assertFalse(report['review_independence']['independent_model_verified'])
        self.assertGreaterEqual(self.off.call_count, 6)

    def test_status_verify_recover_are_provider_free_and_do_not_rewrite_report(self):
        self.cycle()
        directory = self.directory()
        original = {str(p.relative_to(directory)): p.read_bytes()
                    for p in directory.rglob('*') if p.is_file()}
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('inference forbidden')):
            value = service.status(self.config, self.now)
            verified = service.verify(self.config)
            recovered = service.recover_attempt(directory, self.config, self.now)
        self.assertEqual(value['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(value['auto_trading'], 'OFF')
        self.assertEqual(value['operational']['attempt_count_today'], 1)
        self.assertEqual(value['brief_age_seconds'], 0)
        self.assertEqual(verified['report_count'], 1)
        self.assertEqual(recovered, value['report'])
        self.assertEqual(len(self.http.calls), 2)
        self.assertEqual(original, {str(p.relative_to(directory)): p.read_bytes()
                                    for p in directory.rglob('*') if p.is_file()})

    def test_deleted_mutable_state_cannot_reset_hourly_admission(self):
        self.cycle()
        atomic_state(self.root / 'state.json', {})
        later = NOW + timedelta(minutes=30)
        self.append_capture(later, headline='A genuinely different headline')
        self.assertEqual(self.cycle(later), 'WAITING_FOR_NEXT_SLOT')
        self.assertEqual(len(self.http.calls), 2)
        self.assertEqual(len(service.ledger(self.runs)), 1)

    def test_daily_budget_comes_from_intents_not_resettable_state(self):
        for index in range(4):
            at = NOW + timedelta(hours=index)
            if index:
                self.append_capture(at, headline='New headline ' + str(index), identity=123 + index)
            self.assertEqual(self.cycle(at), 'CHALLENGED_INTERPRETATION')
        atomic_state(self.root / 'state.json', {})
        fifth = NOW + timedelta(hours=4)
        self.append_capture(fifth, headline='Fifth new headline', identity=999)
        self.assertEqual(self.cycle(fifth), 'DAILY_BUDGET_EXHAUSTED')
        self.assertEqual(len(self.http.calls), 8)
        self.assertEqual(service.status(self.config, fifth)['operational']['attempt_count_today'], 4)

    def test_same_headline_revisions_do_not_rerun_when_prices_refresh(self):
        self.cycle()
        later = NOW + timedelta(hours=1)
        self.append_capture(later, same_news=True)
        self.assertEqual(self.cycle(later), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(len(self.http.calls), 2)
        value = service.status(self.config, later)
        self.assertTrue(value['newer_evidence_available'])
        self.assertEqual(value['brief_age_seconds'], 3600)
        self.assertEqual(value['report']['context']['as_of'], catalyst.stamp(NOW))

    def test_disabled_and_outside_hours_never_call_client(self):
        self.control['enabled'] = False
        atomic_state(self.root / 'control.json', self.control)
        self.assertEqual(self.cycle(), 'PAUSED')
        self.control['enabled'] = True
        atomic_state(self.root / 'control.json', self.control)
        self.assertEqual(self.cycle(NOW.replace(hour=3)), 'OUTSIDE_MONITORING_HOURS')
        self.assertEqual(self.cycle(NOW + timedelta(days=2)), 'OUTSIDE_MONITORING_HOURS')
        self.assertEqual(self.factories, [])
        self.assertEqual(self.http.calls, [])

    def test_reversed_clock_cannot_bypass_retained_hourly_reservation(self):
        self.cycle()
        self.assertEqual(self.cycle(NOW - timedelta(minutes=1)), 'CLOCK_BLOCKED')
        self.assertEqual(len(self.http.calls), 2)

    def test_off_gate_failure_prevents_reservation_or_client(self):
        self.off.side_effect = ValueError('private runtime path')
        with self.assertRaises(ValueError):
            self.cycle()
        self.assertFalse(self.runs.exists())
        self.assertEqual(self.factories, [])

    def test_source_corruption_blocks_before_client_and_status_fails_closed(self):
        source = self.store.root / 'entries/00000001.json'
        source.chmod(0o600)
        source.write_bytes(b'{}')
        with self.assertRaises(Exception):
            self.cycle()
        value = service.status(self.config, NOW)
        self.assertEqual(value['status'], 'UNAVAILABLE')
        self.assertEqual(value['auto_trading'], 'UNVERIFIED')
        self.assertIsNone(value['report'])
        self.assertEqual(self.factories, [])

    def test_stale_capture_and_no_headlines_do_not_spend_model_budget(self):
        self.assertEqual(self.cycle(NOW + timedelta(minutes=11)), 'SOURCE_CAPTURE_STALE')
        empty = service.current_packet(self.config, as_of=NOW)
        empty['selection']['selected_headline_count'] = 0
        with patch.object(service, 'current_packet', return_value=empty):
            self.assertEqual(self.cycle(NOW), 'NO_HEADLINE_EVIDENCE')
        self.assertFalse(self.runs.exists())
        self.assertEqual(self.factories, [])

    def test_interrupted_oracle_recovers_uncertain_without_resend(self):
        self.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.cycle()
        directory = self.directory()
        self.assertTrue((directory / 'oracle/intent.json').exists())
        self.assertFalse((directory / 'oracle/receipt.json').exists())
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no resend')):
            report = service.recover_attempt(directory, self.config, NOW)
            self.assertEqual(service.verify(self.config)['report_count'], 1)
        self.assertEqual(report['status'], 'UNCERTAIN')
        self.assertIsNone(report['draft'])
        later = NOW + timedelta(hours=1)
        self.append_capture(later, same_news=True)
        self.assertEqual(self.cycle(later), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(len(self.http.calls), 1)

    def test_interrupted_challenge_preserves_original_draft_and_missing_review(self):
        original = self.http.request
        def interrupt_second(**kwargs):
            if len(self.http.calls) == 1:
                self.http.exception = KeyboardInterrupt()
            return original(**kwargs)
        self.http.request = interrupt_second
        with self.assertRaises(KeyboardInterrupt):
            self.cycle()
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no resend')):
            report = service.recover_attempt(self.directory(), self.config, NOW)
        self.assertEqual(report['status'], 'DRAFT_ONLY')
        self.assertIsNotNone(report['draft'])
        self.assertIsNone(report['challenge'])
        self.assertEqual(len(self.http.calls), 2)

    def test_durable_run_intent_consumes_budget_if_display_state_write_interrupts(self):
        with patch.object(service, 'atomic_state', side_effect=OSError('interrupted state write')):
            with self.assertRaises(OSError):
                self.cycle()
        entries = service.ledger(self.runs)
        self.assertEqual(len(entries), 1)
        self.assertEqual(self.factories, [])
        self.assertEqual(self.cycle(NOW + timedelta(minutes=1)), 'WAITING_FOR_NEXT_SLOT')
        report = service.recover_attempt(entries[0][0], self.config, NOW)
        self.assertEqual(report['status'], 'UNCERTAIN')
        self.assertEqual(self.http.calls, [])

    def test_packet_only_interruption_is_retained_without_invented_reservation_or_send(self):
        publish = service.write_json_once
        def interrupt_intent(directory, name, value):
            if name == 'run-intent.json':
                raise OSError('fixture interruption')
            return publish(directory, name, value)
        with patch.object(service, 'write_json_once', side_effect=interrupt_intent):
            with self.assertRaises(OSError):
                self.cycle()
        self.assertEqual(service.ledger(self.runs), [])
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertEqual(service.status(self.config, NOW)['status'], 'UNCERTAIN')
        self.assertEqual(self.cycle(), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(self.factories, [])
        self.assertEqual(self.http.calls, [])
        later = NOW + timedelta(hours=1)
        self.append_capture(later, headline='Unrelated later evidence', identity=456)
        self.assertEqual(self.cycle(later), 'CHALLENGED_INTERPRETATION')
        self.assertEqual(service.verify(self.config)['attempt_count'], 1)

    def test_empty_preintent_directory_is_uncertain_and_does_not_block_unrelated_evidence(self):
        empty = self.runs / ('0' * 64)
        (empty / 'staging').mkdir(parents=True)
        self.assertEqual(service.ledger(self.runs), [])
        verified = service.verify(self.config)
        self.assertEqual(verified['attempt_count'], 0)
        self.assertEqual(verified['abandoned_pre_reservation_count'], 1)
        self.assertEqual(service.status(self.config, NOW)['status'], 'UNCERTAIN')
        self.assertEqual(self.factories, [])
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        self.assertEqual(len(self.http.calls), 2)

    def test_capacity_count_and_reserved_byte_margin_gate_before_client(self):
        self.cycle()
        later = NOW + timedelta(hours=1)
        self.append_capture(later, headline='New evidence for capacity test', identity=456)
        with patch.object(service, 'MAX_RUNS', 1):
            self.assertEqual(self.cycle(later), 'ARCHIVE_REVIEW_REQUIRED')
        total = sum(p.stat().st_size for p in self.runs.rglob('*') if p.is_file())
        with patch.object(service, 'MAX_BYTES', total + 8 * 1024 * 1024 - 1):
            self.assertEqual(self.cycle(later), 'ARCHIVE_REVIEW_REQUIRED')
        self.assertEqual(len(self.http.calls), 2)

    def test_tampered_report_fails_closed_and_blocks_later_provider_work(self):
        self.cycle()
        report_path = self.directory() / 'report.json'
        report = json.loads(report_path.read_bytes())
        report['draft']['overview']['text'] = 'Tampered meaning'
        report_path.chmod(0o600)
        report_path.write_bytes(canonical_json_bytes(report))
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            with self.assertRaises(ValueError):
                service.verify(self.config)
            self.assertEqual(service.status(self.config, NOW)['status'], 'UNAVAILABLE')
            later = NOW + timedelta(hours=1)
            self.append_capture(later, headline='Later valid source must not bypass a corrupt report', identity=456)
            with self.assertRaises(ValueError):
                self.cycle(later)
        self.assertEqual(len(self.http.calls), 2)

    def test_changed_intent_binding_is_not_a_retry_or_budget_reset(self):
        self.cycle()
        path = self.directory() / 'run-intent.json'
        intent = json.loads(path.read_bytes())
        intent['reserved_at'] = catalyst.stamp(NOW - timedelta(hours=1))
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(intent))
        with self.assertRaises(ValueError):
            service.ledger(self.runs)
        with self.assertRaises(ValueError):
            self.cycle(NOW + timedelta(hours=1))
        self.assertEqual(len(self.http.calls), 2)

    def test_conflicting_completion_clock_recovery_never_rewrites_or_resends(self):
        self.cycle()
        directory = self.directory()
        path = directory / 'completion-clock.json'
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes({'completed_at': catalyst.stamp(NOW - timedelta(seconds=1))}))
        before = path.read_bytes()
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            with self.assertRaises(ValueError):
                service.recover_attempt(directory, self.config, NOW)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.http.calls), 2)

    def test_status_postflight_off_failure_hides_retained_report_and_off_claim(self):
        self.cycle()
        self.off.side_effect = [None, ValueError('runtime changed during status')]
        value = service.status(self.config, NOW)
        self.assertEqual(value['status'], 'UNAVAILABLE')
        self.assertEqual(value['auto_trading'], 'UNVERIFIED')
        self.assertIsNone(value['report'])
        self.assertEqual(len(self.http.calls), 2)

    def test_postflight_off_change_never_publishes_a_successful_report_or_calls_challenge(self):
        self.http.mutate = lambda envelope: setattr(self.off, 'side_effect', ValueError('OFF state changed'))
        self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        directory = self.directory()
        self.assertFalse((directory / 'report.json').exists())
        self.assertFalse((directory / 'challenge').exists())
        receipt = json.loads((directory / 'oracle/receipt.json').read_bytes())
        self.assertEqual(receipt['status'], 'REJECTED')
        self.assertIsNone(receipt['response'])
        self.assertEqual(len(self.http.calls), 1)

    def test_terminal_model_failure_is_not_resent_and_cannot_create_challenge(self):
        self.http.exception = TimeoutError('private fixture failure')
        self.assertEqual(self.cycle(), 'FAILED')
        report = service.read_report(self.directory(), self.config)
        self.assertIsNone(report['draft'])
        self.assertIsNone(report['challenge'])
        self.assertFalse((self.directory() / 'challenge').exists())
        self.assertNotIn('private fixture failure', json.dumps(report))
        later = NOW + timedelta(hours=1)
        self.append_capture(later, same_news=True)
        self.assertEqual(self.cycle(later), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(len(self.http.calls), 1)

    def test_duplicate_worker_lock_cannot_construct_client(self):
        with service.service_lock(self.root), self.assertRaises(ValueError):
            self.cycle()
        self.assertEqual(self.factories, [])
        self.assertEqual(self.http.calls, [])

    def test_symlink_run_inventory_cannot_reach_outside_storage_or_call_client(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        self.runs.mkdir()
        (self.runs / ('1' * 64)).symlink_to(outside)
        with self.assertRaises(ValueError):
            self.cycle()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.factories, [])

    def test_cli_status_verify_and_recover_are_provider_free(self):
        self.cycle()
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            for command in ('status', 'verify', 'recover'):
                with self.subTest(command=command), patch('sys.stdout', new_callable=StringIO) as output:
                    self.assertEqual(service.main([command, '--config', '/private/tmp/fixture-config.json']), 0)
                    result = json.loads(output.getvalue())
                    self.assertIn(result['status'], {'CHALLENGED_INTERPRETATION', 'VERIFIED', 'RECOVERED'})
        self.assertEqual(len(self.http.calls), 2)


class ExplicitV2ValidationTests(unittest.TestCase):
    """Legacy failure capsules are authored fixtures, never new v1 deliveries."""
    def setUp(self):
        self.helper = SentrySynthesisServiceTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.config = self.helper.config
        self.config.update(experiment_id='frozen-fixture', protocol_sha256='a' * 64)
        atomic_state(service.catalyst_paths(self.config)[0] / 'control.json',
            {'schema_version': catalyst.VERSION, 'enabled': True, 'symbols': WATCH})
        self.pins = self.enterContext(patch.object(service, '_pinned_view',
            return_value={'journal': {'last_entry_sha256': 'b' * 64}}))
        self.parent, self.parent_report = self.legacy_failure()
        self.source_id = self.parent_report['report_id']
        self.original_parent = service.capsule_hashes(self.parent)
        self.helper.now = NOW + timedelta(hours=1)

    def legacy_failure(self, status='FAILED', *, receipt=True):
        packet = service.current_packet(self.config, as_of=NOW)
        directory = self.helper.runs / packet['evidence_signature']
        service.write_json_once(directory, 'packet.json', packet)
        service.write_json_once(directory, 'run-intent.json', {'schema_version': service.VERSION,
            'context_id': packet['context_id'], 'packet_sha256': sha256_bytes(canonical_json_bytes(packet)),
            'evidence_signature': packet['evidence_signature'], 'reserved_at': catalyst.stamp(NOW),
            'modeldock': self.helper.modeldock})
        config = service.configuration(self.helper.modeldock)
        wire, bindings, modeldock = transport._request('oracle', packet, config, None,
            version=transport.LEGACY_VERSION)
        original_intent = {'schema_version': transport.LEGACY_VERSION, 'bindings': bindings,
            'configuration': modeldock, 'wire_request': wire,
            'request_sha256': sha256_bytes(canonical_json_bytes(wire)), 'reserved_at': catalyst.stamp(NOW)}
        service.write_json_once(directory / 'oracle', 'intent.json', original_intent)
        if receipt:
            original_receipt = {'schema_version': transport.LEGACY_VERSION, 'bindings': bindings,
                'intent_sha256': sha256_bytes(canonical_json_bytes(original_intent)), 'status': status,
                'finished_at': catalyst.stamp(NOW), 'response': None, 'provenance': None,
                'failure_code': 'MODELDOCK_HTTP_STATUS'}
            original_receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes(original_receipt))
            service.write_json_once(directory / 'oracle', 'receipt.json', original_receipt)
        return directory, service.recover_attempt(directory, self.config, NOW)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_v2(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id)

    def test_exact_old_packet_separate_role_ids_parent_link_and_no_parent_modification(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(result['completed_at'], catalyst.stamp(self.helper.now))
        validation = result['validation']
        self.assertEqual(validation['purpose'], 'EXPLICIT_V2_VALIDATION')
        self.assertEqual(validation['parent_report_id'], self.source_id)
        self.assertEqual(validation['parent_report_sha256'], sha256_bytes(canonical_json_bytes(self.parent_report)))
        self.assertEqual(validation['transport_schema_version'], transport.VERSION)
        old_id = self.parent_report['provenance']['oracle']['request_id']
        self.assertNotEqual(result['provenance']['oracle']['request_id'], old_id)
        self.assertEqual(self.original_parent, service.capsule_hashes(self.parent))
        self.assertEqual(service.verify(self.config)['attempt_count'], 2)
        self.assertEqual(service.verify(self.config)['report_dispositions'],
                         {'FAILED': 1, 'CHALLENGED_INTERPRETATION': 1})
        self.assertTrue(all(v is False for v in result['authority'].values()))
        self.assertGreaterEqual(self.pins.call_count, 2)

    def test_duplicate_validation_and_recovery_never_resend_even_if_collection_paused(self):
        first = self.run_validation()
        self.helper.control['enabled'] = False
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no resend')):
            self.assertEqual(self.run_validation(), first)
            self.assertEqual(service.recover_attempt(self.child(), self.config, self.helper.now), first)
            self.assertEqual(service.read_report(self.child(), self.config), first)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual(self.original_parent, service.capsule_hashes(self.parent))

    def test_shared_hourly_budget_is_not_bypassed_by_explicit_validation(self):
        result = self.run_validation(now=NOW + timedelta(minutes=59))
        self.assertEqual(result['status'], 'WAITING_FOR_NEXT_SLOT')
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_shared_daily_budget_counts_original_and_other_normal_reservations(self):
        for index in range(1, 4):
            at = NOW + timedelta(hours=index)
            self.helper.append_capture(at, headline='Independent later headline ' + str(index), identity=200 + index)
            self.assertEqual(self.helper.cycle(at), 'CHALLENGED_INTERPRETATION')
        self.helper.now = NOW + timedelta(hours=4)
        result = self.run_validation()
        self.assertEqual(result['status'], 'DAILY_BUDGET_EXHAUSTED')
        self.assertFalse(self.child().exists())
        self.assertEqual(len(self.helper.http.calls), 6)

    def test_child_reservation_survives_mutable_state_write_interruption(self):
        with patch.object(service, 'atomic_state', side_effect=OSError('state interruption')):
            with self.assertRaises(OSError):
                self.run_validation()
        self.assertEqual(len(service.ledger(self.helper.runs)), 2)
        self.assertEqual(self.helper.http.calls, [])
        report = self.run_validation()
        self.assertEqual(report['status'], 'UNCERTAIN')
        self.assertEqual(self.helper.http.calls, [])
        self.assertEqual(self.original_parent, service.capsule_hashes(self.parent))

    def test_packet_only_child_remains_uncertain_without_reservation_or_resend(self):
        publish = service.write_json_once
        def fail_intent(directory, name, value):
            if name == 'run-intent.json':
                raise OSError('fixture pre-reservation interruption')
            return publish(directory, name, value)
        with patch.object(service, 'write_json_once', side_effect=fail_intent):
            with self.assertRaises(OSError):
                self.run_validation()
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(self.helper.http.calls, [])
        self.assertEqual(self.original_parent, service.capsule_hashes(self.parent))

    def test_interrupted_oracle_is_not_resent_and_recovers_uncertain(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(self.original_parent, service.capsule_hashes(self.parent))

    def test_interrupted_challenge_preserves_draft_without_resend(self):
        original = self.helper.http.request
        def interrupt_second(**kwargs):
            if len(self.helper.http.calls) == 1:
                self.helper.http.exception = KeyboardInterrupt()
            return original(**kwargs)
        self.helper.http.request = interrupt_second
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        result = self.run_validation()
        self.assertEqual(result['status'], 'DRAFT_ONLY')
        self.assertIsNotNone(result['draft'])
        self.assertIsNone(result['challenge'])
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_terminal_child_failure_is_not_another_validation_parent(self):
        self.helper.http.exception = TimeoutError('fixture terminal failure')
        failed = self.run_validation()
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(self.run_validation(), failed)
        with self.assertRaises(ValueError):
            service.validate_v2(self.config, failed['report_id'], now=self.helper.now,
                                client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 1)

    def test_v2_normal_accepted_or_failed_delivery_is_not_a_legacy_validation_parent(self):
        at = NOW + timedelta(hours=1)
        self.helper.append_capture(at, headline='New normal v2 source', identity=456)
        self.helper.cycle(at)
        report = service.read_report(self.helper.directory(), self.config)
        with self.assertRaises(ValueError):
            service.validate_v2(self.config, report['report_id'], now=at + timedelta(hours=1),
                                client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_off_pin_watchlist_and_capacity_gates_prevent_new_calls(self):
        for gate in ('off', 'pins'):
            selected = self.helper.off if gate == 'off' else self.pins
            selected.side_effect = ValueError('fixture blocked')
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                self.run_validation()
            selected.side_effect = None
        with patch.object(service, 'MAX_RUNS', 1):
            self.assertEqual(self.run_validation()['status'], 'ARCHIVE_REVIEW_REQUIRED')
        atomic_state(service.catalyst_paths(self.config)[0] / 'control.json',
            {'schema_version': catalyst.VERSION, 'enabled': True, 'symbols': ['SPY']})
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_parent_tampering_during_model_delivery_fails_closed(self):
        def tamper(envelope):
            path = self.parent / 'completion-clock.json'
            path.chmod(0o600)
            path.write_bytes(canonical_json_bytes({'completed_at': catalyst.stamp(NOW + timedelta(seconds=1))}))
        self.helper.http.mutate = tamper
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertFalse((self.child() / 'report.json').exists())

    def test_child_packet_parent_hash_and_validation_identity_are_replayed_not_trusted(self):
        self.run_validation()
        path = self.child() / 'run-intent.json'
        value = json.loads(path.read_bytes())
        value['validation']['parent_report_sha256'] = '0' * 64
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            service.read_report(self.child(), self.config)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_incomplete_validation_attempt_must_replay_parent_link_during_verify(self):
        with patch.object(service, 'atomic_state', side_effect=OSError('before role delivery')):
            with self.assertRaises(OSError):
                self.run_validation()
        path = self.child() / 'run-intent.json'
        value = json.loads(path.read_bytes())
        value['validation']['parent_report_sha256'] = '0' * 64
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            service.verify(self.config)
        self.assertEqual(self.helper.http.calls, [])

    def test_worker_does_not_automatically_revalidate_same_legacy_failure(self):
        self.helper.append_capture(self.helper.now, same_news=True)
        self.assertEqual(self.helper.cycle(self.helper.now), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_cli_explicit_source_parameter_has_no_force_or_reset_flags(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_v2', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-v2', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        for extra in ('--force', '--reset'):
            with self.subTest(extra=extra), patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
                service.main(['validate-v2', '--config', '/private/tmp/config.json',
                              '--source-report-id', self.source_id, extra])


if __name__ == '__main__':
    unittest.main()
