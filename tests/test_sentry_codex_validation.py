"""Authored complete Codex capsules; no inference, credentials or broker calls."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_codex_validation as validation
from blackpod_build_week import sentry_modeldock_codex as provider
from blackpod_build_week import sentry_synthesis_transport as transport
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.modeldock_client import HttpResponse
from blackpod_build_week.sentry_synthesis import compose_report
from blackpod_build_week.sentry_synthesis_presentation import render
from test_sentry_codex_contracts import full_packet, array_draft, WATCHLIST
from test_sentry_modeldock_codex import envelope, known, ReadinessTransport
from test_sentry_synthesis_contracts import challenge

NOW = datetime(2026, 10, 20, 18, 0, 3, tzinfo=timezone.utc)


class CodexQualificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / 'proof'
        self.config = {k: str(base / k) for k in ('station_root', 'runtime_root',
                       'experiment_root', 'historical_root', 'ui_root')}
        self.config.update(credentials_file=str(base / 'private/keys.yaml'),
                           experiment_id='frozen-pilot', protocol_sha256='a' * 64)
        self.packet = full_packet()
        self.packet.update(as_of='2026-10-18T15:00:00Z', evidence_signature='f' * 64,
                           quality={'news_truncated': True}, limitations=['SINGLE_PROVIDER'],
                           portfolio={'status': 'NO_VERIFIED_HOLDINGS'}, authority={})
        self.dock = provider.SentryCodexConfig('http://localhost:8000', 900)
        self.calls = []
        self.bad_oracle = False
        self.bad_challenge = False
        self.interrupt = False
        self.source = self.enterContext(patch('blackpod_build_week.sentry_synthesis.verify_packet'))
        self.pins = self.enterContext(patch('blackpod_build_week.shadow_station_collection._pinned_view'))
        self.off = self.enterContext(patch('blackpod_build_week.shadow_station_collection._off'))
        self.enterContext(patch('blackpod_build_week.sentry_catalyst.control', return_value={'symbols': WATCHLIST}))
        owner = self

        class CapturingTransport:
            def __init__(self, capture=None):
                self.capture = capture

            def request(self, **kwargs):
                owner.calls.append(kwargs)
                if owner.interrupt:
                    raise KeyboardInterrupt()
                wire = json.loads(kwargs['body'])
                supplied = json.loads(wire['messages'][1]['content'])
                original = supplied.get('original_oracle_draft')
                content = challenge(original) if original else array_draft(supplied['evidence_packet'], symbols=['SPY'])
                if owner.bad_oracle and original is None:
                    content['themes'][0]['implications'].append(deepcopy(content['themes'][0]['implications'][0]))
                if owner.bad_challenge and original is not None:
                    content['reviews'].append(deepcopy(content['reviews'][0]))
                value = envelope()
                value['metadata']['blackpod_correlation'] = wire['metadata']['blackpod_correlation']
                for key in ('started_at', 'completed_at'):
                    value['metadata']['execution_provenance'][key] = known(NOW.isoformat(), 'execution_boundary')
                value['content'] = canonical_json_bytes(content).decode()
                raw = canonical_json_bytes(value)
                result = HttpResponse(200, {'Content-Length': str(len(raw))}, raw)
                if self.capture:
                    self.capture(kwargs['body'], result)
                return result

        self.enterContext(patch.object(transport, '_NamedSentryTransport', CapturingTransport))
        real_client = provider.CodexSentryClient
        self.enterContext(patch.object(provider, 'CodexSentryClient', side_effect=lambda config, **kw:
            real_client(config, **kw, readiness_transport=ReadinessTransport(), now=lambda: NOW)))

    def capture(self):
        return validation.capture(self.config, self.packet, self.root, self.dock, now=NOW)

    def test_real_client_fixture_capture_and_network_free_replay(self):
        proof = self.capture()
        self.assertEqual(proof['watchlist'], WATCHLIST)
        self.assertEqual(len(self.calls), 2)
        with patch.object(provider.UrlLibTransport, 'request', side_effect=AssertionError('no network')):
            self.assertEqual(validation.verify_qualification(self.root), proof)
        self.assertTrue(self.off.called and self.pins.called and self.source.called)
        self.assertEqual(transport.CODEX_ECONOMIC_VERSION, 'blackpod.sentry_synthesis_transport.v18')

    def test_repeated_capture_only_reads_original_pair(self):
        first = self.capture()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*.json')}
        self.assertEqual(self.capture(), first)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*.json')})

    def test_conflicting_packet_or_config_never_reuses_success_or_sends(self):
        self.capture()
        self.packet['as_of'] = '2026-10-18T15:01:00Z'
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.capture()
        self.packet['as_of'] = '2026-10-18T15:00:00Z'
        self.dock = provider.SentryCodexConfig('http://localhost:8000', 899)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.capture()
        self.assertEqual(len(self.calls), 2)

    def test_rehashed_non_success_http_status_cannot_qualify(self):
        self.capture()
        raw_path = self.root / 'oracle/raw-response.json'
        value = json.loads(raw_path.read_bytes()); value['http_status'] = 500
        raw = canonical_json_bytes(value)
        raw_path.chmod(0o600); raw_path.write_bytes(raw)
        receipt_path = self.root / 'oracle/receipt.json'
        receipt = json.loads(receipt_path.read_bytes())
        receipt['raw_response_capture_sha256'] = sha256_bytes(raw)
        receipt['receipt_sha256'] = sha256_bytes(canonical_json_bytes({k:v for k,v in receipt.items() if k != 'receipt_sha256'}))
        receipt_path.chmod(0o600); receipt_path.write_bytes(canonical_json_bytes(receipt))
        with self.assertRaises(ValueError):
            validation.verify_qualification(self.root)

    def test_rejected_oracle_blocks_challenge_and_cannot_be_resent(self):
        self.bad_oracle = True
        with self.assertRaises(ValueError):
            self.capture()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.root / 'challenge').exists())
        with self.assertRaises(ValueError):
            self.capture()
        self.assertEqual(len(self.calls), 1)

    def test_interruption_preserves_reservation_and_never_resends(self):
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.capture()
        self.assertTrue((self.root / 'oracle/intent.json').exists())
        with self.assertRaises(ValueError):
            self.capture()
        self.assertEqual(len(self.calls), 1)

    def test_wrong_watchlist_is_blocked_before_reservation(self):
        self.packet['watchlist'] = self.packet['watchlist'][:-1]
        with self.assertRaises(ValueError):
            self.capture()
        self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_off_and_pin_failures_block_before_any_post(self):
        for gate in (self.off, self.pins):
            with self.subTest(gate=gate):
                gate.side_effect = ValueError('blocked')
                with self.assertRaises(ValueError):
                    self.capture()
                gate.side_effect = None
                self.assertEqual(self.calls, [])

    def test_packet_tamper_invalidates_qualification(self):
        self.capture()
        path = self.root / 'packet.json'
        value = json.loads(path.read_bytes()); value['as_of'] = '2026-10-14T00:00:00Z'
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            validation.verify_qualification(self.root)

    def test_missing_raw_evidence_cannot_qualify(self):
        self.capture()
        (self.root / 'oracle/raw-response.json').unlink()
        with self.assertRaises((ValueError, OSError, RuntimeError)):
            validation.verify_qualification(self.root)

    def test_raw_tamper_cannot_qualify(self):
        self.capture()
        path = self.root / 'oracle/raw-response.json'
        value = json.loads(path.read_bytes()); value['body_base64'] = 'e30='
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            validation.verify_qualification(self.root)

    def test_new_wire_and_challenge_retain_original_array_and_hash(self):
        self.capture()
        original = json.loads((self.root / 'oracle/receipt.json').read_bytes())['response']
        wire = json.loads(self.calls[1]['body'])
        supplied = json.loads(wire['messages'][1]['content'])
        self.assertEqual(supplied['original_oracle_draft'], original)
        self.assertIn('implications', original['themes'][0])
        self.assertNotIn('implications_by_symbol', original['themes'][0])
        self.assertEqual(wire['response_format']['schema']['properties']['draft_sha256']['const'],
                         sha256_bytes(canonical_json_bytes(original)))
        oracle_wire = json.loads(self.calls[0]['body'])
        self.assertNotIn('use implications_by_symbol', oracle_wire['messages'][0]['content'])
        self.assertEqual(oracle_wire['response_format']['schema']['properties']['schema_version']['const'],
                         'blackpod.sentry_oracle_draft.v5')

    def test_report_and_ui_keep_actual_model_and_authority_disabled(self):
        self.capture()
        oracle = transport.read_role('oracle', self.packet, self.root / 'oracle', self.dock,
                                      version=transport.CODEX_ECONOMIC_VERSION)
        review = transport.read_role('challenge', self.packet, self.root / 'challenge', self.dock,
                                      draft=oracle['response'], version=transport.CODEX_ECONOMIC_VERSION)
        report = compose_report(self.packet, oracle, review, NOW.isoformat())
        self.assertEqual(report['draft'], oracle['response'])
        self.assertIn('analytical_quality', report)
        self.assertFalse(any(report['authority'].values()))
        html = render({'status': report['status'], 'report': report, 'auto_trading': 'OFF'})
        self.assertIn('gpt-fixture', html)
        self.assertIn('codex-app-server', html)
        self.assertIn('Max tokens enforced', html)
        self.assertIn('Actual Codex model', html)
        self.assertIn('Registry alias', html)

    def test_ui_distinguishes_scheduled_route_from_retained_report_and_escapes_it(self):
        value = {'status': 'NOT_GENERATED', 'report': None, 'auto_trading': 'OFF',
                 'operational': {'enabled': True, 'provider_policy': {'provider': 'codex',
                    'prompt_version': 'ECONOMIC_V4', 'monitoring': 'WEEKDAY_BOUNDED'}}}
        html = render(value)
        self.assertIn('Scheduled route: ModelDock → codex (cloud)', html)
        self.assertIn('Model provenance below belongs to the retained report.', html)
        self.assertIn('at least one hour apart', html)
        value['operational']['provider_policy']['prompt_version'] = '<script>alert(1)</script>'
        html = render(value)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def failed_pair(self):
        self.bad_challenge = True
        with self.assertRaises(ValueError):
            self.capture()
        self.bad_challenge = False
        original = json.loads((self.root / 'challenge/receipt.json').read_bytes())
        self.assertEqual(original['status'], 'REJECTED')
        return original

    def approve_followup(self, **changes):
        plan = json.loads((self.root / 'validation.json').read_bytes())
        receipt = json.loads((self.root / 'challenge/receipt.json').read_bytes())
        value = {'schema_version': validation.FOLLOWUP_VERSION, 'authority': 'HUMAN_USER',
                 'answer': 'Approve one linked challenge request', 'max_additional_requests': 1,
                 'automatic_resends': False, 'packet_sha256': plan['packet_sha256'],
                 'original_challenge_receipt_sha256': sha256_bytes(canonical_json_bytes(receipt)), **changes}
        validation.write_json_once(self.root, 'challenge-followup-approval.json', value)

    def followup(self):
        return validation.capture_challenge(self.config, self.root, now=NOW)

    def test_one_explicit_followup_preserves_original_and_never_resends(self):
        self.failed_pair(); self.approve_followup()
        original = {str(p): p.read_bytes() for p in (self.root / 'challenge').rglob('*.json')}
        proof = self.followup()
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.followup(), proof)
        self.assertEqual(self.capture(), proof)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(original, {str(p): p.read_bytes() for p in (self.root / 'challenge').rglob('*.json')})
        self.assertEqual(validation.verify_qualification(self.root), proof)

    def test_followup_without_approval_or_with_bool_allowance_cannot_send(self):
        self.failed_pair()
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            self.followup()
        self.assertEqual(len(self.calls), 2)
        self.approve_followup(max_additional_requests=True)
        with self.assertRaises(ValueError):
            self.followup()
        self.assertFalse((self.root / 'challenge-followup.json').exists())
        self.assertEqual(len(self.calls), 2)

    def test_followup_rejects_unlinked_preexisting_role(self):
        self.failed_pair(); self.approve_followup()
        (self.root / 'challenge-followup-001').mkdir()
        with self.assertRaisesRegex(ValueError, 'unlinked'):
            self.followup()
        self.assertFalse((self.root / 'challenge-followup.json').exists())
        self.assertEqual(len(self.calls), 2)

    def test_followup_interruption_is_preserved_without_automatic_resume(self):
        self.failed_pair(); self.approve_followup()
        self.interrupt = True
        with self.assertRaises(KeyboardInterrupt):
            self.followup()
        self.assertTrue((self.root / 'challenge-followup-001/intent.json').exists())
        self.assertEqual(len(self.calls), 3)
        with self.assertRaises(ValueError):
            self.followup()
        self.assertEqual(len(self.calls), 3)

    def test_followup_role_cannot_predate_its_approval_link(self):
        self.failed_pair(); self.approve_followup(); self.followup()
        path = self.root / 'challenge-followup.json'
        value = json.loads(path.read_bytes()); value['reserved_at'] = '2026-10-20T18:00:04Z'
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(ValueError, 'predates its explicit link'):
            validation.verify_qualification(self.root)

    def test_original_failure_still_requires_full_replay_after_followup(self):
        self.failed_pair(); self.approve_followup(); self.followup()
        path = self.root / 'challenge/receipt.json'
        original = json.loads(path.read_bytes()); original['failure_code'] = 'CHANGED_WITHOUT_SELF_HASH'
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(original))
        for name in ('challenge-followup-approval.json', 'challenge-followup.json'):
            path = self.root / name
            value = json.loads(path.read_bytes())
            value['original_challenge_receipt_sha256'] = sha256_bytes(canonical_json_bytes(original))
            if name == 'challenge-followup.json':
                approval = json.loads((self.root / 'challenge-followup-approval.json').read_bytes())
                value['approval_sha256'] = sha256_bytes(canonical_json_bytes(approval))
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
        with self.assertRaises(ValueError):
            validation.verify_qualification(self.root)


if __name__ == '__main__':
    unittest.main()
