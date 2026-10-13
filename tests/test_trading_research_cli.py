"""The new research commands never start legacy strategies or execution."""
import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_research_cli import main, render_research_review
from blackpod_build_week.trading_research_example import prepare_example, example_material, EVALUATED_AT
from blackpod_build_week.trading_research_journal import build_evaluation_event, evidence_for_research


class ResearchCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('process forbidden')))
        self.enterContext(patch('blackpod_build_week.galactica_trading_adapter.run_guarded_navigator', side_effect=AssertionError('legacy executor forbidden')))
        self.enterContext(patch('blackpod_build_week.shadow_brigade_analysis.build_shadow_brigade_analysis', side_effect=AssertionError('Brigade rules forbidden')))
        self.enterContext(patch('blackpod_build_week.shadow_galactica_analysis.build_shadow_galactica_analysis', side_effect=AssertionError('Spyglass rules forbidden')))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve(); self.example = self.base/'example'
        prepare_example(self.example)
        self.journal = self.example/'journal'; self.plan = self.example/'input/plan.json'
        self.evidence = self.example/'evidence'

    def call(self, command, *extras, **overrides):
        args = [command,'--journal-root',str(overrides.get('journal',self.journal))]
        if command in {'register','evaluate','record'}:
            args += ['--plan',str(overrides.get('plan',self.plan)), '--evidence-root',str(self.evidence)]
        args += list(extras)
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            status = main(args)
        return status, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()

    def record(self):
        return self.call('record','--evaluation-id','root-cli-evaluation','--recorded-at',EVALUATED_AT)

    def test_evaluate_is_data_only_and_does_not_append_an_event(self):
        status, output, errors = self.call('evaluate')
        self.assertEqual(status,0,errors)
        self.assertEqual(JournalStore(self.journal).verify().event_count,1)
        self.assertEqual(output['provider_calls'],0)
        self.assertEqual(output['orders_submitted'],0)
        self.assertFalse(output['auto_trading_changed'])
        self.assertIsNone(output['result']['realized_trade_pnl'])

    def test_register_retry_reuses_original_trial(self):
        status, output, errors = self.call('register')
        self.assertEqual(status,0,errors)
        self.assertFalse(output['written'])
        self.assertEqual(output['sequence'],1)

    def test_evaluation_requires_registration_even_with_valid_files(self):
        status, _, errors = self.call('evaluate', journal=self.base/'empty-journal')
        self.assertEqual(status,2)
        self.assertIn('registration',errors)

    def test_record_show_verify_and_retry_are_consistent(self):
        status, recorded, errors = self.record(); self.assertEqual(status,0,errors)
        status, shown, errors = self.call('show','--event-id',recorded['event_id'])
        self.assertEqual(status,0,errors)
        self.assertEqual(shown['schema_version'],'blackpod.decision_journal_event.v12')
        self.assertEqual(shown['payload']['result']['mode'],'OFFLINE_SIMULATION')
        status, report, errors = self.call('verify'); self.assertEqual(status,0,errors)
        self.assertEqual(report['event_count'],2)
        self.assertEqual(report['orphan_evidence_count'],0)
        self.assertFalse(self.record()[1]['written'])

    def test_render_preserves_simulated_and_holdout_boundaries(self):
        status, recorded, errors = self.record(); self.assertEqual(status,0,errors)
        output = self.base/'reports/review.html'
        status, report, errors = self.call('render','--event-id',recorded['event_id'],'--output',str(output))
        self.assertEqual(status,0,errors)
        html = output.read_text()
        self.assertIn('SIMULATED ONLY',html)
        self.assertIn('AUTOMATION AUTHORITY OFF',html)
        self.assertIn('FINAL HOLDOUT UNSCORED',html)
        self.assertIn('not realized trade P&amp;L',html)
        self.assertIn('no Brigade votes',html)

    def test_report_cannot_be_written_into_runtime_or_journal(self):
        status, recorded, errors = self.record(); self.assertEqual(status,0,errors)
        for output in (self.journal/'review.html',self.example/'review.html'):
            status, _, _ = self.call('render','--event-id',recorded['event_id'],'--output',str(output))
            self.assertEqual(status,2)

    def test_render_registration_has_no_simulated_outcomes_to_present(self):
        identifier = JournalStore(self.journal).events()[0].event_id
        status, _, errors = self.call('render','--event-id',identifier,'--output',str(self.base/'reports/plan.html'))
        self.assertEqual(status,2)
        self.assertIn('evaluation',errors)

    def test_unknown_event_cannot_be_shown(self):
        status, _, _ = self.call('show','--event-id','journal-event-'+'0'*64)
        self.assertEqual(status,2)

    def test_redundant_external_evidence_cannot_replace_registered_bytes(self):
        path = self.evidence/'research/intents.json'; path.write_bytes(b'{}')
        status, output, errors = self.call('evaluate')
        self.assertEqual(status,0,errors)
        self.assertEqual(output['result']['folds'][0]['metrics']['simulated_total_pnl'],'4.295')

    def test_unregistered_changed_evidence_fails_before_registration(self):
        path = self.evidence/'research/intents.json'; path.write_bytes(b'{}')
        status, _, errors = self.call('register',journal=self.base/'empty-journal')
        self.assertEqual(status,2)
        self.assertIn('hash',errors)

    def test_no_execution_field_can_be_smuggled_into_plan(self):
        value = json.loads(self.plan.read_bytes()); value['execution_enabled'] = True
        path = self.base/'new-source/unsafe.json'; path.parent.mkdir(); path.write_bytes(canonical_json_bytes(value))
        status, _, errors = self.call('register',plan=path)
        self.assertEqual(status,2)
        self.assertIn('unknown fields',errors)

    def test_no_plan_inside_journal_can_be_used_as_external_input(self):
        source = self.journal/'plan.json'; source.write_bytes(self.plan.read_bytes())
        status, _, _ = self.call('register',plan=source)
        self.assertEqual(status,2)

    def test_html_escapes_external_hypothesis_and_expected_edge(self):
        material = example_material(); value = material['plan'].to_dict()
        value['strategy']['hypothesis'] = '<script>alert("unsafe")</script>'
        value['strategy']['expected_edge'] = '<img src=x onerror=alert(1)>'
        plan = TradingResearchPlan.from_mapping(value)
        from blackpod_build_week.trading_research_journal import build_plan_event
        registration = build_plan_event(plan,(),material['blobs'])
        event = build_evaluation_event(plan,(registration,),material['blobs'],evaluation_id='escaped-evaluation',recorded_at=EVALUATED_AT)
        html = render_research_review(event)
        self.assertNotIn('<script>',html); self.assertNotIn('<img src=x',html)
        self.assertIn('&lt;script&gt;',html)


if __name__ == '__main__': unittest.main()
