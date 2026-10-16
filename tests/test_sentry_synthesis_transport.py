"""Offline ModelDock-envelope fixtures only; no local service or providers."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import ModelDockClient, HttpResponse
from blackpod_build_week.modeldock_config import ModelDockConfig
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


def challenge():
    return {'schema_version': 'blackpod.sentry_challenge.v2', 'draft_sha256': sha256_bytes(canonical_json_bytes(draft())),
        'reviews': [{'theme_id': 'theme-1', 'status': 'UNTESTED', 'reason': 'The headline lacks fundamental context.',
            'evidence_ids': ['headline-1'], 'alternative': 'The announcement may be routine.',
            'missing_evidence': ['Original company announcement']}], 'overall_limitations': ['Same provider and evidence.']}


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
                'requested_max_tokens': 2500, 'effective_max_tokens': 2500, 'generated_token_count': 200,
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
        self.assertEqual(wire['max_tokens'], 2500)
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
        wire, bindings, configuration = transport._request('oracle', packet(), self.config, None)
        self.assertEqual(wire['timeout'], 900)
        self.assertEqual(self.config.delivery_timeout_seconds, 930)
        for field in ('messages', 'response_format', 'max_tokens', 'profile', 'capabilities'):
            self.assertEqual(wire[field], old[field])
        self.assertNotEqual(wire['metadata'], old['metadata'])
        self.assertEqual(bindings['configuration_sha256'], sha256_bytes(canonical_json_bytes(configuration)))
        self.assertNotIn('configuration_sha256', old_bindings)
        result = self.generate()
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


if __name__ == '__main__':
    unittest.main()
