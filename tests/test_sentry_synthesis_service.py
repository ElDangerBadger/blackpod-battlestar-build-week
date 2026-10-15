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


if __name__ == '__main__':
    unittest.main()
