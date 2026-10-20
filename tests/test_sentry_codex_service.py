"""Authored offline Sentry policy tests; no credentials, models or brokers.

Source evidence uses the real CatalystStore; role delivery is a deterministic
in-memory fixture. Transport/provider envelope verification has its own tests.
"""
from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst as catalyst
from blackpod_build_week import sentry_synthesis_service as service
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_station import atomic_state
from test_sentry_catalyst import NOW, packet
from test_sentry_codex_contracts import WATCHLIST, array_draft
from test_sentry_synthesis_transport import challenge


class CodexSentryServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.config = {key: str(self.base / key) for key in
            ('station_root', 'runtime_root', 'experiment_root', 'historical_root', 'ui_root')}
        self.config.update(credentials_file=str(self.base / 'private/keys.yaml'),
            experiment_id='frozen-fixture', protocol_sha256='a' * 64)
        self.root, self.runs = service.paths(self.config)
        self.store = catalyst.CatalystStore(service.catalyst_paths(self.config)[1])
        self.now = NOW
        self.qualified = {'root':str(self.base / 'qualified'), 'packet_sha256':'b' * 64,
            'oracle_receipt_sha256':'c' * 64, 'challenge_receipt_sha256':'d' * 64,
            'watchlist':list(WATCHLIST)}
        self.control = {'schema_version':service.CODEX_CONTROL_VERSION, 'enabled':True,
            'modeldock':{'base_url':'http://127.0.0.1:8000', 'timeout_seconds':900,
                'profile':'default', 'provider':'codex', 'max_response_bytes':1024 * 1024,
                'delivery_grace_seconds':30},
            'analysis':{'prompt_version':'ECONOMIC_V4', 'include_article_content':False},
            'monitoring':'WEEKDAY_BOUNDED', 'qualification':deepcopy(self.qualified)}
        self.off = self.enterContext(patch.object(service, '_off'))
        self.pins = self.enterContext(patch.object(service, '_pinned_view'))
        self.proof = self.enterContext(patch('blackpod_build_week.sentry_codex_validation.verify_qualification',
            side_effect=lambda root: deepcopy(self.qualified)))
        self.enterContext(patch.object(service, 'utc_now', side_effect=lambda:self.now))
        self.enterContext(patch.object(service, 'awake_while_generating', side_effect=lambda dock:nullcontext()))
        self.calls = []
        self.results = {}
        self.during_delivery = None
        self.oracle_status = 'ACCEPTED'
        self.enterContext(patch.object(service, 'generate_role', side_effect=self.generate))
        self.enterContext(patch.object(service, 'read_role', side_effect=self.read_role))
        self.save_control()
        self.append_capture()

    def save_control(self):
        atomic_state(self.root / 'control.json', self.control)

    def append_capture(self, *, headline='Company announces an agreement', identity=123, same_news=False):
        _, blobs = packet(at=self.now, headline=headline, identity=identity)
        if same_news:
            blobs['news'] = self.original_news
        else:
            self.original_news = blobs['news']
        for kind in ('news', 'snapshots'):
            receipt = json.loads(blobs[kind + '_receipt'])
            receipt['query']['symbols'] = ','.join(WATCHLIST)
            receipt.update(body_sha256=sha256_bytes(blobs[kind]), size_bytes=len(blobs[kind]))
            blobs[kind + '_receipt'] = canonical_json_bytes(receipt)
        projection = catalyst.project(blobs['news'], blobs['snapshots'], WATCHLIST, catalyst.stamp(self.now))
        self.store.append(projection, blobs)

    def generate(self, role, context, directory, dock, *, off_check, verify_source,
                 client_factory=None, version, draft=None):
        off_check(); verify_source()
        self.assertEqual(version, service.CODEX_TRANSPORT_VERSION)
        self.assertEqual(dock.provider, 'codex')
        self.assertTrue((directory.parent / 'run-intent.json').exists())
        self.calls.append(role)
        response = array_draft(context, symbols=['SPY']) if role == 'oracle' else challenge(draft)
        if role == 'challenge':
            response['reviews'][0]['evidence_ids'] = draft['themes'][0]['evidence_ids']
        status = self.oracle_status if role == 'oracle' else 'ACCEPTED'
        result = {'status':status, 'response':response if status == 'ACCEPTED' else None,
            'failure_code':None if status == 'ACCEPTED' else 'FIXTURE_TERMINAL_FAILURE',
            'receipt_sha256':sha256_bytes(canonical_json_bytes(response)),
            'provenance':{'provider':'codex', 'model':'codex-default', 'actual_model':'fixture-model',
                'started_at':catalyst.stamp(self.now), 'observed_at':catalyst.stamp(self.now)}}
        self.results[str(directory)] = result
        if self.during_delivery is not None:
            self.during_delivery(role)
        off_check(); verify_source()
        return deepcopy(result)

    def read_role(self, role, context, directory, dock, *, version, draft=None):
        self.assertEqual(version, service.CODEX_TRANSPORT_VERSION)
        return deepcopy(self.results.get(str(directory),
            {'status':'UNCERTAIN', 'response':None, 'failure_code':'MISSING_RETAINED_FIXTURE'}))

    def cycle(self):
        return service.cycle(self.config, now=self.now)

    def directory(self):
        return service.ledger(self.runs)[-1][0]

    def test_accepted_pair_binds_new_provider_prompt_transport_and_proof(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        self.assertEqual(self.calls, ['oracle', 'challenge'])
        directory = self.directory()
        intent = service.immutable_read(directory, 'run-intent.json')
        self.assertEqual(intent['schema_version'], service.CODEX_ATTEMPT_VERSION)
        self.assertEqual(intent['transport_version'], service.CODEX_TRANSPORT_VERSION)
        self.assertEqual(intent['qualification'], self.qualified)
        self.assertEqual(intent['analysis']['prompt_version'], 'ECONOMIC_V4')
        report = service.read_report(directory, self.config)
        self.assertEqual(report['draft']['schema_version'], 'blackpod.sentry_oracle_draft.v5')
        self.assertFalse(report['review_independence']['independent_model_verified'])
        self.assertTrue(all(value is False for value in report['authority'].values()))
        self.assertGreaterEqual(self.pins.call_count, 6)

    def test_historical_controls_and_generic_configuration_cannot_enable_codex(self):
        with self.assertRaises(ValueError):
            service.configuration(self.control['modeldock'])
        for version in (service.CONTROL_VERSION, service.SCHEDULE_CONTROL_VERSION, service.ECONOMIC_CONTROL_VERSION):
            value = {'schema_version':version, 'enabled':True, 'modeldock':self.control['modeldock']}
            if version == service.ECONOMIC_CONTROL_VERSION:
                value['analysis'] = self.control['analysis']
            if version == service.SCHEDULE_CONTROL_VERSION:
                value['schedule'] = {'id':'legacy', 'slots':[catalyst.stamp(NOW)], 'window_seconds':60}
            with self.subTest(version=version), self.assertRaises(ValueError):
                service.control(value)

    def test_codex_control_rejects_provider_or_prompt_downgrade(self):
        for section, field, value in (('modeldock', 'provider', 'mlx'), ('analysis', 'prompt_version', 'ECONOMIC_V3')):
            document = deepcopy(self.control); document[section][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                service.control(document)

    def test_control_requires_explicit_monitoring_mode_and_full_watchlist_proof(self):
        for key in ('monitoring', 'qualification'):
            value = deepcopy(self.control); value.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                service.control(value)
        for symbols in (WATCHLIST[:2], WATCHLIST[:-1] + [WATCHLIST[0]], WATCHLIST + ['CRWV']):
            value = deepcopy(self.control); value['qualification']['watchlist'] = symbols
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                service.control(value)

    def test_missing_changed_or_unaccepted_proof_blocks_before_reservation(self):
        self.proof.side_effect = ValueError('authored proof failure')
        with self.assertRaises(ValueError): self.cycle()
        self.assertFalse(self.runs.exists())
        self.assertEqual(self.calls, [])
        self.proof.side_effect = lambda root:{**self.qualified, 'oracle_receipt_sha256':'e' * 64}
        with self.assertRaises(ValueError): self.cycle()
        self.assertFalse(self.runs.exists())

    def test_current_watchlist_must_match_qualified_order_and_members(self):
        self.control['qualification']['watchlist'].reverse()
        self.qualified = deepcopy(self.control['qualification'])
        self.save_control()
        with self.assertRaisesRegex(ValueError, 'watchlist'):
            self.cycle()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.runs.exists())

    def test_off_or_frozen_pin_failure_blocks_before_reservation(self):
        for guard in (self.off, self.pins):
            guard.side_effect = ValueError('authored gate failure')
            with self.subTest(guard=guard), self.assertRaises(ValueError): self.cycle()
            self.assertFalse(self.runs.exists())
            self.assertEqual(self.calls, [])
            guard.side_effect = None

    def test_changed_frozen_pin_during_oracle_blocks_challenge_and_success(self):
        self.during_delivery = lambda role:setattr(self.pins, 'side_effect', ValueError('changed pin'))
        self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        self.assertEqual(self.calls, ['oracle'])
        self.assertFalse((self.directory() / 'report.json').exists())

    def test_changed_proof_during_oracle_blocks_challenge_and_success(self):
        self.during_delivery = lambda role:setattr(self.proof, 'side_effect', ValueError('changed proof'))
        self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        self.assertEqual(self.calls, ['oracle'])
        self.assertFalse((self.directory() / 'report.json').exists())

    def test_pausing_control_during_oracle_blocks_challenge(self):
        def pause(role):
            self.control['enabled'] = False
            self.save_control()
        self.during_delivery = pause
        self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        self.assertEqual(self.calls, ['oracle'])

    def test_changed_off_gate_during_challenge_cannot_publish_success(self):
        def change(role):
            if role == 'challenge': self.off.side_effect = ValueError('OFF gate changed')
        self.during_delivery = change
        self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        self.assertEqual(self.calls, ['oracle', 'challenge'])
        self.assertFalse((self.directory() / 'report.json').exists())

    def test_terminal_oracle_failure_preserved_without_challenge_or_resend(self):
        self.oracle_status = 'FAILED'
        self.assertEqual(self.cycle(), 'FAILED')
        self.assertEqual(self.calls, ['oracle'])
        self.now += timedelta(hours=1)
        self.append_capture(same_news=True)
        self.assertEqual(self.cycle(), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(self.calls, ['oracle'])

    def test_replay_recovery_and_verify_do_not_generate_or_rewrite(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        directory = self.directory()
        original = (directory / 'report.json').read_bytes()
        with patch.object(service, 'generate_role', side_effect=AssertionError('no generation')):
            self.assertEqual(service.verify(self.config)['report_count'], 1)
            self.assertEqual(service.recover_attempt(directory, self.config)['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual((directory / 'report.json').read_bytes(), original)
        self.assertEqual(self.calls, ['oracle', 'challenge'])

    def test_interrupted_reserved_oracle_is_not_resent_by_recovery_or_later_cycle(self):
        with patch.object(service, 'generate_role', side_effect=RuntimeError('authored delivery interruption')):
            self.assertEqual(self.cycle(), 'SOURCE_OR_OFF_BLOCKED')
        directory = self.directory()
        with patch.object(service, 'generate_role', side_effect=AssertionError('no resends')):
            self.assertEqual(service.recover_attempt(directory, self.config)['status'], 'UNCERTAIN')
            self.now += timedelta(hours=1)
            self.append_capture(same_news=True)
            self.assertEqual(self.cycle(), 'NO_NEW_HEADLINE_EVIDENCE')
        self.assertEqual(self.calls, [])

    def test_status_reads_proof_and_actual_retained_report_without_generation(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        with patch.object(service, 'generate_role', side_effect=AssertionError('read-only status')):
            status = service.status(self.config, now=self.now)
        self.assertEqual(status['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(status['auto_trading'], 'OFF')
        self.assertEqual(status['operational']['provider_policy']['provider'], 'codex')
        self.assertEqual(status['operational']['provider_policy']['monitoring'], 'WEEKDAY_BOUNDED')
        self.assertIn('intake_quality', status)
        self.assertEqual(status['operational']['background_attempt_count_today'], 1)
        self.assertEqual(status['operational']['manual_attempt_count_today'], 0)

    def test_status_cannot_claim_off_or_publish_report_when_proof_is_unverifiable(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        self.proof.side_effect = ValueError('proof cannot replay')
        status = service.status(self.config, now=self.now)
        self.assertEqual(status['status'], 'UNAVAILABLE')
        self.assertEqual(status['auto_trading'], 'UNVERIFIED')
        self.assertIsNone(status['report'])

    def test_deleted_display_state_does_not_reset_hourly_budget(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        (self.root / 'state.json').unlink()
        self.now += timedelta(minutes=30)
        self.append_capture(headline='A different headline', identity=124)
        self.assertEqual(self.cycle(), 'WAITING_FOR_NEXT_SLOT')
        self.assertEqual(self.calls, ['oracle', 'challenge'])

    def test_codex_and_legacy_reservations_share_four_per_day_admission(self):
        entries = [(None, None, {'schema_version':version, 'reserved_at':catalyst.stamp(NOW - timedelta(hours=i + 1))}, None)
            for i, version in enumerate((service.CODEX_ATTEMPT_VERSION, service.ECONOMIC_ATTEMPT_VERSION,
                service.SCHEDULE_ATTEMPT_VERSION, service.VERSION))]
        self.assertEqual(service.due(NOW, entries, True), (False, 'DAILY_BUDGET_EXHAUSTED'))

    def test_finite_schedule_reservation_is_once_without_weekday_fallback(self):
        self.control.update(monitoring='FINITE_SCHEDULE', schedule={'id':'codex-test',
            'slots':[catalyst.stamp(NOW)], 'window_seconds':60})
        self.save_control()
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        self.assertIn('schedule', service.immutable_read(self.directory(), 'run-intent.json'))
        (self.root / 'state.json').unlink()
        self.now += timedelta(hours=1)
        self.assertEqual(self.cycle(), 'SCHEDULE_FINISHED')
        self.assertEqual(self.calls, ['oracle', 'challenge'])

    def test_tampered_codex_intent_transport_binding_cannot_replay(self):
        self.assertEqual(self.cycle(), 'CHALLENGED_INTERPRETATION')
        directory = self.directory(); path = directory / 'run-intent.json'
        document = json.loads(path.read_bytes()); document['transport_version'] = 'blackpod.sentry_synthesis_transport.v16'
        path.chmod(0o600)  # Corrupt this test's disposable evidence, never real history.
        path.write_bytes(canonical_json_bytes(document))
        with self.assertRaisesRegex(ValueError, 'versioned qualified policy'):
            service.load_attempt(directory)

    def test_cli_rejects_implicit_recurring_codex_and_legacy_downgrades(self):
        common = ['configure', '--config', str(self.base / 'config.json'), '--modeldock-provider', 'codex',
            '--economic-prompt', '--economic-prompt-version', 'ECONOMIC_V4',
            '--codex-validation-root', self.qualified['root']]
        for arguments in (common, common + ['--weekday-monitoring', '--schedule', '/private/tmp/schedule.json'],
                ['configure', '--config', '/private/tmp/config.json', '--weekday-monitoring']):
            with self.subTest(args=arguments), patch('sys.stderr', new_callable=StringIO), self.assertRaises(SystemExit):
                service.main(arguments)

    def test_cli_configures_only_after_provider_free_qualification_and_pins(self):
        arguments = ['configure', '--config', str(self.base / 'config.json'), '--modeldock-provider', 'codex',
            '--modeldock-base-url', 'http://127.0.0.1:8000', '--modeldock-timeout-seconds', '900',
            '--economic-prompt', '--economic-prompt-version', 'ECONOMIC_V4',
            '--codex-validation-root', self.qualified['root'], '--weekday-monitoring', '--enabled']
        with patch('blackpod_build_week.shadow_station.load_config', return_value=self.config), \
                patch('sys.stdout', new_callable=StringIO):
            self.assertEqual(service.main(arguments), 0)
        saved = service.control(service.read_state(self.root / 'control.json'))
        self.assertEqual(saved['schema_version'], service.CODEX_CONTROL_VERSION)
        self.assertEqual(saved['monitoring'], 'WEEKDAY_BOUNDED')
        self.assertEqual(saved['qualification'], self.qualified)
        self.assertTrue(self.pins.called)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
