"""Offline governed-worker integration over real retained catalyst fixtures.

ModelDockClient is real; its HTTP transport is an authored response fixture.
No broker, news service, inference server, credentials, or live runtime is used.
"""
from datetime import timedelta
from io import StringIO, BytesIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_synthesis_service as service
from blackpod_build_week import sentry_synthesis_transport as transport
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient, HttpResponse
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
        self.assertEqual(service.BACKGROUND_TRANSPORT_VERSION, service.MODEL_TRANSPORT_VERSION)
        self.assertEqual([item['max_tokens'] for item in requests], [2500, 2500])
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
        self.assertEqual(validation['transport_schema_version'], service.VALIDATION_TRANSPORT_VERSION)
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


class ExplicitDeadlineValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitV2ValidationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        old_http = self.helper.http
        def timeout_504(**kwargs):
            old_http.calls.append(kwargs)
            return HttpResponse(504, {'Content-Length': '2'}, b'{}')
        old_http.request = timeout_504
        self.parent_report = self.fixture.run_validation()
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_HTTP_504')
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.helper.http = BoundFixtureTransport()
        self.helper.control['modeldock'] = {**self.helper.modeldock, 'timeout_seconds': 900,
                                           'delivery_grace_seconds': 30}
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        # 7 p.m. LA is deliberately outside ordinary monitoring. The named
        # manual retained-evidence scope changes neither clock nor schedule.
        self.helper.now = NOW + timedelta(hours=8)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_deadline(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, deadline=True)

    def test_named_manual_scope_outside_hours_uses_fixed_deadline_exact_packet_and_preserves_both_parents(self):
        self.assertEqual(service.due(self.helper.now, service.ledger(self.helper.runs), True)[1],
                         'OUTSIDE_MONITORING_HOURS')
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_DEADLINE_VALIDATION')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.DEADLINE_TRANSPORT_VERSION)
        self.assertEqual(result['validation']['parent_report_id'], self.source_id)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual([json.loads(call['body'])['timeout'] for call in self.helper.http.calls], [900, 900])
        intent = service.immutable_read(self.child(), 'run-intent.json')
        self.assertEqual(intent['schema_version'], 'blackpod.sentry_synthesis_validation.v3')
        self.assertEqual(intent['modeldock']['delivery_grace_seconds'], 30)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(service.verify(self.config)['attempt_count'], 3)
        self.assertTrue(all(v is False for v in result['authority'].values()))

    def test_idempotent_inspection_keeps_old_v2_deadline_and_never_resends_any_generation(self):
        first = self.run_validation()
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no resend')):
            self.assertEqual(self.run_validation(), first)
            self.assertEqual(service.recover_attempt(self.child(), self.config, self.helper.now), first)
            # Old v2 inspection replays stored 60/5 config, despite new 900/30 control.
            self.assertEqual(self.fixture.run_validation(), self.parent_report)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_manual_scope_has_separate_spacing_but_respects_disabled_control(self):
        self.assertEqual(service.due(NOW + timedelta(hours=1, minutes=59),
            service.ledger(self.helper.runs), True, manual_retained=True)[1], 'DUE')
        self.helper.control['enabled'] = False
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        self.assertEqual(self.run_validation()['status'], 'PAUSED')
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_manual_diagnostic_does_not_consume_or_share_background_daily_budget(self):
        for index in (2, 3):
            at = NOW + timedelta(hours=index)
            self.helper.append_capture(at, headline='Later independently admitted evidence ' + str(index), identity=500 + index)
            self.assertEqual(self.helper.cycle(at), 'CHALLENGED_INTERPRETATION')
        self.helper.now = NOW + timedelta(hours=8)
        self.assertEqual(self.run_validation()['status'], 'CHALLENGED_INTERPRETATION')
        self.assertTrue(self.child().exists())
        self.assertEqual(len(self.helper.http.calls), 6)

    def test_other_deadlines_do_not_enter_fixed_manual_validation(self):
        for timeout, grace in ((899, 30), (900, 29), (901, 30), (900, 31)):
            self.helper.control['modeldock'].update(timeout_seconds=timeout, delivery_grace_seconds=grace)
            atomic_state(self.helper.root / 'control.json', self.helper.control)
            with self.subTest(timeout=timeout, grace=grace), self.assertRaises(ValueError):
                self.run_validation()
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_unknown_http_status_is_not_assumed_to_be_504(self):
        receipt_path = self.parent / 'oracle/receipt.json'
        saved = json.loads(receipt_path.read_bytes())
        saved['failure_code'] = 'MODELDOCK_HTTP_STATUS'
        saved['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in saved.items() if k != 'receipt_sha256'}))
        receipt_path.chmod(0o600)
        receipt_path.write_bytes(canonical_json_bytes(saved))
        packet, intent, dock = service.load_attempt(self.parent)
        oracle, challenge = service.retained_roles(self.parent, packet, dock)
        changed = service.compose_report(packet, oracle, challenge, self.parent_report['completed_at'],
                                         validation=intent['validation'])
        path = self.parent / 'report.json'
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(changed))
        self.source_id = changed['report_id']
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(self.helper.http.calls, [])

    def test_v1_or_v3_parent_cannot_create_an_unbounded_validation_chain(self):
        with self.assertRaises(ValueError):
            service.validate_deadline(self.config, self.fixture.source_id, now=self.helper.now,
                                       client_factory=self.helper.factory)
        report = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_deadline(self.config, report['report_id'], now=self.helper.now,
                                       client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_interrupted_oracle_recovery_is_provider_free_and_never_resends(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_interrupted_challenge_remains_draft_only_without_resend(self):
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
        self.assertIsNone(result['challenge'])
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_oldest_ancestor_tamper_during_generation_blocks_success(self):
        def mutate(envelope):
            original = self.fixture.parent / 'completion-clock.json'
            original.chmod(0o600)
            original.write_bytes(canonical_json_bytes({'completed_at': catalyst.stamp(NOW + timedelta(seconds=1))}))
        self.helper.http.mutate = mutate
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertFalse((self.child() / 'report.json').exists())

    def test_private_scope_missing_from_intent_cannot_replay(self):
        self.run_validation()
        path = self.child() / 'run-intent.json'
        intent = json.loads(path.read_bytes())
        del intent['validation']['scope']
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(intent))
        with self.assertRaises(ValueError):
            service.verify(self.config)

    def test_idle_health_stays_five_minutes_but_pending_delivery_has_bounded_lease(self):
        self.run_validation()
        heartbeat = self.helper.now
        atomic_state(self.helper.root / 'health.json', {'heartbeat_at': catalyst.stamp(heartbeat)})
        idle = service.status(self.config, heartbeat + timedelta(seconds=400))
        self.assertFalse(idle['operational']['worker_healthy'])
        self.assertEqual(idle['operational']['worker_health_bound_seconds'], 300)

    def test_pending_long_delivery_health_does_not_imply_token_progress_or_extend_forever(self):
        with patch.object(service, 'atomic_state', side_effect=OSError('before display state')):
            with self.assertRaises(OSError):
                self.run_validation()
        reserved = self.helper.now
        atomic_state(self.helper.root / 'state.json', {'schema_version': service.VERSION,
            'last_run': self.child().name, 'last_result': 'ATTEMPT_STARTED'})
        atomic_state(self.helper.root / 'health.json', {'heartbeat_at': catalyst.stamp(reserved)})
        during = service.status(self.config, reserved + timedelta(seconds=600))
        self.assertTrue(during['operational']['awaiting_retained_completion'])
        self.assertTrue(during['operational']['worker_healthy'])
        self.assertEqual(during['operational']['worker_health_bound_seconds'], 1890)
        after = service.status(self.config, reserved + timedelta(seconds=1891))
        self.assertFalse(after['operational']['awaiting_retained_completion'])
        self.assertFalse(after['operational']['worker_healthy'])
        self.assertEqual(after['operational']['worker_health_bound_seconds'], 300)

    def test_configure_cli_records_explicit_grace_and_manual_command_has_no_force_flags(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['configure', '--config', '/private/tmp/config.json', '--enabled',
                '--modeldock-base-url', 'http://127.0.0.1:8000', '--modeldock-timeout-seconds', '900',
                '--modeldock-delivery-grace-seconds', '30']), 0)
        selected = service.control(service.read_state(self.helper.root / 'control.json'))
        self.assertEqual(selected['modeldock']['timeout_seconds'], 900)
        self.assertEqual(selected['modeldock']['delivery_grace_seconds'], 30)
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_deadline', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-deadline', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)


class HistoricalMissingRoleReplayTests(unittest.TestCase):
    def ordinary_capsule(self):
        helper = SentrySynthesisServiceTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        packet = service.current_packet(helper.config, as_of=NOW)
        directory = helper.runs / packet['evidence_signature']
        service.write_json_once(directory, 'packet.json', packet)
        service.write_json_once(directory, 'run-intent.json', {'schema_version': service.VERSION,
            'context_id': packet['context_id'], 'packet_sha256': sha256_bytes(canonical_json_bytes(packet)),
            'evidence_signature': packet['evidence_signature'], 'reserved_at': catalyst.stamp(NOW),
            'modeldock': helper.modeldock})
        return helper, directory, packet, service.configuration(helper.modeldock)

    def publish(self, directory, packet, oracle, challenge):
        report = service.compose_report(packet, oracle, challenge, catalyst.stamp(NOW))
        service.write_json_once(directory, 'completion-clock.json', {'completed_at': catalyst.stamp(NOW)})
        service.write_json_once(directory, 'report.json', report)
        return report

    def test_v1_v2_uncertain_report_without_role_intents_retains_original_not_reserved_identity(self):
        for version in (transport.LEGACY_VERSION, service.VALIDATION_TRANSPORT_VERSION):
            with self.subTest(version=version):
                helper, directory, packet, dock = self.ordinary_capsule()
                oracle = transport.read_role('oracle', packet, directory / 'oracle', dock, version=version)
                challenge = {'status': 'UNCERTAIN', 'response': None, 'failure_code': 'ORACLE_NOT_ACCEPTED'}
                expected = self.publish(directory, packet, oracle, challenge)
                before = service.capsule_hashes(directory)
                with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('read cannot infer')):
                    self.assertEqual(service.read_report(directory, helper.config), expected)
                    self.assertEqual(service.verify(helper.config)['incomplete_attempt_count'], 0)
                self.assertEqual(service.capsule_hashes(directory), before)
                self.assertEqual(helper.http.calls, [])

    def test_v2_draft_only_normal_report_keeps_missing_challenge_request_identity(self):
        helper, directory, packet, dock = self.ordinary_capsule()
        oracle = transport.generate_role('oracle', packet, directory / 'oracle', dock,
            off_check=lambda: None, verify_source=lambda: service.verify_packet(packet, helper.config),
            client_factory=helper.factory, now=lambda: NOW, version=service.VALIDATION_TRANSPORT_VERSION)
        self.assertEqual(oracle['status'], 'ACCEPTED')
        missing = transport.read_role('challenge', packet, directory / 'challenge', dock, draft=oracle['response'],
            version=service.VALIDATION_TRANSPORT_VERSION)
        expected = self.publish(directory, packet, oracle, missing)
        before = service.capsule_hashes(directory)
        self.assertEqual(service.read_report(directory, helper.config), expected)
        self.assertEqual(expected['status'], 'DRAFT_ONLY')
        self.assertEqual(service.capsule_hashes(directory), before)
        self.assertEqual(len(helper.http.calls), 1)


class ExplicitErrorDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitDeadlineValidationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        old = self.helper.http
        def error_500(**kwargs):
            old.calls.append(kwargs)
            return HttpResponse(500, {'Content-Length': '2'}, b'{}')
        old.request = error_500
        self.parent_report = self.fixture.run_validation()
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_HTTP_500')
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 3)
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(hours=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_error(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, error_diagnostic=True)

    def test_fourth_manual_child_preserves_three_failures_without_consuming_background_budget(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_ERROR_CODE_DIAGNOSTIC')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.ERROR_TRANSPORT_VERSION)
        self.assertEqual(result['validation']['parent_report_id'], self.source_id)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(self.helper.http.calls), 2)
        entries = service.ledger(self.helper.runs)
        self.assertEqual(len(entries), 4)
        self.assertEqual(service.due(self.helper.now + timedelta(hours=1), entries, True, manual_retained=True)[1],
                         'DUE')
        status = service.status(self.config, self.helper.now)
        self.assertEqual(status['operational']['background_attempt_count_today'], 1)
        self.assertEqual(status['operational']['manual_attempt_count_today'], 3)
        self.assertEqual(service.verify(self.config)['report_dispositions'],
                         {'FAILED': 3, 'CHALLENGED_INTERPRETATION': 1})
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(self.fixture.run_validation(), self.parent_report)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_safe_correlated_error_observation_is_read_without_a_second_generation(self):
        from unittest.mock import Mock
        calls = []
        def opened(request, timeout):
            calls.append(request)
            identity = json.loads(request.data)['metadata']['blackpod_correlation']['request_id']
            raw = canonical_json_bytes({'error': {'code': 'INFERENCE_FAILURE', 'request_id': identity,
                'message': 'PRIVATE_MODEL_ERROR', 'details': [{'path': '/PRIVATE_MODEL_PATH'}]}})
            raise HTTPError(request.full_url, 500, 'private', {'Content-Length': str(len(raw))}, BytesIO(raw))
        with patch('blackpod_build_week.modeldock_client.urllib.request.build_opener', return_value=Mock(open=opened)):
            result = self.run_validation(client_factory=lambda config: ModelDockClient(config,
                transport=transport._NamedSentryTransport(), now=lambda: self.helper.now))
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['provenance']['oracle']['failure_code'], 'MODELDOCK_HTTP_500')
        packet, _, config = service.load_attempt(self.child())
        with patch.object(ModelDockClient, 'generate_text', side_effect=AssertionError('no replay generation')):
            error = transport.read_error_observation('oracle', packet, self.child() / 'oracle', config)
            self.assertEqual(error['code'], 'INFERENCE_FAILURE')
            self.assertEqual(error['request_id'], result['provenance']['oracle']['request_id'])
            self.assertEqual(self.run_validation(), result)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('PRIVATE_MODEL', json.dumps(error))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_named_error_diagnostic_is_not_subject_to_background_hourly_spacing(self):
        result = service.due(self.helper.now - timedelta(seconds=1), service.ledger(self.helper.runs),
                             True, manual_retained=True)
        self.assertEqual(result[1], 'DUE')
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_interrupted_fourth_attempt_is_never_resent_or_reset(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        result = self.run_validation()
        self.assertEqual(result['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(len(service.ledger(self.helper.runs)), 4)
        with self.assertRaises(ValueError):
            service.validate_error(self.config, result['report_id'], now=self.helper.now,
                                   client_factory=self.helper.factory)

    def test_only_terminal_v3_http500_is_eligible_not_unknown_status_or_earlier_parent(self):
        with self.assertRaises(ValueError):
            service.validate_error(self.config, self.fixture.source_id, now=self.helper.now,
                                   client_factory=self.helper.factory)
        receipt_path = self.parent / 'oracle/receipt.json'
        receipt = json.loads(receipt_path.read_bytes())
        receipt['failure_code'] = 'MODELDOCK_HTTP_STATUS'
        receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in receipt.items() if k != 'receipt_sha256'}))
        receipt_path.chmod(0o600)
        receipt_path.write_bytes(canonical_json_bytes(receipt))
        packet, intent, dock = service.load_attempt(self.parent)
        oracle, challenge = service.retained_roles(self.parent, packet, dock)
        report = service.compose_report(packet, oracle, challenge, self.parent_report['completed_at'],
                                        validation=intent['validation'])
        path = self.parent / 'report.json'
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(report))
        self.source_id = report['report_id']
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(self.helper.http.calls, [])

    def test_accepted_v4_cannot_be_used_to_create_another_error_diagnostic(self):
        result = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_error(self.config, result['report_id'], now=self.helper.now + timedelta(hours=1),
                                   client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_off_or_pin_failure_prevents_fourth_reservation(self):
        for gate in (self.helper.off, self.fixture.fixture.pins):
            gate.side_effect = ValueError('blocked')
            with self.assertRaises(ValueError):
                self.run_validation()
            gate.side_effect = None
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_cli_error_diagnostic_is_explicit_and_does_not_add_reset_flags(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_error', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-error', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)


class SeparateManualBudgetTests(unittest.TestCase):
    def row(self, at, *, manual=False):
        return (None, None, {'schema_version': service.RUNTIME_VALIDATION_VERSION if manual else service.VERSION,
                             'reserved_at': catalyst.stamp(at)}, None)

    def test_manual_admission_bypasses_only_monitoring_hourly_and_daily_caps(self):
        entries = [self.row(NOW - timedelta(hours=n)) for n in (1, 2, 3, 4)]
        entries += [self.row(NOW - timedelta(seconds=1), manual=True)]
        self.assertEqual(service.due(NOW, entries, True)[1], 'DAILY_BUDGET_EXHAUSTED')
        self.assertEqual(service.due(NOW, entries, True, manual_retained=True)[1], 'DUE')
        self.assertEqual(service.due(NOW, entries, False, manual_retained=True)[1], 'PAUSED')
        entries.append(self.row(NOW + timedelta(seconds=1), manual=True))
        self.assertEqual(service.due(NOW, entries, True, manual_retained=True)[1], 'CLOCK_BLOCKED')
        self.assertEqual(service.due(NOW, entries, True)[1], 'CLOCK_BLOCKED')

    def test_recent_manual_reservations_do_not_consume_background_spacing_or_daily_budget(self):
        entries = [self.row(NOW - timedelta(hours=2))]
        entries += [self.row(NOW - timedelta(seconds=n), manual=True) for n in (1, 2, 3, 4, 5)]
        self.assertEqual(service.due(NOW, entries, True)[1], 'DUE')
        self.assertEqual(service.due(NOW.replace(hour=3), [], True)[1], 'OUTSIDE_MONITORING_HOURS')
        self.assertEqual(service.due(NOW.replace(hour=3), [], True, manual_retained=True)[1], 'DUE')
        entries.append(self.row(NOW - timedelta(minutes=30)))
        self.assertEqual(service.due(NOW, entries, True)[1], 'WAITING_FOR_NEXT_SLOT')


class ExplicitRuntimeDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitErrorDiagnosticTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        from unittest.mock import Mock
        def opened(request, timeout):
            identity = json.loads(request.data)['metadata']['blackpod_correlation']['request_id']
            raw = canonical_json_bytes({'error': {'code': 'STRUCTURED_OUTPUT_INVALID', 'request_id': identity,
                'message': 'private fixture diagnostics', 'details': None}})
            raise HTTPError(request.full_url, 500, 'private', {'Content-Length': str(len(raw))}, BytesIO(raw))
        with patch('blackpod_build_week.modeldock_client.urllib.request.build_opener', return_value=Mock(open=opened)):
            self.parent_report = self.fixture.run_validation(client_factory=lambda config: ModelDockClient(config,
                transport=transport._NamedSentryTransport(), now=lambda: self.helper.now))
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 4)
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(seconds=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_runtime(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, runtime_diagnostic=True)

    def test_v5_is_one_separate_manual_child_with_exact_retained_evidence_and_no_parent_changes(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_RUNTIME_DIAGNOSTIC')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.RUNTIME_TRANSPORT_VERSION)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(len(self.helper.http.calls), 2)
        counts = service.status(self.config, self.helper.now)['operational']
        self.assertEqual(counts['background_attempt_count_today'], 1)
        self.assertEqual(counts['manual_attempt_count_today'], 4)
        self.assertEqual(service.verify(self.config)['attempt_count'], 5)
        self.assertTrue(all(v is False for v in result['authority'].values()))

    def test_missing_or_wrong_safe_error_code_cannot_authorize_runtime_diagnostic(self):
        path = self.parent / 'oracle/http-error.json'
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.run_validation()
        value = json.loads(raw)
        value['code'] = 'INFERENCE_FAILURE'
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in value.items() if k != 'observation_sha256'}))
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(self.helper.http.calls, [])

    def test_mismatched_observation_request_binding_blocks_before_inference(self):
        path = self.parent / 'oracle/http-error.json'
        value = json.loads(path.read_bytes())
        value['request_id'] = 'different-request'
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in value.items() if k != 'observation_sha256'}))
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertEqual(self.helper.http.calls, [])

    def test_pause_future_clock_archive_off_and_pins_still_block_new_manual_work(self):
        self.helper.control['enabled'] = False
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        self.assertEqual(self.run_validation()['status'], 'PAUSED')
        self.helper.control['enabled'] = True
        atomic_state(self.helper.root / 'control.json', self.helper.control)
        self.assertEqual(self.run_validation(now=self.helper.now - timedelta(seconds=2))['status'], 'CLOCK_BLOCKED')
        with patch.object(service, 'MAX_RUNS', 4):
            self.assertEqual(self.run_validation()['status'], 'ARCHIVE_REVIEW_REQUIRED')
        for gate in (self.helper.off, self.fixture.fixture.fixture.pins):
            gate.side_effect = ValueError('source gate blocked')
            with self.assertRaises(ValueError):
                self.run_validation()
            gate.side_effect = None
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_runtime_diagnostic_stays_serial_and_interrupted_delivery_is_never_resent(self):
        with service.service_lock(self.helper.root), self.assertRaises(ValueError):
            self.run_validation()
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_v5_cannot_be_used_as_another_runtime_parent(self):
        result = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_runtime(self.config, result['report_id'], now=self.helper.now,
                                     client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_runtime_cli_requires_explicit_source_and_exposes_no_reset_flags(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_runtime', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-runtime', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)


class ExplicitModelSelectionValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitRuntimeDiagnosticTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        self.diagnostic = {'schema': 'modeldock.structured-validation-diagnostic.v1',
            'stage': 'RESULT_VALIDATION', 'reason': 'JSON_SYNTAX', 'schema_keyword': None,
            'generated_token_count': 2500, 'generated_token_count_source': 'native',
            'stop_reason': 'length', 'stop_reason_source': 'native'}
        from unittest.mock import Mock
        def opened(request, timeout):
            wire = json.loads(request.data)
            self.assertEqual(wire['max_tokens'], 2500)
            identity = wire['metadata']['blackpod_correlation']['request_id']
            raw = canonical_json_bytes({'error': {'code': 'STRUCTURED_OUTPUT_INVALID', 'request_id': identity,
                'message': 'private model fixture', 'details': [self.diagnostic]}})
            raise HTTPError(request.full_url, 500, 'private', {'Content-Length': str(len(raw))}, BytesIO(raw))
        with patch('blackpod_build_week.modeldock_client.urllib.request.build_opener', return_value=Mock(open=opened)):
            self.parent_report = self.fixture.run_validation(client_factory=lambda config: ModelDockClient(config,
                transport=transport._NamedSentryTransport(), now=lambda: self.helper.now))
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 5)
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_HTTP_500')
        self.observation_path = self.parent / 'oracle/http-error.json'
        self.observation_bytes = self.observation_path.read_bytes()
        self.assertEqual(json.loads(self.observation_bytes)['schema_version'], 'blackpod.sentry_http_error_observation.v2')
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(seconds=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_model(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, model_selection=True)

    def replace_observation(self, value):
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes(
            {key: item for key, item in value.items() if key != 'observation_sha256'}))
        self.observation_path.chmod(0o600)
        self.observation_path.write_bytes(canonical_json_bytes(value))

    def test_v6_retains_original_budget_evidence_and_five_ancestors_with_no_resend(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_MODEL_SELECTION_VALIDATION')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.MODEL_TRANSPORT_VERSION)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(service.validation_chain_hashes(self.child(), self.config)), 6)
        self.assertEqual(len(self.helper.http.calls), 2)
        for role in ('oracle', 'challenge'):
            intent = service.immutable_read(self.child() / role, 'intent.json')
            self.assertEqual(intent['schema_version'], service.MODEL_TRANSPORT_VERSION)
            self.assertEqual(intent['wire_request']['max_tokens'], 2500)
        modeldock = service.immutable_read(self.child(), 'run-intent.json')['modeldock']
        self.assertEqual((modeldock['timeout_seconds'], modeldock['delivery_grace_seconds']), (900, 30))
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual(service.verify(self.config)['attempt_count'], 6)
        self.assertTrue(all(item is False for item in result['authority'].values()))

    def test_model_validation_requires_exact_native_failure_not_assumed_telemetry(self):
        variants = [
            {'reason': 'VALIDATION_FAILURE'},
            {'generated_token_count': 2499},
            {'generated_token_count': 4096},
            {'generated_token_count': True},
            {'generated_token_count': None, 'generated_token_count_source': 'unavailable'},
            {'generated_token_count_source': 'inferred'},
            {'stop_reason': 'stop'},
            {'stop_reason': 'unknown', 'stop_reason_source': 'unavailable'},
            {'stop_reason_source': 'inferred'},
        ]
        for change in variants:
            with self.subTest(change=change):
                value = json.loads(self.observation_bytes)
                value['validation_diagnostic'].update(change)
                self.replace_observation(value)
                with self.assertRaises(ValueError):
                    self.run_validation()
                self.assertFalse(self.child().exists())
                self.assertEqual(self.helper.http.calls, [])
        self.observation_path.chmod(0o600)
        self.observation_path.write_bytes(self.observation_bytes)

    def test_missing_or_v1_sidecar_cannot_authorize_model_validation(self):
        self.observation_path.unlink()
        with self.assertRaises(ValueError):
            self.run_validation()
        value = json.loads(self.observation_bytes)
        value['schema_version'] = 'blackpod.sentry_http_error_observation.v1'
        value.pop('validation_diagnostic')
        self.observation_path.write_bytes(self.observation_bytes)
        self.replace_observation(value)
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_model_validation_interruption_remains_uncertain_without_resending(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_v6_and_earlier_diagnostics_cannot_be_another_model_validation_parent(self):
        for report in (self.fixture.parent_report, self.fixture.fixture.parent_report):
            with self.assertRaises(ValueError):
                service.validate_model(self.config, report['report_id'], now=self.helper.now,
                                       client_factory=self.helper.factory)
        self.assertEqual(self.helper.http.calls, [])
        result = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_model(self.config, result['report_id'], now=self.helper.now,
                                   client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_model_cli_requires_explicit_source_and_rejects_arbitrary_token_overrides(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_model', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-model', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        with patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
            service.main(['validate-model', '--config', '/private/tmp/config.json',
                          '--source-report-id', self.source_id, '--max-tokens', '4096'])


class ExplicitOutputBudgetValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitModelSelectionValidationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        from unittest.mock import Mock
        def opened(request, timeout):
            wire = json.loads(request.data)
            self.assertEqual(wire['max_tokens'], 2500)
            identity = wire['metadata']['blackpod_correlation']['request_id']
            raw = canonical_json_bytes({'error': {'code': 'STRUCTURED_OUTPUT_INVALID', 'request_id': identity,
                'message': 'private repeated syntax fixture', 'details': [self.fixture.diagnostic]}})
            raise HTTPError(request.full_url, 500, 'private', {'Content-Length': str(len(raw))}, BytesIO(raw))
        with patch('blackpod_build_week.modeldock_client.urllib.request.build_opener', return_value=Mock(open=opened)):
            self.parent_report = self.fixture.run_validation(client_factory=lambda config: ModelDockClient(config,
                transport=transport._NamedSentryTransport(), now=lambda: self.helper.now))
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 6)
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_HTTP_500')
        self.observation_path = self.parent / 'oracle/http-error.json'
        self.observation_bytes = self.observation_path.read_bytes()
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(seconds=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_output_budget(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, output_budget=True)

    def replace_observation(self, value):
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes(
            {key: item for key, item in value.items() if key != 'observation_sha256'}))
        self.observation_path.chmod(0o600)
        self.observation_path.write_bytes(canonical_json_bytes(value))

    def test_v7_is_explicit_4096_child_preserving_six_originals_and_no_resend(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_OUTPUT_BUDGET_VALIDATION')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.OUTPUT_TRANSPORT_VERSION)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(service.validation_chain_hashes(self.child(), self.config)), 7)
        for role in ('oracle', 'challenge'):
            intent = service.immutable_read(self.child() / role, 'intent.json')
            self.assertEqual(intent['schema_version'], service.OUTPUT_TRANSPORT_VERSION)
            self.assertEqual(intent['wire_request']['max_tokens'], 4096)
        modeldock = service.immutable_read(self.child(), 'run-intent.json')['modeldock']
        self.assertEqual((modeldock['timeout_seconds'], modeldock['delivery_grace_seconds']), (900, 30))
        self.assertEqual(service.read_state(self.helper.root / 'control.json'), self.helper.control)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(service.verify(self.config)['attempt_count'], 7)
        service.status(self.config, self.helper.now)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertTrue(all(item is False for item in result['authority'].values()))

    def test_output_budget_requires_exact_native_2500_length_diagnostic(self):
        variants = [
            {'reason': 'VALIDATION_FAILURE'},
            {'generated_token_count': 2499},
            {'generated_token_count': 2500.0},
            {'generated_token_count': True},
            {'generated_token_count': 4096},
            {'generated_token_count': None, 'generated_token_count_source': 'unavailable'},
            {'generated_token_count_source': 'inferred'},
            {'stop_reason': 'stop'},
            {'stop_reason': 'unknown', 'stop_reason_source': 'unavailable'},
            {'stop_reason_source': 'inferred'},
        ]
        for change in variants:
            with self.subTest(change=change):
                value = json.loads(self.observation_bytes)
                value['validation_diagnostic'].update(change)
                self.replace_observation(value)
                with self.assertRaises(ValueError):
                    self.run_validation()
                self.assertFalse(self.child().exists())
                self.assertEqual(self.helper.http.calls, [])

    def test_output_budget_rejects_missing_or_uncorrelated_diagnostic(self):
        self.observation_path.unlink()
        with self.assertRaises(ValueError):
            self.run_validation()
        self.observation_path.write_bytes(self.observation_bytes)
        value = json.loads(self.observation_bytes)
        value['request_id'] = 'unrelated-request'
        self.replace_observation(value)
        with self.assertRaises(ValueError):
            self.run_validation()
        self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_output_budget_interruption_stays_uncertain_and_never_resends(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_packet_only_output_child_is_retained_uncertain_without_generating(self):
        service.write_json_once(self.child(), 'packet.json', self.parent_report['context'])
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertEqual(self.helper.http.calls, [])

    def test_only_v6_failure_is_source_and_v7_cannot_create_another_child(self):
        for report in (self.fixture.parent_report, self.fixture.fixture.parent_report):
            with self.assertRaises(ValueError):
                service.validate_output_budget(self.config, report['report_id'], now=self.helper.now,
                                               client_factory=self.helper.factory)
        self.assertEqual(self.helper.http.calls, [])
        result = self.run_validation()
        with self.assertRaises(ValueError):
            service.validate_output_budget(self.config, result['report_id'], now=self.helper.now,
                                           client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_output_budget_cli_requires_explicit_source(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_output_budget', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-output-budget', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        with patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
            service.main(['validate-output-budget', '--config', '/private/tmp/config.json'])


class ExplicitContractValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitOutputBudgetValidationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        def host_rejection(envelope):
            value = json.loads(envelope['content'])
            value['themes'][0]['evidence_ids'] = ['not-supplied-evidence']
            envelope['content'] = json.dumps(value)
        self.helper.http = BoundFixtureTransport(mutate=host_rejection)
        self.parent_report = self.fixture.run_validation()
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 7)
        self.assertEqual(self.parent_report['status'], 'REJECTED')
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
        self.assertFalse((self.parent / 'oracle/http-error.json').exists())
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(seconds=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_contract(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, contract_validation=True)

    def test_v8_preserves_seven_originals_4096_and_exact_evidence_without_resend(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_CONTRACT_VALIDATION')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.CONTRACT_TRANSPORT_VERSION)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(service.validation_chain_hashes(self.child(), self.config)), 8)
        for role in ('oracle', 'challenge'):
            intent = service.immutable_read(self.child() / role, 'intent.json')
            self.assertEqual(intent['schema_version'], service.CONTRACT_TRANSPORT_VERSION)
            self.assertEqual(intent['wire_request']['max_tokens'], 4096)
        modeldock = service.immutable_read(self.child(), 'run-intent.json')['modeldock']
        self.assertEqual((modeldock['timeout_seconds'], modeldock['delivery_grace_seconds']), (900, 30))
        self.assertEqual(service.BACKGROUND_TRANSPORT_VERSION, service.MODEL_TRANSPORT_VERSION)
        self.assertEqual(service.read_state(self.helper.root / 'control.json'), self.helper.control)
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(service.verify(self.config)['attempt_count'], 8)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertTrue(all(item is False for item in result['authority'].values()))
        with self.assertRaises(ValueError):
            service.validate_contract(self.config, result['report_id'], now=self.helper.now,
                                      client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_only_exact_v7_host_rejection_is_eligible_not_http_or_json_failures(self):
        with self.assertRaises(ValueError):
            service.validate_contract(self.config, self.fixture.parent_report['report_id'],
                                      now=self.helper.now, client_factory=self.helper.factory)
        receipt_path = self.parent / 'oracle/receipt.json'
        original = json.loads(receipt_path.read_bytes())
        for failure, status in [('MODELDOCK_HTTP_500', 'FAILED'), ('MODELDOCK_NARRATIVE_JSON_INVALID', 'REJECTED')]:
            with self.subTest(failure=failure):
                value = {**original, 'failure_code': failure, 'status': status}
                value['receipt_sha256'] = sha256_bytes(canonical_json_bytes(
                    {key: item for key, item in value.items() if key != 'receipt_sha256'}))
                receipt_path.chmod(0o600)
                receipt_path.write_bytes(canonical_json_bytes(value))
                (self.parent / 'report.json').unlink()
                changed = service.recover_attempt(self.parent, self.config)
                with self.assertRaises(ValueError):
                    service.validate_contract(self.config, changed['report_id'], now=self.helper.now,
                                              client_factory=self.helper.factory)
        self.assertEqual(self.helper.http.calls, [])

    def test_contract_interruption_stays_uncertain_without_resending(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_packet_only_contract_child_stays_uncertain_without_generating(self):
        service.write_json_once(self.child(), 'packet.json', self.parent_report['context'])
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertEqual(self.helper.http.calls, [])

    def test_contract_cli_requires_explicit_source_and_exposes_no_force(self):
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_contract', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-contract', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        for extra in ([], ['--source-report-id', self.source_id, '--force']):
            with patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
                service.main(['validate-contract', '--config', '/private/tmp/config.json', *extra])


class ExplicitTextValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ExplicitContractValidationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper, self.config = self.fixture.helper, self.fixture.config
        def format_rejection(envelope):
            value = json.loads(envelope['content'])
            value['overview']['text'] = 'First line.\nSecond line.'
            envelope['content'] = json.dumps(value)
        self.helper.http = BoundFixtureTransport(mutate=format_rejection)
        self.parent_report = self.fixture.run_validation()
        self.parent = self.fixture.child()
        self.source_id = self.parent_report['report_id']
        self.originals = service.validation_chain_hashes(self.parent, self.config)
        self.assertEqual(len(self.originals), 8)
        self.assertEqual(self.parent_report['status'], 'REJECTED')
        self.assertEqual(self.parent_report['provenance']['oracle']['failure_code'], 'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
        self.observation_path = self.parent / 'oracle/local-contract-error.json'
        self.observation_bytes = self.observation_path.read_bytes()
        observation = json.loads(self.observation_bytes)
        self.assertEqual(observation['schema_version'], 'blackpod.sentry_local_contract_observation.v1')
        self.assertEqual(observation['reason'], 'TEXT_FORMAT')
        self.helper.http = BoundFixtureTransport()
        self.helper.now += timedelta(seconds=1)

    def run_validation(self, **changes):
        options = {'now': self.helper.now, 'client_factory': self.helper.factory}
        options.update(changes)
        return service.validate_text(self.config, self.source_id, **options)

    def child(self):
        return self.helper.runs / service.validation_directory(self.source_id, text_validation=True)

    def replace_observation(self, value):
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes(
            {key: item for key, item in value.items() if key != 'observation_sha256'}))
        self.observation_path.chmod(0o600)
        self.observation_path.write_bytes(canonical_json_bytes(value))

    def test_v9_preserves_eight_originals_same_budget_and_evidence_without_resend(self):
        result = self.run_validation()
        self.assertEqual(result['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(result['validation']['purpose'], 'EXPLICIT_TEXT_VALIDATION')
        self.assertEqual(result['validation']['scope'], 'MANUAL_RETAINED_EVIDENCE')
        self.assertEqual(result['validation']['transport_schema_version'], service.TEXT_TRANSPORT_VERSION)
        self.assertEqual((self.child() / 'packet.json').read_bytes(), (self.parent / 'packet.json').read_bytes())
        self.assertEqual(result['context']['as_of'], catalyst.stamp(NOW))
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)
        self.assertEqual(len(service.validation_chain_hashes(self.child(), self.config)), 9)
        for role in ('oracle', 'challenge'):
            intent = service.immutable_read(self.child() / role, 'intent.json')
            self.assertEqual(intent['schema_version'], service.TEXT_TRANSPORT_VERSION)
            self.assertEqual(intent['wire_request']['max_tokens'], 4096)
        modeldock = service.immutable_read(self.child(), 'run-intent.json')['modeldock']
        self.assertEqual((modeldock['timeout_seconds'], modeldock['delivery_grace_seconds']), (900, 30))
        self.assertEqual(service.BACKGROUND_TRANSPORT_VERSION, service.MODEL_TRANSPORT_VERSION)
        self.assertEqual(service.read_state(self.helper.root / 'control.json'), self.helper.control)
        self.assertEqual(self.run_validation(), result)
        self.assertEqual(service.verify(self.config)['attempt_count'], 9)
        self.assertEqual(len(self.helper.http.calls), 2)
        self.assertTrue(all(item is False for item in result['authority'].values()))
        with self.assertRaises(ValueError):
            service.validate_text(self.config, result['report_id'], now=self.helper.now,
                                  client_factory=self.helper.factory)
        self.assertEqual(len(self.helper.http.calls), 2)

    def test_text_validation_requires_original_verified_text_format_observation(self):
        self.observation_path.unlink()
        with self.assertRaises(ValueError):
            self.run_validation()
        self.observation_path.write_bytes(self.observation_bytes)
        for change in ({'reason': 'TYPE_REJECTED'}, {'request_id': 'unrelated-request'}):
            with self.subTest(change=change):
                value = json.loads(self.observation_bytes)
                value.update(change)
                self.replace_observation(value)
                with self.assertRaises(ValueError):
                    self.run_validation()
                self.assertFalse(self.child().exists())
        self.assertEqual(self.helper.http.calls, [])

    def test_text_interruption_stays_uncertain_without_resending(self):
        self.helper.http.exception = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_validation()
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.helper.http.calls), 1)
        self.assertEqual(service.validation_chain_hashes(self.parent, self.config), self.originals)

    def test_packet_only_text_child_stays_uncertain_without_generating(self):
        service.write_json_once(self.child(), 'packet.json', self.parent_report['context'])
        self.assertEqual(self.run_validation()['status'], 'UNCERTAIN')
        self.assertEqual(service.verify(self.config)['abandoned_pre_reservation_count'], 1)
        self.assertEqual(self.helper.http.calls, [])

    def test_text_cli_is_explicit_and_earlier_parent_is_ineligible(self):
        with self.assertRaises(ValueError):
            service.validate_text(self.config, self.fixture.parent_report['report_id'], now=self.helper.now,
                                  client_factory=self.helper.factory)
        self.assertEqual(self.helper.http.calls, [])
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch.object(service, 'validate_text', return_value={'status': 'FIXTURE_ONLY'}) as call, \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(['validate-text', '--config', '/private/tmp/config.json',
                                           '--source-report-id', self.source_id]), 0)
        call.assert_called_once_with(self.config, self.source_id)
        for extra in ([], ['--source-report-id', self.source_id, '--force']):
            with patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
                service.main(['validate-text', '--config', '/private/tmp/config.json', *extra])


if __name__ == '__main__':
    unittest.main()
