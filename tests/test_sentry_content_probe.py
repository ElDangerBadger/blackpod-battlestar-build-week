"""One bounded entitlement GET, with authored offline data and no providers.

Content bodies are transport evidence only. Metadata availability cannot prove
full-article access, source quality, or contractual reuse rights.
"""
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from pathlib import Path
import json
import os
import socket
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler

from blackpod_build_week import sentry_content_probe as probe
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.paper_account_probe import PaperCredentials
from blackpod_build_week.sentry_catalyst import stamp
from blackpod_build_week.shadow_station import atomic_state
from test_sentry_catalyst import NOW, WATCH
import test_sentry_synthesis_service as synthesis_fixtures
from test_sentry_catalyst_capture import Response
from test_paper_account_probe import GALACTICA_YAML


VERSION = 'blackpod.sentry_content_probe.v1'
URL = 'https://data.alpaca.markets/v1beta1/news'
CREDS = PaperCredentials('fixture-paper-id', 'fixture-paper-secret')
BODY = '<p>PRIVATE_ARTICLE_BODY_42 &amp; context</p><script>untrusted()</script>'
SUMMARY = 'PRIVATE_SUMMARY_42'


def query():
    return {'symbols': ','.join(WATCH), 'start': stamp(NOW - timedelta(hours=24)),
            'end': stamp(NOW), 'limit': 3, 'sort': 'desc', 'include_content': 'true'}


def article(**changes):
    return {'id': 123, 'source': 'Benzinga', 'headline': 'A retained headline',
            'url': 'https://example.com/article', 'created_at': stamp(NOW - timedelta(hours=1)),
            'updated_at': stamp(NOW - timedelta(minutes=30)), 'symbols': ['SPY', 'UNRELATED'],
            'content': BODY, 'summary': SUMMARY, **changes}


def response(items=None):
    return canonical_json_bytes({'news': [article()] if items is None else items, 'next_page_token': None})


def receipt(raw, selected=None):
    return {'schema_version': VERSION, 'method': 'GET', 'url': URL,
            'query': selected or query(), 'captured_at': stamp(NOW), 'status': 200,
            'body_sha256': sha256_bytes(raw), 'size_bytes': len(raw)}


def intent():
    return {'schema_version': VERSION, 'reviewed_report_id': 'sentry-synthesis-' + 'a' * 64,
            'context_id': 'sentry-context-' + 'b' * 64, 'report_sha256': 'c' * 64,
            'watchlist': WATCH, 'query': query(), 'reserved_at': stamp(NOW),
            'frozen_before': {'last_entry_sha256': 'd' * 64}, 'authority': 'OBSERVATION_ONLY'}


class ContentTransportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))

    def get(self, raw=None, change=None):
        requests = []
        def opened(request, timeout):
            requests.append((request, timeout))
            result = Response(request.full_url, response() if raw is None else raw)
            if change:
                change(result)
            return result
        with patch.object(probe, 'build_opener', return_value=Mock(open=opened)) as factory:
            result = probe.content_get(query(), CREDS)
        return result, requests, factory

    def test_fixed_single_https_get_query_no_proxy_redirect_and_no_body(self):
        (raw, saved), seen, factory = self.get()
        self.assertEqual(len(seen), 1)
        request, timeout = seen[0]
        self.assertEqual(timeout, 20)
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertTrue(request.full_url.startswith(URL + '?'))
        self.assertEqual(request.get_header('Apca-api-key-id'), CREDS.key_id)
        self.assertEqual(saved['query'], query())
        self.assertEqual(saved['url'], URL)
        self.assertEqual(saved['body_sha256'], sha256_bytes(raw))
        self.assertEqual(saved['size_bytes'], len(raw))
        self.assertNotIn(CREDS.key_id, json.dumps(saved))
        self.assertNotIn(CREDS.secret_key, json.dumps(saved))
        handlers = factory.call_args.args
        self.assertTrue(any(getattr(handler, 'proxies', None) == {} for handler in handlers))
        redirects = [h for h in handlers if isinstance(h, HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        with self.assertRaises(probe.ProbeError):
            redirects[0].redirect_request(Mock(), Mock(), 302, 'redirect', {}, 'https://example.com')
        tls = next(h for h in handlers if isinstance(h, HTTPSHandler))
        self.assertEqual(tls._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls._context.check_hostname)

    def test_query_cannot_expand_watchlist_history_page_or_content_scope(self):
        changes = [{'limit': 50}, {'limit': True}, {'include_content': 'false'}, {'page_token': 'more'},
                   {'sort': 'asc'}, {'symbols': 'SPY&url=https://example.com'}, {'symbols': 'SPY,SPY'},
                   {'symbols': ''}, {'symbols': ','.join('A' + str(i) for i in range(11))},
                   {'start': stamp(NOW - timedelta(hours=25))}, {'end': stamp(NOW - timedelta(days=2))},
                   {'url': 'https://example.com'}]
        for change in changes:
            with self.subTest(change=change), patch.object(probe, 'build_opener') as opened:
                with self.assertRaises(probe.ProbeError):
                    probe.content_get({**query(), **change}, CREDS)
                opened.assert_not_called()

    def test_401_403_429_and_transport_errors_are_sanitized(self):
        failures = [HTTPError(URL, code, 'fixture-paper-secret', {}, None) for code in (401, 403, 429)]
        failures += [URLError('fixture-paper-secret'), OSError('fixture-paper-secret'), TimeoutError('fixture-paper-secret')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(probe, 'build_opener') as factory:
                factory.return_value.open.side_effect = failure
                with self.assertRaises(probe.ProbeError) as caught:
                    probe.content_get(query(), CREDS)
                self.assertNotIn('fixture-paper-secret', str(caught.exception))
                if isinstance(failure, HTTPError):
                    self.assertEqual(caught.exception.http_status, failure.code)

    def test_oversized_empty_redirected_and_invalid_json_refused(self):
        cases = [(b'x' * (1024 * 1024 + 1), None), (b'', None),
                 (b'{"news":[],"news":[]}', None), (b'{"news":NaN}', None),
                 (response(), lambda r: setattr(r, 'url', 'https://example.com'))]
        for raw, change in cases:
            with self.subTest(size=len(raw)), self.assertRaises(probe.ProbeError):
                self.get(raw, change)

    def test_literal_and_json_escaped_credential_echoes_are_refused(self):
        for raw in (b'{"news":[],"x":"fixture-paper-secret"}',
                    b'{"news":[],"x":"fixture-paper-secr\\u0065t"}'):
            with self.subTest(raw=raw), self.assertRaises(probe.ProbeError):
                self.get(raw)

    def test_wall_clock_timeout_is_bounded_before_reading_more_body(self):
        with patch.object(probe.time, 'monotonic', side_effect=[0, 21]), self.assertRaises(probe.ProbeError) as caught:
            self.get()
        self.assertEqual(caught.exception.code, 'TIMEOUT')


class ContentProjectionTests(unittest.TestCase):
    def projected(self, items):
        raw = response(items)
        return probe.project(raw, receipt(raw), intent())

    def test_content_observed_metadata_only_not_full_article_or_rights_claim(self):
        report = self.projected([article()])
        self.assertEqual(report['status'], 'CONTENT_OBSERVED')
        row = report['articles'][0]
        self.assertTrue(row['content_field_present'])
        self.assertTrue(row['content_present'])
        self.assertTrue(row['content_is_string'])
        self.assertEqual(row['content_bytes'], len(BODY.encode()))
        self.assertEqual(row['content_sha256'], sha256_bytes(BODY.encode()))
        self.assertEqual(row['summary_bytes'], len(SUMMARY.encode()))
        self.assertEqual(row['matched_symbols'], ['SPY'])
        serialized = json.dumps(report)
        self.assertNotIn(BODY, serialized)
        self.assertNotIn(SUMMARY, serialized)
        self.assertNotIn('<script>', serialized)
        self.assertIn('UNKNOWN', serialized)
        self.assertIn('DOES_NOT_GUARANTEE_FULL_ARTICLE', serialized)

    def test_missing_null_nonstring_empty_whitespace_and_summary_only_are_not_content(self):
        missing = article()
        del missing['content']
        for item in [missing] + [article(content=v) for v in (None, 123, {}, [], '', ' \n\t')]:
            with self.subTest(content=item.get('content')):
                report = self.projected([item])
                self.assertEqual(report['status'], 'NO_CONTENT_IN_SAMPLE')
                row = report['articles'][0]
                self.assertFalse(row['content_present'])
                self.assertEqual(row['content_field_present'], 'content' in item)
                self.assertEqual(row['content_is_string'], isinstance(item.get('content'), str))
                self.assertNotIn(SUMMARY, json.dumps(report))

    def test_utf8_bytes_and_hash_are_counts_not_character_length(self):
        report = self.projected([article(content='é正文')])
        row = report['articles'][0]
        self.assertEqual(row['content_bytes'], len('é正文'.encode()))
        self.assertEqual(row['content_sha256'], sha256_bytes('é正文'.encode()))

    def test_no_articles_is_inconclusive_not_no_news_or_denied_entitlement(self):
        report = self.projected([])
        self.assertEqual(report['status'], 'NO_ARTICLES')
        self.assertEqual(report['articles'], [])
        self.assertIn('UNKNOWN', json.dumps(report))

    def test_raw_hash_receipt_query_or_sample_size_mismatch_fails_closed(self):
        raw = response()
        for changed in [{**receipt(raw), 'body_sha256': '0' * 64},
                        {**receipt(raw), 'size_bytes': len(raw) + 1},
                        {**receipt(raw), 'query': {**query(), 'include_content': 'false'}},
                        {**receipt(raw), 'url': 'https://example.com'}]:
            with self.subTest(changed=changed), self.assertRaises((probe.ProbeError, ValueError)):
                probe.project(raw, changed, intent())
        raw = response([article(id=n) for n in range(4)])
        with self.assertRaises((probe.ProbeError, ValueError)):
            probe.project(raw, receipt(raw), intent())

    def test_page_token_is_disclosed_without_assuming_full_coverage(self):
        raw = canonical_json_bytes({'news': [article()], 'next_page_token': 'more'})
        report = probe.project(raw, receipt(raw), intent())
        self.assertTrue(report['pagination_available'])
        self.assertIn('NO_PAGINATION_RETRY_PAYWALL_FETCH_OR_PROVIDER_FALLBACK', report['limitations'])

    def test_duplicate_fractional_negative_or_unrelated_article_metadata_refused(self):
        cases = [[article(), article()], [article(id=1.25)], [article(id=-1)],
                 [article(id=True)], [article(symbols=['UNRELATED'])],
                 [article(created_at=stamp(NOW + timedelta(minutes=10)))],
                 [article(updated_at=stamp(NOW + timedelta(minutes=10)))]]
        for articles in cases:
            with self.subTest(articles=articles), self.assertRaises((probe.ProbeError, ValueError)):
                self.projected(articles)


class ContentCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.config = {key: str(self.base / key) for key in
                       ('station_root', 'runtime_root', 'experiment_root', 'historical_root', 'ui_root')}
        self.config['repo_root'] = str(self.base)
        self.credentials = self.base / 'private/keys.yaml'
        self.credentials.parent.mkdir()
        self.credentials.write_bytes(GALACTICA_YAML)
        self.config.update(credentials_file=str(self.credentials), credential_format='GALACTICA_YAML')
        self.destination = self.base / 'output/content-probe'
        self.binding = {key: intent()[key] for key in ('reviewed_report_id', 'context_id', 'report_sha256', 'watchlist')}
        self.review = self.enterContext(patch.object(probe, '_review', return_value=self.binding))
        self.off = self.enterContext(patch.object(probe, '_off'))
        self.frozen = self.enterContext(patch.object(probe, '_frozen', return_value=intent()['frozen_before']))
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.calls = []

    def getter(self, selected, credentials):
        self.assertTrue((self.destination / 'intent.json').exists())
        self.assertEqual(selected, query())
        self.assertEqual(credentials, CREDS)
        self.calls.append(selected)
        raw = response()
        return raw, receipt(raw, selected)

    def capture(self, **changes):
        options = {'getter': self.getter, 'now': lambda: NOW}
        options.update(changes)
        return probe.capture(self.config, self.destination, self.binding['reviewed_report_id'], **options)

    def test_success_retains_raw_evidence_but_never_returns_body_and_retry_never_resends(self):
        first = self.capture()
        self.assertEqual(first['report']['status'], 'CONTENT_OBSERVED')
        self.assertEqual(self.calls, [query()])
        self.assertEqual((self.destination / 'response.bin').read_bytes(), response())
        self.assertNotIn(BODY, json.dumps(first))
        self.assertNotIn(SUMMARY, json.dumps(first))
        original = {p.name: p.read_bytes() for p in self.destination.iterdir() if p.is_file()}
        retained = {**first, 'provider_calls': 0}
        self.assertEqual(self.capture(), retained)
        self.assertEqual(probe.verify(self.config, self.destination), retained)
        self.assertEqual(probe.status(self.config, self.destination), retained)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(original, {p.name: p.read_bytes() for p in self.destination.iterdir() if p.is_file()})

    def test_unaccepted_review_off_failure_or_pin_failure_never_reads_credentials_or_gets(self):
        for check in (self.review, self.off, self.frozen):
            with self.subTest(check=check):
                check.side_effect = ValueError('gate blocked')
                with patch.object(probe, 'parse_credentials') as credentials:
                    with self.assertRaises((probe.ProbeError, ValueError)):
                        self.capture()
                    credentials.assert_not_called()
                check.side_effect = None
        self.assertEqual(self.calls, [])

    def test_interrupted_get_remains_uncertain_and_never_resends(self):
        def interrupt(selected, credentials):
            self.calls.append(selected)
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.capture(getter=interrupt)
        self.assertTrue((self.destination / 'intent.json').exists())
        with patch.object(probe, 'content_get', side_effect=AssertionError('provider forbidden')):
            value = self.capture()
            self.assertEqual(value['status'], 'UNCERTAIN')
            self.assertEqual(probe.status(self.config, self.destination)['status'], 'UNCERTAIN')
        self.assertEqual(len(self.calls), 1)

    def test_durable_http_failure_is_sanitized_and_never_retried(self):
        def fail(selected, credentials):
            self.calls.append(selected)
            raise probe.ProbeError('HTTP_ERROR', 403)
        first = self.capture(getter=fail)
        self.assertEqual(first['http_status'], 403)
        self.assertEqual(first['failure_code'], 'HTTP_ERROR')
        self.assertEqual(self.capture(), {**first, 'provider_calls': 0})
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn(CREDS.secret_key, json.dumps(first))

    def test_changed_frozen_head_after_get_cannot_publish_success(self):
        self.frozen.side_effect = lambda config: ({'last_entry_sha256': 'e' * 64}
                                                if self.calls else intent()['frozen_before'])
        result = self.capture()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['provider_calls'], 1)
        self.assertEqual(result['failure_code'], 'PRESERVATION_OR_OFF_GATE_FAILED')
        self.assertEqual(result['verification_status'], 'NOT_COMPLETE')
        self.assertIsNone(result.get('report'))
        self.assertTrue((self.destination / 'response.bin').exists())
        outcome = json.loads((self.destination / 'outcome.json').read_bytes())
        self.assertEqual(outcome['status'], 'FAILED')
        self.assertFalse((self.destination / 'report.json').exists())
        self.assertEqual(len(self.calls), 1)

    def test_tampered_body_or_external_hardlink_is_not_recovered_as_valid(self):
        self.capture()
        body = self.destination / 'response.bin'
        body.chmod(0o600)
        body.write_bytes(response([article(content='Different body')]))
        with self.assertRaises((probe.ProbeError, ValueError)):
            probe.verify(self.config, self.destination)
        self.assertEqual(len(self.calls), 1)

    def test_external_hardlink_or_symlink_blocks_reads(self):
        self.capture()
        body = self.destination / 'response.bin'
        alias = self.base / 'external-copy'
        os.link(body, alias)
        with self.assertRaises((probe.ProbeError, ValueError)):
            probe.verify(self.config, self.destination)
        alias.unlink()
        body.rename(alias)
        body.symlink_to(alias)
        with self.assertRaises((probe.ProbeError, ValueError, OSError)):
            probe.verify(self.config, self.destination)
        self.assertEqual(len(self.calls), 1)

    def test_destination_must_be_separate_from_source_runtime_and_credential_roots(self):
        for destination in (Path(self.config['runtime_root']), Path(self.config['experiment_root']) / 'probe',
                            self.credentials.parent / 'probe', Path(self.config['station_root']) / 'synthesis',
                            Path(self.config['station_root']) / 'catalyst', Path(self.config['station_root']),
                            Path(self.config['repo_root']) / 'src/probe',
                            Path(self.config['repo_root']) / '.git/probe',
                            Path(self.config['repo_root']) / 'docs/probe',
                            Path(self.config['repo_root']) / 'output/nested/probe'):
            with self.subTest(destination=destination), self.assertRaises((probe.ProbeError, ValueError)):
                probe.capture(self.config, destination, self.binding['reviewed_report_id'],
                              getter=self.getter, now=lambda: NOW)
        self.assertEqual(self.calls, [])

    def test_provider_free_verification_and_cli_status_never_read_keys_or_print_bodies(self):
        self.capture()
        with patch.object(probe, 'parse_credentials', side_effect=AssertionError('keys forbidden')), \
                patch.object(probe, 'content_get', side_effect=AssertionError('GET forbidden')), \
                patch('blackpod_build_week.shadow_station.load_config', return_value=self.config):
            self.assertEqual(probe.verify(self.config, self.destination)['status'], 'CONTENT_OBSERVED')
            for command in ('status', 'verify'):
                with self.subTest(command=command), patch('sys.stdout', new_callable=StringIO) as output:
                    self.assertEqual(probe.main([command, '--config', '/private/tmp/fixture.json',
                                                 '--output', str(self.destination)]), 0)
                    public = output.getvalue()
                    self.assertNotIn(BODY, public)
                    self.assertNotIn(SUMMARY, public)
                    self.assertNotIn('<script>', public)
                    self.assertEqual(json.loads(public)['provider_calls'], 0)
        self.assertEqual(len(self.calls), 1)

    def test_interrupted_publication_keeps_uncertainty_and_never_resends(self):
        original = probe._publish
        for stage in ('report.json', 'outcome.json'):
            self.destination = self.base / 'output' / ('interrupt-' + stage)
            self.calls = []
            def interrupted(root, staging, name, value):
                if name == stage:
                    raise KeyboardInterrupt()
                return original(root, staging, name, value)
            with self.subTest(stage=stage), patch.object(probe, '_publish', side_effect=interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    self.capture()
            self.assertTrue((self.destination / 'response.bin').exists())
            self.assertTrue((self.destination / 'transport.json').exists())
            with patch.object(probe, 'parse_credentials', side_effect=AssertionError('no keys during recovery')):
                self.assertEqual(self.capture()['status'], 'UNCERTAIN')
                self.assertEqual(probe.verify(self.config, self.destination)['status'], 'UNCERTAIN')
            self.assertEqual(len(self.calls), 1)

    def test_different_review_id_is_a_conflict_not_a_second_capture(self):
        self.capture()
        with self.assertRaises(probe.ProbeError) as caught:
            probe.capture(self.config, self.destination, 'sentry-synthesis-' + 'e' * 64,
                          getter=self.getter, now=lambda: NOW)
        self.assertEqual(caught.exception.code, 'REVIEW_ID_CONFLICT')
        self.assertEqual(len(self.calls), 1)

    def test_credential_failure_is_terminal_without_a_get_or_automatic_retry(self):
        with patch.object(probe, 'parse_credentials', side_effect=ValueError('fixture-paper-secret')):
            failed = self.capture()
        self.assertEqual(failed['status'], 'FAILED')
        self.assertEqual(failed['provider_calls'], 0)
        self.assertEqual(self.calls, [])
        self.assertNotIn('fixture-paper-secret', json.dumps(failed))
        self.assertEqual(self.capture(), failed)
        self.assertEqual(self.calls, [])

    def test_secret_echo_from_injected_getter_is_not_persisted(self):
        def echo(selected, credentials):
            self.calls.append(selected)
            raw = response([article(content='fixture-paper-secret')])
            return raw, receipt(raw, selected)
        result = self.capture(getter=echo)
        self.assertEqual(result['status'], 'FAILED')
        self.assertFalse((self.destination / 'response.bin').exists())
        self.assertNotIn('fixture-paper-secret', json.dumps(result))
        self.assertEqual(len(self.calls), 1)

    def test_preexisting_public_output_directory_is_refused_without_chmod_or_capture(self):
        for mode in (0o755, 0o777):
            self.destination = self.base / 'output' / ('public-' + oct(mode))
            self.destination.mkdir(parents=True)
            self.destination.chmod(mode)
            with self.subTest(mode=mode), patch.object(probe, 'parse_credentials') as keys:
                with self.assertRaises(probe.ProbeError) as caught:
                    self.capture()
                self.assertEqual(caught.exception.code, 'PRIVATE_OUTPUT_REQUIRED')
                keys.assert_not_called()
            self.assertEqual(self.destination.stat().st_mode & 0o777, mode)
            self.assertFalse((self.destination / 'intent.json').exists())
        self.assertEqual(self.calls, [])

    def test_external_staging_hardlink_is_refused_without_data_loss(self):
        self.destination.mkdir(parents=True, mode=0o700)
        staging = self.destination / 'staging'
        staging.mkdir(mode=0o700)
        external = self.base / 'external-original'
        original = b'PRIVATE_EXTERNAL_SOURCE_BYTES_MUST_REMAIN_UNCHANGED'
        external.write_bytes(original)
        alias = staging / ('.publish-' + 'a' * 32 + '.tmp')
        os.link(external, alias)
        before = external.stat()
        with self.assertRaises(probe.ProbeError):
            self.capture()
        self.assertEqual(external.read_bytes(), original)
        self.assertEqual(alias.read_bytes(), original)
        self.assertEqual(external.stat().st_ino, before.st_ino)
        self.assertEqual(external.stat().st_nlink, 2)
        self.assertFalse((self.destination / 'intent.json').exists())
        self.assertEqual(self.calls, [])

    def test_known_interrupted_publication_link_is_verified_without_cleanup_or_resend(self):
        self.capture()
        body = self.destination / 'response.bin'
        retained_link = self.destination / 'staging' / ('.publish-' + 'b' * 32 + '.tmp')
        os.link(body, retained_link)
        before = body.read_bytes()
        self.assertEqual(probe.verify(self.config, self.destination)['status'], 'CONTENT_OBSERVED')
        self.assertEqual(self.capture()['status'], 'CONTENT_OBSERVED')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(body.read_bytes(), before)
        self.assertEqual(retained_link.read_bytes(), before)
        self.assertEqual(body.stat().st_nlink, 2)

    def test_idempotent_replay_rechecks_off_without_resending_or_rewriting(self):
        self.capture()
        outcome = (self.destination / 'outcome.json').read_bytes()
        # Capture preflight succeeds; the OFF gate changes after replay.
        self.off.side_effect = [None, ValueError('OFF changed during replay')]
        with self.assertRaises(probe.ProbeError):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((self.destination / 'outcome.json').read_bytes(), outcome)

    def set_frozen_prefix(self):
        entry = Path(self.config['experiment_root']) / 'entries/00000001.json'
        entry.parent.mkdir(parents=True)
        raw = canonical_json_bytes({'fixture': 'original frozen event'})
        entry.write_bytes(raw)
        before = {'event_count': 1, 'evidence_blob_count': 1, 'last_entry_sha256': sha256_bytes(raw)}
        self.frozen.return_value = before
        return entry, before

    def test_legitimate_pilot_append_during_get_preserves_original_prefix_and_succeeds(self):
        _, before = self.set_frozen_prefix()
        after = {'event_count': 2, 'evidence_blob_count': 2, 'last_entry_sha256': 'e' * 64}
        def appended(selected, credentials):
            result = self.getter(selected, credentials)
            self.frozen.return_value = after
            return result
        captured = self.capture(getter=appended)
        self.assertEqual(captured['status'], 'CONTENT_OBSERVED')
        stored_intent = json.loads((self.destination / 'intent.json').read_bytes())
        outcome = json.loads((self.destination / 'outcome.json').read_bytes())
        self.assertEqual(stored_intent['frozen_before'], before)
        self.assertEqual(outcome['frozen_after'], after)
        self.assertEqual(probe.verify(self.config, self.destination)['status'], 'CONTENT_OBSERVED')
        self.assertEqual(len(self.calls), 1)

    def test_truncated_or_tampered_pilot_during_get_retains_failure_without_accepted_report(self):
        entry, before = self.set_frozen_prefix()
        def tampered(selected, credentials):
            result = self.getter(selected, credentials)
            entry.write_bytes(canonical_json_bytes({'fixture': 'changed original event'}))
            self.frozen.return_value = {**before, 'event_count': 2, 'last_entry_sha256': 'e' * 64}
            return result
        captured = self.capture(getter=tampered)
        self.assertEqual(captured['status'], 'FAILED')
        self.assertEqual(captured['failure_code'], 'PRESERVATION_OR_OFF_GATE_FAILED')
        self.assertIsNone(captured['report'])
        self.assertTrue((self.destination / 'response.bin').exists())
        self.assertFalse((self.destination / 'report.json').exists())
        self.assertEqual(len(self.calls), 1)

    def test_truncated_pilot_during_get_cannot_publish_success(self):
        _, before = self.set_frozen_prefix()
        def truncated(selected, credentials):
            result = self.getter(selected, credentials)
            self.frozen.return_value = {**before, 'event_count': 0}
            return result
        result = self.capture(getter=truncated)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['provider_calls'], 1)
        self.assertEqual(result['verification_status'], 'NOT_COMPLETE')
        self.assertFalse((self.destination / 'report.json').exists())
        self.assertEqual(len(self.calls), 1)


class AcceptedReviewGateTests(unittest.TestCase):
    def setUp(self):
        # Reuse authored catalyst/ModelDock fixtures; this constructs no real
        # provider transport and does not run the helper's test methods.
        self.helper = synthesis_fixtures.SentrySynthesisServiceTests()
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.assertEqual(self.helper.cycle(), 'CHALLENGED_INTERPRETATION')
        self.report = self.helper.directory()
        value = synthesis_fixtures.service.read_report(self.report, self.helper.config)
        self.report_id = value['report_id']
        catalyst_root = synthesis_fixtures.service.catalyst_paths(self.helper.config)[0]
        from blackpod_build_week.sentry_catalyst import VERSION as CATALYST_VERSION
        atomic_state(catalyst_root / 'control.json', {'schema_version': CATALYST_VERSION, 'enabled': True, 'symbols': WATCH})

    def test_only_exact_accepted_pair_and_current_watchlist_pass_review_gate(self):
        binding = probe._review(self.helper.config, self.report_id)
        self.assertEqual(binding['reviewed_report_id'], self.report_id)
        self.assertEqual(binding['watchlist'], WATCH)
        self.assertEqual(binding['report_sha256'], sha256_bytes((self.report / 'report.json').read_bytes()))
        with self.assertRaises((probe.ProbeError, ValueError)):
            probe._review(self.helper.config, 'sentry-synthesis-' + '0' * 64)

    def test_draft_only_pair_cannot_pass_review_gate(self):
        real_read = synthesis_fixtures.service.read_report
        original = real_read(self.report, self.helper.config)
        changed = deepcopy(original)
        changed['status'] = 'DRAFT_ONLY'
        changed['challenge'] = None
        with patch.object(probe, 'read_report', return_value=changed):
            with self.assertRaises((probe.ProbeError, ValueError)):
                probe._review(self.helper.config, self.report_id)

    def test_changed_watchlist_cannot_repurpose_a_reviewed_pair(self):
        catalyst_root = synthesis_fixtures.service.catalyst_paths(self.helper.config)[0]
        from blackpod_build_week.sentry_catalyst import VERSION as CATALYST_VERSION
        atomic_state(catalyst_root / 'control.json', {'schema_version': CATALYST_VERSION, 'enabled': True,
                                                     'symbols': ['SPY']})
        with self.assertRaises(probe.ProbeError) as caught:
            probe._review(self.helper.config, self.report_id)
        self.assertEqual(caught.exception.code, 'WATCHLIST_DIFFERS_FROM_REVIEW')

    def test_historical_probe_verify_survives_later_watchlist_change_but_new_capture_does_not(self):
        config = self.helper.config
        root = Path(config['station_root']).parent
        config.update(repo_root=str(root), credential_format='GALACTICA_YAML')
        keys = Path(config['credentials_file'])
        keys.parent.mkdir(parents=True, exist_ok=True)
        keys.write_bytes(GALACTICA_YAML)
        destination = root / 'output/content-probe'
        calls = []
        def getter(selected, credentials):
            calls.append(selected)
            raw = response()
            return raw, receipt(raw, selected)
        with patch.object(probe, '_off'), patch.object(probe, '_frozen', return_value=intent()['frozen_before']):
            captured = probe.capture(config, destination, self.report_id, getter=getter, now=lambda: NOW)
            self.assertEqual(captured['status'], 'CONTENT_OBSERVED')
            catalyst_root = synthesis_fixtures.service.catalyst_paths(config)[0]
            from blackpod_build_week.sentry_catalyst import VERSION as CATALYST_VERSION
            atomic_state(catalyst_root / 'control.json', {'schema_version': CATALYST_VERSION,
                                                         'enabled': True, 'symbols': ['SPY']})
            self.assertEqual(probe.verify(config, destination)['status'], 'CONTENT_OBSERVED')
            with self.assertRaises(probe.ProbeError) as caught:
                probe.capture(config, root / 'output/different-probe', self.report_id,
                              getter=getter, now=lambda: NOW)
            self.assertEqual(caught.exception.code, 'WATCHLIST_DIFFERS_FROM_REVIEW')
        self.assertEqual(len(calls), 1)


class FrozenPinGateTests(unittest.TestCase):
    def test_frozen_check_delegates_to_original_pinned_view_and_keeps_journal_identity(self):
        config = {'experiment_root': '/private/tmp/frozen-fixture', 'experiment_id': 'frozen-fixture',
                  'protocol_sha256': 'a' * 64}
        journal = {'last_entry_sha256': 'b' * 64}
        with patch.object(probe, '_pinned_view', return_value={'journal': journal}) as checked:
            self.assertEqual(probe._frozen(config), journal)
        checked.assert_called_once_with(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])
        with patch.object(probe, '_pinned_view', side_effect=ValueError('source pin changed')):
            with self.assertRaises(ValueError):
                probe._frozen(config)

    def test_later_legitimate_pilot_append_preserves_original_probe_prefix(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            root = Path(temporary)
            entry = root / 'entries/00000001.json'
            entry.parent.mkdir()
            original = canonical_json_bytes({'fixture': 'original registered event'})
            entry.write_bytes(original)
            before = {'event_count': 1, 'evidence_blob_count': 1, 'last_entry_sha256': sha256_bytes(original)}
            later = {'event_count': 2, 'evidence_blob_count': 2, 'last_entry_sha256': 'e' * 64}
            # The pinned-view gate has already replayed the complete current
            # journal; this helper additionally checks the recorded old prefix.
            with patch.object(probe, '_frozen', return_value=later):
                probe._verify_frozen({'experiment_root': str(root)}, before)
                entry.write_bytes(canonical_json_bytes({'fixture': 'tampered original event'}))
                with self.assertRaises(probe.ProbeError):
                    probe._verify_frozen({'experiment_root': str(root)}, before)

    def test_truncated_pilot_prefix_cannot_verify_prior_probe(self):
        before = {'event_count': 2, 'evidence_blob_count': 2, 'last_entry_sha256': 'b' * 64}
        current = {'event_count': 1, 'evidence_blob_count': 1, 'last_entry_sha256': 'c' * 64}
        with patch.object(probe, '_frozen', return_value=current), self.assertRaises(probe.ProbeError):
            probe._verify_frozen({'experiment_root': '/private/tmp/nonexistent-fixture'}, before)


if __name__ == '__main__':
    unittest.main()
