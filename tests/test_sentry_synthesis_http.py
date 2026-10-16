"""Actual local HTTP handlers over in-memory connections; no ports or inference."""
import json
import unittest
from unittest.mock import patch

from blackpod_build_week import shadow_station
from blackpod_build_week.sentry_catalyst_presentation import render as render_feed
from test_shadow_station import _LocalHTTPMixin


class SentrySynthesisHTTPTests(_LocalHTTPMixin, unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.value = {'status': 'NOT_GENERATED', 'report': None, 'auto_trading': 'OFF',
                      'operational': {'enabled': True, 'last_result': 'NOT_RUN'}}
        def supplier():
            self.calls.append('read')
            return self.value
        self.start(shadow_station.LocalStatusServer(('127.0.0.1', 0), lambda: {},
            bind_and_activate=False, catalyst_synthesis_supplier=supplier))

    def test_html_and_json_read_saved_status_only(self):
        with patch('blackpod_build_week.sentry_synthesis_transport.generate_role', side_effect=AssertionError('inference forbidden')):
            code, headers, body = self.request('/sentry-synthesis')
            self.assertEqual(code, 200)
            self.assertIn('text/html', headers['Content-Type'])
            self.assertIn(b'Sentry market brief', body)
            self.assertIn(b'No synthesis generated', body)
            self.assertIn(b'Auto-trading OFF', body)
            self.assertNotIn(b'<form', body)
            code, headers, body = self.request('/sentry-synthesis.json')
            self.assertEqual(code, 200)
            self.assertEqual(headers['Content-Type'], 'application/json')
            self.assertEqual(json.loads(body), self.value)
        self.assertEqual(self.calls, ['read', 'read'])

    def test_head_returns_correct_headers_without_body_or_inference(self):
        with patch('blackpod_build_week.sentry_synthesis_transport.generate_role', side_effect=AssertionError('inference forbidden')):
            for path in ('/sentry-synthesis', '/sentry-synthesis.json'):
                with self.subTest(path=path):
                    code, headers, body = self.request(path, 'HEAD')
                    self.assertEqual(code, 200)
                    self.assertGreater(int(headers['Content-Length']), 0)
                    self.assertEqual(body, b'')

    def test_non_readonly_methods_rejected_before_supplier(self):
        for path in ('/sentry-synthesis', '/sentry-synthesis.json'):
            for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'CONNECT', 'TRACE'):
                with self.subTest(path=path, method=method):
                    self.assertEqual(self.request(path, method)[0], 405)
        self.assertEqual(self.calls, [])

    def test_host_origin_and_cross_site_rules_preserved(self):
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
                        {'Sec-Fetch-Site': 'cross-site'},
                        {'Host': '127.0.0.1:5183\r\nHost: evil.example'},
                        {'Origin': 'http://127.0.0.1:5183\r\nOrigin: http://127.0.0.1:5183'}):
            for path in ('/sentry-synthesis', '/sentry-synthesis.json'):
                with self.subTest(headers=headers, path=path):
                    self.assertEqual(self.request(path, headers=headers)[0], 403)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.request('/sentry-synthesis.json', headers={'Host': 'localhost:5183', 'Origin': 'http://localhost:5183'})[0], 200)

    def test_only_exact_paths_are_available(self):
        for path in ('/sentry-synthesis?generate=true', '/sentry-synthesis.json?collect=true',
                     '/sentry-synthesis/', '/sentry-synthesis/generate', '/sentry-synthesis/intent.json',
                     '/../sentry-synthesis.json', '/sentry-synthesis%2f'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.calls, [])

    def test_unconfigured_supplier_is_unavailable(self):
        self.server.catalyst_synthesis_supplier = None
        for path in ('/sentry-synthesis', '/sentry-synthesis.json'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 503)
        self.assertEqual(self.calls, [])

    def test_security_headers_and_untrusted_html_escape(self):
        self.value['operational']['last_result'] = '<script>bad</script>'
        code, headers, body = self.request('/sentry-synthesis')
        self.assertEqual(code, 200)
        self.assertNotIn(b'<script>', body)
        self.assertIn(b'&lt;script&gt;', body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Cross-Origin-Resource-Policy'], 'same-origin')
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertIn("form-action 'none'", headers['Content-Security-Policy'])

    def test_feed_has_readonly_market_brief_link(self):
        html = render_feed({'status': 'PAUSED', 'symbols': [], 'capture': None,
                            'collector': None, 'auto_trading': 'OFF'})
        self.assertIn('href="/sentry-synthesis"', html)
        self.assertIn('Market brief + challenge', html)
        self.assertIn('href="/sentry-audit"', html)
        self.assertNotIn('<form', html)

    def test_retained_price_volume_is_labeled_iex_only_and_json_stays_original(self):
        from test_sentry_synthesis_presentation import fixture
        self.value = fixture()
        self.value['report']['context']['evidence'][1]['data']['day_volume'] = '501362'
        with patch('blackpod_build_week.sentry_synthesis_transport.generate_role', side_effect=AssertionError('inference forbidden')):
            code, _, body = self.request('/sentry-synthesis')
            self.assertEqual(code, 200)
            self.assertIn(b'IEX-only volume: 501362 shares', body)
            self.assertIn(b'not total market volume', body)
            self.assertIn(b'Volume is not relative volume', body)
            self.assertNotIn(b'Day volume', body)
            code, _, body = self.request('/sentry-synthesis.json')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), self.value)

    def test_new_delayed_market_panel_does_not_replace_original_model_inputs(self):
        from test_sentry_synthesis_presentation import fixture
        self.value = fixture()
        self.value['report']['context']['evidence'][1]['data']['day_volume'] = '501362'
        self.value['current_market_context'] = {
            'status': 'FRESH', 'captured_at': '2026-10-15T22:00:00Z',
            'market_feed': 'delayed_sip', 'feed_delay_seconds': 900,
            'contexts': [{'symbol': 'NVDA', 'status': 'DELAYED', 'feed': 'delayed_sip',
                          'feed_delay_seconds': 900, 'day_volume': '19243640',
                          'change_from_previous_close_pct': '2.50',
                          'minute_at': '2026-10-15T21:44:00Z'}]}
        with patch('blackpod_build_week.sentry_synthesis_transport.generate_role', side_effect=AssertionError('inference forbidden')):
            code, _, body = self.request('/sentry-synthesis')
            self.assertEqual(code, 200)
            self.assertIn(b'Current market context', body)
            self.assertIn(b'15-minute delayed', body)
            self.assertIn(b'Market volume <b>19,243,640</b> shares', body)
            self.assertIn(b'IEX-only volume: 501362 shares', body)
            self.assertIn(b'do not update the Oracle interpretation or its review', body)
            code, _, body = self.request('/sentry-synthesis.json')
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body), self.value)


if __name__ == '__main__':
    unittest.main()
