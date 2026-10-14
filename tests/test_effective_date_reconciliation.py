"""Deterministic reconciliation with unchanged native histories and no gates."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.effective_date_reconciliation import *
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.effective_date_reconciliation import reconcile_effective_dates
from blackpod_build_week.trading_continuity_intake import build_continuity_intake
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_trading_continuity_intake import continuity_fixture, native_action
from test_trading_historical_intake_contracts import source_material, refresh
from blackpod_build_week.trading_historical_intake import build_historical_intake
from test_independent_action_sources import workbook, inventory as workbook_inventory


def ref(path, raw): return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def independent_row(identity='independent-cash-1', **changes):
    return {"source_action_id": identity, "native_type": "cash_dividends", "affected_symbols": ["SYNTHA"], "effective_date": "2026-01-09", "record_date": "2026-01-12", "payable_date": "2026-01-20", "status": "EFFECTIVE", "cusip": "000000001", "amount_lexemes": {"dividend": "0.500000", "short_term_capital_gain": None, "long_term_capital_gain": None}, "replaces_source_action_id": None, **changes}


def fixture_material(rows=None, *, groups=None, completeness='DECLARED_COMPLETE', noncanonical=False):
    value, _, _, original = continuity_fixture(groups=groups if groups is not None else {'cash_dividends': [native_action()]})
    native = build_continuity_intake(value, original)
    blobs = {**original, **native['blobs']}
    export_raw = native['export'].to_bytes(); export_ref = ref('native/export.json', export_raw); blobs[export_ref['sha256']] = export_raw
    body = {'schema_version': AUTHORED_VERSION, 'label': 'AUTHORED_UNVERIFIED', 'actions': [independent_row()] if rows is None else rows}
    body_raw = json.dumps(body, indent=2).encode() if noncanonical else canonical_json_bytes(body)
    body_ref = ref('independent/actions.json', body_raw); blobs[body_ref['sha256']] = body_raw
    inventory = IndependentActionInventory.from_mapping({'schema_version': INVENTORY_VERSION, 'inventory_id': 'unit-independent-actions', 'recorded_at': '2026-01-24T12:00:00Z',
        'profile': AUTHORED_PROFILE, 'evidence_scope': 'SYNTHETIC_FIXTURE_ONLY', 'publisher': 'authored-fictional-independent-source', 'source_url': 'https://example.invalid/authored-source', 'captured_at': '2026-01-24T11:00:00Z',
        'body_evidence': body_ref, 'declared_coverage': {'symbols': native['dataset'].universe, 'action_types': list(ACTION_TYPES), 'effective_start': '2026-01-05', 'effective_end': '2026-01-21', 'completeness': completeness},
        'supporting_evidence': [], 'auto_trading_enabled': False, 'authority': AUTHORITY})
    inventory_raw = json.dumps(inventory.to_dict(), indent=4).encode() if noncanonical else inventory.to_bytes()
    inventory_ref = ref('independent/inventory.json', inventory_raw); blobs[inventory_ref['sha256']] = inventory_raw
    request = EffectiveDateReconciliationRequest.from_mapping({'schema_version': REQUEST_VERSION, 'reconciliation_id': 'unit-effective-date-reconciliation', 'recorded_at': '2026-01-25T12:00:00Z', 'data_cutoff_at': '2026-01-25T11:00:00Z',
        'domain': 'TRADING', 'mode': 'SHADOW_RESEARCH', 'scope': SCOPE, 'dataset_evidence': native['export'].dataset_evidence, 'native_continuity_export_evidence': export_ref,
        'independent_inventories': [inventory_ref], 'auto_trading_enabled': False, 'authority': AUTHORITY})
    return {'request': request, 'blobs': blobs, 'native': native, 'inventory': inventory, 'inventory_raw': inventory_raw, 'body_raw': body_raw}


def ssga_reconciliation_fixture(raw):
    """Authored SPY calendar/bars permit full XLSX→result validation, no returns."""
    history_request, values, _ = source_material(days=['2023-12-15','2023-12-18','2023-12-19','2023-12-20'])
    history_request['universe'] = ['SPY']
    values['bars_evidence']['bars'] = {'SPY':values['bars_evidence']['bars']['SYNTHA']}
    values['bars_receipt_evidence']['query']['symbols'] = 'SPY'
    history_request, _, blobs = refresh(history_request,values)
    history = build_historical_intake(history_request,blobs); blobs.update(history['blobs'])
    dataset_ref = ref('historical-intake/dataset.v2.json',history['dataset'].to_bytes())
    body = canonical_json_bytes({'corporate_actions':{},'next_page_token':None}); body_ref = ref('native/actions.raw',body)
    receipt = canonical_json_bytes({'schema_version':'blackpod.trading_evidence_capture.v1','method':'GET','url':'https://data.alpaca.markets/v1/corporate-actions',
        'query':{'symbols':'SPY','start':'2023-12-15','end':'2023-12-20','limit':1000,'sort':'asc'},'captured_at':'2026-10-13T23:58:00Z','status':200,'body_sha256':body_ref['sha256'],'size_bytes':len(body)})
    receipt_ref = ref('native/receipt.json',receipt); blobs.update({sha256_bytes(body):body,sha256_bytes(receipt):receipt})
    native = build_continuity_intake({'schema_version':'blackpod.trading_continuity_intake_request.v1','run_id':'authored-spy-xlsx-validation','recorded_at':'2026-10-13T23:59:00Z',
        'domain':'TRADING','mode':'SHADOW_RESEARCH','scope':'RETAINED_CORPORATE_ACTION_INTAKE_ONLY','dataset_evidence':dataset_ref,'universe':['SPY'],'process_date_range':{'start':'2023-12-15','end':'2023-12-20'},
        'pages':[{'response_evidence':body_ref,'capture_receipt_evidence':receipt_ref}],'coverage_basis':'EX_DATE_COVERAGE_UNVERIFIED','evidence_scope':'RETAINED_HISTORY_RESEARCH','coverage_review_evidence':None,
        'reviewer_id':'authored-unverified-test-source','review_notes':'Calendar and numeric bars are authored solely for parser-to-result validation; no actual market-data claim.','auto_trading_enabled':False,'authority':AUTHORITY},blobs)
    blobs.update(native['blobs']); export_raw = native['export'].to_bytes(); export_ref = ref('native/export.json',export_raw); blobs[sha256_bytes(export_raw)] = export_raw
    inventory = workbook_inventory(raw); inventory_ref = ref('independent/workbook-inventory.json',inventory.to_bytes())
    blobs.update({sha256_bytes(raw):raw,inventory_ref['sha256']:inventory.to_bytes()})
    request = EffectiveDateReconciliationRequest.from_mapping({'schema_version':REQUEST_VERSION,'reconciliation_id':'unit-ssga-full-result','recorded_at':'2026-10-14T02:00:00Z','data_cutoff_at':'2026-10-14T01:30:00Z',
        'domain':'TRADING','mode':'SHADOW_RESEARCH','scope':SCOPE,'dataset_evidence':dataset_ref,'native_continuity_export_evidence':export_ref,'independent_inventories':[inventory_ref],'auto_trading_enabled':False,'authority':AUTHORITY})
    return {'request':request,'blobs':blobs,'native':native,'inventory':inventory}


class EffectiveDateReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('workers forbidden')))

    def assess(self, fixture): return reconcile_effective_dates(fixture['request'], fixture['blobs'])

    def change_inventory(self, fixture, **changes):
        value = fixture['inventory'].to_dict(); value.update(changes); raw = canonical_json_bytes(value)
        reference = ref('independent/changed-inventory.json', raw); fixture['blobs'][reference['sha256']] = raw
        value = fixture['request'].to_dict(); value['independent_inventories'] = [reference]
        fixture['request'] = EffectiveDateReconciliationRequest.from_mapping(value)

    def test_exact_match_is_descriptive_only_and_does_not_verify_amount_or_payment(self):
        fixture = fixture_material(); original = fixture['native']['export'].to_bytes()
        material = self.assess(fixture); result = material['result']
        self.assertEqual(len(result['matches']), 1); self.assertEqual(result['matches'][0]['comparison'], 'EVENT_KEY_ONLY_AMOUNT_AND_STATUS_UNVERIFIED')
        self.assertEqual(result['native_only'], []); self.assertEqual(result['independent_only'], [])
        self.assertEqual(result['native_actions'], fixture['native']['export'].native_actions)
        self.assertEqual(material['native_material']['export'].to_bytes(), original)
        self.assertEqual(result['coverage_proposal']['status'], 'UNRESOLVED'); self.assertFalse(result['coverage_supported'])
        self.assertEqual(result['status'], 'DESCRIPTIVE_RECONCILIATION_ONLY'); self.assertIsNone(result['realized_trade_pnl'])

    def test_full_workbook_reconciliation_keeps_blank_padded_and_unicode_cell_lexemes(self):
        raw = workbook([["  SPY Trust®  ","SPY","78462F103","12/15/2023","12/18/2023","01/31/2024"," 1.906073 ",""," \t ","Quarterly"]])
        material = self.assess(ssga_reconciliation_fixture(raw)); row = material['result']['independent_actions'][0]
        self.assertEqual(row['amount_lexemes'],{'dividend':' 1.906073 ','short_term_capital_gain':None,'long_term_capital_gain':None})
        self.assertEqual(row['provenance']['cells']['A']['lexeme'],'  SPY Trust®  ')
        self.assertEqual(row['provenance']['cells']['H']['lexeme'],'')
        self.assertEqual(row['provenance']['cells']['I']['lexeme'],' \t ')
        self.assertEqual(validate_result(material['result']),material['result'])
        retained = {sha256_bytes(value):value for value in material['evidence'].values()}
        self.assertEqual(reconcile_effective_dates(material['request'],retained),material)

    @unittest.skipUnless(Path('output/effective-date-applicability-real-001/source/ssga-historical-distributions.xlsx').exists(),'retained real SSGA workbook not present')
    def test_full_retained_real_ssga_parse_flows_through_nested_result_validation(self):
        raw = Path('output/effective-date-applicability-real-001/source/ssga-historical-distributions.xlsx').read_bytes()
        self.assertEqual(sha256_bytes(raw),'b162dd17027d1128f2209e312b0f634960daa78319dafe0ab821ab0b7e77ce23')
        material = self.assess(ssga_reconciliation_fixture(raw)); result = validate_result(material['result'])
        self.assertEqual(len(result['independent_actions']),136)
        rows = {row['provenance']['row']:row for row in result['independent_actions']}
        self.assertEqual(rows[9129]['provenance']['cells']['H']['lexeme'],'')
        self.assertEqual(rows[9129]['provenance']['cells']['I']['lexeme'],'')
        self.assertEqual(rows[9140]['amount_lexemes']['dividend'],'1.906073')
        self.assertEqual(result['coverage_proposal']['status'],'UNRESOLVED'); self.assertFalse(result['coverage_supported'])

    def test_raw_cell_validator_rejects_nontext_oversize_and_unencodable_surrogates(self):
        material = self.assess(ssga_reconciliation_fixture(workbook()))
        for lexeme in (None,1,'x'*10001,'\ud800'):
            result = deepcopy(material['result']); cells = result['independent_actions'][0]['provenance']['cells']; cells['H']['lexeme'] = lexeme
            # Validate the raw text before accepting any supplied source hash.
            with self.assertRaises(ContractValidationError): validate_result(result)

    def test_declared_complete_all_types_never_closes_calendar_span_gaps(self):
        result = self.assess(fixture_material())['result']
        self.assertEqual(len(result['coverage_matrix']), 26)
        self.assertEqual(result['effective_span'], {'start':'2026-01-05','end':'2026-01-21','calendar_days':17})
        self.assertTrue(all(not row['coverage_supported'] and row['uncovered_intervals'] for row in result['coverage_matrix']))
        self.assertFalse(result['source_inventory'][0]['completeness_verified'])

    def test_empty_positive_and_partial_inventories_never_imply_no_actions(self):
        result = self.assess(fixture_material([], completeness='PARTIAL'))['result']
        self.assertEqual(len(result['native_only']), 1); self.assertEqual(result['matches'], [])
        self.assertEqual(result['independent_actions'], []); self.assertFalse(result['coverage_supported'])

    def test_independent_only_actions_are_retained_without_invented_alpaca_records(self):
        fixture = fixture_material([independent_row(effective_date='2026-01-12')], groups={})
        result = self.assess(fixture)['result']
        self.assertEqual(len(result['independent_only']), 1); self.assertEqual(result['native_actions'], [])
        self.assertEqual(result['independent_actions'][0]['source_action_id'], 'independent-cash-1')
        self.assertFalse(any(row['independent_action_id'].startswith('alpaca-action-') for row in result['independent_actions']))

    def test_distinct_same_key_duplicates_remain_ambiguous_without_arbitrary_matching(self):
        result = self.assess(fixture_material([independent_row('row-one'), independent_row('row-two')]))['result']
        self.assertEqual(result['matches'], []); self.assertEqual(len(result['ambiguous']), 1)
        self.assertEqual(len(result['duplicate_groups'][0]['independent_action_ids']), 2)

    def test_date_type_conflicts_remain_unresolved(self):
        for change in ({'effective_date':'2026-01-12'}, {'native_type':'forward_splits'}):
            result = self.assess(fixture_material([independent_row(**change)]))['result']
            self.assertEqual(result['matches'], []); self.assertTrue(result['conflicts'])
            self.assertEqual(len(result['native_only']), 1); self.assertEqual(len(result['independent_only']), 1)

    def test_full_symbol_alias_sets_must_match_without_dropping_counterparties(self):
        fixture = fixture_material([independent_row(native_type='unit_splits')], groups={'unit_splits':[native_action('unit_splits')]})
        result = self.assess(fixture)['result']
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['conflicts'][0]['kind'], 'POSSIBLE_SYMBOL_CONFLICT_NOT_RESOLVED')
        self.assertEqual(result['native_actions'][0]['affected_symbols'], ['ALTERNATE','OTHER','SYNTHA'])

    def test_adjacent_overlap_and_weekend_declared_interval_union_is_separate(self):
        first, last = '2026-01-05', '2026-01-21'
        def interval(start,end): return {'start':start,'end':end}
        self.assertEqual(declared_scope_gaps(first,last,[interval(first,'2026-01-09'),interval('2026-01-10',last)]),[])
        self.assertEqual(declared_scope_gaps(first,last,[interval(first,'2026-01-12'),interval('2026-01-08',last)]),[])
        self.assertEqual(declared_scope_gaps(first,last,[interval(first,'2026-01-09'),interval('2026-01-12',last)]),[interval('2026-01-10','2026-01-11')])
        self.assertEqual(declared_scope_gaps(first,last,[interval('2025-12-01','2026-01-06'),interval('2026-01-20','2026-02-01')]),[interval('2026-01-07','2026-01-19')])

    def test_multiple_packet_partial_union_cannot_verify_weekend_or_other_types(self):
        fixture = fixture_material()
        coverage = fixture['inventory'].declared_coverage; coverage.update(effective_end='2026-01-09',completeness='PARTIAL')
        self.change_inventory(fixture,declared_coverage=coverage)
        second_raw = canonical_json_bytes({'schema_version':AUTHORED_VERSION,'label':'AUTHORED_UNVERIFIED','actions':[]})
        second_ref = ref('independent/second-body.json',second_raw); fixture['blobs'][second_ref['sha256']] = second_raw
        second = fixture['inventory'].to_dict(); second.update(inventory_id='second-independent-source',body_evidence=second_ref)
        second['declared_coverage'].update(effective_start='2026-01-12',completeness='PARTIAL')
        raw = canonical_json_bytes(second); reference = ref('independent/second.json',raw); fixture['blobs'][reference['sha256']] = raw
        request = fixture['request'].to_dict(); request['independent_inventories'].append(reference)
        result = reconcile_effective_dates(request,fixture['blobs'])['result']
        self.assertEqual(result['coverage_matrix'][0]['declared_scope_gaps'],[{'start':'2026-01-10','end':'2026-01-11'}])
        self.assertEqual(result['coverage_matrix'][0]['uncovered_intervals'][0]['start'],'2026-01-05')
        self.assertFalse(result['coverage_matrix'][0]['coverage_supported'])

    def test_unknown_dates_never_use_process_or_payable_dates(self):
        result = self.assess(fixture_material([independent_row(effective_date=None)], groups={'worthless_removals':[native_action('worthless_removals')]}))['result']
        self.assertEqual(len(result['unknown_effective_dates']), 2); self.assertEqual(result['matches'], [])
        self.assertIsNone(result['native_actions'][0]['effective_date']); self.assertIsNone(result['independent_actions'][0]['effective_date'])

    def test_scheduled_cancelled_revised_and_unknown_statuses_preserved(self):
        rows = [independent_row('row-'+status.lower(), status=status) for status in ('SCHEDULED','CANCELLED','REVISED','UNKNOWN')]
        result = self.assess(fixture_material(rows))['result']
        self.assertEqual(result['matches'], []); self.assertEqual(len(result['conflicts']), 4)
        self.assertEqual([row['status'] for row in result['independent_actions']], [row['status'] for row in rows])

    def test_outside_span_rows_retained_without_becoming_in_span_matches(self):
        result = self.assess(fixture_material([independent_row('before',effective_date='2025-12-01'), independent_row('after',effective_date='2026-02-01')]))['result']
        self.assertEqual([row['dataset_disposition'] for row in result['independent_actions']], ['BEFORE_DATASET','AFTER_DATASET'])
        self.assertEqual(result['independent_only'], [])

    def test_noncanonical_manifest_and_body_bytes_survive_retained_only_replay(self):
        fixture = fixture_material(noncanonical=True); material = self.assess(fixture)
        self.assertIn(fixture['body_raw'], material['evidence'].values()); self.assertIn(fixture['inventory_raw'], material['evidence'].values())
        retained = {sha256_bytes(raw):raw for raw in material['evidence'].values()}
        self.assertEqual(reconcile_effective_dates(fixture['request'], retained), material)

    def test_dataset_native_source_manifest_and_body_tampering_reject(self):
        for field in ('dataset_evidence','native_continuity_export_evidence','independent_inventories'):
            fixture = fixture_material(); value = getattr(fixture['request'], field); reference = value[0] if isinstance(value,list) else value
            fixture['blobs'][reference['sha256']] += b' '
            with self.assertRaises(ValueError): self.assess(fixture)
        fixture = fixture_material(); del fixture['blobs'][fixture['inventory'].body_evidence['sha256']]
        with self.assertRaises(ValueError): self.assess(fixture)

    def test_future_native_inventory_and_capture_cutoffs_reject(self):
        fixture = fixture_material(); request = fixture['request'].to_dict(); request['data_cutoff_at'] = '2026-01-22T23:00:00Z'
        with self.assertRaises(ValueError): reconcile_effective_dates(request,fixture['blobs'])
        fixture = fixture_material(); self.change_inventory(fixture,recorded_at='2026-01-26T12:00:00Z')
        with self.assertRaisesRegex(ValueError,'cutoff'): self.assess(fixture)

    def test_reused_original_native_body_is_not_independent(self):
        fixture = fixture_material(); source = fixture['native']['request'].pages[0]['response_evidence']
        self.change_inventory(fixture,body_evidence=source)
        with self.assertRaisesRegex(ValueError,'reuse'): self.assess(fixture)

    def test_duplicate_inventory_identity_and_body_reject(self):
        fixture = fixture_material(); request = fixture['request'].to_dict(); first = request['independent_inventories'][0]
        request['independent_inventories'].append({**first,'path':'alias/inventory.json'})
        with self.assertRaisesRegex(ValueError,'duplicate'): reconcile_effective_dates(request,fixture['blobs'])

    def test_fixed_universe_and_evidence_scope_reject_relabeling(self):
        for change in ({'evidence_scope':'RETAINED_HISTORY_RESEARCH'}, {'declared_coverage':{'symbols':['OTHER'],'action_types':['cash_dividends'],'effective_start':'2026-01-05','effective_end':'2026-01-21','completeness':'UNKNOWN'}}):
            fixture = fixture_material(); self.change_inventory(fixture,**change)
            with self.assertRaisesRegex(ValueError,'scope|universe'): self.assess(fixture)

    def test_request_contract_strict_roundtrip_and_disabled_authority(self):
        request = fixture_material()['request']; self.assertEqual(request,EffectiveDateReconciliationRequest.from_bytes(request.to_bytes()))
        for changes in ({'extra':False},{'scope':'TRADING'},{'auto_trading_enabled':0},{'authority':{}},{'independent_inventories':[{}]},{'data_cutoff_at':'2026-01-26T00:00:00Z'}):
            with self.assertRaises(ContractValidationError): EffectiveDateReconciliationRequest.from_mapping({**request.to_dict(),**changes})

    def test_result_contract_cannot_upgrade_native_coverage_or_execution(self):
        result = self.assess(fixture_material())['result']
        for change in ({'coverage_supported':True},{'native_gate_override':True},{'economic_hypothesis_supported':True},{'uncertainty_computed':True},{'realized_trade_pnl':'1'},{'authority':{}},{'status':'SUPPORTED'}):
            with self.assertRaises(ContractValidationError): validate_result({**result,**change})
        changed = deepcopy(result); changed['coverage_proposal']['status'] = 'SUPPORTED'
        with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_nested_result_unknown_keys_types_and_fabricated_gaps_reject_cleanly(self):
        result = self.assess(fixture_material())['result']
        mutations = [lambda row: row['source_inventory'][0].update(extra=False),
            lambda row: row['source_inventory'][0].update(completeness_verified=True),
            lambda row: row['independent_actions'][0]['provenance'].update(extra=False),
            lambda row: row['independent_actions'][0].update(status='APPROVED'),
            lambda row: row['native_actions'][0].update(extra=False),
            lambda row: row['matches'][0].update(extra=False),
            lambda row: row['matches'][0].update(native_action_ids=[{}]),
            lambda row: row['coverage_matrix'][0].update(declared_scope_gaps=[{'start':'2026-01-05','end':'2026-01-06'}]),
            lambda row: row['coverage_matrix'][0]['uncovered_intervals'][0].update(verified=True),
            lambda row: row['coverage_matrix'][0].update(coverage_supported=True)]
        for mutate in mutations:
            changed = deepcopy(result); mutate(changed)
            with self.assertRaises(ContractValidationError): validate_result(changed)

    def test_missing_support_and_source_limits_reject_before_body_parser(self):
        fixture = fixture_material()
        self.change_inventory(fixture,supporting_evidence=[ref('independent/support.raw',b'missing')])
        with self.assertRaises(ValueError): self.assess(fixture)
        fixture = fixture_material(); oversized = {**fixture['inventory'].body_evidence,'size_bytes':64*1024*1024}
        self.change_inventory(fixture,body_evidence=oversized)
        with patch('blackpod_build_week.effective_date_reconciliation.parse_independent_inventory',side_effect=AssertionError('must not parse oversized closure')):
            with self.assertRaisesRegex(ValueError,'before parsing'): self.assess(fixture)

    def test_original_blobs_and_results_remain_immutable_and_retry_is_exact(self):
        fixture = fixture_material(); before = dict(fixture['blobs']); first = self.assess(fixture)
        second = self.assess(fixture); self.assertEqual(first,second); self.assertEqual(fixture['blobs'],before)
        second['result']['independent_actions'][0]['amount_lexemes']['dividend'] = '1000'
        self.assertEqual(self.assess(fixture),first)


if __name__ == '__main__': unittest.main()
