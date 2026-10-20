"""Authored Codex envelope fixtures; no provider, login or network required."""
import copy
from datetime import UTC, datetime
import unittest
from unittest.mock import patch

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import HttpResponse, ModelDockClient, ModelDockClientError
from blackpod_build_week.modeldock_config import ModelDockConfig, ModelDockConfigurationError, load_modeldock_config
from blackpod_build_week.sentry_modeldock_codex import (
    SentryCodexConfig, CodexSentryClient, codex_projection, validate_projection,
    MAX_RETAINED_RESPONSE_BYTES,
)

START = '2026-10-20T18:00:00Z'
OBSERVED = '2026-10-20T18:00:03Z'


def known(value, source):
    return {'status': 'known', 'value': value, 'source': source}


def unavailable():
    return {'status': 'unavailable', 'reason': 'native_telemetry_not_observed'}


def wire():
    return {'profile': 'default', 'capabilities': ['text'],
        'response_format': {'type': 'json_schema', 'schema': {'type': 'object',
            'properties': {'text': {'type': 'string'}}, 'required': ['text'], 'additionalProperties': False}},
        'timeout': 900, 'max_tokens': 4096,
        'messages': [{'role': 'system', 'content': 'Observation only.'}, {'role': 'user', 'content': 'Saved evidence.'}],
        'metadata': {'blackpod_correlation': {'mission_id': 'sentry-fixture', 'request_id': 'request-fixture',
            'symbol': 'WATCHLIST', 'run_mode': 'LIVE'}}}


def envelope():
    return {'status': 'ok', 'request_type': 'text.generate', 'profile': 'default',
        'provider': 'codex', 'model': 'selected-alias', 'content': '{"text":"Insufficient evidence."}',
        'data': {}, 'trace_id': 'server-trace', 'mocked': False,
        'metadata': {'engine': 'codex-app-server', 'codex_model': 'gpt-fixture',
            'codex_thread_id': 'thread-fixture', 'codex_turn_id': 'turn-fixture',
            'generated_token_count': 5666, 'generated_token_count_source': 'native',
            'stop_reason': 'unknown', 'stop_reason_source': 'unavailable',
            'max_tokens_enforced': False, 'prefill_cache_supported': False,
            'streaming_mode': 'buffered', 'structured_output': {'mode': 'json_schema', 'validated': True},
            'blackpod_correlation': copy.deepcopy(wire()['metadata']['blackpod_correlation']),
            'execution_provenance': {'schema': 'modeldock.execution-provenance.v1',
                'execution_id': 'execution-fixture', 'request_id': 'server-trace',
                'started_at': known('2026-10-20T18:00:01Z', 'execution_boundary'),
                'completed_at': known('2026-10-20T18:00:02Z', 'execution_boundary'),
                'environment': {'operation': known('text.generate', 'dispatch'),
                    'model': {'resolved_model': known('gpt-fixture', 'codex_thread_start')},
                    'runtime': {'provider': known('codex', 'dispatch'), 'engine': known('codex-app-server', 'dispatch'),
                        'implementation': known('providers.codex.CodexProvider', 'dispatch'),
                        'untrusted_private_path': '/private/not-for-public-projection'},
                    'execution_kind': known('inference', 'provider_result')},
                'completion': {'generated_token_count': known(5666, 'native'), 'finish_reason': unavailable()}}}}


class ReadinessTransport:
    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def request(self, **kwargs):
        self.calls.append(kwargs)
        alias = 'selected-alias'
        values = {'health': {'ready': True, 'state': 'READY', 'provider_available': True},
            'stats': {'active_compute': 0, 'active_requests': 0, 'current_model': alias, 'configured_model': alias},
            'active': {'active_model': alias, 'model': {'name': alias, 'provider': 'codex',
                'engine': 'codex-app-server', 'status': 'ACTIVE', 'availability': 'PROVIDER_MANAGED',
                'structured_output': {'mode': 'json_schema', 'supported': True, 'reason': None}}}}
        name = kwargs['url'].rsplit('/', 1)[1]
        value = values[name]
        if self.mutate:
            self.mutate(name, value)
        body = canonical_json_bytes(value)
        return HttpResponse(200, {'Content-Length': str(len(body))}, body)


class InferenceTransport:
    def __init__(self, mutate=None, exception=None, status=200, complete=True):
        self.calls = []
        self.mutate, self.exception, self.status, self.complete = mutate, exception, status, complete

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.exception:
            raise self.exception
        value = envelope()
        if self.mutate:
            self.mutate(value)
        body = canonical_json_bytes(value)
        return HttpResponse(self.status, {'Content-Length': str(len(body))}, body, self.complete)


class SentryCodexTests(unittest.TestCase):
    def config(self, **kwargs):
        return SentryCodexConfig('http://127.0.0.1:8000/', 900, **kwargs)

    def client(self, *, mutate=None, preflight=None, exception=None, status=200, complete=True, ticks=None):
        self.inference = InferenceTransport(mutate, exception, status, complete)
        self.readiness = ReadinessTransport(preflight)
        moments = iter([datetime.fromisoformat(START.replace('Z', '+00:00')),
                        datetime.fromisoformat(OBSERVED.replace('Z', '+00:00')),
                        datetime.fromisoformat(OBSERVED.replace('Z', '+00:00'))])
        return CodexSentryClient(self.config(), transport=self.inference,
            readiness_transport=self.readiness, now=lambda: next(moments), monotonic=ticks or (lambda: 1.0))

    def run_client(self, client, **kwargs):
        return client.generate_text(wire(), mission_id='sentry-fixture', request_id='request-fixture',
            symbol='WATCHLIST', run_mode='LIVE', content_requires_correlation=False,
            content_validator=kwargs.pop('validator', lambda value: value), **kwargs)

    def test_explicit_config_preserves_base_defaults_and_validation(self):
        self.assertEqual(self.config().provider, 'codex')
        self.assertEqual(self.config().base_url, 'http://127.0.0.1:8000')
        self.assertEqual(self.config().delivery_timeout_seconds, 930)
        self.assertEqual(ModelDockConfig('http://127.0.0.1:8000', 900).provider, 'mlx')
        with self.assertRaises(ModelDockConfigurationError):
            ModelDockConfig('http://127.0.0.1:8000', 900, provider='codex')
        with self.assertRaises(ModelDockConfigurationError):
            load_modeldock_config(environ={'MODELDOCK_BASE_URL': 'http://localhost:8000',
                'MODELDOCK_TIMEOUT_SECONDS': '900', 'MODELDOCK_PROVIDER': 'codex'})
        for kwargs in ({'provider': 'mlx'}, {'provider': 'arbitrary'}, {'delivery_grace_seconds': 31},
                       {'max_response_bytes': True}, {'model': '/private/unsafe'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ModelDockConfigurationError):
                self.config(**kwargs)
        for url, timeout in [('https://provider.example', 900), ('http://localhost:8000', 901),
                             ('http://localhost:8000', float('nan'))]:
            with self.subTest(url=url, timeout=timeout), self.assertRaises(ModelDockConfigurationError):
                SentryCodexConfig(url, timeout)
        with self.assertRaises(ModelDockConfigurationError):
            CodexSentryClient(ModelDockConfig('http://localhost:8000', 60))

    def test_success_keeps_original_content_and_truthful_telemetry(self):
        result = self.run_client(self.client())
        self.assertEqual(result.provider, 'codex')
        self.assertEqual(result.model, 'selected-alias')
        self.assertIsNone(result.model_revision)
        self.assertEqual(result.parsed_content, {'text': 'Insufficient evidence.'})
        self.assertEqual(result.request_bytes, canonical_json_bytes(wire()))
        self.assertEqual(len(self.inference.calls), 1)
        self.assertEqual(len(self.readiness.calls), 3)
        self.assertTrue(all(call['method'] == 'GET' and call['body'] is None
                            and call['timeout_seconds'] <= 5 for call in self.readiness.calls))
        self.assertEqual(self.inference.calls[0]['max_response_bytes'], MAX_RETAINED_RESPONSE_BYTES)
        self.assertLessEqual(self.inference.calls[0]['timeout_seconds'], 930)
        self.assertEqual(result.safe_response['metadata']['generated_token_count'], 5666)
        self.assertIs(result.safe_response['metadata']['max_tokens_enforced'], False)
        self.assertEqual(result.safe_response['metadata']['stop_reason'], 'unknown')
        self.assertNotIn('/private/', result.safe_response_bytes.decode())
        self.assertEqual(result.safe_response['content'], envelope()['content'])

    def test_host_guard_changed_during_readiness_blocks_post(self):
        client = self.client()
        def blocked():
            raise ValueError('frozen source or OFF changed')
        client.before_post = blocked
        with self.assertRaises(ModelDockClientError):
            self.run_client(client)
        self.assertEqual(len(self.readiness.calls), 3)
        self.assertEqual(self.inference.calls, [])

    def test_projection_and_replay_are_provider_free(self):
        original = envelope()
        projection = codex_projection(original)
        self.assertEqual(projection['metadata']['execution_provenance_sha256'],
                         sha256_bytes(canonical_json_bytes(original['metadata']['execution_provenance'])))
        with patch('blackpod_build_week.sentry_modeldock_codex.UrlLibTransport', side_effect=AssertionError('network')):
            self.assertEqual(validate_projection(projection, wire(), started_at=START, observed_at=OBSERVED),
                             {'text': 'Insufficient evidence.'})
        self.assertIn('untrusted_private_path', original['metadata']['execution_provenance']['environment']['runtime'])

    def test_unavailable_usage_is_preserved(self):
        original = envelope()
        original['metadata'].update(generated_token_count=None, generated_token_count_source='unavailable')
        original['metadata']['execution_provenance']['completion']['generated_token_count'] = unavailable()
        projection = codex_projection(original)
        self.assertIsNone(projection['metadata']['generated_token_count'])
        validate_projection(projection, wire(), started_at=START, observed_at=OBSERVED)

    def test_provider_metadata_and_proof_mutations_reject(self):
        changes = [lambda v: v.update(provider='mlx'), lambda v: v.update(mocked=True),
            lambda v: v.update(data={'engine': 'mlx-lm'}), lambda v: v.update(trace_id='other-trace'),
            lambda v: v['metadata'].update(engine='mlx-lm'),
            lambda v: v['metadata'].update(max_tokens_enforced=True),
            lambda v: v['metadata'].update(stop_reason='stop'),
            lambda v: v['metadata'].update(generated_token_count=True),
            lambda v: v['metadata'].update(generated_token_count_source='estimated'),
            lambda v: v['metadata'].update(codex_model='/private/model'),
            lambda v: v['metadata'].update(codex_turn_id='sk-proj-abcdefghijklmnop'),
            lambda v: v['metadata']['structured_output'].update(validated=False),
            lambda v: v['metadata']['structured_output'].update(validated=1),
            lambda v: v['metadata']['execution_provenance']['completion']['generated_token_count'].update(value=5666.0),
            lambda v: v['metadata']['execution_provenance']['environment']['model']['resolved_model'].update(value='other-model'),
            lambda v: v['metadata']['execution_provenance']['environment']['runtime']['provider'].update(value='other-provider'),
            lambda v: v['metadata']['execution_provenance']['completed_at'].update(value=START)]
        for change in changes:
            value = envelope(); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                codex_projection(value)

    def test_projection_binding_clocks_and_extra_fields_reject(self):
        changes = [lambda v: v.update(profile='other-profile'),
            lambda v: v['metadata']['blackpod_correlation'].update(request_id='other-request'),
            lambda v: v['metadata'].update(execution_provenance_sha256='x'*64),
            lambda v: v['metadata']['execution_provenance'].update(extra='unsafe'),
            lambda v: v['metadata']['execution_provenance']['started_at'].update(value='2026-10-20T17:59:59Z'),
            lambda v: v['metadata']['execution_provenance']['completed_at'].update(value='2026-10-20T18:00:04Z'),
            lambda v: v.update(content='{"text":"a","text":"b"}'),
            lambda v: v.update(content='{"text":NaN}')]
        for change in changes:
            value = codex_projection(envelope()); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_projection(value, wire(), started_at=START, observed_at=OBSERVED)

    def test_readiness_busy_unavailable_or_other_provider_never_posts(self):
        changes = [lambda n, v: v.update(ready=False) if n == 'health' else None,
            lambda n, v: v.update(active_requests=1) if n == 'stats' else None,
            lambda n, v: v.update(active_compute=True) if n == 'stats' else None,
            lambda n, v: v['model'].update(provider='mlx') if n == 'active' else None,
            lambda n, v: v['model']['structured_output'].update(supported=1) if n == 'active' else None,
            lambda n, v: v.update(current_model='different') if n == 'stats' else None]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ModelDockClientError):
                self.run_client(self.client(preflight=change))
            self.assertEqual(self.inference.calls, [])

    def test_post_http_timeout_invalid_and_host_failures_never_retry(self):
        for options in ({'exception': TimeoutError()}, {'status': 500}, {'complete': False},
                        {'mutate': lambda v: v.update(model='different-alias')},
                        {'mutate': lambda v: v.update(content='{"text":"a","text":"b"}')},
                        {'mutate': lambda v: v.update(content='x'*(MAX_RETAINED_RESPONSE_BYTES+1))}):
            with self.subTest(options=options), self.assertRaises(ModelDockClientError):
                self.run_client(self.client(**options))
            self.assertEqual(len(self.inference.calls), 1)
        with self.assertRaises(ModelDockClientError) as caught:
            self.run_client(self.client(), validator=lambda value: (_ for _ in ()).throw(ValueError('private evidence')))
        self.assertEqual(caught.exception.failure.code, 'narrative_schema_invalid')
        self.assertNotIn('private evidence', str(caught.exception))
        self.assertFalse(caught.exception.resumable)

    def test_interruption_propagates_without_another_request(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_client(self.client(exception=KeyboardInterrupt()))
        self.assertEqual(len(self.inference.calls), 1)

    def test_readiness_consumes_the_same_total_deadline(self):
        elapsed = [0.0]
        def slow(name, value):
            elapsed[0] += 500
        with self.assertRaises(ModelDockClientError) as caught:
            self.run_client(self.client(preflight=slow, ticks=lambda: elapsed[0]))
        self.assertEqual(caught.exception.failure.code, 'timeout')
        self.assertEqual(self.inference.calls, [])

    def test_wrong_runmode_and_invalid_request_never_query_readiness(self):
        client = self.client()
        with self.assertRaises(ModelDockClientError):
            client.generate_text(wire(), mission_id='sentry-fixture', request_id='wrong-id',
                symbol='WATCHLIST', run_mode='LIVE')
        self.assertEqual(self.readiness.calls, [])
        self.assertEqual(self.inference.calls, [])

    def test_generic_client_rejects_codex_even_when_given_subclass(self):
        fixture = InferenceTransport()
        generic = ModelDockClient(self.config(), transport=fixture)
        with self.assertRaises(ModelDockClientError) as caught:
            generic.generate_text(wire(), mission_id='sentry-fixture', request_id='request-fixture',
                symbol='WATCHLIST', run_mode='LIVE', content_requires_correlation=False,
                content_validator=lambda v: v)
        self.assertEqual(caught.exception.failure.code, 'live_provider_policy')


if __name__ == '__main__':
    unittest.main()
