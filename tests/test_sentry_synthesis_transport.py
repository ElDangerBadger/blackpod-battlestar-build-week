"""Offline ModelDock-envelope fixtures only; no local service or providers."""
import copy
from datetime import datetime, timezone
import json
from io import BytesIO
import os
from pathlib import Path
import tempfile
import threading
import socket
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient, HttpResponse, UrlLibTransport
from blackpod_build_week.modeldock_config import ModelDockConfig
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week import sentry_synthesis_transport as transport

NOW = datetime(2026, 10, 15, 18, 0, tzinfo=timezone.utc)


def packet():
    return {'context_id': 'sentry-context-test', 'as_of': '2026-10-15T18:00:00Z', 'watchlist': ['SPY', 'NVDA'],
        'evidence': [{'evidence_id': 'headline-1', 'kind': 'HEADLINE', 'symbols': ['NVDA'],
                      'data': {'headline': 'Company issues a product update', 'source': 'Benzinga'}}],
        'evidence_signature': 'f' * 64, 'quality': {'news_truncated': True},
        'limitations': ['SINGLE_PROVIDER', 'HEADLINES_ONLY'],
        'portfolio': {'status': 'NO_VERIFIED_HOLDINGS'}, 'authority': {'auto_trading_enabled': False}}


def draft():
    return {'schema_version': 'blackpod.sentry_oracle_draft.v2',
        'overview': {'text': 'The available headlines are insufficient to establish a broad market theme.', 'evidence_ids': ['headline-1']},
        'themes': [{'theme_id': 'theme-1', 'title': 'Product development',
            'interpretation': 'The headline could indicate a product catalyst; its importance remains unverified.',
            'evidence_ids': ['headline-1'], 'implications': [{'symbol': 'NVDA', 'linkage': 'DIRECT_MENTION',
                'trading': 'A short-horizon reaction remains unmeasured.', 'investment': 'Fundamental consequences remain unverified.'}],
            'alternative': 'The announcement may have been expected.', 'proposed_invalidation': {'status': 'UNSPECIFIED', 'text': ''},
            'proposed_review_horizon': 'UNSPECIFIED'}], 'unresolved_questions': ['What is the original company statement?']}


def keyed_draft():
    original = draft()
    original['schema_version'] = 'blackpod.sentry_oracle_draft.v3'
    for theme in original['themes']:
        theme['implications_by_symbol'] = {
            row['symbol']:{key:value for key,value in row.items() if key != 'symbol'}
            for row in theme.pop('implications')}
    return original


def challenge(original=None):
    return {'schema_version': 'blackpod.sentry_challenge.v2', 'draft_sha256': sha256_bytes(canonical_json_bytes(draft() if original is None else original)),
        'reviews': [{'theme_id': 'theme-1', 'status': 'UNTESTED', 'reason': 'The headline lacks fundamental context.',
            'evidence_ids': ['headline-1'], 'alternative': 'The announcement may be routine.',
            'missing_evidence': ['Original company announcement']}], 'overall_limitations': ['Same provider and evidence.']}


def validation_diagnostic(**changes):
    return {'schema': 'modeldock.structured-validation-diagnostic.v1', 'stage': 'RESULT_VALIDATION',
        'reason': 'JSON_SYNTAX', 'schema_keyword': None, 'generated_token_count': 2500,
        'generated_token_count_source': 'native', 'stop_reason': 'length', 'stop_reason_source': 'native',
        **changes}


class FixtureTransport:
    def __init__(self, response=None, *, mutate=None, exception=None):
        self.content = response if response is not None else draft()
        self.mutate = mutate
        self.exception = exception
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.exception:
            raise self.exception
        wire = json.loads(kwargs['body'])
        envelope = {'status': 'ok', 'request_type': 'text.generate', 'profile': wire['profile'], 'provider': 'mlx',
            'model': 'local-fixture-model', 'content': json.dumps(self.content),
            'data': {'engine': 'mlx-vlm', 'model_path': '/private/fixture-model-path', 'profile': wire['profile']},
            'metadata': {'blackpod_correlation': wire['metadata']['blackpod_correlation'],
                'requested_max_tokens': wire['max_tokens'], 'effective_max_tokens': wire['max_tokens'], 'generated_token_count': 200,
                'generated_token_count_source': 'native', 'stop_reason': 'stop', 'stop_reason_source': 'native',
                'generation_options': {}, 'structured_output': {'mode': 'json_schema', 'validated': True}},
            'trace_id': 'fixture-trace', 'mocked': False}
        if self.mutate:
            self.mutate(envelope)
        raw = canonical_json_bytes(envelope)
        return HttpResponse(200, {'Content-Length': str(len(raw))}, raw)


class SentrySynthesisTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'role'
        self.config = ModelDockConfig('http://127.0.0.1:8000', 60, delivery_grace_seconds=10)
        self.fixture = FixtureTransport()
        self.gates = []

    def factory(self, config):
        return ModelDockClient(config, transport=self.fixture, now=lambda: NOW)

    def generate(self, role='oracle', **kwargs):
        return transport.generate_role(role, packet(), self.root, self.config,
            off_check=lambda: self.gates.append('off'), verify_source=lambda: self.gates.append('source'),
            client_factory=self.factory, now=lambda: NOW, **kwargs)

    def test_accepted_real_client_fixture_and_provider_free_read(self):
        result = self.generate()
        self.assertEqual(result['status'], 'ACCEPTED')
        self.assertEqual(result['response'], draft())
        self.assertEqual(result['provenance']['model'], 'local-fixture-model')
        self.assertEqual(self.gates, ['off', 'source', 'off', 'source'])
        self.assertEqual(len(self.fixture.calls), 1)
        with patch.object(transport.ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), result)
        saved = (self.root / 'receipt.json').read_text()
        self.assertNotIn('/private/fixture-model-path', saved)
        self.assertNotIn('generation_options', saved)

    def test_wire_has_local_only_schema_and_fixed_safety(self):
        self.generate()
        call = self.fixture.calls[0]
        self.assertEqual(call['method'], 'POST')
        self.assertEqual(call['url'], 'http://127.0.0.1:8000/text/generate')
        wire = json.loads(call['body'])
        self.assertEqual(wire['max_tokens'], 4096)
        self.assertEqual(wire['timeout'], 60)
        self.assertEqual(wire['response_format']['type'], 'json_schema')
        self.assertNotIn('model', wire)
        self.assertEqual(wire['metadata']['blackpod_correlation']['symbol'], 'WATCHLIST')
        for text in ('UNTRUSTED DATA', 'SINGLE_PROVIDER', 'No verified holdings', 'auto-trading remains OFF', 'no article bodies'):
            self.assertIn(text, wire['messages'][0]['content'])

    def test_idempotent_retry_no_resend_or_mutation(self):
        first = self.generate()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(self.generate(), first)
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_challenge_separate_request_binds_original_draft(self):
        oracle = self.generate()
        oracle_wire = json.loads(self.fixture.calls[0]['body'])
        self.root = Path(self.tmp.name) / 'challenge'
        self.fixture = FixtureTransport(challenge())
        result = self.generate('challenge', draft=oracle['response'])
        self.assertEqual(result['status'], 'ACCEPTED')
        wire = json.loads(self.fixture.calls[0]['body'])
        self.assertNotEqual(wire['metadata']['blackpod_correlation']['request_id'], oracle_wire['metadata']['blackpod_correlation']['request_id'])
        self.assertIn('original_oracle_draft', wire['messages'][1]['content'])
        self.assertIn('not proof of independent model', wire['messages'][0]['content'])
        self.assertEqual(transport.read_role('challenge', packet(), self.root, self.config, draft=draft()), result)

    def test_role_and_draft_requirements_before_io(self):
        for role, value in [('unsupported', None), ('challenge', None), ('oracle', draft())]:
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.generate(role, draft=value)
        self.assertFalse(self.root.exists())
        self.assertEqual(len(self.fixture.calls), 0)

    def test_timeout_and_grace_fail_before_io(self):
        for timeout, grace in [(901, 30), (900, 31)]:
            self.config = ModelDockConfig('http://localhost:8000', timeout, delivery_grace_seconds=grace)
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.generate()
        self.assertFalse(self.root.exists())
        self.assertEqual(len(self.fixture.calls), 0)

    def test_v3_long_budget_reaches_service_and_delivery_without_prompt_changes(self):
        old, old_bindings, _ = transport._request('oracle', packet(), self.config, None, version=transport.V2_VERSION)
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        wire, bindings, configuration = transport._request('oracle', packet(), self.config, None, version=transport.V3_VERSION)
        self.assertEqual(wire['timeout'], 900)
        self.assertEqual(self.config.delivery_timeout_seconds, 930)
        for field in ('messages', 'response_format', 'max_tokens', 'profile', 'capabilities'):
            self.assertEqual(wire[field], old[field])
        self.assertNotEqual(wire['metadata'], old['metadata'])
        self.assertEqual(bindings['configuration_sha256'], sha256_bytes(canonical_json_bytes(configuration)))
        self.assertNotIn('configuration_sha256', old_bindings)
        result = self.generate(version=transport.V3_VERSION)
        self.assertEqual(result['status'], 'ACCEPTED')
        request = self.fixture.calls[0]
        self.assertEqual(json.loads(request['body'])['timeout'], 900)
        self.assertGreater(request['timeout_seconds'], 900)
        self.assertLessEqual(request['timeout_seconds'], 930)
        self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), result)

    def test_historical_versions_keep_their_old_deadline_bounds(self):
        for version in (transport.LEGACY_VERSION, transport.V2_VERSION):
            for timeout, grace in ((121, 10), (120, 11)):
                config = ModelDockConfig('http://localhost:8000', timeout, delivery_grace_seconds=grace)
                with self.subTest(version=version, timeout=timeout, grace=grace), self.assertRaises(ValueError):
                    transport._request('oracle', packet(), config, None, version=version)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_v2_receipt_replays_exactly_under_v3_default_without_resend(self):
        first = self.generate(version=transport.V2_VERSION)
        self.assertEqual(first['status'], 'ACCEPTED')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old_wire = json.loads(before['intent.json'])['wire_request']
        self.assertEqual(json.loads(before['intent.json'])['schema_version'], transport.V2_VERSION)
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(first['request_id'], old_wire['metadata']['blackpod_correlation']['request_id'])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v3_long_deadline_replays_exactly_under_v4_default_without_resend(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        first = self.generate(version=transport.V3_VERSION)
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old = json.loads(before['intent.json'])
        current, bindings, _ = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(old['schema_version'], transport.V3_VERSION)
        self.assertEqual(old['bindings']['configuration_sha256'], bindings['configuration_sha256'])
        self.assertNotEqual(old['bindings']['transport_schema_version'], bindings['transport_schema_version'])
        self.assertNotEqual(old['wire_request']['metadata'], current['metadata'])
        for key in ('response_format','timeout','profile','capabilities'):
            self.assertEqual(old['wire_request'][key], current[key])
        self.assertEqual(current['messages'][0]['content'], old['wire_request']['messages'][0]['content'] + transport.CONTRACT_GUIDANCE + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], old['wire_request']['messages'][1:])
        self.assertEqual(old['wire_request']['max_tokens'], 2500)
        self.assertEqual(current['max_tokens'], 4096)
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v4_exact_replay_under_current_default_preserves_old_budget(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        first = self.generate(version=transport.V4_VERSION)
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old = json.loads(before['intent.json'])
        current, bindings, configuration = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(old['schema_version'], transport.V4_VERSION)
        self.assertEqual(transport.VERSION, 'blackpod.sentry_synthesis_transport.v9')
        self.assertEqual(old['bindings']['configuration_sha256'], bindings['configuration_sha256'])
        self.assertNotEqual(old['bindings']['transport_schema_version'], bindings['transport_schema_version'])
        self.assertNotEqual(old['wire_request']['metadata'], current['metadata'])
        self.assertEqual(old['configuration'], configuration)
        for key in ('response_format', 'timeout', 'profile', 'capabilities'):
            self.assertEqual(old['wire_request'][key], current[key])
        self.assertEqual(current['messages'][0]['content'], old['wire_request']['messages'][0]['content'] + transport.CONTRACT_GUIDANCE + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], old['wire_request']['messages'][1:])
        self.assertEqual(old['wire_request']['max_tokens'], 2500)
        self.assertEqual(current['max_tokens'], 4096)
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v5_golden_wire_and_receipt_replay_exactly_under_current_without_resend(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        first = self.generate(version=transport.V5_VERSION)
        self.assertEqual(first['status'], 'ACCEPTED')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old = json.loads(before['intent.json'])
        wire = old['wire_request']
        self.assertEqual(old['schema_version'], 'blackpod.sentry_synthesis_transport.v5')
        self.assertEqual(wire['max_tokens'], 2500)
        # Captured before introducing v6: configuration, prompts, schema and
        # correlation identity all remain byte-for-byte reproducible.
        self.assertEqual(sha256_bytes(canonical_json_bytes(wire)),
                         'd5fc017d417f44ab86541e0c4b0499640f640d2983976eb0f7320f59d9b0baf5')
        self.assertEqual(first['request_id'],
                         'sentry-oracle-7b68495bebb143e2784de215089f3562749acc82213536e04a802ad7d39279cc')
        receipt_hash = sha256_bytes(before['receipt.json'])
        current, bindings, configuration = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(current['max_tokens'], 4096)
        self.assertEqual(old['configuration'], configuration)
        self.assertEqual(old['bindings']['configuration_sha256'], bindings['configuration_sha256'])
        self.assertNotEqual(old['bindings']['transport_schema_version'], bindings['transport_schema_version'])
        self.assertNotEqual(wire['metadata'], current['metadata'])
        self.assertEqual({k:v for k,v in wire.items() if k not in {'max_tokens', 'metadata', 'messages'}},
                         {k:v for k,v in current.items() if k not in {'max_tokens', 'metadata', 'messages'}})
        self.assertEqual(current['messages'][0]['content'], wire['messages'][0]['content'] + transport.CONTRACT_GUIDANCE + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], wire['messages'][1:])
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(sha256_bytes((self.root / 'receipt.json').read_bytes()), receipt_hash)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v7_v8_v9_use_4096_and_earlier_versions_keep_2500(self):
        for version in (transport.LEGACY_VERSION, transport.V2_VERSION, transport.V3_VERSION,
                        transport.V4_VERSION, transport.V5_VERSION, transport.V6_VERSION,
                        transport.V7_VERSION, transport.V8_VERSION, transport.VERSION):
            wire, _, _ = transport._request('oracle', packet(), self.config, None, version=version)
            with self.subTest(version=version):
                self.assertEqual(wire['max_tokens'], 4096 if version in {transport.V7_VERSION, transport.V8_VERSION, transport.VERSION} else 2500)

    def test_v6_golden_wire_and_receipt_replay_under_v7_without_resend(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        first = self.generate(version=transport.V6_VERSION)
        self.assertEqual(first['status'], 'ACCEPTED')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old = json.loads(before['intent.json'])
        wire = old['wire_request']
        self.assertEqual(old['schema_version'], 'blackpod.sentry_synthesis_transport.v6')
        self.assertEqual(wire['max_tokens'], 2500)
        # Captured from v6 before the v7 token-budget change.
        self.assertEqual(sha256_bytes(canonical_json_bytes(wire)),
                         'd5bafe9c6dea31b602ccd784b2b3bdb43fed74ee3593b72a2933cafb8d21f041')
        self.assertEqual(first['request_id'],
                         'sentry-oracle-c4a65e9713180e5ac1be5dd9b713e789b3a1efbd080f94a47bdae25360559f12')
        current, bindings, configuration = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(current['max_tokens'], 4096)
        self.assertEqual(old['configuration'], configuration)
        self.assertEqual(old['bindings']['configuration_sha256'], bindings['configuration_sha256'])
        self.assertNotEqual(old['bindings']['transport_schema_version'], bindings['transport_schema_version'])
        self.assertNotEqual(wire['metadata'], current['metadata'])
        self.assertEqual({k:v for k,v in wire.items() if k not in {'max_tokens', 'metadata', 'messages'}},
                         {k:v for k,v in current.items() if k not in {'max_tokens', 'metadata', 'messages'}})
        self.assertEqual(current['messages'][0]['content'], wire['messages'][0]['content'] + transport.CONTRACT_GUIDANCE + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], wire['messages'][1:])
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(first['receipt_sha256'], sha256_bytes((self.root / 'receipt.json').read_bytes()))
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_native_completed_4096_budget_is_accepted_but_native_length_is_rejected(self):
        self.fixture = FixtureTransport(mutate=lambda e: e['metadata'].update(generated_token_count=4096))
        self.assertEqual(self.generate()['status'], 'ACCEPTED')
        self.root = Path(self.tmp.name) / 'truncated'
        self.fixture = FixtureTransport(mutate=lambda e: e['metadata'].update(generated_token_count=4096,
                                                                             stop_reason='length'))
        result = self.generate()
        self.assertEqual(result['status'], 'FAILED')
        self.assertIsNone(result['response'])
        self.assertIsNone(result['provenance'])
        self.assertEqual(self.generate(), result)
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v7_golden_wire_and_rejected_receipt_replay_under_v8_without_new_diagnostics(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        invalid = draft()
        invalid['themes'][0]['evidence_ids'] *= 2
        self.fixture = FixtureTransport(invalid)
        first = self.generate(version=transport.V7_VERSION)
        self.assertEqual(first['failure_code'], 'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        wire = json.loads(before['intent.json'])['wire_request']
        self.assertEqual(sha256_bytes(canonical_json_bytes(wire)),
                         'f2acf7830a5938ff25890d09115eff7a6786c0711dde0e242e603da205f04558')
        self.assertEqual(first['request_id'],
                         'sentry-oracle-4b8b8337dfc9ee7de078dd99559542e6c6251f6ce012aa719cf28cd39b64324a')
        current, bindings, _ = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(current['max_tokens'], wire['max_tokens'])
        self.assertEqual(current['messages'][0]['content'], wire['messages'][0]['content'] + transport.CONTRACT_GUIDANCE + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], wire['messages'][1:])
        self.assertEqual({k:v for k,v in current.items() if k not in {'metadata', 'messages'}},
                         {k:v for k,v in wire.items() if k not in {'metadata', 'messages'}})
        self.assertNotEqual(bindings['transport_schema_version'], transport.V7_VERSION)
        self.assertNotEqual(current['metadata'], wire['metadata'])
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
            self.assertIsNone(transport.read_local_contract_observation('oracle', packet(), self.root, self.config))
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v8_explicit_guidance_matches_existing_strict_rules_for_both_roles(self):
        for role, original in (('oracle', None), ('challenge', draft())):
            wire, _, _ = transport._request(role, packet(), self.config, original, version=transport.V8_VERSION)
            old, _, _ = transport._request(role, packet(), self.config, original, version=transport.V7_VERSION)
            self.assertEqual(wire['messages'][0]['content'], old['messages'][0]['content'] + transport.CONTRACT_GUIDANCE)
            self.assertEqual(wire['response_format'], old['response_format'])
            for text in ('unique known IDs', 'each implication symbol at most once',
                         'HEADLINE in that same theme evidence_ids', 'leading or trailing whitespace',
                         'Unicode formatting characters', 'exactly one review', 'reviews=[]'):
                self.assertIn(text, wire['messages'][0]['content'])

    def test_v8_golden_wire_failed_receipt_and_v1_sidecar_replay_unchanged_under_v9(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30)
        invalid = draft(); invalid['overview']['text'] = ' leading whitespace'
        self.fixture = FixtureTransport(invalid)
        first = self.generate(version=transport.V8_VERSION)
        self.assertEqual(first['failure_code'], 'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        old = json.loads(before['intent.json'])['wire_request']
        self.assertEqual(sha256_bytes(canonical_json_bytes(old)),
                         '93d54270542fda0ddcfbef24645695b4a9fd6b7c78fcae13c90e961a6a20afd9')
        self.assertEqual(first['request_id'],
                         'sentry-oracle-9b02393a0a0c7bd164f066f7b67cc2aa3f700d624b427af1b27f0ea49c5f5539')
        self.assertEqual(sha256_bytes(before['receipt.json']),
                         '3fa2e86903238ddb11dda5d9536bda7cf79abe8b42d9bb4d2290eaa7b4e56ad2')
        self.assertEqual(sha256_bytes(before['local-contract-error.json']),
                         '9ace64b1af91d3130178bc7d113de067cf5720dea894827ee76b5eb9b8a65da2')
        observed = transport.read_local_contract_observation('oracle', packet(), self.root, self.config)
        self.assertEqual(observed['schema_version'], transport.LOCAL_CONTRACT_OBSERVATION_VERSION)
        self.assertEqual(observed['reason'], 'TEXT_FORMAT')
        self.assertNotIn('rule', observed)
        self.assertNotIn('field', observed)
        current, _, _ = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(current['messages'][0]['content'], old['messages'][0]['content'] + transport.COMPACT_GUIDANCE)
        self.assertEqual(current['messages'][1:], old['messages'][1:])
        self.assertEqual({k:v for k,v in current.items() if k not in {'metadata', 'messages'}},
                         {k:v for k,v in old.items() if k not in {'metadata', 'messages'}})
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay network')):
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.generate(), first)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v9_compact_guidance_is_generation_only_with_original_v2_schema_and_budget(self):
        for role, original in (('oracle', None), ('challenge', draft())):
            wire, _, _ = transport._request(role, packet(), self.config, original)
            old, _, _ = transport._request(role, packet(), self.config, original, version=transport.V8_VERSION)
            self.assertEqual(wire['messages'][0]['content'], old['messages'][0]['content'] + transport.COMPACT_GUIDANCE)
            self.assertEqual(wire['response_format'], old['response_format'])
            self.assertEqual(wire['max_tokens'], 4096)
            for text in ('one short plain-English sentence', 'printable ASCII only', 'straight quotes and hyphens',
                         'at most two implications', 'most two themes', '300', '80', '180',
                         'smaller original schema bounds', 'do not repair failed outputs'):
                self.assertIn(text, wire['messages'][0]['content'])
            self.assertNotIn(transport.COMPACT_GUIDANCE, old['messages'][0]['content'])
        # Instruction-only conciseness does not silently change the historical
        # host contract: valid v2 text remains accepted without rewriting it.
        value = draft(); value['overview']['text'] = 'Café ' + 'a' * 350
        self.fixture = FixtureTransport(value)
        result = self.generate()
        self.assertEqual(result['status'], 'ACCEPTED')
        self.assertEqual(result['response']['overview']['text'], value['overview']['text'])

    def test_budget_provenance_must_match_exact_reserved_wire_for_current_v5_and_v6(self):
        for version, wrong in ((transport.VERSION, 2500), (transport.V5_VERSION, 4096),
                               (transport.V6_VERSION, 4096)):
            for field in ('requested_max_tokens', 'effective_max_tokens', 'generated_token_count'):
                self.root = Path(self.tmp.name) / f'{version[-2:]}-{field}'
                observed = 4097 if version == transport.VERSION and field == 'generated_token_count' else wrong
                self.fixture = FixtureTransport(mutate=lambda e, f=field, n=observed:
                                                e['metadata'].update({f:n}))
                with self.subTest(version=version, field=field):
                    result = self.generate(version=version)
                    self.assertNotEqual(result['status'], 'ACCEPTED')
                    self.assertIsNone(result['response'])
                    self.assertEqual(self.generate(version=version), result)
                    self.assertEqual(len(self.fixture.calls), 1)

    def test_rehashed_receipt_cannot_change_its_versioned_token_budget_or_integer_types(self):
        for version, own_budget, other_budget in ((transport.VERSION, 4096, 2500),
                                                  (transport.V5_VERSION, 2500, 4096),
                                                  (transport.V6_VERSION, 2500, 4096)):
            for field, observed in (('requested_max_tokens', other_budget),
                                     ('effective_max_tokens', other_budget),
                                     ('generated_token_count', own_budget + 1),
                                     ('requested_max_tokens', float(own_budget)),
                                     ('effective_max_tokens', float(own_budget))):
                self.root = Path(self.tmp.name) / f'{version[-2:]}-{field}-{observed}'
                self.fixture = FixtureTransport()
                self.assertEqual(self.generate(version=version)['status'], 'ACCEPTED')
                receipt = json.loads((self.root / 'receipt.json').read_bytes())
                safe = receipt['provenance']['safe_response']
                safe['metadata'][field] = observed
                receipt['provenance']['safe_response_sha256'] = sha256_bytes(canonical_json_bytes(safe))
                receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k:v for k,v in receipt.items()
                                                                            if k != 'receipt_sha256'}))
                (self.root / 'receipt.json').chmod(0o600)
                (self.root / 'receipt.json').write_bytes(canonical_json_bytes(receipt))
                with self.subTest(version=version, field=field, observed=observed), self.assertRaises(ValueError):
                    transport.read_role('oracle', packet(), self.root, self.config)
                self.assertEqual(len(self.fixture.calls), 1)

    def test_configuration_changes_get_distinct_v3_request_id(self):
        one, _, _ = transport._request('oracle', packet(), self.config, None)
        two, _, _ = transport._request('oracle', packet(),
            ModelDockConfig('http://127.0.0.1:8000', 900, delivery_grace_seconds=30), None)
        self.assertNotEqual(one['metadata']['blackpod_correlation']['request_id'],
                            two['metadata']['blackpod_correlation']['request_id'])

    def test_unreserved_v2_role_uses_explicit_version_hint(self):
        old, _, _ = transport._request('oracle', packet(), self.config, None, version=transport.V2_VERSION)
        result = transport.read_role('oracle', packet(), self.root, self.config, version=transport.V2_VERSION)
        self.assertEqual(result['request_id'], old['metadata']['blackpod_correlation']['request_id'])
        self.assertEqual(result['failure_code'], 'NOT_RESERVED')
        self.assertFalse(self.root.exists())

    def test_pre_gate_rejection_never_reserves_or_calls(self):
        for gate in ('off_check', 'verify_source'):
            kwargs = {'off_check': lambda: None, 'verify_source': lambda: None}
            kwargs[gate] = lambda: (_ for _ in ()).throw(ValueError('blocked'))
            with self.subTest(gate=gate), self.assertRaises(ValueError):
                transport.generate_role('oracle', packet(), self.root, self.config, client_factory=self.factory,
                                        now=lambda: NOW, **kwargs)
        self.assertFalse(self.root.exists())

    def test_post_gate_failure_cannot_publish_accepted_content(self):
        calls = []
        def gate():
            calls.append(True)
            if len(calls) == 2:
                raise ValueError('runtime changed')
        result = transport.generate_role('oracle', packet(), self.root, self.config, off_check=gate,
            verify_source=lambda: None, client_factory=self.factory, now=lambda: NOW)
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIsNone(result['response'])
        self.assertIsNone(result['provenance'])
        self.assertNotIn('Product development', (self.root / 'receipt.json').read_text())
        self.assertEqual(self.generate()['status'], 'REJECTED')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_malformed_semantics_rejected_not_repaired_or_retried(self):
        self.fixture.content = {'BUY': 'NVDA', 'quantity': 100}
        result = self.generate()
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIsNone(result['response'])
        self.assertNotIn('BUY', (self.root / 'receipt.json').read_text())
        self.assertEqual(self.generate()['status'], 'REJECTED')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_unverified_schema_completion_and_provider_rejected(self):
        changes = [lambda e: e.update(provider='cloud'), lambda e: e.update(mocked=True),
            lambda e: e['metadata'].update(stop_reason='length'),
            lambda e: e['metadata'].pop('structured_output'),
            lambda e: e['metadata']['blackpod_correlation'].update(symbol='OTHER')]
        for index, change in enumerate(changes):
            self.root = Path(self.tmp.name) / str(index)
            self.fixture = FixtureTransport(mutate=change)
            with self.subTest(index=index):
                self.assertEqual(self.generate()['status'], 'FAILED')
                self.assertEqual(self.generate()['status'], 'FAILED')
                self.assertEqual(len(self.fixture.calls), 1)

    def test_timeout_terminal_failure_and_post_gates(self):
        self.fixture = FixtureTransport(exception=TimeoutError('private secret value'))
        result = self.generate()
        self.assertEqual(result['status'], 'FAILED')
        self.assertIsNone(result['response'])
        self.assertEqual(self.gates, ['off', 'source', 'off', 'source'])
        self.assertNotIn('private secret value', (self.root / 'receipt.json').read_text())
        self.assertEqual(self.generate()['status'], 'FAILED')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_interrupt_retains_intent_uncertain_without_resend(self):
        self.fixture = FixtureTransport(exception=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.generate()
        self.assertTrue((self.root / 'intent.json').exists())
        self.assertFalse((self.root / 'receipt.json').exists())
        self.assertEqual(self.gates, ['off', 'source', 'off', 'source'])
        self.assertEqual(self.generate()['status'], 'UNCERTAIN')
        self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config)['status'], 'UNCERTAIN')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_absent_read_is_pure_and_uncertain(self):
        with patch.object(transport.ModelDockClient, 'generate_text', side_effect=AssertionError('no inference')):
            result = transport.read_role('oracle', packet(), self.root, self.config)
        self.assertEqual(result['failure_code'], 'NOT_RESERVED')
        self.assertFalse(self.root.exists())

    def test_changed_packet_config_or_draft_conflicts_without_resend(self):
        self.generate()
        changed = packet(); changed['quality']['news_truncated'] = False
        with self.assertRaises(ValueError):
            transport.read_role('oracle', changed, self.root, self.config)
        other_config = ModelDockConfig('http://localhost:8000', 60, delivery_grace_seconds=10)
        with self.assertRaises(ValueError):
            transport.read_role('oracle', packet(), self.root, other_config)
        self.assertEqual(len(self.fixture.calls), 1)

    def test_tampered_receipt_rejected(self):
        self.generate()
        receipt = json.loads((self.root / 'receipt.json').read_bytes())
        receipt['response']['overview']['text'] = 'Different'
        (self.root / 'receipt.json').chmod(0o600)
        (self.root / 'receipt.json').write_bytes(canonical_json_bytes(receipt))
        with self.assertRaises(ValueError):
            transport.read_role('oracle', packet(), self.root, self.config)

    def test_rehashed_invalid_provenance_rejected(self):
        self.generate()
        receipt = json.loads((self.root / 'receipt.json').read_bytes())
        receipt['provenance']['safe_response']['metadata']['generated_token_count_source'] = 'inferred'
        receipt['provenance']['safe_response_sha256'] = sha256_bytes(canonical_json_bytes(receipt['provenance']['safe_response']))
        receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in receipt.items() if k != 'receipt_sha256'}))
        (self.root / 'receipt.json').chmod(0o600)
        (self.root / 'receipt.json').write_bytes(canonical_json_bytes(receipt))
        with self.assertRaises(ValueError):
            transport.read_role('oracle', packet(), self.root, self.config)

    def test_external_hardlink_or_symlink_rejected(self):
        self.generate()
        os.link(self.root / 'receipt.json', Path(self.tmp.name) / 'external-copy')
        with self.assertRaises(ValueError):
            transport.read_role('oracle', packet(), self.root, self.config)
        (Path(self.tmp.name) / 'external-copy').unlink()
        (self.root / 'receipt.json').rename(self.root / 'receipt-copy')
        (self.root / 'receipt.json').symlink_to(self.root / 'receipt-copy')
        with self.assertRaises(Exception):
            transport.read_role('oracle', packet(), self.root, self.config)

    def test_no_duplicate_delivery_under_concurrent_generate(self):
        entered, release = threading.Event(), threading.Event()
        original = self.fixture.request
        def request(**kwargs):
            entered.set()
            if not release.wait(3):
                raise AssertionError('fixture release timed out')
            return original(**kwargs)
        self.fixture.request = request
        results, errors = [], []
        def work():
            try:
                results.append(self.generate())
            except BaseException as exc:
                errors.append(exc)
        first = threading.Thread(target=work); first.start()
        self.assertTrue(entered.wait(3))
        second = threading.Thread(target=work); second.start()
        release.set(); first.join(5); second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.fixture.calls), 1)

    def test_publication_interruption_preserves_reservation(self):
        original = transport._publish
        def publish(directory, staging, name, value):
            if name == 'receipt.json':
                raise OSError('simulated publication interruption')
            return original(directory, staging, name, value)
        with patch.object(transport, '_publish', side_effect=publish), self.assertRaises(OSError):
            self.generate()
        self.assertEqual(self.generate()['status'], 'UNCERTAIN')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_false_gate_is_blocked_before_reservation(self):
        with self.assertRaises(ValueError):
            transport.generate_role('oracle', packet(), self.root, self.config, off_check=lambda: False,
                verify_source=lambda: True, client_factory=self.factory, now=lambda: NOW)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.fixture.calls, [])

    def test_future_packet_never_inferred_or_reserved(self):
        future = packet(); future['as_of'] = '2026-10-15T18:01:00Z'
        with self.assertRaises(ValueError):
            transport.generate_role('oracle', future, self.root, self.config, off_check=lambda: None,
                verify_source=lambda: None, client_factory=self.factory, now=lambda: NOW)
        self.assertFalse((self.root / 'intent.json').exists())
        self.assertEqual(self.fixture.calls, [])

    def test_write_json_once_idempotent_and_conflicts(self):
        capsule = Path(self.tmp.name) / 'capsule'
        value = {'frozen': 'evidence'}
        digest = transport.write_json_once(capsule, 'packet.json', value)
        before = (capsule / 'packet.json').read_bytes()
        self.assertEqual(digest, sha256_bytes(before))
        self.assertEqual(transport.write_json_once(capsule, 'packet.json', value), digest)
        self.assertEqual((capsule / 'packet.json').stat().st_mode & 0o777, 0o444)
        with self.assertRaises(ValueError):
            transport.write_json_once(capsule, 'packet.json', {'frozen': 'changed'})
        self.assertEqual((capsule / 'packet.json').read_bytes(), before)

    def test_write_json_once_rejects_unsafe_name_type_and_size(self):
        for name in ('../outside.json', 'nested/outside.json', '/absolute.json', '.hidden.json'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                transport.write_json_once(self.root, name, {'value': True})
        with self.assertRaises(ValueError):
            transport.write_json_once(self.root, 'packet.json', [])
        with self.assertRaises(ValueError):
            transport.write_json_once(self.root, 'packet.json', {'text': 'x' * (1024 * 1024)})
        self.assertFalse(self.root.exists())

    def test_write_json_once_rejects_external_links(self):
        transport.write_json_once(self.root, 'packet.json', {'value': 1})
        os.link(self.root / 'packet.json', Path(self.tmp.name) / 'external')
        with self.assertRaises(ValueError):
            transport.write_json_once(self.root, 'packet.json', {'value': 1})
        (Path(self.tmp.name) / 'external').unlink()
        target = Path(self.tmp.name) / 'target.json'
        target.write_bytes(b'original')
        (self.root / 'packet.json').unlink()
        (self.root / 'packet.json').symlink_to(target)
        with self.assertRaises(Exception):
            transport.write_json_once(self.root, 'packet.json', {'value': 1})
        self.assertEqual(target.read_bytes(), b'original')

    def test_write_json_once_interruption_recovery_before_commit(self):
        original = transport._publish_immutable
        def interrupted(staging, directory, name, payload):
            descriptor = os.open('.publish-' + 'a' * 32 + '.tmp', os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                 0o600, dir_fd=staging)
            try:
                os.write(descriptor, payload[:4]); os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raise OSError('fixture interruption before commit')
        with patch.object(transport, '_publish_immutable', side_effect=interrupted), self.assertRaises(OSError):
            transport.write_json_once(self.root, 'packet.json', {'value': 1})
        self.assertFalse((self.root / 'packet.json').exists())
        digest = transport.write_json_once(self.root, 'packet.json', {'value': 1})
        self.assertEqual(digest, sha256_bytes((self.root / 'packet.json').read_bytes()))
        self.assertEqual(len(list((self.root / 'staging').iterdir())), 1)

    def save_legacy_attempt(self, *, accepted=False):
        """Frozen v1 receipt fixture, never generated through the new wire."""
        wire, bindings, configuration = transport._request('oracle', packet(), self.config, None, version=transport.LEGACY_VERSION)
        intent = {'schema_version': transport.LEGACY_VERSION, 'bindings': bindings, 'configuration': configuration,
                  'wire_request': wire, 'request_sha256': sha256_bytes(canonical_json_bytes(wire)), 'reserved_at': '2026-10-15T18:00:00Z'}
        transport.write_json_once(self.root, 'intent.json', intent)
        (self.root / '.role.lock').touch(mode=0o600)
        response, provenance = None, None
        if accepted:
            original = draft(); original['schema_version'] = 'blackpod.sentry_oracle_draft.v1'
            original['themes'][0]['proposed_invalidation'] = None
            self.fixture.content = original
            result = self.factory(self.config).generate_text(wire, mission_id=packet()['context_id'],
                request_id=wire['metadata']['blackpod_correlation']['request_id'], symbol='WATCHLIST', run_mode='LIVE',
                content_validator=lambda value: transport._validate_response('oracle', value, packet(), None, wire),
                content_requires_correlation=False)
            provenance = {key: getattr(result, key) for key in ('request_sha256', 'raw_response_sha256', 'response_byte_size',
                'provider', 'model', 'model_revision', 'trace_id', 'mocked', 'latency_ms', 'started_at', 'observed_at')}
            provenance.update(safe_response=dict(result.safe_response), safe_response_sha256=sha256_bytes(result.safe_response_bytes))
            response = result.parsed_content
        receipt = {'schema_version': transport.LEGACY_VERSION, 'bindings': bindings,
                   'intent_sha256': sha256_bytes(canonical_json_bytes(intent)), 'status': 'ACCEPTED' if accepted else 'FAILED',
                   'finished_at': '2026-10-15T18:00:00Z', 'response': response, 'provenance': provenance,
                   'failure_code': None if accepted else 'MODELDOCK_HTTP_STATUS'}
        receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes(receipt))
        transport.write_json_once(self.root, 'receipt.json', receipt)
        return wire

    def test_legacy_failed_attempt_replays_exactly_without_rewrite_or_retry(self):
        legacy_wire = self.save_legacy_attempt()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertIn('anyOf', json.dumps(legacy_wire['response_format']['schema']))
        result = transport.read_role('oracle', packet(), self.root, self.config)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_STATUS')
        self.assertEqual(result['request_id'], legacy_wire['metadata']['blackpod_correlation']['request_id'])
        self.assertEqual(self.generate(), result)
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_legacy_accepted_response_keeps_null_and_original_version(self):
        self.save_legacy_attempt(accepted=True)
        before = (self.root / 'receipt.json').read_bytes()
        result = transport.read_role('oracle', packet(), self.root, self.config)
        self.assertEqual(result['status'], 'ACCEPTED')
        self.assertEqual(result['response']['schema_version'], 'blackpod.sentry_oracle_draft.v1')
        self.assertIsNone(result['response']['themes'][0]['proposed_invalidation'])
        self.assertEqual(self.generate(), result)
        self.assertEqual(len(self.fixture.calls), 1)  # Fixture construction only.
        self.assertEqual((self.root / 'receipt.json').read_bytes(), before)

    def test_current_wire_has_distinct_version_identity_and_rejects_v1_output(self):
        current, bindings, _ = transport._request('oracle', packet(), self.config, None)
        legacy, _, _ = transport._request('oracle', packet(), self.config, None, version=transport.LEGACY_VERSION)
        self.assertEqual(bindings['transport_schema_version'], transport.VERSION)
        self.assertNotEqual(current['metadata']['blackpod_correlation']['request_id'], legacy['metadata']['blackpod_correlation']['request_id'])
        self.assertEqual(current['response_format']['schema']['properties']['schema_version']['const'], 'blackpod.sentry_oracle_draft.v2')
        self.assertNotIn('anyOf', json.dumps(current['response_format']['schema']))
        invalid = draft(); invalid['schema_version'] = 'blackpod.sentry_oracle_draft.v1'
        invalid['themes'][0]['proposed_invalidation'] = None
        self.fixture.content = invalid
        result = self.generate()
        self.assertEqual(result['status'], 'REJECTED')
        self.assertIsNone(result['response'])
        self.assertEqual(json.loads((self.root / 'intent.json').read_bytes())['schema_version'], transport.VERSION)

    def test_http_error_retains_status_without_error_body(self):
        def request(**kwargs):
            self.fixture.calls.append(kwargs)
            return HttpResponse(422, {}, b'private error body and keys', complete=False)
        self.fixture.request = request
        result = self.generate()
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_422')
        self.assertEqual(result['status'], 'FAILED')
        self.assertNotIn('private error body', (self.root / 'receipt.json').read_text())
        self.assertEqual(self.generate(), result)
        self.assertEqual(len(self.fixture.calls), 1)

    def test_legacy_uncertain_reservation_cannot_be_upgraded_to_a_new_send(self):
        wire = self.save_legacy_attempt()
        (self.root / 'receipt.json').unlink()
        before = (self.root / 'intent.json').read_bytes()
        result = self.generate()
        self.assertEqual(result['status'], 'UNCERTAIN')
        self.assertEqual(result['request_id'], wire['metadata']['blackpod_correlation']['request_id'])
        self.assertEqual((self.root / 'intent.json').read_bytes(), before)
        self.assertEqual(self.fixture.calls, [])

    def test_default_sentry_transport_adds_named_header_without_changing_wire(self):
        expected, _, _ = transport._request('oracle', packet(), self.config, None)
        expected_bytes = canonical_json_bytes(expected)
        original_client = transport.ModelDockClient
        def fixed_clock_client(config, **kwargs):
            return original_client(config, now=lambda: NOW, **kwargs)
        with patch.object(transport, 'UrlLibTransport', return_value=self.fixture), \
             patch.object(transport, 'ModelDockClient', side_effect=fixed_clock_client):
            result = transport.generate_role('oracle', packet(), self.root, self.config,
                off_check=lambda: None, verify_source=lambda: None, now=lambda: NOW)
        self.assertEqual(result['status'], 'ACCEPTED')
        self.assertEqual(len(self.fixture.calls), 1)
        request = self.fixture.calls[0]
        self.assertEqual(request['headers']['X-ModelDock-Client'], 'BlackPod-Sentry')
        self.assertEqual(request['headers']['X-Request-ID'], result['request_id'])
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['url'], 'http://127.0.0.1:8000/text/generate')
        self.assertEqual(request['body'], expected_bytes)
        self.assertEqual(json.loads((self.root / 'intent.json').read_bytes())['request_sha256'], sha256_bytes(expected_bytes))
        self.assertEqual(json.loads(request['body'])['messages'], expected['messages'])
        self.assertEqual(request['max_response_bytes'], self.config.max_response_bytes)
        self.assertGreater(request['timeout_seconds'], 0)
        self.assertLessEqual(request['timeout_seconds'], self.config.delivery_timeout_seconds)
        self.assertNotIn('model', json.loads(request['body']))

    def test_injected_factory_still_owns_its_transport_without_header_mutation(self):
        self.generate()
        request = self.fixture.calls[0]
        self.assertNotIn('X-ModelDock-Client', request['headers'])
        self.assertEqual(request['url'], 'http://127.0.0.1:8000/text/generate')

    def test_legacy_replay_never_constructs_the_named_network_transport(self):
        self.save_legacy_attempt()
        with patch.object(transport, 'UrlLibTransport', side_effect=AssertionError('no transport on replay')):
            result = transport.generate_role('oracle', packet(), self.root, self.config,
                off_check=lambda: None, verify_source=lambda: None, now=lambda: NOW)
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(self.fixture.calls, [])


class KeyedSynthesisTransportTests(unittest.TestCase):
    factory = SentrySynthesisTransportTests.factory
    generate = SentrySynthesisTransportTests.generate

    def setUp(self):
        SentrySynthesisTransportTests.setUp(self)
        self.config = ModelDockConfig('http://127.0.0.1:8000',900,delivery_grace_seconds=30)
        self.fixture = FixtureTransport(keyed_draft())
        self.enterContext(patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')))

    def test_v10_is_explicit_and_v9_default_wire_remains_byte_identical(self):
        self.assertEqual(transport.VERSION,transport.V9_VERSION)
        self.assertEqual(transport.VERSION,'blackpod.sentry_synthesis_transport.v9')
        old,old_bindings,_ = transport._request('oracle',packet(),self.config,None)
        self.assertEqual(sha256_bytes(canonical_json_bytes(old)),
                         '91cd11240b3f8c156bb881439830cf95f06b8bd17c390e8e8d7d4637d1a739af')
        self.assertEqual(old['metadata']['blackpod_correlation']['request_id'],
                         'sentry-oracle-9c1efe027928b8ccc35d5c52a2afb560a9b30760fac180282d373c73d28aa5ed')
        wire,bindings,_ = transport._request('oracle',packet(),self.config,None,version=transport.SYMBOL_VERSION)
        self.assertEqual(wire['messages'][0]['content'],old['messages'][0]['content']+transport.KEYED_SYMBOL_GUIDANCE)
        self.assertEqual(wire['messages'][1:],old['messages'][1:])
        self.assertEqual(wire['max_tokens'],4096)
        self.assertEqual(wire['timeout'],900)
        self.assertEqual(bindings['configuration_sha256'],old_bindings['configuration_sha256'])
        self.assertNotEqual(wire['metadata'],old['metadata'])
        self.assertEqual(wire['response_format']['schema']['properties']['schema_version']['const'],
                         'blackpod.sentry_oracle_draft.v3')
        self.assertEqual(old['response_format']['schema']['properties']['schema_version']['const'],
                         'blackpod.sentry_oracle_draft.v2')
        mapping = wire['response_format']['schema']['properties']['themes']['items']['properties']['implications_by_symbol']
        self.assertEqual(mapping['required'],[])
        self.assertEqual(set(mapping['properties']),set(packet()['watchlist']))
        self.assertNotIn('minProperties',mapping)

    def test_accepted_v10_map_and_v2_challenge_retain_exact_original_hashes(self):
        original = keyed_draft()
        first = self.generate(version=transport.SYMBOL_VERSION)
        self.assertEqual(first['status'],'ACCEPTED')
        self.assertEqual(first['response'],original)
        self.assertNotIn('implications',first['response']['themes'][0])
        oracle_root = self.root
        before = {p.name:p.read_bytes() for p in oracle_root.iterdir() if p.is_file()}
        self.root = Path(self.tmp.name)/'challenge'
        self.fixture = FixtureTransport(challenge(original))
        reviewed = self.generate('challenge',draft=original,version=transport.SYMBOL_VERSION)
        self.assertEqual(reviewed['status'],'ACCEPTED')
        self.assertEqual(reviewed['response']['schema_version'],'blackpod.sentry_challenge.v2')
        self.assertEqual(reviewed['response']['draft_sha256'],sha256_bytes(canonical_json_bytes(original)))
        wire = json.loads(self.fixture.calls[0]['body'])
        self.assertEqual(json.loads(wire['messages'][1]['content'])['original_oracle_draft'],original)
        with patch.object(transport,'_default_client',side_effect=AssertionError('no inference')):
            self.assertEqual(transport.read_role('oracle',packet(),oracle_root,self.config),first)
            self.assertEqual(transport.read_role('challenge',packet(),self.root,self.config,draft=original),reviewed)
            self.assertEqual(self.generate('challenge',draft=original,version=transport.SYMBOL_VERSION),reviewed)
        self.assertEqual({p.name:p.read_bytes() for p in oracle_root.iterdir() if p.is_file()},before)
        self.assertEqual(len(self.fixture.calls),1)
        self.assertIsNone(transport.read_local_contract_observation('oracle',packet(),oracle_root,self.config))

    def test_v10_rejects_valid_v2_body_and_v9_rejects_valid_v3_body(self):
        for version,body in ((transport.SYMBOL_VERSION,draft()),(transport.V9_VERSION,keyed_draft())):
            self.root = Path(self.tmp.name)/version.rsplit('.',1)[1]
            self.fixture = FixtureTransport(body)
            with self.subTest(version=version):
                result = self.generate(version=version)
                self.assertEqual(result['status'],'REJECTED')
                self.assertEqual(result['failure_code'],'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
                self.assertIsNone(result['response'])
                observation = transport.read_local_contract_observation('oracle',packet(),self.root,self.config)
                self.assertEqual(observation['reason'],'VALUE_REJECTED')
                self.assertEqual(observation['schema_version'],transport.LOCAL_CONTRACT_DETAIL_OBSERVATION_VERSION)

    def test_v10_empty_map_host_rejection_is_retained_and_never_repaired_or_resent(self):
        invalid = keyed_draft();invalid['themes'][0]['implications_by_symbol'] = {}
        self.fixture = FixtureTransport(invalid)
        result = self.generate(version=transport.SYMBOL_VERSION)
        self.assertEqual(result['status'],'REJECTED')
        self.assertEqual(result['failure_code'],'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
        self.assertIsNone(result['response'])
        observation = transport.read_local_contract_observation('oracle',packet(),self.root,self.config)
        self.assertEqual(observation['reason'],'CONTRACT_REJECTED')
        self.assertEqual(observation['schema_version'],transport.LOCAL_CONTRACT_DETAIL_OBSERVATION_VERSION)
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch.object(transport,'_default_client',side_effect=AssertionError('no inference')):
            self.assertEqual(self.generate(version=transport.SYMBOL_VERSION),result)
            self.assertEqual(transport.read_role('oracle',packet(),self.root,self.config),result)
        self.assertEqual({p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()},before)
        self.assertEqual(len(self.fixture.calls),1)

    def test_v10_raw_duplicate_symbol_keys_never_reach_collapsing_dict_validation(self):
        original = keyed_draft()
        entry = json.dumps(original['themes'][0]['implications_by_symbol']['NVDA'])
        fragment = '"NVDA": '+entry
        for index,key in enumerate(('"NVDA"','"\\u004eVDA"')):
            self.root = Path(self.tmp.name)/str(index)
            content = json.dumps(original).replace(fragment,fragment+', '+key+': '+entry,1)
            self.fixture = FixtureTransport(original,mutate=lambda envelope: envelope.update(content=content))
            result = self.generate(version=transport.SYMBOL_VERSION)
            self.assertEqual(result['status'],'FAILED')
            self.assertEqual(result['failure_code'],'MODELDOCK_RESPONSE_DUPLICATE_FIELD')
            self.assertIsNone(result['response'])
            self.assertEqual(self.generate(version=transport.SYMBOL_VERSION),result)
            self.assertEqual(len(self.fixture.calls),1)
            self.assertIsNone(transport.read_local_contract_observation('oracle',packet(),self.root,self.config))

    def test_v10_bound_deadlines_and_gate_fail_before_any_delivery(self):
        for timeout,grace in ((901,30),(900,31)):
            config = ModelDockConfig('http://127.0.0.1:8000',timeout,delivery_grace_seconds=grace)
            with self.subTest(timeout=timeout,grace=grace),self.assertRaises(ValueError):
                transport._request('oracle',packet(),config,None,version=transport.SYMBOL_VERSION)
        with self.assertRaises(ValueError):
            transport.generate_role('oracle',packet(),self.root,self.config,
                off_check=lambda:False,verify_source=lambda:None,client_factory=self.factory,
                now=lambda:NOW,version=transport.SYMBOL_VERSION)
        self.assertEqual(self.fixture.calls,[])
        self.assertFalse(self.root.exists())


class SentryLocalContractObservationTests(unittest.TestCase):
    setUp = SentrySynthesisTransportTests.setUp
    factory = SentrySynthesisTransportTests.factory
    generate = SentrySynthesisTransportTests.generate

    def observe(self, **kwargs):
        return transport.read_local_contract_observation('oracle', packet(), self.root, self.config, **kwargs)

    def invalid_response(self):
        value = draft()
        value['themes'][0]['evidence_ids'] *= 2
        return value

    def test_actual_contract_rejections_get_only_the_correct_closed_category(self):
        cases = []
        value = self.invalid_response(); cases.append(('DUPLICATE_CITATIONS', value))
        value = draft(); value['themes'] *= 2; cases.append(('DUPLICATE_THEME_ID', value))
        value = draft(); value['themes'][0]['implications'] *= 2; cases.append(('DUPLICATE_SYMBOL', value))
        value = draft(); value['unresolved_questions'] *= 2; cases.append(('DUPLICATE_TEXT', value))
        value = draft(); value['themes'][0]['implications'][0]['symbol'] = 'SPY'
        cases.append(('DIRECT_MENTION_CITATION_MISSING', value))
        value = draft(); value['themes'][0]['proposed_invalidation']['text'] = 'Not explicitly empty'
        cases.append(('INVALID_UNSPECIFIED_TEXT', value))
        for text in (' leading whitespace', 'trailing whitespace ', 'two\nlines', 'format\u200dcharacter', '\u2028separator'):
            value = draft(); value['overview']['text'] = text; cases.append(('TEXT_FORMAT', value))
        for index, (expected, value) in enumerate(cases):
            self.root = Path(self.tmp.name) / str(index)
            self.fixture = FixtureTransport(value)
            with self.subTest(reason=expected, index=index):
                result = self.generate()
                self.assertEqual(result['status'], 'REJECTED')
                self.assertEqual(result['failure_code'], 'MODELDOCK_NARRATIVE_SCHEMA_INVALID')
                observed = self.observe()
                self.assertEqual(observed['reason'], expected)
                self.assertEqual(observed['stage'], 'HOST_RESPONSE_CONTRACT')
                self.assertEqual(set(observed), {'schema_version', 'stage', 'reason', 'rule', 'field',
                    'request_sha256', 'request_id', 'receipt_sha256', 'observation_sha256'})
                self.assertLessEqual((self.root / 'local-contract-error.json').stat().st_size,
                                     transport.MAX_LOCAL_CONTRACT_BYTES)
                self.assertIsNone(result['response'])
                self.assertIsNone(result['provenance'])
                self.assertEqual(self.generate(), result)
                self.assertEqual(len(self.fixture.calls), 1)

    def test_challenge_coverage_rejection_is_observed_without_changing_original_draft(self):
        value = challenge(); value['reviews'] = []
        original = draft()
        before = canonical_json_bytes(original)
        self.fixture = FixtureTransport(value)
        result = self.generate('challenge', draft=original)
        self.assertEqual(result['status'], 'REJECTED')
        observed = transport.read_local_contract_observation('challenge', packet(), self.root, self.config, draft=original)
        self.assertEqual(observed['reason'], 'THEME_COVERAGE')
        self.assertEqual(canonical_json_bytes(original), before)

    def test_v9_exact_static_text_rules_record_closed_field_and_rule_only(self):
        cases = [(' leading', 'WHITESPACE_OR_BLANK'), ('a' * 601, 'CONTROL_OR_LENGTH'),
                 ('escaped\nnewline', 'CONTROL_OR_LENGTH'), ('format\u200dcharacter', 'UNICODE_FORMAT'),
                 ('bad\ud800encoding', 'UNICODE_ENCODING')]
        for index, (text, rule) in enumerate(cases):
            self.root = Path(self.tmp.name) / str(index)
            value = draft(); value['overview']['text'] = text
            self.fixture = FixtureTransport(value)
            with self.subTest(rule=rule):
                self.assertEqual(self.generate()['status'], 'REJECTED')
                observed = self.observe()
                self.assertEqual(observed['schema_version'], transport.LOCAL_CONTRACT_DETAIL_OBSERVATION_VERSION)
                self.assertEqual(observed['reason'], 'TEXT_FORMAT')
                self.assertEqual(observed['rule'], rule)
                self.assertEqual(observed['field'], 'overview.text')
                self.assertNotIn(text, (self.root / 'local-contract-error.json').read_text())

    def test_finer_classifier_has_closed_fields_and_unknown_messages_are_unclassified(self):
        suffixes = [(' must be a nonblank string without surrounding whitespace', 'WHITESPACE_OR_BLANK'),
                    (' contains unsupported control or line-separator characters', 'UNICODE_FORMAT'),
                    (' must contain valid Unicode text', 'UNICODE_ENCODING')]
        for field, maximum in transport.LOCAL_TEXT_FIELDS.items():
            for suffix, rule in suffixes + [(f' contains unsupported characters or exceeds {maximum} characters',
                                             'CONTROL_OR_LENGTH')]:
                message = field + suffix
                details = transport._local_contract_details(ContractValidationError(message))
                self.assertEqual(details, {'reason':'TEXT_FORMAT', 'field':field, 'rule':rule})
                self.assertEqual(transport._local_contract_details(ContractValidationError(message + ' /PRIVATE_VALUE')),
                                 {'reason':'CONTRACT_REJECTED', 'field':'UNCLASSIFIED', 'rule':'OTHER'})
        self.assertEqual(transport._local_contract_details(ContractValidationError('duplicate theme_id')),
                         {'reason':'DUPLICATE_THEME_ID', 'field':'UNCLASSIFIED', 'rule':'OTHER'})

    def test_v2_rule_field_tampering_and_version_downgrade_fail_closed(self):
        value = draft(); value['overview']['text'] = ' leading'
        self.fixture = FixtureTransport(value)
        self.generate()
        path = self.root / 'local-contract-error.json'
        original = json.loads(path.read_bytes())
        cases = []
        for field, changed_value in (('rule', 'PRIVATE_VALUE'), ('rule', []), ('rule', 'OTHER'),
                                     ('field', 'overview[0].text'), ('field', 'UNCLASSIFIED'),
                                     ('field', {}), ('reason', 'CONTRACT_REJECTED'),
                                     ('schema_version', transport.LOCAL_CONTRACT_OBSERVATION_VERSION)):
            changed = copy.deepcopy(original); changed[field] = changed_value; cases.append(changed)
        changed = copy.deepcopy(original); changed.pop('rule'); cases.append(changed)
        changed = copy.deepcopy(original); changed['message'] = '/PRIVATE_PATH'; cases.append(changed)
        for changed in cases:
            changed['observation_sha256'] = sha256_bytes(canonical_json_bytes(
                {k:v for k,v in changed.items() if k != 'observation_sha256'}))
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(changed))
            with self.assertRaises(ValueError):
                self.observe()
        self.assertEqual(len(self.fixture.calls), 1)

    def test_v8_v1_observation_rejects_added_detail_fields_or_v2_upgrade(self):
        value = draft(); value['overview']['text'] = ' leading'
        self.fixture = FixtureTransport(value)
        self.generate(version=transport.V8_VERSION)
        path = self.root / 'local-contract-error.json'
        original = json.loads(path.read_bytes())
        changed = dict(original, rule='WHITESPACE_OR_BLANK', field='overview.text')
        cases = [changed, dict(changed, schema_version=transport.LOCAL_CONTRACT_DETAIL_OBSERVATION_VERSION)]
        for data in cases:
            data['observation_sha256'] = sha256_bytes(canonical_json_bytes(
                {k:v for k,v in data.items() if k != 'observation_sha256'}))
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(data))
            with self.assertRaises(ValueError):
                self.observe()
        self.assertEqual(len(self.fixture.calls), 1)

    def test_callback_classifier_never_retains_unknown_or_hostile_exception_strings(self):
        secret = '/PRIVATE_PATH PRIVATE_MODEL_TEXT API_KEY=secret'
        errors = [(ContractValidationError(secret), 'CONTRACT_REJECTED'),
                  (ValueError(secret), 'VALUE_REJECTED'), (TypeError(secret), 'TYPE_REJECTED'),
                  (KeyError(secret), 'REQUIRED_VALUE_MISSING'), (RuntimeError(secret), 'VALIDATOR_FAILURE')]
        for index, (error, expected) in enumerate(errors):
            self.root = Path(self.tmp.name) / str(index)
            self.fixture = FixtureTransport()
            with patch.object(transport, '_validate_response', side_effect=error):
                self.assertEqual(self.generate()['status'], 'REJECTED')
            observed = self.observe()
            self.assertEqual(observed['reason'], expected)
            files = ''.join(p.read_text() for p in self.root.iterdir() if p.is_file())
            self.assertNotIn(secret, files)
            for disallowed in ('PRIVATE_MODEL_TEXT', 'private_path', 'exception_message', 'generated_token_count'):
                self.assertNotIn(disallowed, (self.root / 'local-contract-error.json').read_text())

    def test_classifier_exact_known_messages_only_and_fixed_fallbacks(self):
        known = {
            'overview.evidence_ids contains duplicate evidence IDs': 'DUPLICATE_CITATIONS',
            'review.evidence_ids contains duplicate evidence IDs': 'DUPLICATE_CITATIONS',
            'duplicate theme review': 'THEME_COVERAGE',
            'challenge must cover every draft theme exactly once': 'THEME_COVERAGE',
            'missing_evidence contains duplicate text': 'DUPLICATE_TEXT',
            'overall_limitations contains duplicate text': 'DUPLICATE_TEXT',
            'reviews must contain 0 to 0 entries': 'THEME_COVERAGE',
            'reviews must contain 3 to 3 entries': 'THEME_COVERAGE',
            'review.reason must be a nonblank string without surrounding whitespace': 'TEXT_FORMAT',
            'implication.trading contains unsupported characters or exceeds 300 characters': 'TEXT_FORMAT',
        }
        for message, reason in known.items():
            self.assertEqual(transport._local_contract_reason(ContractValidationError(message)), reason)
            self.assertEqual(transport._local_contract_reason(ContractValidationError(message + ' PRIVATE_VALUE')),
                             'CONTRACT_REJECTED')
        self.assertEqual(transport._local_contract_reason(ContractValidationError({'unknown':'PRIVATE_VALUE'})),
                         'CONTRACT_REJECTED')

    def test_tampered_or_private_observation_is_rejected_even_with_recomputed_self_hash(self):
        self.fixture = FixtureTransport(self.invalid_response())
        self.generate()
        path = self.root / 'local-contract-error.json'
        original = json.loads(path.read_bytes())
        cases = []
        for field, value in [('schema_version', 'unknown'), ('stage', 'MODEL_OUTPUT'),
                             ('reason', 'PRIVATE_PATH'), ('reason', []),
                             ('request_sha256', 'f'*64), ('request_id', 'another-request'),
                             ('receipt_sha256', 'f'*64), ('model', '/private/model'),
                             ('generated_token_count', 4096)]:
            changed = copy.deepcopy(original); changed[field] = value; cases.append(changed)
        changed = copy.deepcopy(original); changed.pop('stage'); cases.append(changed)
        for changed in cases:
            changed['observation_sha256'] = sha256_bytes(canonical_json_bytes(
                {k:v for k,v in changed.items() if k != 'observation_sha256'}))
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(changed))
            with self.assertRaises(ValueError):
                self.observe()
        self.assertEqual(len(self.fixture.calls), 1)

    def test_mismatched_receipt_hash_and_noncanonical_observation_fail_closed(self):
        self.fixture = FixtureTransport(self.invalid_response())
        self.generate()
        path = self.root / 'local-contract-error.json'
        original = path.read_bytes()
        path.chmod(0o600); path.write_bytes(original + b'\n')
        with self.assertRaises(ValueError):
            self.observe()
        path.write_bytes(original)
        receipt = self.root / 'receipt.json'
        data = json.loads(receipt.read_bytes()); data['failure_code'] = 'MODELDOCK_FAILED'
        data['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k:v for k,v in data.items()
                                                                if k != 'receipt_sha256'}))
        receipt.chmod(0o600); receipt.write_bytes(canonical_json_bytes(data))
        with self.assertRaises(ValueError):
            self.observe()

    def test_no_diagnostic_for_uninvoked_callback_or_gate_failure(self):
        self.fixture = FixtureTransport(mutate=lambda envelope: envelope.update(provider='cloud'))
        self.assertEqual(self.generate()['status'], 'FAILED')
        self.assertIsNone(self.observe())
        self.root = Path(self.tmp.name) / 'gate-failure'
        self.fixture = FixtureTransport(self.invalid_response())
        self.assertEqual(transport.generate_role('oracle', packet(), self.root, self.config,
            off_check=lambda: True if not self.fixture.calls else False, verify_source=lambda: None,
            client_factory=self.factory, now=lambda: NOW)['failure_code'], 'VALIDATION_OR_GATE_FAILED')
        self.assertIsNone(self.observe())

    def test_missing_optional_sidecar_after_interrupted_publication_never_resends_or_backfills(self):
        self.fixture = FixtureTransport(self.invalid_response())
        publish = transport._publish
        def interrupted(root, staging, name, value):
            if name == 'local-contract-error.json':
                raise OSError('private interrupted publication')
            return publish(root, staging, name, value)
        with patch.object(transport, '_publish', side_effect=interrupted):
            result = self.generate()
        self.assertEqual(result['status'], 'REJECTED')
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertIsNone(self.observe())
        self.assertEqual(self.generate(), result)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(len(self.fixture.calls), 1)

    def test_old_role_rejects_new_sidecar_and_orphan_sidecar_cannot_trigger_delivery(self):
        self.fixture = FixtureTransport(self.invalid_response())
        self.generate()
        value = json.loads((self.root / 'local-contract-error.json').read_bytes())
        self.root = Path(self.tmp.name) / 'old-v7'
        self.generate(version=transport.V7_VERSION)
        wire = json.loads((self.root / 'intent.json').read_bytes())['wire_request']
        value.update(request_sha256=sha256_bytes(canonical_json_bytes(wire)),
            request_id=wire['metadata']['blackpod_correlation']['request_id'],
            receipt_sha256=sha256_bytes((self.root / 'receipt.json').read_bytes()))
        value['observation_sha256'] = sha256_bytes(canonical_json_bytes({k:v for k,v in value.items()
                                                                     if k != 'observation_sha256'}))
        transport.write_json_once(self.root, 'local-contract-error.json', value)
        with self.assertRaises(ValueError):
            self.observe()
        self.root = Path(self.tmp.name) / 'orphan'
        transport.write_json_once(self.root, 'local-contract-error.json', value)
        before = len(self.fixture.calls)
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(len(self.fixture.calls), before)


class SentryHttpErrorObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'role'
        self.config = ModelDockConfig('http://127.0.0.1:8000', 60, delivery_grace_seconds=5)
        self.code, self.status = 'INFERENCE_FAILURE', 500
        self.error_details = [{'private_path': '/PRIVATE_MODEL_PATH', 'text': 'PRIVATE_MODEL_OUTPUT'}]
        self.foreign_id, self.raw_override, self.declared = None, None, 'AUTO'
        self.read_failure, self.expire_after_headers, self.read_advance = None, False, 0
        self.clock = 0
        self.calls, self.streams = [], []
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        original_client = ModelDockClient
        self.enterContext(patch.object(transport, 'ModelDockClient', side_effect=lambda config, **kw:
            original_client(config, now=lambda: NOW, monotonic=lambda: self.clock, **kw)))
        self.enterContext(patch.object(transport, 'UrlLibTransport', side_effect=lambda:
            UrlLibTransport(monotonic=lambda: self.clock)))
        self.enterContext(patch('blackpod_build_week.modeldock_client.urllib.request.build_opener',
            return_value=Mock(open=self.opened)))

    def opened(self, request, timeout):
        self.calls.append((request, timeout))
        wire = json.loads(request.data)
        identity = wire['metadata']['blackpod_correlation']['request_id']
        envelope = {'error': {'code': self.code, 'request_id': self.foreign_id or identity,
            'message': 'PRIVATE_ERROR_MESSAGE sk-proj-fixture-not-real',
            'details': self.error_details}}
        raw = self.raw_override if self.raw_override is not None else canonical_json_bytes(envelope)
        owner = self
        class ErrorBody(BytesIO):
            def __init__(self, body):
                super().__init__(body)
                self.read_sizes, self.supplied, self.timeouts = [], 0, []
            def settimeout(self, remaining):
                self.timeouts.append(remaining)
            def read(self, count=-1):
                self.read_sizes.append(count)
                if owner.read_failure:
                    raise owner.read_failure
                result = super().read(count)
                self.supplied += len(result)
                owner.clock += owner.read_advance
                return result
        stream = ErrorBody(raw)
        self.streams.append(stream)
        headers = {'Content-Type': 'application/json', 'X-Request-ID': identity}
        if self.declared == 'AUTO':
            headers['Content-Length'] = str(len(raw))
        elif self.declared is not None:
            headers['Content-Length'] = self.declared
        if self.expire_after_headers:
            self.clock = timeout - 0.5
        raise HTTPError(request.full_url, self.status, 'PRIVATE_HTTP_REASON', headers, stream)

    def generate(self, **changes):
        return transport.generate_role('oracle', packet(), self.root, self.config,
            off_check=lambda: None, verify_source=lambda: None, now=lambda: NOW, **changes)

    def observation(self):
        return transport.read_error_observation('oracle', packet(), self.root, self.config)

    def test_v10_http_error_observation_is_bound_and_read_without_resend(self):
        self.config = ModelDockConfig('http://127.0.0.1:8000',900,delivery_grace_seconds=30)
        result = self.generate(version=transport.SYMBOL_VERSION)
        self.assertEqual(result['failure_code'],'MODELDOCK_HTTP_500')
        self.assertEqual(json.loads((self.root/'receipt.json').read_bytes())['schema_version'],transport.SYMBOL_VERSION)
        observation = self.observation()
        self.assertEqual(observation['code'],'INFERENCE_FAILURE')
        self.assertEqual(observation['request_id'],result['request_id'])
        self.assertEqual(observation['receipt_sha256'],sha256_bytes((self.root/'receipt.json').read_bytes()))
        with patch.object(transport,'_default_client',side_effect=AssertionError('no resend')):
            self.assertEqual(self.generate(version=transport.SYMBOL_VERSION),result)
            self.assertEqual(transport.read_role('oracle',packet(),self.root,self.config),result)
            self.assertEqual(self.observation(),observation)
        self.assertEqual(len(self.calls),1)

    def test_actual_urllib_http_error_stream_retains_only_correlated_safe_metadata(self):
        result = self.generate()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
        saved = self.observation()
        self.assertEqual(saved['status'], 'AVAILABLE')
        self.assertEqual(saved['code'], 'INFERENCE_FAILURE')
        self.assertEqual(saved['http_status'], 500)
        self.assertEqual(saved['request_id'], result['request_id'])
        self.assertTrue(saved['body_complete'])
        request = self.calls[0][0]
        self.assertEqual(saved['request_sha256'], sha256_bytes(request.data))
        self.assertEqual(saved['receipt_sha256'], sha256_bytes((self.root / 'receipt.json').read_bytes()))
        self.assertEqual(request.get_header('X-modeldock-client'), 'BlackPod-Sentry')
        self.assertTrue(self.streams[0].closed)
        self.assertTrue(self.streams[0].timeouts)
        self.assertTrue(all(0 < t <= self.config.delivery_timeout_seconds for t in self.streams[0].timeouts))
        for path in self.root.rglob('*'):
            if path.is_file():
                raw = path.read_bytes()
                for private in (b'PRIVATE_ERROR_MESSAGE', b'PRIVATE_MODEL_PATH', b'PRIVATE_MODEL_OUTPUT', b'PRIVATE_HTTP_REASON'):
                    self.assertNotIn(private, raw)

    def test_sidecar_does_not_change_role_result_or_receipt_and_retry_is_provider_free(self):
        first = self.generate()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch.object(transport, '_default_client', side_effect=AssertionError('no inference on replay')):
            self.assertEqual(self.generate(), first)
            self.assertEqual(transport.read_role('oracle', packet(), self.root, self.config), first)
            self.assertEqual(self.observation()['code'], 'INFERENCE_FAILURE')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertNotIn('error_observation', first)
        self.assertNotIn('http-error', (self.root / 'receipt.json').read_text())

    def test_unknown_code_and_mismatched_id_never_retain_untrusted_strings(self):
        for index, (code, identity) in enumerate([('PRIVATE_SECRET_CODE', None), ('INFERENCE_FAILURE', 'PRIVATE_FOREIGN_ID'),
                                                 ({'private': 'PRIVATE_CODE_OBJECT'}, None)]):
            self.root = Path(self.tmp.name) / str(index)
            self.code, self.foreign_id = code, identity
            self.assertEqual(self.generate()['failure_code'], 'MODELDOCK_HTTP_500')
            value = self.observation()
            self.assertEqual(value['status'], 'UNAVAILABLE')
            self.assertIsNone(value['code'])
            self.assertTrue(value['body_complete'])
            self.assertNotIn('PRIVATE_', json.dumps(value))

    def test_malformed_duplicate_keys_or_non_json_envelope_has_no_code(self):
        cases = [b'<html>PRIVATE_ERROR_BODY</html>', b'{"error":{},"error":{}}', b'{"error":NaN}', b'[]']
        for index, raw in enumerate(cases):
            self.root = Path(self.tmp.name) / str(index)
            self.raw_override = raw
            self.generate()
            value = self.observation()
            self.assertEqual(value['status'], 'UNAVAILABLE')
            self.assertIsNone(value['code'])
            self.assertTrue(value['body_complete'])
            self.assertEqual(value['body_sha256'], sha256_bytes(raw))
            self.assertEqual(value['size_bytes'], len(raw))

    def test_oversize_and_declared_size_mismatch_never_claim_complete_body_hash(self):
        cases = [(b'x' * 8193, None), (b'{}', '100'), (b'{}', 'invalid'), (b'{}', '8193')]
        for index, (raw, declared) in enumerate(cases):
            self.root = Path(self.tmp.name) / str(index)
            self.raw_override, self.declared = raw, declared
            self.assertEqual(self.generate()['failure_code'], 'MODELDOCK_HTTP_500')
            value = self.observation()
            self.assertEqual(value['status'], 'UNAVAILABLE')
            self.assertFalse(value['body_complete'])
            self.assertIsNone(value['body_sha256'])
            self.assertIsNone(value['size_bytes'])
            self.assertLessEqual(self.streams[-1].supplied, 8193)

    def test_deadline_and_read_failure_preserve_original_http_status_without_retry(self):
        for index, failure in enumerate([TimeoutError('PRIVATE_TIMEOUT'), OSError('PRIVATE_SOCKET')]):
            self.root = Path(self.tmp.name) / str(index)
            self.read_failure = failure
            result = self.generate()
            self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
            self.assertEqual(self.observation()['status'], 'UNAVAILABLE')
            self.assertFalse(self.observation()['body_complete'])
        self.root = Path(self.tmp.name) / 'expired'
        self.read_failure, self.expire_after_headers = None, True
        self.assertEqual(self.generate()['failure_code'], 'MODELDOCK_HTTP_500')
        self.assertEqual(self.streams[-1].supplied, 0)
        self.assertEqual(self.observation()['status'], 'UNAVAILABLE')
        self.assertEqual(len(self.calls), 3)

    def test_slow_error_body_has_two_second_diagnostic_cap_without_masking_http_failure(self):
        self.read_advance = 2.1
        result = self.generate()
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
        value = self.observation()
        self.assertEqual(value['status'], 'UNAVAILABLE')
        self.assertFalse(value['body_complete'])
        self.assertIsNone(value['body_sha256'])
        self.assertLessEqual(self.streams[-1].timeouts[0], 2)
        self.assertEqual(len(self.calls), 1)

    def test_near_delivery_deadline_skips_diagnostic_read_and_preserves_http_status(self):
        self.expire_after_headers = True
        result = self.generate()
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
        self.assertEqual(self.streams[-1].read_sizes, [])
        self.assertEqual(self.observation()['status'], 'UNAVAILABLE')
        self.assertEqual(len(self.calls), 1)

    def test_tampered_metadata_fails_closed_even_when_self_hash_recomputed(self):
        self.generate()
        path = self.root / 'http-error.json'
        original = json.loads(path.read_bytes())
        for field, value in [('request_sha256', '0' * 64), ('receipt_sha256', '0' * 64), ('http_status', 503),
                             ('request_id', 'wrong-request'), ('code', 'PRIVATE_SECRET_CODE')]:
            changed = copy.deepcopy(original)
            changed[field] = value
            changed['observation_sha256'] = sha256_bytes(canonical_json_bytes({k: v for k, v in changed.items() if k != 'observation_sha256'}))
            path.chmod(0o600)
            path.write_bytes(canonical_json_bytes(changed))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.observation()
        self.assertEqual(len(self.calls), 1)

    def test_optional_diagnostic_write_failure_does_not_erase_http_failure_or_resend(self):
        original = transport._publish
        def interrupted(root, staging, name, value):
            if name == 'http-error.json':
                raise OSError('fixture optional metadata publication failure')
            return original(root, staging, name, value)
        with patch.object(transport, '_publish', side_effect=interrupted):
            result = self.generate()
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
        self.assertIsNone(self.observation())
        self.assertEqual(self.generate(), result)
        self.assertEqual(len(self.calls), 1)

    def test_old_failures_are_never_backfilled_or_resent(self):
        class EmptyHttpFailure:
            def request(self, **kwargs):
                return HttpResponse(500, {}, b'', complete=False)
        for index, version in enumerate((transport.LEGACY_VERSION, transport.V2_VERSION,
                                         transport.V3_VERSION, transport.V4_VERSION, transport.V5_VERSION,
                                         transport.V6_VERSION, transport.V7_VERSION, transport.V8_VERSION,
                                         transport.VERSION, transport.SYMBOL_VERSION)):
            self.root = Path(self.tmp.name) / str(index)
            result = self.generate(version=version, client_factory=lambda config:
                ModelDockClient(config, transport=EmptyHttpFailure(), now=lambda: NOW))
            self.assertEqual(result['status'], 'FAILED')
            before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
            with patch.object(transport, '_default_client', side_effect=AssertionError('no historical retry')):
                self.assertEqual(self.generate(), result)
                self.assertIsNone(self.observation())
            self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertEqual(self.calls, [])

    def test_safe_closed_structured_diagnostic_is_versioned_and_receipt_bound_without_private_strings(self):
        self.code = 'STRUCTURED_OUTPUT_INVALID'
        self.error_details = [validation_diagnostic()]
        result = self.generate()
        saved = self.observation()
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['failure_code'], 'MODELDOCK_HTTP_500')
        self.assertEqual(saved['schema_version'], transport.ERROR_DETAIL_OBSERVATION_VERSION)
        self.assertEqual(saved['code'], 'STRUCTURED_OUTPUT_INVALID')
        self.assertEqual(saved['validation_diagnostic'], validation_diagnostic())
        self.assertEqual(saved['request_id'], result['request_id'])
        self.assertEqual(saved['receipt_sha256'], sha256_bytes((self.root/'receipt.json').read_bytes()))
        before = {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay inference')):
            self.assertEqual(self.generate(), result)
            self.assertEqual(self.observation(), saved)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        for path in self.root.rglob('*'):
            if path.is_file():
                for private in (b'PRIVATE_ERROR_MESSAGE', b'sk-proj-fixture-not-real', b'PRIVATE_HTTP_REASON',
                                b'PRIVATE_MODEL_OUTPUT', b'PRIVATE_MODEL_PATH'):
                    self.assertNotIn(private, path.read_bytes())
        self.assertNotIn('validation_diagnostic', result)

    def test_all_closed_reason_categories_preserve_only_known_semantics(self):
        for index, reason in enumerate(sorted(transport.VALIDATION_REASONS)):
            self.root = Path(self.tmp.name)/str(index)
            self.code = 'STRUCTURED_OUTPUT_INVALID'
            detail = validation_diagnostic(reason=reason,
                schema_keyword='type' if reason == 'SCHEMA_VIOLATION' else None)
            if reason == 'MOCK_OUTPUT':
                detail.update(generated_token_count=None, generated_token_count_source='unavailable',
                              stop_reason='unknown', stop_reason_source='unavailable')
            self.error_details = [detail]
            self.generate()
            with self.subTest(reason=reason): self.assertEqual(self.observation()['validation_diagnostic'], detail)

    def test_safe_schema_keywords_are_finite_and_never_paths_or_schema_values(self):
        for keyword in transport.VALIDATION_KEYWORDS | {None}:
            detail = validation_diagnostic(reason='SCHEMA_VIOLATION', schema_keyword=keyword)
            self.assertEqual(transport._validation_diagnostic(detail), detail)
        for keyword in ('/themes/0/PRIVATE_SCHEMA_PATH', 'PRIVATE_PROPERTY_NAME', ['type'], {'type': 'private'}):
            self.assertIsNone(transport._validation_diagnostic(
                validation_diagnostic(reason='SCHEMA_VIOLATION', schema_keyword=keyword)))

    def test_unavailable_count_and_stop_remain_unknown_with_independent_native_fields(self):
        cases = [validation_diagnostic(generated_token_count=None, generated_token_count_source='unavailable',
                                      stop_reason='unknown', stop_reason_source='unavailable'),
                 validation_diagnostic(generated_token_count=0, stop_reason='stop'),
                 validation_diagnostic(generated_token_count=2**63-1, stop_reason='unknown', stop_reason_source='unavailable'),
                 validation_diagnostic(generated_token_count=None, generated_token_count_source='unavailable', stop_reason='stop')]
        for index, detail in enumerate(cases):
            self.root = Path(self.tmp.name)/str(index)
            self.code, self.error_details = 'STRUCTURED_OUTPUT_INVALID', [detail]
            self.generate()
            with self.subTest(detail=detail): self.assertEqual(self.observation()['validation_diagnostic'], detail)

    def test_malformed_extra_or_private_details_are_ignored_without_changing_code_only_schema(self):
        invalid_details = [None, [], {}, 'PRIVATE_DETAILS', [validation_diagnostic(), validation_diagnostic()], [{}],
            [validation_diagnostic(private_path='/PRIVATE_MODEL_PATH')],
            [validation_diagnostic(schema='PRIVATE_SCHEMA')], [validation_diagnostic(stage='PRIVATE_STAGE')],
            [validation_diagnostic(reason='PRIVATE_REASON')], [validation_diagnostic(reason=['JSON_SYNTAX'])],
            [validation_diagnostic(schema_keyword='type')], [validation_diagnostic(generated_token_count=True)],
            [validation_diagnostic(generated_token_count=2500.0)], [validation_diagnostic(generated_token_count=-1)],
            [validation_diagnostic(generated_token_count=2**63)], [validation_diagnostic(generated_token_count=None)],
            [validation_diagnostic(generated_token_count_source='estimated')],
            [validation_diagnostic(generated_token_count_source='unavailable')],
            [validation_diagnostic(stop_reason='unknown')], [validation_diagnostic(stop_reason='PRIVATE_STOP')],
            [validation_diagnostic(stop_reason_source='inferred')], [validation_diagnostic(stop_reason_source='unavailable')],
            [validation_diagnostic(reason='MOCK_OUTPUT')]]
        for index, details in enumerate(invalid_details):
            self.root = Path(self.tmp.name)/str(index)
            self.code, self.error_details = 'STRUCTURED_OUTPUT_INVALID', details
            self.generate()
            saved = self.observation()
            with self.subTest(details=details):
                self.assertEqual(saved['status'], 'AVAILABLE')
                self.assertEqual(saved['code'], 'STRUCTURED_OUTPUT_INVALID')
                self.assertEqual(saved['schema_version'], transport.ERROR_OBSERVATION_VERSION)
                self.assertNotIn('validation_diagnostic', saved)
                self.assertNotIn('PRIVATE_', json.dumps(saved))

    def test_safe_detail_requires_complete_correlated_http500_structured_output_failure(self):
        for index, (code, status, foreign, advance) in enumerate([
                ('INFERENCE_FAILURE', 500, None, 0), ('STRUCTURED_OUTPUT_INVALID', 422, None, 0),
                ('STRUCTURED_OUTPUT_INVALID', 500, 'foreign-request', 0),
                ('STRUCTURED_OUTPUT_INVALID', 500, None, 2.1)]):
            self.root = Path(self.tmp.name)/str(index)
            self.code, self.status, self.foreign_id, self.read_advance = code, status, foreign, advance
            self.error_details = [validation_diagnostic()]
            self.generate()
            with self.subTest(code=code, status=status, foreign=foreign, advance=advance):
                saved = self.observation()
                self.assertEqual(saved['schema_version'], transport.ERROR_OBSERVATION_VERSION)
                self.assertNotIn('validation_diagnostic', saved)

    def test_detailed_sidecar_tampering_fails_closed_even_with_recomputed_self_hash(self):
        self.code, self.error_details = 'STRUCTURED_OUTPUT_INVALID', [validation_diagnostic()]
        self.generate()
        path = self.root/'http-error.json'
        original = json.loads(path.read_bytes())
        cases = []
        for field, value in [('request_sha256', '0'*64), ('receipt_sha256', '0'*64),
                             ('request_id', 'wrong-request'), ('http_status', 422), ('status', 'UNAVAILABLE'),
                             ('code', 'INFERENCE_FAILURE'), ('body_complete', False)]:
            changed = copy.deepcopy(original); changed[field] = value; cases.append(changed)
        for field, value in [('reason', 'PRIVATE_REASON'), ('schema_keyword', 'type'),
                             ('generated_token_count', True), ('generated_token_count_source', 'estimated'),
                             ('stop_reason', 'eos'), ('stop_reason_source', 'inferred')]:
            changed = copy.deepcopy(original); changed['validation_diagnostic'][field] = value; cases.append(changed)
        changed = copy.deepcopy(original); changed['validation_diagnostic']['private'] = 'PRIVATE_VALUE'; cases.append(changed)
        changed = copy.deepcopy(original); changed['schema_version'] = transport.ERROR_OBSERVATION_VERSION; cases.append(changed)
        changed = copy.deepcopy(original); del changed['validation_diagnostic']; cases.append(changed)
        for changed in cases:
            changed['observation_sha256'] = sha256_bytes(canonical_json_bytes({k:v for k,v in changed.items() if k!='observation_sha256'}))
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(changed))
            with self.subTest(changed=changed), self.assertRaises(ValueError): self.observation()
        self.assertEqual(len(self.calls), 1)

    def test_legacy_code_only_sidecar_bytes_are_unchanged_and_never_gain_new_fields(self):
        result = self.generate(version=transport.V4_VERSION)
        path = self.root/'http-error.json'
        before = path.read_bytes()
        self.assertEqual(json.loads(before)['schema_version'], transport.ERROR_OBSERVATION_VERSION)
        self.assertNotIn(b'validation_diagnostic', before)
        with patch.object(transport, '_default_client', side_effect=AssertionError('no replay calls')):
            self.assertEqual(self.generate(), result)
            self.assertIsNone(self.observation().get('validation_diagnostic'))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.calls), 1)

    def test_unbound_sidecar_cannot_trigger_a_new_delivery(self):
        transport.write_json_once(self.root, 'http-error.json', {'fake': 'metadata without a request'})
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
