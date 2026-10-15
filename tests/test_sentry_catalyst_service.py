"""Worker/HTTP integration with authored provider fixtures and no live calls."""
from datetime import timedelta
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst_service as service
from blackpod_build_week import sentry_catalyst_presentation as presentation
from blackpod_build_week import shadow_station
from blackpod_build_week.sentry_catalyst import VERSION, CatalystStore, stamp
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
        atomic_state(self.root / 'control.json', {'schema_version': VERSION, 'enabled': True, 'symbols': WATCH})
        self.off = self.enterContext(patch.object(service, '_off'))
        self.enterContext(patch.object(service, 'utc_now', return_value=NOW))
        self.enterContext(patch.object(service, '_read_regular', return_value=b'not-a-real-key'))
        self.enterContext(patch.object(service, 'parse_credentials', return_value=PaperCredentials('fixture-key', 'fixture-secret')))
        self.projection, self.blobs = packet()
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
            atomic_state(self.root / 'control.json', {'schema_version': VERSION, 'enabled': False, 'symbols': WATCH})
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
