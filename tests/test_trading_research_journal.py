"""Frozen independent research plans, trial registry and passive v12 replay."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalVerificationError, JournalPersistenceError,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_research_example import example_material, EVALUATED_AT
from blackpod_build_week.trading_research_journal import (
    build_plan_event, build_evaluation_event, assess_registered_research, evidence_for_research,
)


class ResearchJournalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('process forbidden')))
        self.enterContext(patch('blackpod_build_week.galactica_trading_adapter.run_guarded_navigator', side_effect=AssertionError('execution forbidden')))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.store = JournalStore(self.root / 'journal')
        self.m = example_material()

    def register(self):
        return self.store.append(self.m['plan_event'], evidence_for_research(self.m['plan'], self.m['blobs']))

    def record(self, evaluation_id='evaluation-root-test', recorded_at=EVALUATED_AT):
        events, blobs = self.store.verified_contents()
        event = build_evaluation_event(self.m['plan'], events, blobs, evaluation_id=evaluation_id, recorded_at=recorded_at)
        return self.store.append(event, evidence_for_research(self.m['plan'], blobs)), event

    def next_trial(self, *, prior=('synthetic-trading-trial-1',), trial_id='trial-2', plan_id='plan-2'):
        value = self.m['plan'].to_dict()
        value.update(plan_id=plan_id, registered_at=EVALUATED_AT)
        value['trial_registry'] = {'trial_id': trial_id, 'prior_trial_ids': list(prior)}
        raw_intents = json.loads(self.m['blobs'][value['intents_evidence']['sha256']])
        raw_intents['plan_id'] = plan_id
        raw = canonical_json_bytes(raw_intents)
        value['intents_evidence'].update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        blobs = dict(self.m['blobs']); blobs[sha256_bytes(raw)] = raw
        return TradingResearchPlan.from_mapping(value), blobs

    def test_registered_plan_then_evaluation_v12_no_real_pnl_or_authority(self):
        self.register(); result, event = self.record()
        self.assertTrue(result.written)
        self.assertEqual(result.sequence, 2)
        self.assertEqual(event.schema_version, 'blackpod.decision_journal_event.v12')
        report = event.payload['result']
        self.assertIsNone(report['realized_trade_pnl'])
        self.assertFalse(report['auto_trading_enabled'])
        self.assertFalse(any(report['authority'].values()))
        self.assertEqual(report['trial_registry']['declared_trial_count_at_registration'], 1)
        self.assertFalse(report['trial_registry']['global_trial_completeness_verified'])
        verified = self.store.verify()
        self.assertEqual(verified.event_count, 2)
        self.assertEqual(verified.orphan_evidence_count, 0)

    def test_evaluation_requires_preceding_registered_plan(self):
        with self.assertRaises(ValueError):
            build_evaluation_event(self.m['plan'], (), self.m['blobs'], evaluation_id='no-registration', recorded_at=EVALUATED_AT)

    def test_evaluation_cannot_change_registered_costs_or_rules(self):
        self.register(); events, blobs = self.store.verified_contents()
        changed = self.m['plan'].to_dict(); changed['cost_model']['fee_per_fill'] = '0'
        with self.assertRaises(ValueError): assess_registered_research(changed, events, blobs)

    def test_records_cannot_claim_actual_trade_pnl(self):
        changed = self.m['evaluation_event'].to_dict()
        changed['payload']['result']['realized_trade_pnl'] = '4.295'
        with self.assertRaises(ValueError): JournalEvent.from_mapping(changed)

    def test_shadow_or_live_mode_and_new_authority_rejected(self):
        for key, replacement in (('mode', 'PAPER'), ('scope', 'LIVE_EXECUTION'), ('auto_trading_enabled', True)):
            changed = self.m['evaluation_event'].to_dict(); changed['payload']['result'][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError): JournalEvent.from_mapping(changed)
        for key in self.m['plan'].authority:
            changed = self.m['evaluation_event'].to_dict(); changed['payload']['result']['authority'][key] = True
            with self.subTest(key=key), self.assertRaises(ValueError): JournalEvent.from_mapping(changed)

    def test_event_v12_only_accepts_new_research_types_and_domain(self):
        for key, replacement in (('domain', 'INVESTMENT'), ('event_type', 'ORDER_AUTHORIZED'), ('schema_version', 'blackpod.decision_journal_event.v11')):
            changed = self.m['plan_event'].to_dict(); changed[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError): JournalEvent.from_mapping(changed)

    def test_dataset_and_source_hashes_are_required(self):
        for ref in (self.m['plan'].dataset_evidence, self.m['dataset'].provenance['source_evidence'][0]):
            changed = dict(self.m['blobs']); changed[ref['sha256']] = b'changed bytes'
            with self.subTest(path=ref['path']), self.assertRaises(ValueError): build_plan_event(self.m['plan'], (), changed)

    def test_source_evidence_is_retained_immutable(self):
        self.register()
        for reference in self.m['plan_event'].evidence:
            path = self.store.root / 'evidence' / reference['sha256']
            self.assertEqual(path.read_bytes(), self.m['blobs'].get(reference['sha256'], self.m['plan'].to_bytes()))
            self.assertEqual(path.stat().st_mode & 0o777, 0o444)

    def nested_source(self):
        value = self.m['plan'].to_dict(); blobs = dict(self.m['blobs'])
        dataset = json.loads(blobs[value['dataset_evidence']['sha256']])
        child = b'nested retained evidence\n'
        child_ref = {'path':'market/child.raw','sha256':sha256_bytes(child),'size_bytes':len(child)}
        raw = canonical_json_bytes({'source_evidence':[child_ref]})
        ref = dataset['provenance']['source_evidence'][0]
        ref.update(sha256=sha256_bytes(raw),size_bytes=len(raw)); blobs[sha256_bytes(raw)] = raw
        dataset_raw = canonical_json_bytes(dataset)
        value['dataset_evidence'].update(sha256=sha256_bytes(dataset_raw),size_bytes=len(dataset_raw))
        blobs[sha256_bytes(dataset_raw)] = dataset_raw; blobs[sha256_bytes(child)] = child
        return TradingResearchPlan.from_mapping(value), blobs, child_ref

    def test_transitive_source_bytes_are_retained_and_replayed(self):
        plan, blobs, child = self.nested_source()
        event = build_plan_event(plan,(),blobs)
        self.store.append(event,evidence_for_research(plan,blobs))
        self.assertIn(child,event.evidence)
        self.assertEqual(self.store.verified_contents()[1][child['sha256']],blobs[child['sha256']])

    def test_missing_transitive_source_rejects_registration(self):
        plan, blobs, child = self.nested_source(); del blobs[child['sha256']]
        with self.assertRaises(ValueError): build_plan_event(plan,(),blobs)

    def test_exact_retries_are_noops_without_changing_history(self):
        self.register(); self.record()
        before = {p.name:p.read_bytes() for p in (self.store.root/'entries').iterdir()}
        self.assertFalse(self.register().written)
        self.assertFalse(self.record()[0].written)
        self.assertEqual(before, {p.name:p.read_bytes() for p in (self.store.root/'entries').iterdir()})

    def test_later_evaluation_appends_without_rewriting_plan(self):
        self.register(); self.record('first-evaluation')
        initial = self.store.events()[0].to_bytes()
        self.record('second-evaluation')
        events = self.store.events()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].to_bytes(), initial)
        self.assertEqual(events[-1].payload['plan_event_id'], events[0].event_id)

    def test_changed_plan_identity_conflicts(self):
        self.register()
        value = self.m['plan'].to_dict(); value['strategy']['hypothesis'] = 'Changed after results'
        with self.assertRaises(ValueError): build_plan_event(value, self.store.events(), self.m['blobs'])

    def test_prior_trial_registry_cannot_omit_registered_failed_or_unscored_trial(self):
        self.register()
        plan, blobs = self.next_trial(prior=())
        with self.assertRaises(ValueError): build_plan_event(plan, self.store.events(), blobs)

    def test_trial_id_cannot_repeat_under_another_plan(self):
        self.register()
        plan, blobs = self.next_trial(trial_id='synthetic-trading-trial-1', prior=())
        with self.assertRaises(ValueError): build_plan_event(plan, self.store.events(), blobs)

    def test_all_registered_trials_count_even_without_evaluation(self):
        self.register(); plan, blobs = self.next_trial()
        event = build_plan_event(plan, self.store.events(), blobs)
        self.store.append(event, evidence_for_research(plan, blobs))
        events, retained = self.store.verified_contents()
        report = assess_registered_research(plan, events, retained)
        self.assertEqual(report['trial_registry']['declared_trial_count_at_registration'], 2)
        self.assertEqual(report['trial_registry']['prior_trial_ids'], ['synthetic-trading-trial-1'])

    def test_comparison_protocol_cannot_change_within_same_experiment(self):
        self.register(); plan, blobs = self.next_trial()
        value = plan.to_dict(); value['risk']['initial_cash'] = '2000'
        with self.assertRaises(ValueError): build_plan_event(value, self.store.events(), blobs)

    def test_exact_first_trial_retry_ignores_later_registrations(self):
        self.register(); plan, blobs = self.next_trial()
        event = build_plan_event(plan, self.store.events(), blobs)
        self.store.append(event, evidence_for_research(plan, blobs))
        self.assertFalse(self.register().written)

    def test_record_time_cannot_predate_declared_inputs(self):
        self.register()
        with self.assertRaises(ValueError): self.record(recorded_at='2026-01-01T00:00:00Z')

    def test_metric_or_trial_registry_tampering_cannot_be_rehashed_into_valid_event(self):
        self.register()
        for mutation in (lambda value:value['payload']['result']['folds'][0]['metrics'].update(ending_equity='999999'),
                         lambda value:value['payload']['result']['trial_registry'].update(declared_trial_count_at_registration=100)):
            changed = self.m['evaluation_event'].to_dict(); mutation(changed)
            event = JournalEvent.from_mapping(changed)
            with self.assertRaises(JournalVerificationError): self.store.append(event, evidence_for_research(self.m['plan'], self.m['blobs']))

    def test_original_registration_link_cannot_point_to_another_event(self):
        self.register(); changed = self.m['evaluation_event'].to_dict()
        changed['payload']['plan_event_id'] = changed['event_id']
        event = JournalEvent.from_mapping(changed)
        with self.assertRaises(JournalVerificationError): self.store.append(event, evidence_for_research(self.m['plan'], self.m['blobs']))

    def test_interrupted_publication_recovers_using_retained_evidence_only(self):
        self.register()
        import blackpod_build_week.decision_journal_store as module
        original = module._publish_immutable
        def interrupt(staging, target, name, payload):
            if name.endswith('.json'):
                raise OSError('injected entry publication failure')
            return original(staging,target,name,payload)
        with patch.object(module, '_publish_immutable', side_effect=interrupt), self.assertRaises((OSError, JournalPersistenceError)):
            self.record('interrupted-evaluation')
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertTrue(self.record('interrupted-evaluation')[0].written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual(self.store.verify().staging_orphan_count, 0)

    def test_mixed_older_journal_schema_remains_independent(self):
        from blackpod_build_week.contracts.decision_journal import CapitalPolicyProposal
        from blackpod_build_week.decision_journal_cli import build_policy_event
        from test_decision_journal_contracts import capital_policy
        policy = CapitalPolicyProposal.from_mapping(capital_policy())
        older = build_policy_event(policy)
        self.store.append(older, {'capital_policy/proposal.json':policy.to_bytes()})
        original = self.store.events()[0].to_bytes()
        self.register(); self.record()
        self.assertEqual(self.store.events()[0].to_bytes(), original)
        self.assertEqual([r.schema_version for r in self.store.events()], ['blackpod.decision_journal_event.v1','blackpod.decision_journal_event.v12','blackpod.decision_journal_event.v12'])


if __name__ == '__main__': unittest.main()
