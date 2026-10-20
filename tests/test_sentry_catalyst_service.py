"""Worker/HTTP integration with authored provider fixtures and no live calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst_service as service
from blackpod_build_week import sentry_catalyst_presentation as presentation
from blackpod_build_week import shadow_station
from blackpod_build_week.sentry_catalyst import (VERSION, CONSOLIDATED_VERSION,
    WINDOW_CONTROL_VERSION, CatalystStore, stamp, control)
from blackpod_build_week.sentry_catalyst_capture import CatalystCaptureError
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.shadow_station import atomic_state, read_state
from test_sentry_catalyst import NOW, WATCH, packet
from test_shadow_station import _LocalHTTPMixin


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.config = {key: str(root / key) for key in ('station_root','runtime_root','experiment_root','historical_root','ui_root','credentials_file')}
        # Credentials may not share a directory with station storage.
        self.config['credentials_file'] = str(root / 'private/keys.yaml')
        self.config['credential_format'] = 'GALACTICA_YAML'
        self.root, self.store = service.paths(self.config)
        atomic_state(self.root / 'control.json', {'schema_version': CONSOLIDATED_VERSION, 'enabled': True, 'symbols': WATCH, 'feed': 'sip'})
        self.off = self.enterContext(patch.object(service, '_off'))
        self.enterContext(patch.object(service, 'utc_now', return_value=NOW))
        self.enterContext(patch.object(service, '_read_regular', return_value=b'not-a-real-key'))
        self.enterContext(patch.object(service, 'parse_credentials', return_value=PaperCredentials('fixture-key', 'fixture-secret')))
        self.projection, self.blobs = packet(feed='sip')
        self.calls = []

    def getter(self, kind, query, credentials):
        self.calls.append((kind, query))
        # An interrupted attempt is durable before the first provider call.
        state = read_state(self.root / 'state.json')
        self.assertEqual(state['status'], 'ATTEMPT_STARTED')
        self.assertEqual(state['attempts_today'], 1)
        return self.blobs[kind], self.blobs[kind + '_receipt']

    def test_complete_cycle_and_restart_never_duplicate_gets(self):
        self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter), 'CAPTURED')
        self.assertEqual([r[0] for r in self.calls], ['news','snapshots'])
        self.assertEqual(CatalystStore(self.store).verify()['capture_count'], 1)
        self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter), 'WAITING_FOR_NEXT_SLOT')
        self.assertEqual(len(self.calls), 2)
        self.assertGreaterEqual(self.off.call_count, 3)

    def test_outside_hours_and_disabled_never_read_credentials_or_call_provider(self):
        with patch.object(service, 'parse_credentials') as credentials:
            self.assertEqual(service.cycle(self.config, now=NOW.replace(hour=3), getter=self.getter), 'OUTSIDE_MONITORING_HOURS')
            atomic_state(self.root / 'control.json', {'schema_version': CONSOLIDATED_VERSION, 'enabled': False, 'symbols': WATCH, 'feed': 'sip'})
            self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter), 'PAUSED')
            credentials.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_on_gate_blocks_before_credentials_and_get(self):
        self.off.side_effect = ValueError('private-path')
        with patch.object(service, 'parse_credentials') as credentials, self.assertRaises(ValueError):
            service.cycle(self.config, now=NOW, getter=self.getter)
        credentials.assert_not_called()
        self.assertEqual(self.calls, [])

    def test_second_request_failure_preserves_first_response_without_alerts(self):
        def fail_second(kind, query, credentials):
            if kind == 'snapshots': raise CatalystCaptureError('HTTP_ERROR', 403)
            return self.getter(kind, query, credentials)
        self.assertEqual(service.cycle(self.config, now=NOW, getter=fail_second), 'HTTP_ERROR')
        verified = CatalystStore(self.store).verify()
        self.assertEqual(verified['capture_count'], 0)
        self.assertEqual(verified['orphan_evidence_count'], 2)
        self.assertEqual(service.cycle(self.config, now=NOW+timedelta(minutes=6), getter=self.getter), 'COOLDOWN')
        self.assertNotIn('private', json.dumps(read_state(self.root / 'state.json')))

    def test_off_postflight_failure_cannot_publish_capture(self):
        self.off.side_effect = [None, None, ValueError('secret')]
        self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter), 'VERIFICATION_OR_CAPTURE_BLOCKED')
        self.assertEqual(CatalystStore(self.store).verify()['capture_count'], 0)

    def test_capacity_gate_blocks_before_reading_keys_or_gets(self):
        CatalystStore(self.store).append(self.projection, self.blobs)
        with patch.object(CatalystStore, 'verify', return_value={'capture_count':4096,'size_bytes':10}), patch.object(service,'parse_credentials') as keys:
            self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter),'VERIFICATION_OR_CAPTURE_BLOCKED')
            keys.assert_not_called()
        self.assertEqual(self.calls,[])

    def test_interrupted_attempt_is_counted_and_never_immediately_retried(self):
        def interrupted(*args):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            service.cycle(self.config, now=NOW, getter=interrupted)
        self.assertEqual(read_state(self.root/'state.json')['attempts_today'],1)
        self.assertEqual(service.cycle(self.config, now=NOW+timedelta(seconds=30),getter=self.getter),'WAITING_FOR_NEXT_SLOT')
        self.assertEqual(self.calls,[])

    def test_corrupt_store_blocks_before_providers(self):
        CatalystStore(self.store).append(self.projection, self.blobs)
        path = self.store / 'entries/00000001.json'
        path.chmod(0o600); path.write_bytes(b'{}')
        self.assertEqual(service.cycle(self.config, now=NOW, getter=self.getter), 'VERIFICATION_OR_CAPTURE_BLOCKED')
        self.assertEqual(self.calls, [])

    def test_status_distinguishes_worker_health_evidence_age_and_off(self):
        service.cycle(self.config, now=NOW, getter=self.getter)
        self.assertEqual(service.status(self.config, NOW)['status'], 'WORKER_STALE_OR_STOPPED')
        atomic_state(self.root / 'health.json', {'schema_version': VERSION, 'heartbeat_at': stamp(NOW)})
        result = service.status(self.config, NOW)
        self.assertTrue(result['collector']['worker_healthy'])
        self.assertEqual(result['capture']['status'], 'FRESH')
        self.assertEqual(service.status(self.config, NOW+timedelta(hours=1))['capture']['status'], 'STALE')
        self.off.side_effect = ValueError('private')
        result = service.status(self.config, NOW)
        self.assertEqual(result['auto_trading'], 'UNVERIFIED')
        self.assertIsNone(result['capture'])

    def window_control(self):
        return {'schema_version': WINDOW_CONTROL_VERSION, 'enabled': True,
                'symbols': WATCH, 'feed': 'delayed_sip', 'monitoring_window': {
                    'start_at': '2026-10-17T23:00:00Z', 'end_at': '2026-10-19T13:30:00Z',
                    'poll_seconds': 600}}

    def test_weekend_window_collects_with_original_off_and_attempt_gates(self):
        value = self.window_control()
        atomic_state(self.root / 'control.json', value)
        saturday = datetime(2026, 10, 17, 23, tzinfo=timezone.utc)
        receipt = {'status': 'CAPTURED', 'captured_at': stamp(saturday)}
        with patch.object(service, 'collect', return_value=receipt) as collect:
            self.assertEqual(service.cycle(self.config, now=saturday), 'CAPTURED')
            self.assertEqual(service.cycle(self.config, now=saturday+timedelta(seconds=599)), 'WAITING_FOR_NEXT_SLOT')
        collect.assert_called_once_with(self.config, WATCH, feed='delayed_sip', getter=service.market_get)
        self.assertEqual(read_state(self.root / 'state.json')['attempts_today'], 1)
        self.assertGreater(self.off.call_count, 0)
        self.off.side_effect = ValueError('off unverified')
        with patch.object(service, 'collect') as collect, self.assertRaises(ValueError):
            service.cycle(self.config, now=saturday+timedelta(seconds=600))
        collect.assert_not_called()

    def test_window_expiry_and_not_yet_started_never_read_keys_or_fall_back(self):
        atomic_state(self.root / 'control.json', self.window_control())
        with patch.object(service, 'parse_credentials') as keys, patch.object(service, 'collect') as collect:
            self.assertEqual(service.cycle(self.config, now=datetime(2026,10,17,22,tzinfo=timezone.utc)), 'BEFORE_MONITORING_WINDOW')
            # Monday at normal weekday monitoring hours must still stop exactly at expiry.
            self.assertEqual(service.cycle(self.config, now=datetime(2026,10,19,13,30,tzinfo=timezone.utc)), 'MONITORING_WINDOW_ENDED')
            keys.assert_not_called()
            collect.assert_not_called()
        self.assertFalse((self.root / 'state.json').exists())

    def test_window_preserves_budget_cooldown_backward_clock_and_day_rollover(self):
        sunday = datetime(2026,10,18,12,tzinfo=timezone.utc)
        window = self.window_control()['monitoring_window']
        state = {'attempt_day': '2026-10-18', 'attempts_today': 144,
                 'last_attempt_at': stamp(sunday-timedelta(minutes=10))}
        self.assertEqual(service.due(sunday,state,True,window)[1], 'DAILY_BUDGET_EXHAUSTED')
        state['attempts_today'] = 143
        state['blocked_until'] = stamp(sunday+timedelta(minutes=15))
        self.assertEqual(service.due(sunday,state,True,window)[1], 'COOLDOWN')
        state.pop('blocked_until')
        self.assertEqual(service.due(sunday-timedelta(minutes=11),state,True,window)[1], 'CLOCK_BLOCKED')
        monday = datetime(2026,10,19,12,tzinfo=timezone.utc)
        self.assertTrue(service.due(monday,state,True,window)[0])
        self.assertEqual(service.due(monday,state,False,window)[1], 'PAUSED')

    def test_window_control_rejects_unbounded_invalid_or_fast_collection(self):
        value = self.window_control()
        self.assertEqual(control(value), value)
        changes = [{'end_at': '2026-10-21T13:30:00Z'}, {'end_at': value['monitoring_window']['start_at']},
                   {'poll_seconds': 300}, {'poll_seconds': True}, {'poll_seconds': 3601},
                   {'start_at': '2026-10-17T23:00:00'}]
        for change in changes:
            invalid = deepcopy(value)
            invalid['monitoring_window'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                control(invalid)
        for key in value['monitoring_window']:
            invalid = deepcopy(value)
            del invalid['monitoring_window'][key]
            with self.assertRaises(ValueError):
                control(invalid)

    def test_window_configure_retains_exact_expiry_and_rejects_partial_window(self):
        from contextlib import redirect_stdout
        import io
        args = ['configure','--config','fixture.json','--symbols',','.join(WATCH),
                '--enabled','--feed','delayed_sip','--window-start','2026-10-17T23:00:00Z',
                '--window-end','2026-10-19T13:30:00Z']
        with patch.object(shadow_station,'load_config',return_value=self.config), redirect_stdout(io.StringIO()):
            self.assertEqual(service.main(args), 0)
            before = (self.root / 'control.json').read_bytes()
            self.assertEqual(service.main(args[:-2]), 2)
        self.assertEqual((self.root / 'control.json').read_bytes(), before)
        self.assertEqual(read_state(self.root / 'control.json'), self.window_control())


class HTTPTests(_LocalHTTPMixin, unittest.TestCase):
    def setUp(self):
        projection, _ = packet(headline='<script>alert("x")</script>')
        projection['status'] = 'FRESH'
        article = projection['articles'][0]
        article.update(first_seen_at=stamp(NOW), last_seen_at=stamp(NOW), revision_count=1)
        self.value = {'symbols': WATCH, 'status':'WAITING_FOR_NEXT_SLOT','auto_trading':'OFF',
                      'capture':projection,'collector':{'last_result':'CAPTURED'}}
        self.start(shadow_station.LocalStatusServer(('127.0.0.1',0),lambda:{},bind_and_activate=False,catalyst_supplier=lambda:self.value))

    def test_read_only_cards_escape_headlines_and_show_evidence_clocks(self):
        status, headers, body = self.request('/sentry')
        self.assertEqual(status,200)
        self.assertNotIn(b'<script>',body)
        self.assertIn(b'&lt;script&gt;',body)
        self.assertIn(b'First seen',body)
        self.assertIn(b'Published',body)
        self.assertIn(b'IEX',body)
        self.assertNotIn(b'<form',body)
        self.assertIn("default-src 'none'",headers['Content-Security-Policy'])

    def test_json_no_provider_calls_and_no_browser_write_path(self):
        with patch.object(service,'market_get',side_effect=AssertionError('network forbidden')):
            self.assertEqual(json.loads(self.request('/sentry.json')[2])['capture']['authority'],'OBSERVATION_ONLY')
        self.assertEqual(self.request('/sentry','POST')[0],405)
        self.assertEqual(self.request('/sentry?collect=true')[0],404)
        self.assertEqual(self.request('/sentry',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('/sentry.json','HEAD')[2],b'')

    def test_volume_labels_name_iex_scope_and_preserve_retained_numbers(self):
        self.value['capture']['contexts'][0]['day_volume'] = '501362'
        self.value['capture']['contexts'][0]['status'] = 'STALE'
        self.value['capture']['contexts'][1]['day_volume'] = '0'
        before = deepcopy(self.value)
        with patch.object(service, 'market_get', side_effect=AssertionError('network forbidden')):
            status, _, body = self.request('/sentry')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(self.request('/sentry.json')[2]), before)
        self.assertEqual(body.count(b'IEX-only volume <b>'), len(WATCH))
        self.assertIn(b'IEX-only volume <b>501,362</b> shares', body)
        self.assertIn(b'IEX-only volume <b>0</b> shares', body)
        self.assertIn(b'shares from IEX only, not total market volume', body)
        self.assertIn(b'Volume is not relative volume', body)
        self.assertIn(b'Saved bars may be stale or incomplete', body)
        self.assertIn(b'STALE', body)
        self.assertNotIn(b'Day volume', body)
        self.assertEqual(self.value, before)

    def test_reader_age_can_expire_delayed_context_without_changing_its_feed_or_count(self):
        row = {'symbol': 'GOOGL', 'feed': 'delayed_sip', 'feed_delay_seconds': 900,
               'status': 'DELAYED', 'freshness_at_packet': 'STALE',
               'day_volume': '19243640', 'price': '349.27',
               'change_from_previous_close_pct': '0.5', 'minute_at': '2026-10-15T19:59:00Z'}
        before = deepcopy(row)
        body = presentation.market_tiles([row])
        self.assertIn('<br>STALE', body)
        self.assertIn('Consolidated SIP · 15-minute delayed', body)
        self.assertIn('19,243,640', body)
        self.assertIn('349.27', body)
        self.assertEqual(row, before)

    def test_consolidated_and_delayed_market_volume_have_exact_feed_labels(self):
        for feed, delay, badge in (('sip', 0, 'Consolidated SIP'),
                                   ('delayed_sip', 900, 'Consolidated SIP · 15-minute delayed')):
            with self.subTest(feed=feed):
                self.value['capture'].update(market_feed=feed, feed_delay_seconds=delay)
                for row in self.value['capture']['contexts']:
                    row.update(feed=feed, feed_delay_seconds=delay, day_volume='19243640',
                               status='DELAYED' if delay else 'OBSERVED')
                before = deepcopy(self.value)
                code, _, body = self.request('/sentry')
                self.assertEqual(code, 200)
                html = body.decode()
                self.assertIn(badge, html)
                self.assertEqual(html.count('Market volume <b>19,243,640</b> shares'), len(WATCH))
                self.assertNotIn('IEX', html)
                self.assertNotIn('Day volume', html)
                self.assertIn('DELAYED' if delay else 'OBSERVED', html)
                self.assertIn('Saved bars may be stale or incomplete', html)
                self.assertEqual(json.loads(self.request('/sentry.json')[2]), before)
                self.assertEqual(self.value, before)

    def test_unverified_feed_or_delay_never_claims_consolidated_volume(self):
        for feed, delay in (('unknown', 0), ('sip', 900), ('delayed_sip', 0), ('sip', False)):
            with self.subTest(feed=feed, delay=delay):
                self.value['capture'].update(market_feed=feed, feed_delay_seconds=delay)
                for row in self.value['capture']['contexts']:
                    row.update(feed=feed, feed_delay_seconds=delay)
                html = presentation.render(self.value)
                self.assertIn('Volume · feed unverified', html)
                self.assertIn('Market feed unverified', html)
                self.assertNotIn('Market volume <b>', html)
                self.assertNotIn('Consolidated SIP', html)

    def test_large_integer_volume_keeps_every_retained_digit(self):
        self.value['capture'].update(market_feed='sip', feed_delay_seconds=0)
        for row in self.value['capture']['contexts']:
            row.update(feed='sip', feed_delay_seconds=0, day_volume='9999999999999999')
        html = presentation.render(self.value)
        self.assertEqual(html.count('Market volume <b>9,999,999,999,999,999</b> shares'), len(WATCH))

    def test_empty_stale_and_truncated_states_are_explicit(self):
        self.value['capture']['news_truncated'] = True
        self.value['capture']['status'] = 'STALE'
        self.value['collector']['last_result'] = 'HTTP_ERROR'
        html = presentation.render(self.value)
        self.assertIn('coverage is incomplete',html)
        self.assertIn('STALE',html)
        self.assertIn('HTTP_ERROR',html)
        self.value['capture'] = None
        self.assertIn('No verified headlines recorded',presentation.render(self.value))

    def test_weekend_window_displays_real_interval_and_stop_without_mutating_evidence(self):
        self.value['monitoring_window'] = {'start_at':'2026-10-17T23:39:57Z',
            'end_at':'2026-10-19T13:35:00Z','poll_seconds':600}
        before = deepcopy(self.value)
        html = presentation.render(self.value)
        self.assertIn('Monitoring · 10-minute polling',html)
        self.assertIn('Oct 19 · 06:35:00 AM PDT',html)
        self.assertIn('pauses at window end',html)
        self.assertNotIn('five-minute polling',html)
        self.assertNotIn('weekdays 5 a.m.',html)
        self.assertEqual(self.value,before)
        self.value['status'] = 'MONITORING_WINDOW_ENDED'
        self.assertIn('Collection window ended · collection paused',presentation.render(self.value))

    def test_invalid_window_does_not_invent_a_default_schedule(self):
        self.value['monitoring_window'] = {'poll_seconds':'<script>bad</script>'}
        html = presentation.render(self.value)
        self.assertIn('Monitoring schedule unavailable',html)
        self.assertNotIn('<script>bad</script>',html)
        self.assertNotIn('weekdays 5 a.m.',html)
