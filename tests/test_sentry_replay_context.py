"""Call-scoped replay over authored historical failure ancestry; no providers."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_synthesis_service as service
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.sentry_synthesis import current_packet
import test_sentry_synthesis_service as legacy_fixtures


class CallScopedReplayTests(unittest.TestCase):
    def setUp(self):
        # Four independently reserved fixture capsules: original legacy failure,
        # timeout validation, HTTP500 diagnostic, then an accepted role pair.
        self.fixture = legacy_fixtures.ExplicitErrorDiagnosticTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.result = self.fixture.run_validation()
        self.child = self.fixture.child()
        self.entries = service.ledger(self.fixture.helper.runs)
        self.assertEqual(len(self.entries), 4)
        self.enterContext(patch.object(service, 'generate_role', side_effect=AssertionError('replay cannot generate')))
        self.enterContext(patch('urllib.request.build_opener', side_effect=AssertionError('replay cannot access network')))

    def test_one_operation_verifies_each_ancestral_capsule_and_role_pair_once(self):
        original_roles = service.retained_roles
        original_packets = service.verify_packet
        original_source = service.CatalystStore.verified_records
        with patch.object(service, 'retained_roles', wraps=original_roles) as roles, \
                patch.object(service, 'verify_packet', wraps=original_packets) as packets, \
                patch.object(service, 'ledger', wraps=service.ledger) as ledger, \
                patch.object(service.CatalystStore, 'verified_records', autospec=True,
                    side_effect=original_source) as source:
            result = service.verify(self.config)
        self.assertEqual(result['report_count'], 4)
        self.assertEqual(Counter(call.args[0] for call in roles.call_args_list),
            Counter({directory:1 for directory, *_ in self.entries}))
        # All four original validations share the exact original evidence packet.
        self.assertEqual(packets.call_count, 1)
        self.assertEqual(source.call_count, 1)
        self.assertEqual(ledger.call_count, 1)

    def test_single_report_default_is_fresh_but_deduplicates_its_ancestry(self):
        with patch.object(service, 'retained_roles', wraps=service.retained_roles) as roles:
            self.assertEqual(service.read_report(self.child, self.config), self.result)
        self.assertEqual(len(roles.call_args_list), 4)
        self.assertEqual(len({call.args[0] for call in roles.call_args_list}), 4)

    def test_cached_and_fresh_results_are_byte_identical_to_original_report(self):
        context = service._ReplayContext(self.config)
        cached = service.read_report(self.child, self.config, _context=context)
        with patch.object(service, 'retained_roles', side_effect=AssertionError('cache hit cannot replay again')):
            again = service.read_report(self.child, self.config, _context=context)
        fresh = service.read_report(self.child, self.config)
        original = (self.child / 'report.json').read_bytes()
        self.assertEqual(canonical_json_bytes(cached), original)
        self.assertEqual(canonical_json_bytes(again), original)
        self.assertEqual(canonical_json_bytes(fresh), original)

    def test_result_mutation_cannot_change_cached_report_or_retained_evidence(self):
        original = (self.child / 'report.json').read_bytes()
        context = service._ReplayContext(self.config)
        result = service.read_report(self.child, self.config, _context=context)
        result['draft']['overview']['text'] = 'Caller mutation'
        result['context']['watchlist'].append('CALLER')
        result['provenance']['oracle']['response']['themes'].clear()
        self.assertEqual(canonical_json_bytes(service.read_report(self.child, self.config, _context=context)), original)
        self.assertEqual((self.child / 'report.json').read_bytes(), original)

    def test_separate_operation_detects_tampered_oldest_ancestor(self):
        service.verify(self.config)
        oldest = self.entries[0][0] / 'report.json'
        oldest.chmod(0o600)
        oldest.write_bytes(b'{}')  # Disposable fixture corruption only.
        with self.assertRaises(ValueError):
            service.verify(self.config)
        with self.assertRaises(ValueError):
            service.read_report(self.child, self.config)

    def test_separate_operation_detects_tampered_original_source(self):
        service.verify(self.config)
        source = self.fixture.helper.store.root / 'entries/00000001.json'
        source.chmod(0o600)
        source.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            service.verify(self.config)

    def test_separate_operation_detects_tampered_role_receipt(self):
        service.read_report(self.child, self.config)
        receipt = self.entries[0][0] / 'oracle/receipt.json'
        receipt.chmod(0o600)
        receipt.write_bytes(b'{}')
        with self.assertRaises(ValueError):
            service.read_report(self.child, self.config)

    def test_context_cannot_cross_configuration_boundaries(self):
        context = service._ReplayContext(self.config)
        service.read_report(self.child, self.config, _context=context)
        other = deepcopy(self.config)
        other['runtime_root'] = str(Path(self.config['runtime_root']).with_name('other-runtime'))
        with self.assertRaisesRegex(ValueError, 'another operation configuration'):
            service.read_report(self.child, other, _context=context)

    def test_current_packet_can_reuse_exact_fresh_source_snapshot_without_rereading(self):
        source = service.CatalystStore(service.catalyst_paths(self.config)[1]).verified_records()
        clock = self.fixture.helper.now
        original = current_packet(self.config, as_of=clock, include_content=True)
        with patch.object(service.CatalystStore, 'verified_records', side_effect=AssertionError('no duplicate full source scan')):
            packet = current_packet(self.config, as_of=clock, include_content=True, verified_source=source)
        self.assertEqual(canonical_json_bytes(packet), canonical_json_bytes(original))

    def test_status_shares_one_fresh_source_and_preserves_original_report(self):
        original_source = service.CatalystStore.verified_records
        original = (self.child / 'report.json').read_bytes()
        with patch.object(service.CatalystStore, 'verified_records', autospec=True,
                side_effect=original_source) as source:
            status = service.status(self.config, now=self.fixture.helper.now)
        self.assertEqual(status['status'], 'CHALLENGED_INTERPRETATION')
        self.assertEqual(canonical_json_bytes(status['report']), original)
        self.assertEqual(source.call_count, 1)
        self.assertEqual((self.child / 'report.json').read_bytes(), original)

    def test_status_call_after_tamper_does_not_reuse_previous_success(self):
        self.assertEqual(service.status(self.config, now=self.fixture.helper.now)['status'], 'CHALLENGED_INTERPRETATION')
        report = self.child / 'report.json'
        report.chmod(0o600)
        report.write_bytes(b'{}')
        status = service.status(self.config, now=self.fixture.helper.now)
        self.assertEqual(status['status'], 'UNAVAILABLE')
        self.assertIsNone(status['report'])
        self.assertEqual(status['auto_trading'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
